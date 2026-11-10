import os
import sys
import argparse
from pathlib import Path
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()

from orchestrator import ExtractionPipelineOrchestrator


def seed_cache_from_qdrant(orchestrator: ExtractionPipelineOrchestrator):
    """
    Qdrant에 이미 저장된 118개 요소의 분석 데이터를 크롭 이미지 해시값과 매핑하여
    gemini_cache.json에 시드(Seed) 캐시로 등록합니다.
    """
    crops_dir = Path(os.getenv("CROPS_DIR", "/data/crops"))
    try:
        records, _ = orchestrator.qdrant_client.scroll(
            collection_name=orchestrator.collection_name,
            limit=500,
            with_payload=True,
            with_vectors=False
        )
        seeded_count = 0
        for rec in records:
            payload = rec.payload or {}
            img_rel_path = payload.get("image_path")  # e.g., /static/crops/fig-xxx_p1.png
            if not img_rel_path:
                continue
            
            img_filename = Path(img_rel_path).name
            full_img_path = crops_dir / img_filename

            if full_img_path.exists():
                img_hash = orchestrator.extractor.get_image_hash(full_img_path)
                if img_hash not in orchestrator.extractor.cache:
                    cached_data = {
                        "element_type": payload.get("element_type", "TABLE"),
                        "title_or_caption": payload.get("title_or_caption", ""),
                        "summary": payload.get("summary", ""),
                        "hashtags": payload.get("hashtags", []),
                        "structured_data": payload.get("structured_data")
                    }
                    orchestrator.extractor.cache[img_hash] = cached_data
                    seeded_count += 1

        if seeded_count > 0:
            orchestrator.extractor._save_cache()
            print(f"[Cache Seed] Qdrant 기존 데이터로부터 {seeded_count}건의 분석 결과를 캐시에 자동 등록했습니다.")
    except Exception as e:
        print(f"[Cache Seed] 기존 데이터 캐시 등록 중 안내: {e}")


def estimate_pipeline_calls(
    orchestrator: ExtractionPipelineOrchestrator,
    target_files: List[Path],
    force: bool = False
) -> Tuple[int, int, int]:
    """
    실행 전 대상 PDF들을 분석하여 Gemini API의 예상 호출 횟수를 계산합니다.
    반환값: (이미 색인된 파일 수, 신규 색인 파일 수, 예상 Gemini API 호출 횟수)
    """
    already_indexed = 0
    new_files = 0
    estimated_api_calls = 0

    print("\n[사전 분석] 리포트 파일 상태 및 캐시 점검 중...")
    for pdf_path in target_files:
        is_indexed = orchestrator.is_document_already_indexed(pdf_path.name)
        if is_indexed and not force:
            already_indexed += 1
        else:
            new_files += 1
            # 각 PDF당 평균 3~4개의 도표가 추출된다고 산출
            estimated_api_calls += 3

    return already_indexed, new_files, estimated_api_calls


