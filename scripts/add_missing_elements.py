#!/usr/bin/env python3
"""
scripts/add_missing_elements.py

이미 색인된 문서에서 '빠진 요소만' 찾아 시험 컬렉션에 추가한다 (결정 19·22).

왜 필요한가
- 예전 색인은 run_index.py 기본값(앞 12쪽, 도표 4개)이라 뒤쪽 표가 빠졌다 (수치 정답셋 '요소 없음' 16개).
- 문서를 통째로 다시 색인하면 element_id가 새로 만들어져(cropper.py가 무작위 발급)
  수치 정답셋 연결 14개, 검수 결과, 표 정리 내용이 깨진다.
- 그래서 0.1.3 규칙(전체 쪽, 목차 건너뛰기)으로 후보를 다시 찾되, 기존 요소와 겹치는 후보
  (IoU ≥ 0.5 또는 후보의 3/4 이상이 기존 박스 안)는 크롭·Gemini 분석 없이 건너뛰고 새 후보만 처리한다.
- 새 요소는 기존 요소와 같은 doc_id와 문서 메타데이터(종목·증권사·발행일 등)를 물려받는다.

안전장치
- 기본은 미리보기(dry-run): Gemini·OpenAI를 부르지 않고, 문서별 새 후보 수와 예상 시간만 보여 준다.
- --apply여도 쓰는 곳은 figindex_test_로 시작하는 시험 컬렉션뿐이다 (서비스 v1·v2, figindex_test_upload 금지).
  서비스(v2) 반영은 확인 후 promote_test_to_service.py --new-only로 따로 한다.
- 시험 컬렉션에 이미 넣은 요소도 '기존 요소'로 보므로, 중간에 멈췄다가 다시 돌려도 이어서 처리한다.
- 기존 요소가 하나도 없는 문서(미색인 문서)는 건너뛴다. 그런 문서는 업로드 작업자나 ingest_missing.py로 처리한다.

실행 (figindex 폴더, Qdrant 실행 중, 업로드 작업자는 멈춘 상태: docker compose stop worker)
    # 1) 미리보기: 수치 정답셋 '요소 없음' 문서 전체
    docker compose --profile index run --rm pipeline python /scripts/add_missing_elements.py --from-gt
    # 2) 한 문서만 먼저 시험
    docker compose --profile index run --rm pipeline python /scripts/add_missing_elements.py \\
        --doc RPT_20261109_한국타이어앤테크놀로지_메리츠증권.pdf --apply --collection figindex_test_addmissing
    # 3) 전체 실행
    docker compose --profile index run --rm pipeline python /scripts/add_missing_elements.py \\
        --from-gt --apply --collection figindex_test_addmissing
    # 4) 서비스 반영 미리보기 → 반영 (저장소 루트)
    python scripts/promote_test_to_service.py --test-collection figindex_test_addmissing --new-only
    python scripts/promote_test_to_service.py --test-collection figindex_test_addmissing --new-only --apply
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# 컨테이너(/app = pipeline, /app/shared)와 저장소 루트 양쪽에서 실행되게 경로를 잡는다
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (Path("/app"), _REPO_ROOT / "figindex", _REPO_ROOT / "figindex" / "pipeline"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from element_match import (  # noqa: E402
    doc_overrides_from_payload,
    group_bboxes_by_page,
    plan_new_candidates,
    single_doc_id,
)

PROTECTED_COLLECTIONS = {"figindex_elements", "figindex_elements_v2", "figindex_test_upload"}
GEMINI_CALLS_PER_MINUTE = 14  # 무료 티어, extractor.GeminiRateLimiter와 같은 값
DEFAULT_MAX_ELEMENTS = 40     # 업로드 작업자(index_document)와 같은 상한, 새 요소만 센다
LINK_MISSING = "요소 없음"


def check_target_collection(name: str) -> None:
    if name in PROTECTED_COLLECTIONS:
        raise SystemExit(f"'{name}'에는 쓸 수 없습니다. --collection figindex_test_<이름> 으로 실행해 주세요.")
    if not name.startswith("figindex_test_"):
        raise SystemExit(f"시험 컬렉션 이름은 figindex_test_로 시작해야 합니다: '{name}'")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def gt_missing_pages(gt_dir: Path) -> Dict[str, Set[int]]:
    """수치 정답셋에서 '요소 없음'으로 연결된 표의 {doc_name: {page_number}}."""
    links_path, cells_path = gt_dir / "links.csv", gt_dir / "cells.csv"
    if not links_path.exists() or not cells_path.exists():
        raise SystemExit(f"수치 정답셋 파일이 없습니다: {links_path}, {cells_path}")
    with links_path.open(encoding="utf-8-sig") as f:
        missing_tables = {r["table_id"] for r in csv.DictReader(f) if r.get("link_status") == LINK_MISSING}
    pages: Dict[str, Set[int]] = {}
    with cells_path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["table_id"] in missing_tables:
                pages.setdefault(nfc(r["doc_name"]), set()).add(int(r["page_number"]))
    return pages


def find_pdf(pdfs_dir: Path, doc_name: str) -> Optional[Path]:
    """pdfs 폴더(하위 폴더 포함)에서 이름이 같은 PDF를 찾는다. 한글 조합 방식(NFC/NFD) 차이는 무시한다."""
    direct = pdfs_dir / doc_name
    if direct.exists():
        return direct
    target = nfc(doc_name)
    for path in pdfs_dir.rglob("*.pdf"):
        if nfc(path.name) == target:
            return path
    return None


def scroll_doc_payloads(client, collection: str, doc_name: str) -> List[Dict[str, Any]]:
    """컬렉션에서 doc_name이 같은 요소 payload 전체. 컬렉션이 없으면 빈 목록."""
    from qdrant_client.http import models as qmodels

    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        return []
    payloads: List[Dict[str, Any]] = []
    offset = None
    flt = qmodels.Filter(must=[qmodels.FieldCondition(key="doc_name", match=qmodels.MatchValue(value=doc_name))])
    while True:
        points, offset = client.scroll(collection_name=collection, scroll_filter=flt, limit=256,
                                       offset=offset, with_payload=True, with_vectors=False)
        payloads.extend(p.payload or {} for p in points)
        if offset is None:
            return payloads


def candidates_by_page(pdf_path: Path, cropper) -> Dict[int, List[List[float]]]:
    """0.1.3 규칙(전체 쪽, 목차 건너뛰기)으로 찾은 후보 박스 {page_number: [[x0, y0, x1, y1], ...]}. 크롭은 하지 않는다."""
    import fitz
    from pdf_text import is_toc_page
    from shared.coords import from_legacy_yxyx

    result: Dict[int, List[List[float]]] = {}
    with fitz.open(str(pdf_path)) as doc:
        for page_number in range(1, len(doc) + 1):
            page = doc[page_number - 1]
            if is_toc_page(page):
                continue
            boxes = [from_legacy_yxyx(c["bbox"]) for c in cropper.detect_candidate_boxes(page)]
            if boxes:
                result[page_number] = boxes
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="기존 요소는 그대로 두고 빠진 요소만 시험 컬렉션에 추가 (기본: 미리보기)")
    parser.add_argument("--from-gt", action="store_true", help="수치 정답셋 '요소 없음' 문서를 대상으로 (links.csv·cells.csv)")
    parser.add_argument("--doc", action="append", default=[], help="대상 PDF 파일명 (여러 번 쓸 수 있음)")
    parser.add_argument("--gt-dir", default=os.getenv("GT_TABLE_DIR", "/data/gt/table"))
    parser.add_argument("--pdfs-dir", default=os.getenv("PDFS_DIR", "/data/pdfs"))
    parser.add_argument("--source-collection", default="figindex_elements_v2", help="기존 요소를 읽을 컬렉션 (읽기만 함)")
    parser.add_argument("--collection", default=None, help="새 요소를 쓸 시험 컬렉션 (--apply일 때 필수)")
    parser.add_argument("--max-elements", type=int, default=DEFAULT_MAX_ELEMENTS, help="문서당 새 요소 상한")
    parser.add_argument("--apply", action="store_true", help="실제로 Gemini 분석 후 시험 컬렉션에 저장")
    args = parser.parse_args()

    target_pages: Dict[str, Set[int]] = gt_missing_pages(Path(args.gt_dir)) if args.from_gt else {}
    for name in args.doc:
        target_pages.setdefault(nfc(name), set())
    if not target_pages:
        raise SystemExit("대상 문서가 없습니다. --from-gt 또는 --doc 파일명 을 지정해 주세요.")
    if args.apply:
        if not args.collection:
            raise SystemExit("--apply에는 --collection figindex_test_<이름> 이 필요합니다.")
        check_target_collection(args.collection)

    from cropper import PDFCropper
    from orchestrator import get_pipeline_qdrant_client

    client = get_pipeline_qdrant_client(
        os.getenv("QDRANT_MODE", "server"),
        os.getenv("QDRANT_URL", "http://qdrant:6333"),
        os.getenv("QDRANT_LOCAL_PATH", "/data/qdrant_local"),
    )
    cropper = PDFCropper()
    pdfs_dir = Path(args.pdfs_dir)
    label = "실행" if args.apply else "미리보기"
    print(f"[{label}] 대상 {len(target_pages)}개 문서, 기존 요소: {args.source_collection}"
          + (f" + {args.collection}" if args.collection else "") + f", 문서당 새 요소 상한 {args.max_elements}")

    plans: List[Dict[str, Any]] = []
    for doc_name in sorted(target_pages):
        pdf_path = find_pdf(pdfs_dir, doc_name)
        if pdf_path is None:
            print(f"  ✖ {doc_name}: PDF를 찾지 못함 ({pdfs_dir})")
            continue
        source_payloads = scroll_doc_payloads(client, args.source_collection, doc_name)
        if not source_payloads:
            print(f"  ✖ {doc_name}: {args.source_collection}에 기존 요소가 없음 → 업로드 작업자나 ingest_missing.py로 처리")
            continue
        test_payloads = scroll_doc_payloads(client, args.collection, doc_name) if args.collection else []
        try:
            doc_id = single_doc_id(source_payloads + test_payloads)
        except ValueError as e:
            print(f"  ✖ {doc_name}: {e} → 건너뜀")
            continue
        existing = group_bboxes_by_page(source_payloads + test_payloads)
        plan = plan_new_candidates(candidates_by_page(pdf_path, cropper), existing, args.max_elements)
        wanted = sorted(target_pages[doc_name])
        reached = [p for p in wanted if p in plan["new_pages"]]
        not_reached = [p for p in wanted if p not in plan["new_pages"]]
        print(f"  • {doc_name}: 기존 {len(source_payloads)}개(+시험 {len(test_payloads)}개), "
              f"새 후보 {len(plan['new_pages'])}개 (상한 초과 {len(plan['over_cap_pages'])}개), 겹쳐서 건너뜀 {plan['skipped_existing']}개")
        if wanted:
            msg = f"      정답셋 페이지 {wanted}: 새 후보 있음 {reached}"
            if not_reached:
                msg += f", 없음 {not_reached} (이미 있는 요소와 겹치거나, 규칙이 못 찾거나, 상한 밖)"
            print(msg)
        plans.append({"doc_name": doc_name, "pdf_path": pdf_path, "doc_id": doc_id,
                      "existing": existing, "overrides": doc_overrides_from_payload(source_payloads[0]),
                      "new_count": len(plan["new_pages"])})

    total_new = sum(p["new_count"] for p in plans)
    minutes = math.ceil(total_new / GEMINI_CALLS_PER_MINUTE)
    print(f"[{label}] 새 후보 합계 {total_new}개 → Gemini 약 {total_new}회, 약 {minutes}분 "
          f"(분당 {GEMINI_CALLS_PER_MINUTE}회 기준, 캐시에 있으면 더 빠름)")
    if not args.apply:
        print("실제로 처리하려면 --apply --collection figindex_test_<이름> 을 붙여 다시 실행하세요. "
              "업로드 작업자는 먼저 멈춰 주세요: docker compose stop worker")
        return

    from orchestrator import ExtractionPipelineOrchestrator
    from worker import ensure_collection

    orchestrator = ExtractionPipelineOrchestrator()
    orchestrator.collection_name = args.collection
    ensure_collection(orchestrator.qdrant_client, args.collection, template=args.source_collection)

    added_total, failed = 0, []
    for plan in plans:
        if plan["new_count"] == 0:
            continue
        print(f"[실행] {plan['doc_name']} (doc_id={plan['doc_id']}, 새 후보 {plan['new_count']}개)")
        try:
            added = orchestrator.process_pdf(
                plan["pdf_path"],
                max_pages=None,
                max_elements_per_pdf=args.max_elements,
                doc_id=plan["doc_id"],
                skip_toc=True,
                existing_bboxes=plan["existing"],
                doc_overrides=plan["overrides"],
            )
        except Exception as e:  # 한 문서가 실패해도 다음 문서로 (실패 문서는 시험 컬렉션에 아무것도 저장되지 않음)
            failed.append(plan["doc_name"])
            print(f"  ✖ 실패: {type(e).__name__}: {str(e)[:200]}")
            continue
        added_total += len(added)
        for element in added:
            print(f"  + {element.element_id}  p.{element.page_number}  {element.element_type.value}  "
                  f"{(element.caption or '')[:40]}  ({element.review_status.value})")

    print(f"[실행] 추가 {added_total}개 → {args.collection}, 실패 문서 {len(failed)}개 {failed}")
    print("다음: python scripts/promote_test_to_service.py --test-collection "
          f"{args.collection} --new-only  (미리보기 후 --apply)")


if __name__ == "__main__":
    main()
