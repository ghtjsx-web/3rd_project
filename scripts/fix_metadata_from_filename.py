#!/usr/bin/env python3
"""
fix_metadata_from_filename.py: RPT 파일명에서 publish_date, source_org, company를 파싱하여
기존 Qdrant 포인트에 set_payload로 일괄 반영하는 1회성 스크립트.

기능:
1. Qdrant 컬렉션의 모든 포인트를 페이징 스크롤
2. RPT_YYYYMMDD_종목_증권사.pdf 형식의 파일명을 가진 포인트 식별
3. 파일명에서 publish_date, source_org, company 파싱
4. 기존 메타데이터와 비교하여 변경 전/후 로그 출력
5. set_payload API를 호출하여 Qdrant에 일괄 반영

사용법:
    python scripts/fix_metadata_from_filename.py
    python scripts/fix_metadata_from_filename.py --dry-run
"""

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 증권사 정규화 사전 (orchestrator.py 기준 정식 명칭 매핑)
BROKER_ALIASES: Dict[str, str] = {
    "IBK투자증권": "IBK투자증권",
    "미래에셋증권": "미래에셋증권",
    "신한투자증권": "신한투자증권",
    "키움증권": "키움증권",
    "하나증권": "하나증권",
    "대신증권": "대신증권",
    "KB증권": "KB증권",
    "삼성증권": "삼성증권",
    "NH투자증권": "NH투자증권",
    "유안타증권": "유안타증권",
    "한국투자증권": "한국투자증권",
    "메리츠증권": "메리츠증권",
    "교보증권": "교보증권",
    "현대차증권": "현대차증권",
    "한화투자증권": "한화투자증권",
    "SK증권": "SK증권",
    "유진투자증권": "유진투자증권",
    "DB증권": "DB증권",
    "iM증권": "iM증권",
    "다올투자증권": "다올투자증권",
    "LS증권": "LS증권",
    "상상인증권": "상상인증권",
    "신영증권": "신영증권",
    "DS투자증권": "DS투자증권",
    "BNK투자증권": "BNK투자증권",
    "한양증권": "한양증권",
    "부국증권": "부국증권",
    "흥국증권": "흥국증권",
    "케이프투자증권": "케이프투자증권",
    "리딩투자증권": "리딩투자증권",
    "DB금융투자": "DB증권",
    "동부증권": "DB증권",
    "하이투자증권": "iM증권",
    "신한금융투자": "신한투자증권",
    "하나금융투자": "하나증권",
    "하나대투증권": "하나증권",
    "미래에셋대우": "미래에셋증권",
    "대우증권": "미래에셋증권",
    "현대증권": "KB증권",
    "KB투자증권": "KB증권",
    "KTB투자증권": "다올투자증권",
    "이베스트투자증권": "LS증권",
    "이베스트증권": "LS증권",
    "동양증권": "유안타증권",
    "한화증권": "한화투자증권",
    "HMC투자증권": "현대차증권",
    "우리투자증권": "NH투자증권",
    "LIG투자증권": "케이프투자증권",
    "한투": "한국투자증권",
    "한투증권": "한국투자증권",
    "한국투자": "한국투자증권",
    "IBK": "IBK투자증권",
    "IBK투자": "IBK투자증권",
    "미래에셋": "미래에셋증권",
    "신한": "신한투자증권",
    "신한투자": "신한투자증권",
    "키움": "키움증권",
    "하나": "하나증권",
    "대신": "대신증권",
    "KB": "KB증권",
    "삼성": "삼성증권",
    "NH": "NH투자증권",
    "NH투자": "NH투자증권",
    "유안타": "유안타증권",
    "메리츠": "메리츠증권",
    "메리츠종금증권": "메리츠증권",
    "교보": "교보증권",
    "현대차": "현대차증권",
    "한화": "한화투자증권",
    "한화투자": "한화투자증권",
    "SK": "SK증권",
    "유진": "유진투자증권",
    "유진투자": "유진투자증권",
    "DB": "DB증권",
    "iM": "iM증권",
    "IM증권": "iM증권",
    "다올": "다올투자증권",
    "다올투자": "다올투자증권",
    "LS": "LS증권",
    "상상인": "상상인증권",
    "신영": "신영증권",
    "DS": "DS투자증권",
}

_BROKER_ALIASES_LOWER: Dict[str, str] = {k.lower(): v for k, v in BROKER_ALIASES.items()}


