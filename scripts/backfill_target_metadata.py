#!/usr/bin/env python3
"""
scripts/backfill_target_metadata.py

Qdrant figindex_elements_v2 컬렉션의 모든 포인트를 순회하여,
extra_metadata.company는 존재하지만 extra_metadata.target이 없거나 비어있는 포인트에 대해
target에 company 값을 채워 넣는(set_payload) 스크립트입니다.
기존 company 값 및 기타 extra_metadata/payload 필드는 일체 삭제하지 않고 보존합니다.

팀장 결정: 종목 키의 표준은 extra_metadata.target이며, 본 작업은 v2 쓰기 예외로 승인되었습니다.
"""
import json
import logging
import os
import sys
import urllib.request
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_target")


def main():
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    collection_name = "figindex_elements_v2"

    scroll_url = f"{qdrant_url}/collections/{collection_name}/points/scroll"
    offset = None
    total_scanned = 0
    targets_to_update: List[Dict[str, Any]] = []

    logger.info(f"Qdrant 컬렉션 '{collection_name}' 포인트 순회 중...")
    while True:
        body = {"limit": 100, "with_payload": True}
        if offset:
            body["offset"] = offset
        req = urllib.request.Request(
            scroll_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))["result"]
        points = res.get("points", [])
        if not points:
            break

        for p in points:
            total_scanned += 1
            pl = p.get("payload") or {}
            em = pl.get("extra_metadata") or {}
            c_val = em.get("company")
            t_val = em.get("target")

            # company는 있고 target은 비어있는 경우
            if c_val and not t_val:
                updated_em = dict(em)
                updated_em["target"] = c_val
                targets_to_update.append({
                    "id": p["id"],
                    "doc_name": pl.get("doc_name"),
                    "page_number": pl.get("page_number"),
                    "caption": pl.get("caption"),
                    "company": c_val,
                    "updated_extra_metadata": updated_em,
                })

        offset = res.get("next_page_offset")
        if not offset:
            break

    logger.info(f"전체 스캔 완료: {total_scanned}건 중 보정 대상: {len(targets_to_update)}건")

    if not targets_to_update:
        logger.info("보정할 대상 포인트가 없습니다.")
        return

    # Qdrant set_payload 실행
    set_payload_url = f"{qdrant_url}/collections/{collection_name}/points/payload"
    updated_count = 0

    for item in targets_to_update:
        payload_body = {
            "payload": {
                "extra_metadata": item["updated_extra_metadata"]
            },
            "points": [item["id"]]
        }
        req = urllib.request.Request(
            set_payload_url,
            data=json.dumps(payload_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
        if resp_data.get("status") != "ok":
            raise RuntimeError(f"set_payload 실패 (point_id={item['id']}): {resp_data}")
        updated_count += 1

    print("\n" + "=" * 65)
    print(" [extra_metadata.target 백필(set_payload) 완료]")
    print(f" - 전체 스캔 포인트: {total_scanned}건")
    print(f" - 보정 완료 포인트: {updated_count}건")
    for idx, item in enumerate(targets_to_update, 1):
        print(f"  [{idx:2d}] point_id={item['id']} | {item['doc_name']} p.{item['page_number']} | target='{item['company']}' (company='{item['company']}')")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
