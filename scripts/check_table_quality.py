#!/usr/bin/env python3
"""
scripts/check_table_quality.py

v2의 TABLE 요소를 읽기만 해서 두 가지를 확인한다. 데이터는 바꾸지 않는다.

1) 행 이름 열 누락 의심 (--out-missing)
   저장된 표의 첫 열 값이 거의 전부 숫자인 표. 행 이름(BPS, 목표주가 …)이 통째로 빠진 경우다.
   이런 표는 비교 엔진·검색에서 조용히 빠진다 (11-23 SK하이닉스 iM fig-6086b1030698 사례).

2) 수치 정답셋 '요소 없음' 재연결 후보 (--out-links)
   figindex/data/gt/table/links.csv에서 '요소 없음'인 표마다, 같은 문서·같은 페이지의 TABLE을 찾아
   캡션 유사도와 정답 행 이름 겹침으로 순위를 매긴다. 사람이 1순위를 확인한 뒤 links.csv에 반영한다.

사용법 (저장소 루트, Qdrant 실행 중):
    python scripts/check_table_quality.py
    python scripts/check_table_quality.py --out-missing C:\\workAi\\figindex_work\\label_missing.csv --out-links C:\\workAi\\figindex_work\\gt_link_candidates.csv
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))

try:
    from shared.schemas import ElementType
except ImportError as e:  # pydantic이 없는 PC
    sys.exit(f"shared 모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 후 다시 실행해 주세요.")

GT_DIR = REPO_ROOT / "figindex" / "data" / "gt" / "table"
LINK_MISSING = "요소 없음"

NUMERIC_SHARE = 0.75  # 첫 열 값 중 숫자 비율이 이 이상이면 행 이름 누락 의심 (확신도 임계값과 무관)
MIN_ROWS = 2

_NUMERIC_RE = re.compile(r"^[\s(△▲▼+\-−]*[\d][\d,]*(\.\d+)?\s*[%)배원]?\s*\)?$")


def nfc(text: Any) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def norm_text(text: Any) -> str:
    """비교용: NFKC, 공백·기호 제거, 소문자."""
    t = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[\s\W_]+", "", t)


def is_numeric_cell(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(_NUMERIC_RE.match(value.strip()))
    return False


def first_column_values(table_data: Dict[str, Any]) -> List[Any]:
    columns = table_data.get("columns") or []
    rows = table_data.get("rows") or []
    if not columns:
        return []
    first = columns[0]
    return [row.get(first) for row in rows if isinstance(row, dict)]


def label_column_missing(table_data: Optional[Dict[str, Any]]) -> Tuple[bool, float]:
    """(의심 여부, 첫 열 숫자 비율). 빈 칸은 세지 않는다."""
    if not isinstance(table_data, dict):
        return False, 0.0
    values = [v for v in first_column_values(table_data) if v not in (None, "")]
    if len(values) < MIN_ROWS:
        return False, 0.0
    share = sum(1 for v in values if is_numeric_cell(v)) / len(values)
    return share >= NUMERIC_SHARE, share


def caption_similarity(a: Any, b: Any) -> float:
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def row_label_overlap(gt_labels: Iterable[str], table_data: Optional[Dict[str, Any]]) -> float:
    """정답 행 이름 중 요소 표의 첫 열(또는 어느 칸)에 나오는 비율."""
    gt = {norm_text(x) for x in gt_labels if norm_text(x)}
    if not gt or not isinstance(table_data, dict):
        return 0.0
    cells = set()
    for row in table_data.get("rows") or []:
        if isinstance(row, dict):
            for v in row.values():
                if isinstance(v, str) and norm_text(v):
                    cells.add(norm_text(v))
    for c in table_data.get("columns") or []:
        cells.add(norm_text(c))
    return sum(1 for g in gt if g in cells) / len(gt)


def rank_candidates(
    gt_caption: str, gt_labels: Sequence[str], candidates: Sequence[Dict[str, Any]]
) -> List[Tuple[float, float, float, Dict[str, Any]]]:
    """[(점수, 캡션 유사도, 행 이름 겹침, payload)] 점수 내림차순. 점수 = 0.5·캡션 + 0.5·행 이름."""
    ranked = []
    for payload in candidates:
        cap = caption_similarity(gt_caption, payload.get("caption"))
        rows = row_label_overlap(gt_labels, payload.get("table_data"))
        ranked.append((round(0.5 * cap + 0.5 * rows, 3), round(cap, 3), round(rows, 3), payload))
    ranked.sort(key=lambda x: -x[0])
    return ranked


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


def read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, columns: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="표 품질 점검 (읽기 전용)")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"))
    parser.add_argument("--frontend-url", default="http://localhost:3000")
    parser.add_argument("--out-missing", default="label_missing_tables.csv")
    parser.add_argument("--out-links", default="gt_link_candidates.csv")
    args = parser.parse_args()

    payloads = scroll_all(args.qdrant_url, args.collection)
    tables = [p for p in payloads if p.get("element_type") == ElementType.TABLE.value]
    print(f"[읽음] {args.collection}: 전체 {len(payloads)}개, TABLE {len(tables)}개")

    # 1) 행 이름 열 누락 의심
    missing_rows = []
    for p in tables:
        suspect, share = label_column_missing(p.get("table_data"))
        if suspect:
            values = first_column_values(p["table_data"])
            missing_rows.append({
                "요소 ID": p.get("element_id"),
                "파일명": p.get("doc_name"),
                "페이지 번호": p.get("page_number"),
                "캡션": p.get("caption"),
                "검수 상태": p.get("review_status"),
                "첫 열 이름": (p["table_data"].get("columns") or [""])[0],
                "첫 열 숫자 비율": round(share, 2),
                "첫 열 앞 3개": " | ".join(str(v) for v in values[:3]),
                "모델": p.get("model_name"),
                "상세 화면": f"{args.frontend_url}/elements/{p.get('element_id')}",
            })
    missing_rows.sort(key=lambda r: (str(r["파일명"]), int(r["페이지 번호"] or 0)))
    write_csv(Path(args.out_missing), list(missing_rows[0].keys()) if missing_rows else ["요소 ID"], missing_rows)
    print(f"[1] 행 이름 열 누락 의심: {len(missing_rows)}개 → {args.out_missing}")
    for r in missing_rows[:20]:
        print(f"    {r['요소 ID']}  {r['파일명']} p.{r['페이지 번호']}  {str(r['캡션'])[:40]}  ({r['검수 상태']})")

    # 2) 수치 정답셋 '요소 없음' 재연결 후보
    links = read_csv(GT_DIR / "links.csv")
    cells = read_csv(GT_DIR / "cells.csv")
    gt_info: Dict[str, Dict[str, Any]] = {}
    for c in cells:
        info = gt_info.setdefault(c["table_id"], {"doc_name": nfc(c["doc_name"]), "page_number": int(c["page_number"]),
                                                  "caption": c["caption"], "labels": []})
        if c["row_label"] and c["row_label"] not in info["labels"]:
            info["labels"].append(c["row_label"])
    by_page: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for p in tables:
        by_page.setdefault((nfc(p.get("doc_name")), int(p.get("page_number") or 0)), []).append(p)

    link_rows = []
    for link in links:
        if link.get("link_status") != LINK_MISSING:
            continue
        info = gt_info.get(link["table_id"])
        if not info:
            continue
        ranked = rank_candidates(info["caption"], info["labels"], by_page.get((info["doc_name"], info["page_number"]), []))
        best = ranked[0] if ranked else None
        link_rows.append({
            "표 ID": link["table_id"],
            "파일명": info["doc_name"],
            "페이지 번호": info["page_number"],
            "정답 캡션": info["caption"],
            "후보 수": len(ranked),
            "1순위 요소 ID": best[3].get("element_id") if best else "",
            "1순위 캡션": best[3].get("caption") if best else "",
            "점수": best[0] if best else "",
            "캡션 유사도": best[1] if best else "",
            "행 이름 겹침": best[2] if best else "",
            "2순위 요소 ID": ranked[1][3].get("element_id") if len(ranked) > 1 else "",
            "2순위 점수": ranked[1][0] if len(ranked) > 1 else "",
            "상세 화면": f"{args.frontend_url}/elements/{best[3].get('element_id')}" if best else "",
        })
    write_csv(Path(args.out_links), list(link_rows[0].keys()) if link_rows else ["표 ID"], link_rows)
    print(f"[2] '요소 없음' {len(link_rows)}개 재연결 후보 → {args.out_links}")
    for r in link_rows:
        print(f"    {r['표 ID']}  p.{r['페이지 번호']}  1순위 {r['1순위 요소 ID'] or '-'}  점수 {r['점수']}"
              f" (캡션 {r['캡션 유사도']}, 행 {r['행 이름 겹침']})  후보 {r['후보 수']}개")
    print("데이터는 바꾸지 않았습니다. 1순위가 맞는지 상세 화면으로 확인한 뒤 links.csv에 반영합니다.")


if __name__ == "__main__":
    main()
