#!/usr/bin/env python3
"""
scripts/promote_test_to_service.py

시험 컬렉션(figindex_test_*)에서 확인을 마친 재추출 요소를 서비스 컬렉션(figindex_elements_v2)에 반영한다.
팀장 확인 후에만 실행한다. (figindex/pipeline/AGENTS.md 1절: 서비스 컬렉션 쓰기는 팀장 승인 후)

반영 기준 (기본)
- 시험 컬렉션 요소 중 TABLE이고 표가 채워진 것만 반영한다.
- 표가 비었거나 유형이 바뀐 요소(예: TABLE → DIAGRAM)는 건너뛰고 목록만 보여 준다. --include-unfilled로 포함.
- 서비스 컬렉션에서 같은 element_id의 포인트를 찾아 그 포인트 ID에 덮어쓴다 (벡터 + payload). 없으면 건너뜀.

--new-only (add_missing_elements.py 결과용, 결정 22)
- 반대로 서비스 컬렉션에 element_id가 없는 새 요소만 추가한다. 기존 포인트는 건드리지 않는다.
- 같은 포인트 ID(같은 문서·페이지·bbox)가 이미 서비스에 있으면 덮어쓰지 않고 건너뛴다.
- 같은 문서·같은 페이지의 기존 요소(반려 포함)와 위치가 겹치면 중복 의심으로 건너뛴다
  (IoU ≥ 0.3 또는 한쪽 넓이의 절반 이상이 겹침). 크롭 규칙 변경·회전 페이지로 좌표가 달라진 같은 표를 막는다.
  확인 후 그래도 넣으려면 --include-overlaps.
- 표가 비었거나 유형이 무엇이든 추가한다 (확신도가 낮으면 PENDING_REVIEW라 검수 탭으로 간다).
- 백업 JSON에는 추가한 포인트 ID를 남기고, --rollback은 그 포인트들을 지운다.

안전장치
- 기본은 미리보기. --apply를 붙여야 쓴다.
- 쓰기 전에 대상 포인트의 원래 payload와 벡터 전체를 백업 JSON으로 저장한다. --rollback 백업파일 로 되돌린다.
- 반영할 payload를 ElementSearchPayload로 검증한다.

사용법 (저장소 루트, Qdrant 실행 중):
    python scripts/promote_test_to_service.py --test-collection figindex_test_ryu
    python scripts/promote_test_to_service.py --test-collection figindex_test_ryu --apply
    python scripts/promote_test_to_service.py --rollback promote_backup_YYYYMMDD-HHMMSS.json
    python scripts/promote_test_to_service.py --test-collection figindex_test_addmissing --new-only [--apply]
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "figindex"))

try:
    from shared.coords import iou, overlap_ratio
    from shared.schemas import ElementSearchPayload, ElementType
except ImportError as e:
    sys.exit(f"shared 모듈을 불러오지 못했습니다: {e}\n'pip install pydantic' 후 다시 실행해 주세요.")


def _request(method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def scroll(qdrant_url: str, collection: str, with_vector: bool) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    offset = None
    while True:
        body: Dict[str, Any] = {"limit": 128, "with_payload": True, "with_vector": with_vector}
        if offset is not None:
            body["offset"] = offset
        result = _request("POST", f"{qdrant_url}/collections/{collection}/points/scroll", body)["result"]
        points.extend(result["points"])
        offset = result.get("next_page_offset")
        if offset is None:
            return points


def has_rows(payload: Dict[str, Any]) -> bool:
    table = payload.get("table_data")
    return isinstance(table, dict) and bool(table.get("rows"))


def plan_promotion(
    test_points: List[Dict[str, Any]], service_points: List[Dict[str, Any]], include_unfilled: bool
) -> Tuple[List[Tuple[Dict[str, Any], Dict[str, Any]]], List[Tuple[Dict[str, Any], str]]]:
    """(반영할 (시험 포인트, 서비스 포인트) 목록, (건너뛸 시험 포인트, 이유) 목록)."""
    service_by_eid = {p["payload"].get("element_id"): p for p in service_points}
    plans, skipped = [], []
    for tp in test_points:
        payload = tp.get("payload") or {}
        eid = payload.get("element_id")
        sp = service_by_eid.get(eid)
        if sp is None:
            skipped.append((tp, "서비스 컬렉션에 같은 element_id 없음"))
            continue
        old_type = sp["payload"].get("element_type")
        new_type = payload.get("element_type")
        if not include_unfilled:
            if new_type != old_type:
                skipped.append((tp, f"유형이 바뀜 {old_type} → {new_type} (원문 확인 필요)"))
                continue
            if new_type == ElementType.TABLE.value and not has_rows(payload):
                skipped.append((tp, "재추출해도 표가 비어 있음"))
                continue
        try:
            ElementSearchPayload.model_validate(payload)
        except Exception as e:
            skipped.append((tp, f"ElementSearchPayload 검증 실패: {str(e).splitlines()[0][:120]}"))
            continue
        plans.append((tp, sp))
    return plans, skipped


OVERLAP_IOU = 0.3
OVERLAP_SHARE = 0.5


def overlapping_element(
    payload: Dict[str, Any], service_by_page: Dict[Tuple[str, int], List[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    """같은 문서·페이지에서 위치가 겹치는 기존 요소 payload (없으면 None)."""
    bbox = payload.get("bbox")
    if not bbox:
        return None
    for old in service_by_page.get((payload.get("doc_name"), payload.get("page_number")), []):
        old_bbox = old.get("bbox")
        if not old_bbox:
            continue
        if (iou(bbox, old_bbox) >= OVERLAP_IOU or overlap_ratio(bbox, old_bbox) >= OVERLAP_SHARE
                or overlap_ratio(old_bbox, bbox) >= OVERLAP_SHARE):
            return old
    return None


def plan_new_elements(
    test_points: List[Dict[str, Any]], service_points: List[Dict[str, Any]], include_overlaps: bool = False
) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], str]]]:
    """(서비스에 추가할 시험 포인트 목록, (건너뛸 시험 포인트, 이유) 목록). --new-only용."""
    service_eids = {p["payload"].get("element_id") for p in service_points}
    service_ids = {str(p["id"]) for p in service_points}
    service_by_page: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for sp in service_points:
        pl = sp.get("payload") or {}
        service_by_page.setdefault((pl.get("doc_name"), pl.get("page_number")), []).append(pl)
    adds, skipped = [], []
    for tp in test_points:
        payload = tp.get("payload") or {}
        if payload.get("element_id") in service_eids:
            skipped.append((tp, "서비스 컬렉션에 같은 element_id 있음 (기존 요소)"))
            continue
        if str(tp["id"]) in service_ids:
            skipped.append((tp, "같은 위치(문서·페이지·bbox)의 포인트가 이미 있음"))
            continue
        old = None if include_overlaps else overlapping_element(payload, service_by_page)
        if old is not None:
            skipped.append((tp, f"중복 의심: 기존 {old.get('element_id')} ({old.get('review_status')})와 위치가 겹침"))
            continue
        try:
            ElementSearchPayload.model_validate(payload)
        except Exception as e:
            skipped.append((tp, f"ElementSearchPayload 검증 실패: {str(e).splitlines()[0][:120]}"))
            continue
        adds.append(tp)
    return adds, skipped


def delete_points(qdrant_url: str, collection: str, point_ids: List[Any]) -> None:
    for i in range(0, len(point_ids), 64):
        _request("POST", f"{qdrant_url}/collections/{collection}/points/delete?wait=true",
                 {"points": point_ids[i:i + 64]})


def promote_new_only(args: argparse.Namespace) -> None:
    test_points = scroll(args.qdrant_url, args.test_collection, with_vector=True)
    service_points = scroll(args.qdrant_url, args.service_collection, with_vector=False)
    adds, skipped = plan_new_elements(test_points, service_points, include_overlaps=args.include_overlaps)

    label = "추가" if args.apply else "미리보기"
    print(f"[{label} --new-only] {args.test_collection} → {args.service_collection}: 추가 {len(adds)}개, 건너뜀 {len(skipped)}개")
    for tp in adds:
        p = tp["payload"]
        rows = len(p["table_data"]["rows"]) if has_rows(p) else 0
        print(f"  추가  {p.get('element_id')}  {p.get('doc_name')} p.{p.get('page_number')}  "
              f"{p.get('element_type')} 표 {rows}행, 확신도 {p.get('confidence_score')} ({p.get('review_status')})")
    for tp, reason in skipped:
        p = tp.get("payload") or {}
        print(f"  건너뜀 {p.get('element_id')}  {p.get('doc_name')} p.{p.get('page_number')}  {reason}")
    if not args.apply:
        print("실제로 추가하려면 --apply를 붙여 다시 실행하세요.")
        return
    if not adds:
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = Path(f"promote_backup_{stamp}.json")
    backup = {"collection": args.service_collection, "points": [], "added_ids": [tp["id"] for tp in adds]}
    backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
    print(f"백업 저장(추가한 포인트 ID): {backup_path}")

    upsert(args.qdrant_url, args.service_collection,
           [{"id": tp["id"], "vector": tp.get("vector"), "payload": tp["payload"]} for tp in adds])
    print(f"{len(adds)}개를 추가했습니다. 되돌리기: python scripts/promote_test_to_service.py --rollback {backup_path}")


def upsert(qdrant_url: str, collection: str, points: List[Dict[str, Any]]) -> None:
    for i in range(0, len(points), 32):
        _request("PUT", f"{qdrant_url}/collections/{collection}/points?wait=true", {"points": points[i:i + 32]})


def main() -> None:
    parser = argparse.ArgumentParser(description="시험 컬렉션 재추출 결과를 서비스 컬렉션에 반영 (기본: 미리보기)")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--service-collection", default="figindex_elements_v2")
    parser.add_argument("--test-collection", help="figindex_test_로 시작하는 시험 컬렉션")
    parser.add_argument("--include-unfilled", action="store_true", help="표가 빈 요소·유형이 바뀐 요소도 반영")
    parser.add_argument("--new-only", action="store_true",
                        help="서비스에 없는 새 요소만 추가 (add_missing_elements.py 결과용)")
    parser.add_argument("--include-overlaps", action="store_true",
                        help="--new-only에서 기존 요소와 위치가 겹치는 '중복 의심'도 추가 (확인 후에만)")
    parser.add_argument("--apply", action="store_true", help="백업 후 실제로 반영")
    parser.add_argument("--rollback", help="백업 JSON으로 되돌리기")
    args = parser.parse_args()

    if args.rollback:
        backup = json.loads(Path(args.rollback).read_text(encoding="utf-8"))
        if backup["points"]:
            upsert(args.qdrant_url, backup["collection"], backup["points"])
        added_ids = backup.get("added_ids") or []
        if added_ids:
            delete_points(args.qdrant_url, backup["collection"], added_ids)
        print(f"{len(backup['points'])}개를 백업 상태로 되돌리고, 추가했던 {len(added_ids)}개를 지웠습니다 "
              f"({backup['collection']}).")
        return

    if not args.test_collection or not args.test_collection.startswith("figindex_test_"):
        raise SystemExit("--test-collection에 figindex_test_로 시작하는 시험 컬렉션 이름을 지정해 주세요.")
    if args.new_only:
        promote_new_only(args)
        return

    test_points = scroll(args.qdrant_url, args.test_collection, with_vector=True)
    service_points = scroll(args.qdrant_url, args.service_collection, with_vector=args.apply)
    plans, skipped = plan_promotion(test_points, service_points, args.include_unfilled)

    label = "반영" if args.apply else "미리보기"
    print(f"[{label}] {args.test_collection} → {args.service_collection}: 반영 {len(plans)}개, 건너뜀 {len(skipped)}개")
    for tp, sp in plans:
        p, o = tp["payload"], sp["payload"]
        rows = len(p["table_data"]["rows"]) if has_rows(p) else 0
        print(f"  반영  {p.get('element_id')}  {p.get('doc_name')} p.{p.get('page_number')}  "
              f"표 {rows}행, 확신도 {o.get('confidence_score')} → {p.get('confidence_score')}, "
              f"{o.get('review_status')} → {p.get('review_status')}")
    for tp, reason in skipped:
        p = tp.get("payload") or {}
        print(f"  건너뜀 {p.get('element_id')}  {p.get('doc_name')} p.{p.get('page_number')}  {reason}")
    if not args.apply:
        print("실제로 반영하려면 --apply를 붙여 다시 실행하세요.")
        return
    if not plans:
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = Path(f"promote_backup_{stamp}.json")
    backup = {"collection": args.service_collection,
              "points": [{"id": sp["id"], "vector": sp.get("vector"), "payload": sp["payload"]} for _, sp in plans]}
    backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
    print(f"백업 저장: {backup_path}")

    upsert(args.qdrant_url, args.service_collection,
           [{"id": sp["id"], "vector": tp.get("vector"), "payload": tp["payload"]} for tp, sp in plans])
    print(f"{len(plans)}개를 반영했습니다. 되돌리기: python scripts/promote_test_to_service.py --rollback {backup_path}")


if __name__ == "__main__":
    main()