def main():
    parser = argparse.ArgumentParser(description="FigIndex Batch Indexing Pipeline Runner (up to 50 reports)")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of PDF documents to process (default: 50)")
    parser.add_argument("--force", action="store_true", help="Force re-indexing even if document already exists")
    parser.add_argument("--dry-run", action="store_true", help="Calculate and print expected API calls without running indexing")
    args = parser.parse_args()

    data_pdfs_dir = Path(os.getenv("PDFS_DIR", "/data/pdfs"))

    print("=" * 68)
    print(" FigIndex 50건 리포트 도표·차트 자동 색인 일괄 실행 파이프라인")
    print(f" - 리포트 저장 폴더: {data_pdfs_dir}")
    print(f" - 최대 처리 리포트 수: {args.limit}건")
    print("=" * 68)

    if not data_pdfs_dir.exists():
        print(f"[Error] Directory {data_pdfs_dir} not found!")
        sys.exit(1)

    pdf_files = sorted(list(data_pdfs_dir.glob("*.pdf")))
    pdf_files = [p for p in pdf_files if not p.name.startswith("sample_")]

    total_found = len(pdf_files)
    print(f"[정보] 리포트 PDF 총 {total_found}건 발견")

    if not pdf_files:
        print("[안내] 처리할 PDF 파일이 없습니다.")
        return

    target_files = pdf_files[:args.limit]
    orchestrator = ExtractionPipelineOrchestrator()

    # 1. Qdrant 기존 데이터 기반 캐시 시드 등록
    seed_cache_from_qdrant(orchestrator)
    cached_items_count = len(orchestrator.extractor.cache)

    # 2. 사전 예상 호출 횟수 계산
    indexed_cnt, new_cnt, est_calls = estimate_pipeline_calls(orchestrator, target_files, force=args.force)

    print("\n" + "=" * 68)
    print(" [사전 진단 보고서] Gemini API 예상 호출 횟수")
    print("=" * 68)
    print(f"  * 전체 대상 리포트 파일: {len(target_files)}건")
    print(f"  * 기존 색인 완료된 리포트: {indexed_cnt}건 (자동 스킵 / API 호출 0회)")
    print(f"  * 신규 처리 대상 리포트: {new_cnt}건")
    print(f"  * 현재 보유 중인 도표 캐시: {cached_items_count}건")
    print(f"  * 예상 Gemini API 호출 횟수: 약 {est_calls}회 (도표당 1회, 캐시 적중 시 자동 0회)")
    print(f"  * 예상 소요 시간: 약 {est_calls * 2.5 / 60:.1f}분 (무료 티어 15 RPM 준수 딜레이 2.0s 포함)")
    print("=" * 68 + "\n")

    if args.dry_run:
        print("[안내] --dry-run 옵션이 켜져 있어 실제 색인을 진행하지 않고 종료합니다.")
        return

    # 3. 일괄 색인 파이프라인 시작
    print(f"[시작] {len(target_files)}건의 리포트 일괄 색인을 시작합니다...\n")

    total_indexed_elements = 0
    skipped_count = 0
    processed_count = 0

    for idx, pdf_path in enumerate(target_files, 1):
        print(f"------------------------------------------------------------")
        print(f"[{idx}/{len(target_files)}] 리포트 처리 중: {pdf_path.name}")
        print(f"------------------------------------------------------------")

        if not args.force and orchestrator.is_document_already_indexed(pdf_path.name):
            print(f"  [스킵] '{pdf_path.name}' 리포트는 이미 Qdrant에 색인되어 있습니다. (--force로 강제 재색인 가능)")
            skipped_count += 1
            continue

        try:
            elements = orchestrator.process_pdf(pdf_path, max_pages=12, max_elements_per_pdf=4)
            total_indexed_elements += len(elements)
            processed_count += 1
            print(f"  [완료] '{pdf_path.name}' -> {len(elements)}개 도표 색인 완료.")
        except Exception as e:
            print(f"  [오류] '{pdf_path.name}' 처리 실패: {e}")

    # 4. 최종 결과 요약
    print("\n" + "=" * 68)
    print(" FigIndex 일괄 색인 파이프라인 최종 결과")
    print("=" * 68)
    print(f"  - 대상 리포트: {len(target_files)}건")
    print(f"  - 신규 처리 리포트: {processed_count}건")
    print(f"  - 스킵된 기존 리포트: {skipped_count}건")
    print(f"  - 이번 실행에서 신규 색인된 도표: {total_indexed_elements}개")

    try:
        col_info = orchestrator.qdrant_client.get_collection(orchestrator.collection_name)
        total_points = col_info.points_count
        print(f"  - Qdrant '{orchestrator.collection_name}' 총 누적 도표: {total_points}개")
    except Exception as e:
        print(f"  - Qdrant 총 포인트 확인 실패: {e}")

    print("=" * 68 + "\n")


if __name__ == "__main__":
    main()