def normalize_broker_name(source: str) -> str:
    """REPORT 출처(증권사)를 정식 명칭으로 정규화합니다."""
    if not source:
        return ""
    cleaned = unicodedata.normalize("NFC", source).strip()
    if cleaned in BROKER_ALIASES:
        return BROKER_ALIASES[cleaned]
    lower_key = cleaned.lower()
    if lower_key in _BROKER_ALIASES_LOWER:
        return _BROKER_ALIASES_LOWER[lower_key]
    return cleaned


def normalize_date_string(date_digits: str) -> Optional[str]:
    """숫자 날짜 문자열(YYYYMMDD, YYYYMM, YYYY)을 YYYY-MM-DD 형식으로 변환합니다."""
    digits = date_digits.strip()
    if not re.fullmatch(r"\d{4}|\d{6}|\d{8}", digits):
        return None
    try:
        if len(digits) == 4:
            return f"{digits}-01-01"
        if len(digits) == 6:
            return f"{digits[:4]}-{digits[4:6]}-01"
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    except Exception:
        return None


def parse_rpt_filename(raw_name: str) -> Optional[Dict[str, Any]]:
    """
    RPT_YYYYMMDD_종목_증권사.pdf 파일명에서 publish_date, source_org, company를 파싱합니다.
    """
    norm_name = unicodedata.normalize("NFC", Path(raw_name).name).strip()
    stem = re.sub(r"\.pdf$", "", norm_name, flags=re.IGNORECASE).strip()
    if not stem.upper().startswith("RPT_"):
        return None

    remainder = stem[4:]
    parts = remainder.split("_")

    if len(parts) >= 4 and re.fullmatch(r"\d+", parts[-1].strip()):
        parts = parts[:-1]

    if len(parts) < 3:
        return None

    date_str = parts[0].strip()
    source_raw = parts[-1].strip()
    company = "_".join(p.strip() for p in parts[1:-1]).strip()

    if not company or not source_raw:
        return None

    publish_date_str = normalize_date_string(date_str)
    if not publish_date_str:
        return None

    source_org = normalize_broker_name(source_raw)

    return {
        "publish_date": publish_date_str,
        "source_org": source_org,
        "company": company,
        "target": company,
        "doc_type": "REPORT",
    }


