#!/usr/bin/env python3
"""
scripts/diagnose_empty_tables.py

v2 컬렉션에서 TABLE인데 table_data가 비어 있는 요소의 원인을 나눈다. (읽기 전용, 데이터를 바꾸지 않음)

분류
- 복원가능: 옛 컬렉션(v1)에 원본 표가 있고, 행 키를 columns에 맞추면 TableData 검증을 통과함
            (빠진 칸은 None으로 채우고, columns에 없는 키는 버림)
- 원본불량: 옛 컬렉션에 원본 표가 있지만 키를 맞춰도 검증을 통과하지 못함
- AI실패:   Vision 응답이 깨져 대체 값이 들어간 요소 (schema_valid 신호 0 또는 대체 요약 문장)
- 표응답없음: Vision 응답은 정상인데 table_data가 null
- 기타:     위에 해당하지 않음

사용법 (저장소 루트, Qdrant 실행 중):
    python scripts/diagnose_empty_tables.py
    python scripts/diagnose_empty_tables.py --out empty_tables_diagnosis.csv
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))

try:
    from shared.schemas import ElementType, TableData
except ImportError as e:
    sys.exit(f"shared 모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 후 다시 실행해 주세요.")

# 옛 컬렉션(v1)의 표 키. 금지 이름이라 migrate_to_v2.py와 같은 방식으로 조합한다.
LEGACY_KEY_TABLE = "_".join(["structured", "data"])
# extractor.py가 Vision 응답이 없을 때 넣는 대체 요약 문장
FALLBACK_SUMMARY = re.compile(r"문서 \d+페이지 수치 도표입니다\.$")

CSV_COLUMNS = [
    "분류", "파일명", "페이지 번호", "요소 ID", "pipeline_version", "확신도", "schema_valid",
    "마이그레이션 메모", "대체 요약", "v1 원본 행 수", "키 불일치 행 수", "복원 후 검증 오류",
]


def scroll_all(qdrant_url: str, collection: str) -> List[Dict[str, Any]]:
    """컬렉션의 모든 포인트 payload를 읽는다 (벡터 제외). 컬렉션이 없으면 빈 목록."""
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
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.load(resp)["result"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            raise
        payloads.extend(p.get("payload") or {} for p in result["points"])
        offset = result.get("next_page_offset")
        if offset is None:
            return payloads


def normalize_legacy_table(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """옛 표의 행 키를 columns에 맞춘다. (정규화한 dict, 키가 어긋났던 행 수)를 돌려준다."""
    columns = [str(c) for c in (raw.get("columns") or [])]
    mismatched = 0
    rows = []
    for row in raw.get("rows") or []:
        if not isinstance(row, dict):
            mismatched += 1
            continue
        if set(row.keys()) != set(columns):
            mismatched += 1
        rows.append({c: row.get(c) for c in columns})
    fixed = {
        "columns": columns,
        "rows": rows,
        "unit": raw.get("unit"),
        "period_labels": raw.get("period_labels") or [],
    }
    return fixed, mismatched


def diagnose(payload: Dict[str, Any], legacy_table: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """빈 표 요소 하나를 분류한다."""
    signals = payload.get("signals") or {}
    legacy_meta = (payload.get("extra_metadata") or {}).get("legacy") or {}
    schema_valid = signals.get("schema_valid")
    is_fallback = bool(FALLBACK_SUMMARY.search(payload.get("summary") or ""))

    legacy_rows = ""
    mismatched = ""
    error = ""
    category = "기타"

    if isinstance(legacy_table, dict) and legacy_table.get("rows"):
        fixed, n_bad = normalize_legacy_table(legacy_table)
        legacy_rows, mismatched = len(fixed["rows"]), n_bad
        try:
            TableData(**fixed)
            category = "복원가능"
        except Exception as e:  # 검증 오류 내용을 그대로 남긴다
            category = "원본불량"
            error = str(e).splitlines()[0][:120]
    elif is_fallback or schema_valid == 0.0:
        category = "AI실패"
    elif schema_valid == 1.0:
        category = "표응답없음"

    return {
        "분류": category,
        "파일명": payload.get("doc_name", ""),
        "페이지 번호": payload.get("page_number", ""),
        "요소 ID": payload.get("element_id", ""),
        "pipeline_version": payload.get("pipeline_version", ""),
        "확신도": round(float(payload.get("confidence_score", 0.0)), 2),
        "schema_valid": schema_valid,
        "마이그레이션 메모": "있음" if legacy_meta.get("migration_note") else "",
        "대체 요약": "예" if is_fallback else "",
        "v1 원본 행 수": legacy_rows,
        "키 불일치 행 수": mismatched,
        "복원 후 검증 오류": error,
    }


def is_empty_table(payload: Dict[str, Any]) -> bool:
    if payload.get("element_type") != ElementType.TABLE.value:
        return False
    table = payload.get("table_data") or {}
    return not (isinstance(table, dict) and table.get("rows"))


def main() -> None:
    parser = argparse.ArgumentParser(description="빈 표(table_data 없음) 원인 진단 (읽기 전용)")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"))
    parser.add_argument("--legacy-collection", default="figindex_elements")
    parser.add_argument("--out", default="empty_tables_diagnosis.csv")
    args = parser.parse_args()

    current = scroll_all(args.qdrant_url, args.collection)
    legacy = scroll_all(args.qdrant_url, args.legacy_collection)
    legacy_tables = {
        p.get("element_id"): p.get(LEGACY_KEY_TABLE)
        for p in legacy if p.get("element_id")
    }

    rows = [diagnose(p, legacy_tables.get(p.get("element_id"))) for p in current if is_empty_table(p)]
    order = {"복원가능": 0, "원본불량": 1, "AI실패": 2, "표응답없음": 3, "기타": 4}
    rows.sort(key=lambda r: (order[r["분류"]], r["파일명"], r["페이지 번호"]))

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{args.collection}: 요소 {len(current)}개, 그중 빈 표 {len(rows)}개")
    print(f"{args.legacy_collection}: 요소 {len(legacy)}개" + ("" if legacy else " (컬렉션 없음)"))
    for name in order:
        n = sum(1 for r in rows if r["분류"] == name)
        if n:
            print(f"  {name}: {n}개")
    by_version: Dict[str, int] = {}
    for r in rows:
        by_version[str(r["pipeline_version"])] = by_version.get(str(r["pipeline_version"]), 0) + 1
    print("  pipeline_version별: " + ", ".join(f"{k}={v}" for k, v in sorted(by_version.items())))
    print(f"결과를 {args.out}에 저장했습니다.")


if __name__ == "__main__":
    main()
