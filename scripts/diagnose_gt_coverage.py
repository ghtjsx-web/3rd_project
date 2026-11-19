#!/usr/bin/env python3
"""
scripts/diagnose_gt_coverage.py

수치 정답셋 표(figindex/data/gt/table/cells.csv)마다, 그 페이지에 카드가 왜 없는지(또는 있는지) 가른다. 읽기 전용.

분류 (표마다 하나)
- 카드 있음(승인):     정답 페이지에 승인된 TABLE 카드가 있음 → 화면 검색으로 연결 가능
- 카드 있음(검수대기): 정답 페이지에 검수 대기 TABLE 카드만 있음 → 화면 검색에 안 나옴, 아래 ID로 연결
- 반려 카드만 있음:    정답 페이지의 TABLE 카드가 모두 반려됨 (목차 오인 등)
- 다른 유형만 있음:    정답 페이지에 CHART·DIAGRAM 카드만 있음 (유형 오분류 가능성)
- 페이지 한도 밖:      정답 페이지가 색인 기본 검사 범위(run_index.py --max-pages 12)를 넘음
- 도표 상한(4개):      문서 카드가 상한 수만큼 있고 모두 정답 페이지 앞쪽 (process_pdf max_elements_per_pdf)
- 탐지 누락:           위에 해당하지 않음 (검사 범위 안인데 카드 없음)

사용법 (저장소 루트, Qdrant 실행 중):
    python scripts/diagnose_gt_coverage.py
    python scripts/diagnose_gt_coverage.py --out gt_coverage.csv
"""
import argparse
import csv
import os
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from shared.schemas import ElementType, ReviewStatus  # noqa: E402
from diagnose_empty_tables import scroll_all  # noqa: E402

DEFAULT_MAX_PAGES = 12      # figindex/pipeline/run_index.py --max-pages 기본값
DEFAULT_MAX_ELEMENTS = 4    # figindex/pipeline/orchestrator.py process_pdf 기본값

STATUS_KO = {
    ReviewStatus.APPROVED.value: "승인",
    ReviewStatus.PENDING_REVIEW.value: "검수대기",
    ReviewStatus.REJECTED.value: "반려",
}
CSV_COLUMNS = ["table_id", "doc_name", "page_number", "caption", "분류", "정답 페이지 카드", "문서 카드 수", "문서 카드 페이지"]


def load_gt_tables(path: Path):
    tables = OrderedDict()
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tables.setdefault(row["table_id"], {
                "doc_name": row["doc_name"], "page_number": int(row["page_number"]), "caption": row["caption"]})
    return tables


def classify(gt, doc_elements, max_pages, max_elements):
    page = gt["page_number"]
    on_page = [e for e in doc_elements if e.get("page_number") == page]
    tables_on_page = [e for e in on_page if e.get("element_type") == ElementType.TABLE.value]
    statuses = {e.get("review_status") for e in tables_on_page}
    if ReviewStatus.APPROVED.value in statuses:
        label = "카드 있음(승인)"
    elif ReviewStatus.PENDING_REVIEW.value in statuses:
        label = "카드 있음(검수대기)"
    elif tables_on_page:
        label = "반려 카드만 있음"
    elif on_page:
        label = "다른 유형만 있음"
    elif page > max_pages:
        label = f"페이지 한도 밖(>{max_pages}p)"
    elif len(doc_elements) >= max_elements and all((e.get("page_number") or 0) < page for e in doc_elements):
        label = f"도표 상한({max_elements}개)"
    else:
        label = "탐지 누락"
    cards = ", ".join(
        f"{e.get('element_id')}({e.get('element_type')}/{STATUS_KO.get(e.get('review_status'), e.get('review_status'))})"
        for e in on_page)
    return label, cards


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="수치 정답셋 표의 카드 유무와 원인 분류 (읽기 전용)")
    ap.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    ap.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"))
    ap.add_argument("--cells", default=str(REPO_ROOT / "figindex/data/gt/table/cells.csv"))
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    ap.add_argument("--max-elements", type=int, default=DEFAULT_MAX_ELEMENTS)
    ap.add_argument("--out", help="결과 CSV 저장 경로 (엑셀용 UTF-8 BOM)")
    args = ap.parse_args()

    payloads = scroll_all(args.qdrant_url, args.collection)
    if not payloads:
        sys.exit(f"컬렉션 {args.collection}에서 읽은 요소가 없습니다. Qdrant가 켜져 있는지 확인해 주세요.")
    by_doc = defaultdict(list)
    for p in payloads:
        by_doc[p.get("doc_name")].append(p)

    rows = []
    counts = defaultdict(int)
    for table_id, gt in load_gt_tables(Path(args.cells)).items():
        doc_elements = by_doc.get(gt["doc_name"], [])
        label, cards = classify(gt, doc_elements, args.max_pages, args.max_elements)
        counts[label] += 1
        pages = sorted({e.get("page_number") for e in doc_elements if e.get("page_number")})
        rows.append({"table_id": table_id, "doc_name": gt["doc_name"], "page_number": gt["page_number"],
                     "caption": gt["caption"], "분류": label, "정답 페이지 카드": cards,
                     "문서 카드 수": len(doc_elements), "문서 카드 페이지": " ".join(map(str, pages))})
        print(f"{table_id} p.{gt['page_number']:<4} {label:<16} 문서 카드 {len(doc_elements)}개 (p.{' '.join(map(str, pages)) or '-'})"
              + (f"\n      정답 페이지: {cards}" if cards else ""))

    print("\n[요약]")
    for label, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {label}: {n}개")
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
