#!/usr/bin/env python3
"""
scripts/check_toc_filter.py

목차 거르기(pipeline/pdf_text.is_toc_page)가 실제 PDF에서 맞게 동작하는지 확인한다. 읽기 전용.
설계서 완료 기준: 11-18 반려한 '요소 아님' 17건 중 15건 이상 건너뜀, 카드 있는 정답 표 14개는 하나도 안 건너뜀.

- 반려 요소: v2에서 review_status=REJECTED인 TABLE 요소의 (문서, 페이지)
- 정답 표: figindex/data/gt/table/links.csv에서 '같은 표'인 표의 (문서, 페이지) (cells.csv에서 문서·페이지)

사용법 (figindex 폴더, PyMuPDF가 있는 pipeline 컨테이너에서):
    docker compose --profile index run --rm pipeline python /scripts/check_toc_filter.py
    docker compose --profile index run --rm pipeline python /scripts/check_toc_filter.py --dump   # 못 거른 페이지의 글자 보기
"""
import csv
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT / "figindex", REPO_ROOT / "figindex" / "pipeline", Path("/app")):
    sys.path.insert(0, str(p))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fitz  # noqa: E402
import pdf_text  # noqa: E402
from pdf_text import is_toc_page  # noqa: E402
from shared.schemas import ElementType, ReviewStatus  # noqa: E402
from diagnose_empty_tables import scroll_all  # noqa: E402

PDFS_DIR = Path(os.getenv("PDFS_DIR", "/data/pdfs"))
GT_DIR = Path(os.getenv("GT_DIR", str(REPO_ROOT / "figindex/data/gt/table")))
if not GT_DIR.exists():
    GT_DIR = Path("/data/gt/table")


def page_is_toc(doc_name: str, page_number: int):
    path = PDFS_DIR / doc_name
    if not path.is_file():
        return None
    with fitz.open(str(path)) as doc:
        return is_toc_page(doc[page_number - 1])


def dump_page(doc_name: str, page_number: int, max_lines: int = 25) -> None:
    """못 거른 페이지가 어떻게 읽히는지: 판단에 쓰는 줄 수와 앞쪽 줄."""
    with fitz.open(str(PDFS_DIR / doc_name)) as doc:
        page = doc[page_number - 1]
        if not pdf_text.has_text_layer(page):
            print("      (텍스트 레이어 없음)")
            return
        text = pdf_text.read_text_in_bbox(page, [0.0, 0.0, 1.0, 1.0])
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    leader = sum(1 for ln in lines if pdf_text._TOC_LEADER_LINE.search(ln))
    numbered = sum(1 for ln in lines if pdf_text._ENDS_WITH_PAGE_NO.search(ln))
    print(f"      줄 {len(lines)}, 점선+쪽번호 {leader}, 쪽번호로 끝남 {numbered}")
    for ln in lines[:max_lines]:
        print(f"      | {ln[:110]}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    dump = "--dump" in sys.argv
    payloads = scroll_all(os.getenv("QDRANT_URL", "http://qdrant:6333"),
                          os.getenv("CHECK_COLLECTION", "figindex_elements_v2"))
    rejected = sorted({(p["doc_name"], p["page_number"]) for p in payloads
                       if p.get("review_status") == ReviewStatus.REJECTED.value
                       and p.get("element_type") == ElementType.TABLE.value})
    pages = {}
    with (GT_DIR / "cells.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pages[r["table_id"]] = (r["doc_name"], int(r["page_number"]))
    with (GT_DIR / "links.csv").open(encoding="utf-8") as f:
        gt = sorted({pages[r["table_id"]] for r in csv.DictReader(f) if r["link_status"] == "같은 표"})

    print(f"[반려 요소 페이지 {len(rejected)}개] 건너뛰어야 함")
    skipped = 0
    for name, page in rejected:
        res = page_is_toc(name, page)
        skipped += bool(res)
        print(f"  {'건너뜀' if res else ('PDF 없음' if res is None else '못 거름')}  {name} p.{page}")
        if dump and res is False:
            dump_page(name, page)
    print(f"[정답 표 페이지 {len(gt)}개] 건너뛰면 안 됨")
    wrongly = 0
    for name, page in gt:
        res = page_is_toc(name, page)
        wrongly += bool(res)
        print(f"  {'잘못 건너뜀' if res else ('PDF 없음' if res is None else '유지')}  {name} p.{page}")
    print(f"\n반려 페이지 건너뜀 {skipped}/{len(rejected)} (기준: 반려 17건 중 15건 이상), 정답 표 잘못 건너뜀 {wrongly}/{len(gt)} (기준 0)")


if __name__ == "__main__":
    main()