def plan_point_update(
    payload: Dict[str, Any], file_source_org: str, file_pub_date: str, file_target: Optional[str]
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """요소 하나를 파일명 정보와 비교해 (바꿀 필드 dict 또는 None, 변경 설명 목록)을 돌려준다.

    extra_metadata와 entities는 그 요소 자신의 값을 바탕으로 필요한 키만 바꾼다.
    """
    diff_logs: List[str] = []
    cur_source_org = payload.get("source_org") or ""
    cur_pub_date = str(payload.get("publish_date") or "")
    cur_extra = payload.get("extra_metadata") or {}
    cur_extra = cur_extra if isinstance(cur_extra, dict) else {}
    cur_target = cur_extra.get("target") or cur_extra.get("company")
    cur_entities = payload.get("entities") or []
    cur_entities = list(cur_entities) if isinstance(cur_entities, list) else []

    if cur_source_org != file_source_org:
        diff_logs.append(f"source_org: '{cur_source_org}' -> '{file_source_org}'")
    if cur_pub_date != file_pub_date:
        diff_logs.append(f"publish_date: '{cur_pub_date}' -> '{file_pub_date}'")
    if cur_target != file_target:
        diff_logs.append(f"extra_metadata.target: '{cur_target}' -> '{file_target}'")

    updated_entities = list(cur_entities)
    if file_target and file_target not in updated_entities:
        updated_entities = [file_target] + [e for e in updated_entities if e != file_target]
        diff_logs.append(f"entities: 종목명 '{file_target}' 추가")
    if not diff_logs:
        return None, []
    if file_source_org and file_source_org not in updated_entities:
        updated_entities.append(file_source_org)

    updated_extra = dict(cur_extra)
    updated_extra["company"] = file_target
    updated_extra["target"] = file_target
    updated_extra["broker"] = file_source_org
    return {
        "source_org": file_source_org,
        "publish_date": file_pub_date,
        "extra_metadata": updated_extra,
        "entities": updated_entities,
    }, diff_logs


def query_all_qdrant_points(qdrant_url: str, collection: str) -> List[Dict[str, Any]]:
    """Qdrant REST API scroll을 사용하여 컬렉션의 모든 포인트를 페이징 로드합니다."""
    scroll_url = f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll"
    all_points: List[Dict[str, Any]] = []
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
        all_points.extend(points)

        next_offset = result.get("next_page_offset")
        if not next_offset:
            break

    return all_points


def update_qdrant_payload(
    qdrant_url: str,
    collection: str,
    point_ids: List[Any],
    payload_dict: Dict[str, Any],
) -> bool:
    """Qdrant REST API set_payload을 호출하여 지정된 포인트들의 페이로드를 일괄 갱신합니다."""
    url = f"{qdrant_url.rstrip('/')}/collections/{collection}/points/payload"
    body = {
        "payload": payload_dict,
        "points": point_ids,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "ok"
    except Exception as e:
        print(f"[Error] set_payload 실패 (points={len(point_ids)}개): {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RPT 파일명에서 publish_date, source_org, company를 파싱하여 Qdrant 포인트에 set_payload로 일괄 반영합니다."
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
        default=os.getenv("QDRANT_URL", "http://localhost:6333"),
        help="Qdrant 서버 URL (기본값: http://localhost:6333)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 DB에 반영하지 않고 변경 전후 로그만 출력합니다.",
    )
    args = parser.parse_args()

    mode_label = "[DRY-RUN] " if args.dry_run else ""
    print(f"[Info] {mode_label}Qdrant 연결: {args.qdrant_url} (컬렉션: {args.collection})")

    points = query_all_qdrant_points(args.qdrant_url, args.collection)
    print(f"[Info] 전체 로드된 포인트: {len(points)}개")

    # 문서별 포인트 묶기
    docs_to_points: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for pt in points:
        payload = pt.get("payload") or {}
        doc_name = unicodedata.normalize("NFC", payload.get("doc_name") or "")
        if doc_name:
            docs_to_points[doc_name].append(pt)

    print(f"[Info] 고유 문서 수: {len(docs_to_points)}개")

    updated_docs_cnt = 0
    updated_points_cnt = 0

    print("\n" + "=" * 90)
    print(f"               {mode_label}파일명 기반 메타데이터 set_payload 일괄 반영 로그")
    print("=" * 90)

    for doc_name, doc_points in sorted(docs_to_points.items()):
        parsed_fn = parse_rpt_filename(doc_name)
        if not parsed_fn:
            continue

        file_pub_date = parsed_fn["publish_date"]
        file_source_org = parsed_fn["source_org"]
        file_target = parsed_fn.get("target") or parsed_fn.get("company")

        # 요소(포인트)마다 따로 비교하고 따로 갱신한다.
        # 문서의 첫 요소만 비교하면 나머지 요소의 불일치를 놓치고, 첫 요소의 extra_metadata·entities를
        # 다른 요소에 덮어써 요소별 기록(restore_note 등)이 지워진다.
        doc_updates = []
        for pt in doc_points:
            payload_update, diff_logs = plan_point_update(
                pt.get("payload") or {}, file_source_org, file_pub_date, file_target
            )
            if payload_update:
                doc_updates.append((pt, payload_update, diff_logs))

        if doc_updates:
            updated_docs_cnt += 1
            updated_points_cnt += len(doc_updates)
            print(f"\n[문서 변경 {updated_docs_cnt}] {doc_name} (포인트 {len(doc_updates)}/{len(doc_points)}개)")
            for pt, payload_update, diff_logs in doc_updates:
                eid = (pt.get("payload") or {}).get("element_id", pt.get("id"))
                print(f"  - {eid}: " + "; ".join(diff_logs))
                if not args.dry_run:
                    success = update_qdrant_payload(
                        qdrant_url=args.qdrant_url,
                        collection=args.collection,
                        point_ids=[pt["id"]],
                        payload_dict=payload_update,
                    )
                    print("    -> [성공] set_payload 완료" if success else "    -> [실패] set_payload 요청 실패")

    print("\n" + "=" * 90)
    print(f"[요약 결과 {mode_label}]")
    print(f"  - 총 검사 문서: {len(docs_to_points)}개")
    print(f"  - 변경 반영 문서: {updated_docs_cnt}개")
    print(f"  - 변경 반영 포인트: {updated_points_cnt}개")
    if args.dry_run:
        print("  - 참고: --dry-run 모드로 실행되어 실제 Qdrant에는 쓰여지지 않았습니다.")
    else:
        print("  - Qdrant 컬렉션에 set_payload 반영이 완료되었습니다.")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
