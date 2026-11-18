#!/usr/bin/env python3
"""
scripts/list_review_candidates.py

오분류 점검(docs/roles/3_정답셋.md 2단계)용 '점검 후보' 목록을 만든다.
Qdrant의 요소 전체를 읽어, 틀렸을 가능성이 높은 요소만 골라 CSV로 저장한다.
데이터는 읽기만 하고 바꾸지 않는다.

의심 사유 (하나라도 걸리면 후보)
- 검수대기: review_status가 PENDING_REVIEW (확신도가 CONFIDENCE_THRESHOLD 미만)
- 아주작음: 페이지 넓이 대비 bbox 넓이가 SMALL_AREA 미만 (로고·아이콘 가능성)
- 머리말꼬리말: bbox가 페이지 위·아래 띠(EDGE_BAND) 안에만 있음
- 표데이터없음: TABLE인데 table_data가 비어 있음 (유형은 맞고 숫자를 못 읽은 경우가 많음)
- 유형불일치: TABLE이 아닌데 table_data가 있음
- 첫페이지그림: 1페이지의 TABLE이 아닌 요소 (표지 장식 가능성)

정렬: 사유가 많은 순 → 확신도가 낮은 순.

사용법 (저장소 루트, Qdrant 실행 중):
    python scripts/list_review_candidates.py
    python scripts/list_review_candidates.py --limit 80 --out review_candidates.csv
"""
import argparse
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))

try:
    from shared.schemas import CONFIDENCE_THRESHOLD, ElementType, ReviewStatus
    from shared.coords import bbox_area
except ImportError as e:  # pydantic이 없는 PC
    sys.exit(f"shared 모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 후 다시 실행해 주세요.")

SMALL_AREA = 0.01   # 페이지의 1% 미만
EDGE_BAND = 0.10    # 위·아래 10%

CSV_COLUMNS = [
    "번호", "파일명", "페이지 번호", "요소 ID", "캡션", "현재 유형", "의심 사유", "확신도",
    "상세 화면", "판정 (맞음/틀림)", "맞는 유형", "이유", "작성자",
]


def suspicion_reasons(payload: Dict[str, Any]) -> List[str]:
    """요소 payload 하나의 의심 사유 목록을 돌려준다. 없으면 빈 목록."""
    reasons: List[str] = []
    element_type = payload.get("element_type")
    bbox = payload.get("bbox") or [0.0, 0.0, 1.0, 1.0]
    table_data = payload.get("table_data") or {}
    has_rows = bool(table_data.get("rows")) if isinstance(table_data, dict) else False

    if payload.get("review_status") == ReviewStatus.PENDING_REVIEW.value:
        reasons.append("검수대기")
    if bbox_area(bbox) < SMALL_AREA:
        reasons.append("아주작음")
    if bbox[3] <= EDGE_BAND or bbox[1] >= 1.0 - EDGE_BAND:
        reasons.append("머리말꼬리말")
    if element_type == ElementType.TABLE.value and not has_rows:
        reasons.append("표데이터없음")
    elif element_type != ElementType.TABLE.value and has_rows:
        reasons.append("유형불일치")
    if payload.get("page_number") == 1 and element_type != ElementType.TABLE.value:
        reasons.append("첫페이지그림")
    return reasons


def scroll_all(qdrant_url: str, collection: str) -> List[Dict[str, Any]]:
    """컬렉션의 모든 포인트 payload를 읽는다 (벡터 제외)."""
    payloads: List[Dict[str, Any]] = []
    offset = None
    while True:
        body: Dict[str, Any] = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        req = urllib.request.Request(
            f"{qdrant_url}/collections/{collection}/points/scroll",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)["result"]
        payloads.extend(p.get("payload") or {} for p in result["points"])
        offset = result.get("next_page_offset")
        if offset is None:
            return payloads


def build_rows(payloads: List[Dict[str, Any]], frontend_url: str, limit: int) -> List[Dict[str, Any]]:
    candidates = []
    for p in payloads:
        reasons = suspicion_reasons(p)
        if reasons:
            candidates.append((p, reasons))
    candidates.sort(key=lambda c: (-len(c[1]), c[0].get("confidence_score", 1.0)))

    rows = []
    for i, (p, reasons) in enumerate(candidates[:limit], start=1):
        rows.append({
            "번호": i,
            "파일명": p.get("doc_name", ""),
            "페이지 번호": p.get("page_number", ""),
            "요소 ID": p.get("element_id", ""),
            "캡션": p.get("caption", ""),
            "현재 유형": p.get("element_type", ""),
            "의심 사유": ", ".join(reasons),
            "확신도": round(float(p.get("confidence_score", 0.0)), 2),
            "상세 화면": f"{frontend_url}/elements/{p.get('element_id', '')}",
            "판정 (맞음/틀림)": "", "맞는 유형": "", "이유": "", "작성자": "",
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="오분류 점검 후보 목록 CSV 만들기 (읽기 전용)")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"))
    parser.add_argument("--frontend-url", default="http://localhost:3000")
    parser.add_argument("--limit", type=int, default=120, help="후보 최대 개수")
    parser.add_argument("--out", default="review_candidates.csv")
    args = parser.parse_args()

    payloads = scroll_all(args.qdrant_url, args.collection)
    rows = build_rows(payloads, args.frontend_url, args.limit)

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    counts: Dict[str, int] = {}
    for p in payloads:
        for r in suspicion_reasons(p):
            counts[r] = counts.get(r, 0) + 1
    print(f"전체 요소 {len(payloads)}개 (확신도 기준 {CONFIDENCE_THRESHOLD})")
    for reason, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {n}개")
    print(f"후보 {len(rows)}개를 {args.out}에 저장했습니다.")


if __name__ == "__main__":
    main()
