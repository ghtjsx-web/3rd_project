#!/usr/bin/env python3
"""
scripts/restore_tables_from_v1.py

v1→v2 이전(migrate_to_v2.py) 때 행 키가 columns와 달라 버려진 표를 옛 컬렉션 원본에서 되살린다.
AI를 다시 호출하지 않는다.

대상: v2의 TABLE 중 table_data가 비어 있고, 옛 컬렉션(figindex_elements)에 같은 element_id의 원본 표가 있으며,
      행 키를 columns에 맞춘 뒤(빠진 칸은 None, 남는 키는 버림) ElementSearchPayload 검증을 통과하는 요소

바꾸는 필드 (그 밖의 필드는 건드리지 않음)
- table_data: 정규화한 원본 표
- review_status: 이전 때 APPROVED → PENDING_REVIEW로 내려간 기록(extra_metadata.legacy.migration_note)이
                 있으면 APPROVED로 되돌림. 기록이 없으면 그대로 둠
- extra_metadata.legacy.restore_note: 복원 기록

안전장치
- 기본은 미리보기(dry-run). --apply를 붙여야 쓴다.
- 쓰기 전에 바꿀 세 필드의 원래 값을 백업 JSON으로 저장한다. --rollback 백업파일 로 되돌린다.
- 저장할 payload 전체를 ElementSearchPayload로 검증하고, 통과한 것만 쓴다.

사용법 (저장소 루트, Qdrant 실행 중):
    python scripts/restore_tables_from_v1.py                 # 미리보기
    python scripts/restore_tables_from_v1.py --apply         # 백업 후 반영
    python scripts/restore_tables_from_v1.py --rollback restore_backup_YYYYMMDD-HHMMSS.json
"""
import argparse
import copy
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from shared.schemas import ElementSearchPayload, ReviewStatus
    from diagnose_empty_tables import LEGACY_KEY_TABLE, is_empty_table, normalize_legacy_table
except ImportError as e:
    sys.exit(f"모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 후, 저장소 루트에서 실행해 주세요.")

CHANGED_FIELDS = ["table_data", "review_status", "extra_metadata"]


def _post(url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def scroll_points(qdrant_url: str, collection: str) -> List[Dict[str, Any]]:
    """컬렉션의 모든 포인트를 {id, payload}로 읽는다 (벡터 제외)."""
    points: List[Dict[str, Any]] = []
    offset = None
    while True:
        body: Dict[str, Any] = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        result = _post(f"{qdrant_url}/collections/{collection}/points/scroll", body)["result"]
        points.extend({"id": p["id"], "payload": p.get("payload") or {}} for p in result["points"])
        offset = result.get("next_page_offset")
        if offset is None:
            return points


def build_restored_payload(
    payload: Dict[str, Any], legacy_table: Dict[str, Any], today: str
) -> Tuple[Optional[Dict[str, Any]], str]:
    """복원한 payload와 설명을 돌려준다. 검증에 실패하면 (None, 오류)."""
    fixed, n_bad = normalize_legacy_table(legacy_table)
    if not fixed["columns"] or not fixed["rows"]:
        return None, "원본 표의 columns 또는 rows가 비어 있음"

    new = copy.deepcopy(payload)
    new["table_data"] = fixed
    extra = new.setdefault("extra_metadata", {}) or {}
    legacy = extra.setdefault("legacy", {}) or {}
    demoted = bool(legacy.get("migration_note"))
    if demoted:
        new["review_status"] = ReviewStatus.APPROVED.value
    legacy["restore_note"] = (
        f"{today} v1 원본 표 복원 (행 {len(fixed['rows'])}개 중 키 정규화 {n_bad}개)"
        + (", 이전 때 내려간 검수 상태를 APPROVED로 되돌림" if demoted else "")
    )
    extra["legacy"] = legacy
    new["extra_metadata"] = extra

    try:
        ElementSearchPayload.model_validate(new)
    except Exception as e:
        return None, f"ElementSearchPayload 검증 실패: {str(e).splitlines()[0][:150]}"
    status_note = f"{payload.get('review_status')} → {new['review_status']}" if demoted else "검수 상태 유지"
    return new, f"행 {len(fixed['rows'])}개 복원, {status_note}"


def set_payload(qdrant_url: str, collection: str, point_id: Any, fields: Dict[str, Any]) -> None:
    _post(f"{qdrant_url}/collections/{collection}/points/payload?wait=true",
          {"payload": fields, "points": [point_id]})


def run(args: argparse.Namespace) -> None:
    if args.rollback:
        backup = json.loads(Path(args.rollback).read_text(encoding="utf-8"))
        for item in backup["items"]:
            set_payload(args.qdrant_url, backup["collection"], item["point_id"], item["before"])
        print(f"{len(backup['items'])}개를 백업 값으로 되돌렸습니다 ({backup['collection']}).")
        return

    current = scroll_points(args.qdrant_url, args.collection)
    legacy_tables = {
        p["payload"].get("element_id"): p["payload"].get(LEGACY_KEY_TABLE)
        for p in scroll_points(args.qdrant_url, args.legacy_collection)
    }
    today = datetime.now().strftime("%Y-%m-%d")

    plans, skipped = [], []
    for point in current:
        payload = point["payload"]
        if not is_empty_table(payload):
            continue
        legacy_table = legacy_tables.get(payload.get("element_id"))
        if not (isinstance(legacy_table, dict) and legacy_table.get("rows")):
            continue
        new, note = build_restored_payload(payload, legacy_table, today)
        row = (payload.get("doc_name", ""), payload.get("page_number", ""), payload.get("element_id", ""), note)
        if new is None:
            skipped.append(row)
        else:
            plans.append((point, new, row))

    print(f"[{'반영' if args.apply else '미리보기'}] {args.collection}: 복원 대상 {len(plans)}개, 건너뜀 {len(skipped)}개")
    for _, _, (doc, page, eid, note) in plans:
        print(f"  복원  {eid}  {doc} p.{page}  {note}")
    for doc, page, eid, note in skipped:
        print(f"  건너뜀 {eid}  {doc} p.{page}  {note}")
    if not args.apply or not plans:
        if not args.apply:
            print("실제로 바꾸려면 --apply를 붙여 다시 실행하세요.")
        return

    backup_path = Path(f"restore_backup_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    backup = {
        "collection": args.collection,
        "items": [
            {"point_id": point["id"], "element_id": point["payload"].get("element_id"),
             "before": {f: point["payload"].get(f) for f in CHANGED_FIELDS}}
            for point, _, _ in plans
        ],
    }
    backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"백업 저장: {backup_path}")

    for point, new, _ in plans:
        set_payload(args.qdrant_url, args.collection, point["id"], {f: new.get(f) for f in CHANGED_FIELDS})
    print(f"{len(plans)}개를 반영했습니다. 되돌리기: python scripts/restore_tables_from_v1.py --rollback {backup_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="v1 원본에서 버려진 표 복원 (기본: 미리보기)")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "figindex_elements_v2"))
    parser.add_argument("--legacy-collection", default="figindex_elements")
    parser.add_argument("--apply", action="store_true", help="백업 후 실제로 반영")
    parser.add_argument("--rollback", help="백업 JSON으로 되돌리기")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
