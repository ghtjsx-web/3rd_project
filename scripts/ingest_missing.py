#!/usr/bin/env python3
"""
ingest_missing.py: data/ 아래 PDF 중 Qdrant에 doc_name이 아직 없는 파일만 골라
기존 orchestrator 파이프라인으로 순서대로 색인하는 스크립트.

개선 사항:
1. Gemini API 호출 단위 공용 rate limiter(분당 최대 14회, 최소 간격 약 4.29초) 적용
2. 문서 하나의 모든 도표 처리가 정상 완료된 후에만 Qdrant에 일괄 upsert (중간 실패 시 미저장 및 실패 목록 기록)
3. parse_rpt_filename에서 증권사 자리가 '미확인'이면 source_org를 파일명에서 가져오지 않고 LLM/표지 추출값 사용
4. --only 옵션으로 파일명 패턴(예: RPT_, 논문 등) 필터링 지원
5. --dry-run 예상 시간을 '도표 수 × 호출 수'(분당 14회 기준)로 정확히 재계산

사용법:
    # 1. 대상 목록 및 예상 시간 확인 (--dry-run)
    python scripts/ingest_missing.py --dry-run
    python scripts/ingest_missing.py --dry-run --only RPT_

    # 2. 실제 색인 실행 (Docker 파이프라인 컨테이너 권장)
    #   docker compose -f figindex/docker-compose.yml run --rm pipeline python /scripts/ingest_missing.py --only RPT_
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# sys.path 설정 (호스트 및 Docker 환경 공통)
_CURRENT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CURRENT_DIR.parent
_FIGINDEX_DIR = _REPO_ROOT / "figindex"
_PIPELINE_DIR = _FIGINDEX_DIR / "pipeline"

for p in (_FIGINDEX_DIR, _PIPELINE_DIR, Path("/app"), Path("/app/shared")):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger(__name__)


def get_default_qdrant_url() -> str:
    """실행 환경(Docker 내부 vs 로컬 호스트)에 맞춰 기본 Qdrant URL을 반환합니다."""
    env_url = os.getenv("QDRANT_URL")
    if env_url:
        return env_url
    if Path("/data/pdfs").exists() or Path("/app/orchestrator.py").exists():
        return "http://qdrant:6333"
    return "http://localhost:6333"


def get_default_data_dir() -> Path:
    """PDF 파일들이 존재하는 기본 데이터 디렉토리를 탐색합니다."""
    candidates = [
        Path(os.getenv("PDFS_DIR", "")),
        Path("/data/pdfs"),
        Path("data/pdfs"),
        Path("figindex/data/pdfs"),
        Path("data"),
        Path("figindex/data"),
    ]
    for cand in candidates:
        if str(cand) and cand.is_dir():
            matched = list(cand.glob("*.pdf"))
            if matched:
                return cand
    return Path("figindex/data/pdfs")


def query_all_indexed_doc_names(qdrant_url: str, collection: str) -> Set[str]:
    """Qdrant REST API scroll을 끝까지 페이징하여 색인된 모든 doc_name을 수집합니다."""
    scroll_url = f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll"
    indexed_names: Set[str] = set()
    next_offset: Optional[Any] = None

    while True:
        payload: Dict[str, Any] = {
            "limit": 100,
            "with_payload": True,
            "with_vector": False,
        }
        if next_offset is not None:
            payload["offset"] = next_offset

        req = urllib.request.Request(
            scroll_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            print(f"[Error] Qdrant scroll 요청 실패 ({scroll_url}): {e}")
            sys.exit(1)

        result = data.get("result", {})
        points = result.get("points", [])
        for pt in points:
            raw_name = pt.get("payload", {}).get("doc_name")
            if raw_name:
                norm_name = unicodedata.normalize("NFC", raw_name).strip()
                indexed_names.add(norm_name)

        next_offset = result.get("next_page_offset")
        if not next_offset:
            break

    return indexed_names


def find_missing_pdfs(
    data_dir: Path,
    indexed_doc_names: Set[str],
    only_pattern: Optional[str] = None,
) -> Tuple[List[Path], int]:
    """데이터 폴더의 PDF 중 Qdrant에 아직 없는 파일 목록과 전체 PDF 수를 반환합니다."""
    all_pdfs = sorted(list(data_dir.glob("*.pdf")))
    # 샘플 파일 제외
    valid_pdfs = [
        p for p in all_pdfs
        if not unicodedata.normalize("NFC", p.name).startswith("sample_")
    ]

    missing_files: List[Path] = []
    for pdf_p in valid_pdfs:
        norm_name = unicodedata.normalize("NFC", pdf_p.name).strip()
        if norm_name in indexed_doc_names:
            continue

        # --only 패턴 필터링 적용
        if only_pattern:
            norm_pat = unicodedata.normalize("NFC", only_pattern).strip().lower()
            if norm_pat not in norm_name.lower():
                continue

        missing_files.append(pdf_p)

    return missing_files, len(valid_pdfs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Qdrant에 없는 미색인 PDF만 골라 orchestrator 파이프라인으로 순서대로 색인합니다."
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="PDF 파일이 있는 디렉토리 (기본값: 자동 감지)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"),
        help="Qdrant 컬렉션 이름 (기본값: figindex_elements_v2)",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default=get_default_qdrant_url(),
        help="Qdrant 서버 URL (기본값: 환경에 맞춰 자동 감지)",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="파일명 패턴 필터링 (예: RPT_, 논문, IR 등 특정 접두어나 문자열을 포함하는 파일만 처리)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 색인을 수행하지 않고 미색인 대상 파일 목록 및 예상 호출 소요시간만 출력하고 종료합니다.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="최대 색인할 문서 수 (0은 미색인 전체 처리)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="429 에러 발생 시 최대 재시도 횟수 (기본값: 5)",
    )
    parser.add_argument(
        "--base-backoff",
        type=float,
        default=5.0,
        help="429 백오프 시작 대기 시간 (초, 기본값: 5.0)",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=60.0,
        help="429 백오프 최대 대기 시간 (초, 기본값: 60.0)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=12,
        help="문서당 최대 검사 페이지 수 (기본값: 12)",
    )
    parser.add_argument(
        "--max-elements",
        type=int,
        default=4,
        help="문서당 최대 추출 도표 수 (기본값: 4)",
    )
    args = parser.parse_args()

    target_data_dir = Path(args.data_dir) if args.data_dir else get_default_data_dir()
    if not target_data_dir.exists():
        print(f"[Error] 데이터 디렉토리를 찾을 수 없습니다: {target_data_dir}")
        sys.exit(1)

    print("=" * 80)
    print(" FigIndex 미색인 PDF 문서 자동 색인 파이프라인 (ingest_missing)")
    print(f" - 대상 디렉토리: {target_data_dir.resolve()}")
    print(f" - Qdrant 컬렉션: {args.collection} ({args.qdrant_url})")
    print(f" - 파일명 필터(--only): {args.only if args.only else '전체 (ALL)'}")
    print(f" - 속도 제한: Gemini API 호출 단위 공용 Rate Limiter 적용 (분당 최대 14회, 최소 ~4.29s)")
    print("=" * 80)

    # 1. Qdrant 기존 색인 목록 수집
    print("[1/3] Qdrant 컬렉션의 색인된 문서 목록 조회 중...")
    indexed_doc_names = query_all_indexed_doc_names(args.qdrant_url, args.collection)
    print(f"  -> Qdrant 기색인 고유 문서: {len(indexed_doc_names)}건")

    # 2. 미색인 대상 파일 탐색 (--only 필터 포함)
    print("[2/3] 데이터 폴더의 미색인 PDF 파일 탐색 중...")
    missing_files, total_pdfs = find_missing_pdfs(
        data_dir=target_data_dir,
        indexed_doc_names=indexed_doc_names,
        only_pattern=args.only,
    )
    filter_label = f" (필터: '{args.only}')" if args.only else ""
    print(f"  -> 폴더 내 유효 PDF: {total_pdfs}건 중 미색인 대상{filter_label}: {len(missing_files)}건")

    if not missing_files:
        print("\n[안내] 처리할 미색인 PDF 파일이 없습니다.")
        return

    # limit 적용
    target_files = missing_files if args.limit <= 0 else missing_files[:args.limit]

    # 3. 미색인 파일 목록 출력
    print("\n" + "-" * 80)
    print(f"                     [미색인 대상 PDF 목록 (총 {len(target_files)}건)]")
    print("-" * 80)
    for idx, pdf_p in enumerate(target_files, 1):
        print(f" {idx:2d}. {pdf_p.name}")
    print("-" * 80)

    # 4. dry-run 모드인 경우: '도표 수 × 호출 수' 기준 예상 소요 시간 계산 후 종료
    if args.dry_run:
        est_elements_per_doc = 3.0  # 문서당 평균 예상 도표 수
        total_est_api_calls = int(len(target_files) * est_elements_per_doc)
        seconds_per_call = 60.0 / 14.0  # 분당 최대 14회 한도 준수 (약 4.29초)
        total_est_seconds = total_est_api_calls * seconds_per_call
        total_est_minutes = total_est_seconds / 60.0

        print(f"\n[사전 진단 보고서 (--dry-run)]")
        print(f"  * 색인 대상 문서: {len(target_files)}건")
        print(f"  * 예상 도표 수: 약 {total_est_api_calls}개 (문서당 평균 {est_elements_per_doc:.0f}개 기준)")
        print(f"  * 예상 Gemini API 호출 수: 약 {total_est_api_calls}회 (캐시 미적중 시)")
        print(f"  * 속도 제한 기준: 분당 최대 14회 (호출 간 최소 {seconds_per_call:.2f}초 강제 대기)")
        print(f"  * 총 예상 소요 시간: 약 {total_est_minutes:.1f}분 ({total_est_seconds:.0f}초)")
        print(f"\n[실제 색인 실행 안내]")
        only_arg = f" --only {args.only}" if args.only else ""
        print(f"  Docker 파이프라인 컨테이너에서 아래 명령어로 실행하세요:")
        print(f"    docker compose -f figindex/docker-compose.yml run --rm pipeline python /scripts/ingest_missing.py{only_arg}\n")
        return

    # 5. 실제 색인 파이프라인 초기화 (lazy import)
    try:
        from orchestrator import ExtractionPipelineOrchestrator
    except ImportError:
        try:
            from pipeline.orchestrator import ExtractionPipelineOrchestrator
        except ImportError as e:
            print("\n[Error] 파이프라인 의존성(PyMuPDF, Kiwi 등)을 로드할 수 없습니다.")
            print(f"  원인: {e}")
            print("\n[권장 실행 방법] 실제 색인은 Docker 파이프라인 컨테이너에서 실행하세요:")
            only_arg = f" --only {args.only}" if args.only else ""
            print(f"  docker compose -f figindex/docker-compose.yml run --rm pipeline python /scripts/ingest_missing.py{only_arg}\n")
            sys.exit(1)

    print("\n[3/3] 파이프라인 초기화 및 순차 색인 시작...")
    # ExtractionPipelineOrchestrator는 환경변수(QDRANT_COLLECTION, QDRANT_URL)에서 설정을 읽음
    if args.collection:
        os.environ["QDRANT_COLLECTION"] = args.collection
    if args.qdrant_url:
        os.environ["QDRANT_URL"] = args.qdrant_url

    orchestrator = ExtractionPipelineOrchestrator()

    success_cnt = 0
    fail_cnt = 0
    total_elements_indexed = 0
    failed_file_logs: List[Tuple[str, str, float]] = []
    pipeline_start_time = time.time()

    print("\n" + "=" * 80)
    print(f"                순차 색인 진행 로그 (총 {len(target_files)}건)")
    print("=" * 80)

    for idx, pdf_p in enumerate(target_files, 1):
        file_start = time.time()
        print(f"\n[{idx}/{len(target_files)}] 시작: {pdf_p.name}")

        # 429 지수 백오프 재시도 루프
        attempt = 1
        current_delay = args.base_backoff
        file_success = False
        elements_count = 0
        last_error = ""

        while attempt <= args.max_retries:
            try:
                # orchestrator.process_pdf는 문서 내 모든 도표 처리가 끝난 뒤에만 일괄 Qdrant upsert 수행
                indexed_elements = orchestrator.process_pdf(
                    pdf_path=pdf_p,
                    max_pages=args.max_pages,
                    max_elements_per_pdf=args.max_elements,
                )
                elements_count = len(indexed_elements)
                file_success = True
                break

            except Exception as e:
                err_str = str(e)
                last_error = err_str
                is_rate_limit = (
                    "429" in err_str
                    or "RESOURCE_EXHAUSTED" in err_str
                    or "quota" in err_str.lower()
                    or "rate" in err_str.lower()
                )

                if is_rate_limit and attempt < args.max_retries:
                    jitter = random.uniform(0.5, 2.0)
                    wait_sec = min(args.max_delay, current_delay + jitter)
                    print(f"  ⚠ [429 RateLimit] Gemini 한도 초과 감지. {wait_sec:.1f}초 대기 후 재시도 (시도 {attempt}/{args.max_retries})...")
                    time.sleep(wait_sec)
                    current_delay = min(args.max_delay, current_delay * 2.0)
                    attempt += 1
                else:
                    print(f"  ✖ [에러 발생] {err_str[:120]}")
                    break

        file_elapsed = time.time() - file_start
        if file_success:
            success_cnt += 1
            total_elements_indexed += elements_count
            print(f"  ✔ [성공] '{pdf_p.name}' | 소요시간: {file_elapsed:.1f}초 | 도표 수: {elements_count}개 (Qdrant 일괄 저장 완료)")
        else:
            fail_cnt += 1
            failed_file_logs.append((pdf_p.name, last_error[:100], file_elapsed))
            print(f"  ✖ [실패] '{pdf_p.name}' | 소요시간: {file_elapsed:.1f}초 | Qdrant 미저장 (에러: {last_error[:100]})")

    total_elapsed = time.time() - pipeline_start_time
    print("\n" + "=" * 80)
    print("                        색인 완료 요약 보고")
    print("=" * 80)
    print(f"  - 처리 대상 문서: {len(target_files)}건")
    print(f"  - 성공: {success_cnt}건 | 실패: {fail_cnt}건")
    print(f"  - 총 색인된 도표 수: {total_elements_indexed}개")
    print(f"  - 총 소요 시간: {total_elapsed / 60.0:.1f}분 ({total_elapsed:.1f}초)")

    if failed_file_logs:
        print("\n" + "-" * 80)
        print(f"                     [실패 문서 목록 (총 {len(failed_file_logs)}건)]")
        print("-" * 80)
        for f_idx, (f_name, f_err, f_time) in enumerate(failed_file_logs, 1):
            print(f" {f_idx:2d}. {f_name} ({f_time:.1f}초) -> {f_err}")
        print("-" * 80)

    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
