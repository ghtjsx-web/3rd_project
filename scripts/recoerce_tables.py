#!/usr/bin/env python3
"""
scripts/recoerce_tables.py

0.1.1 이전에 색인된 표의 table_data를 지금 규칙(glossary 9절)으로 다시 정리해 시험 컬렉션에 쓴다.
Gemini·OpenAI를 부르지 않는다. 서비스 컬렉션(v2)은 읽기만 한다.

배경 (11-19 eval_tables.py 측정)
- 표 489개 중 300개가 숫자를 '1,202.2', '6.0%' 같은 문자열로 저장 (pipeline_version 0.0.0·0.1.0)
- 0.1.1의 pipeline/table_parse.py coerce_table_data를 거친 표는 0개

하는 일
1. v2에서 TABLE 요소 중 숫자 문자열 칸이 있는 것을 고른다 (반려 제외).
2. 지금 table_data에 coerce_table_data를 다시 적용한다. 숫자 값·행 라벨·열 이름은 바뀌지 않고 저장 형태만 바뀐다.
3. 안전 확인을 통과한 요소만, 벡터는 그대로 두고 payload의 table_data만 바꿔 시험 컬렉션에 쓴다.
   (벡터는 캡션·요약·해시태그로 만들어서 표 값과 무관하다)
   - 행 수, 열 이름, 행 라벨이 그대로인지
   - 모든 칸의 숫자 값이 정리 전과 같은지
   - columns에 없는 키에 값이 있거나, 기존 unit_by_row·unit_by_column 항목이 사라지지 않는지
4. v2 반영은 promote_test_to_service.py로 따로 한다 (결정 8: v2 쓰기는 시험 컬렉션을 거친다).

pipeline_version은 바꾸지 않는다 (추출은 예전 버전이 했고, 바뀐 것은 저장 형태뿐).

사용법 (저장소 루트, Qdrant 실행 중):
    python scripts/recoerce_tables.py --dry-run                      # 세기만
    python scripts/recoerce_tables.py                                # figindex_test_coerce에 씀 (있으면 비우고 다시 만듦)
    python scripts/promote_test_to_service.py --test-collection figindex_test_coerce          # 미리보기
    python scripts/promote_test_to_service.py --test-collection figindex_test_coerce --apply  # 백업 후 v2 반영
    python scripts/eval_tables.py                                    # 저장 규칙 위반 0개인지 확인
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

try:
    from shared.schemas import ElementType, ReviewStatus
    from pipeline.table_parse import coerce_table_data, parse_cell_value
except ImportError as e:
    sys.exit(f"figindex 모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 후 다시 실행해 주세요.")

from eval_tables import count_rule_violations, is_number
from promote_test_to_service import scroll, upsert

DEFAULT_TARGET = "figindex_test_coerce"


def _request(method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def check_same_content(before: Dict[str, Any], after: Dict[str, Any]) -> Optional[str]:
    """정리 전후 표 내용이 같은지. 다르면 이유, 같으면 None."""
    columns = [str(c) for c in before.get("columns") or []]
    if after["columns"] != columns:
        return "열 이름이 바뀜"
    old_rows = [r for r in before.get("rows") or [] if isinstance(r, dict)]
    if len(old_rows) != len(after["rows"]):
        return f"행 수가 바뀜 {len(old_rows)} → {len(after['rows'])}"
    for old in old_rows:
        extra = [k for k, v in old.items() if str(k) not in columns and v not in (None, "")]
        if extra:
            return f"columns에 없는 키에 값이 있음 {extra[:3]}"
    for key in ("unit_by_row", "unit_by_column"):
        lost = set(before.get(key) or {}) - set(after.get(key) or {})
        if lost:
            return f"{key} 항목이 사라짐 {sorted(lost)[:3]}"
    label_col = columns[0]
    for old, new in zip(old_rows, after["rows"]):
        if old.get(label_col) != new.get(label_col):
            return f"행 라벨이 바뀜 '{old.get(label_col)}' → '{new.get(label_col)}'"
        for col in columns[1:]:
            old_value = parse_cell_value(old.get(col))[0]
            new_value = new.get(col)
            if is_number(old_value) or is_number(new_value):
                if not (is_number(old_value) and is_number(new_value) and old_value == new_value):
                    return f"값이 바뀜 ({old.get(label_col)}, {col}) '{old.get(col)}' → '{new_value}'"
    return None


def plan(points: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], str]], Dict[str, int]]:
    """(시험 컬렉션에 쓸 포인트, (건너뛸 포인트, 이유), 버전별 바뀐 칸 수)."""
    to_write, skipped = [], []
    cells_by_version: Dict[str, int] = defaultdict(int)
    for p in points:
        payload = p.get("payload") or {}
        if payload.get("element_type") != ElementType.TABLE.value:
            continue
        if payload.get("review_status") == ReviewStatus.REJECTED.value:
            continue
        table = payload.get("table_data")
        violations = count_rule_violations(table)
        if not violations:
            continue
        coerced, note = coerce_table_data(table)
        if coerced is None:
            skipped.append((p, f"정리 실패: {note}"))
            continue
        after = coerced.model_dump(mode="json")
        reason = check_same_content(table, after)
        if reason:
            skipped.append((p, reason))
            continue
        if count_rule_violations(after):
            skipped.append((p, "정리 후에도 숫자 문자열이 남음"))
            continue
        new_payload = {**payload, "table_data": after}
        to_write.append({"id": p["id"], "vector": p.get("vector"), "payload": new_payload})
        cells_by_version[str(payload.get("pipeline_version") or "없음")] += violations
    return to_write, skipped, dict(cells_by_version)


def recreate_collection(qdrant_url: str, source: str, target: str) -> None:
    """source와 같은 벡터 설정으로 target을 새로 만든다 (있으면 지움)."""
    params = _request("GET", f"{qdrant_url}/collections/{source}")["result"]["config"]["params"]
    try:
        _request("DELETE", f"{qdrant_url}/collections/{target}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    body: Dict[str, Any] = {"vectors": params["vectors"]}
    if params.get("sparse_vectors"):
        body["sparse_vectors"] = params["sparse_vectors"]
    _request("PUT", f"{qdrant_url}/collections/{target}", body)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="예전 표의 table_data를 지금 규칙으로 정리해 시험 컬렉션에 씀")
    ap.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    ap.add_argument("--source", default="figindex_elements_v2", help="읽기만 하는 서비스 컬렉션")
    ap.add_argument("--target", default=DEFAULT_TARGET, help="figindex_test_로 시작하는 시험 컬렉션 (새로 만듦)")
    ap.add_argument("--dry-run", action="store_true", help="세기만 하고 쓰지 않음")
    args = ap.parse_args()

    if not args.target.startswith("figindex_test_"):
        sys.exit("--target은 figindex_test_로 시작해야 합니다 (서비스 컬렉션에 직접 쓰지 않음).")

    points = scroll(args.qdrant_url, args.source, with_vector=True)
    to_write, skipped, cells_by_version = plan(points)

    print(f"[{'세기만' if args.dry_run else '시험 컬렉션 쓰기'}] {args.source} → {args.target}")
    print(f"  정리할 표 {len(to_write)}개, 건너뜀 {len(skipped)}개")
    for version, n in sorted(cells_by_version.items()):
        print(f"  pipeline_version {version}: 숫자로 바뀔 칸 {n}개")
    for p, reason in skipped:
        pl = p.get("payload") or {}
        print(f"  건너뜀 {pl.get('element_id')}  {pl.get('doc_name')} p.{pl.get('page_number')}  {reason}")

    if args.dry_run or not to_write:
        return
    recreate_collection(args.qdrant_url, args.source, args.target)
    upsert(args.qdrant_url, args.target, to_write)
    print(f"{args.target}에 {len(to_write)}개를 썼습니다.")
    print(f"다음: python scripts/promote_test_to_service.py --test-collection {args.target}")


if __name__ == "__main__":
    main()
