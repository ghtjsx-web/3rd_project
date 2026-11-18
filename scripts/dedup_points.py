#!/usr/bin/env python3
"""
scripts/dedup_points.py

중복 4건 정리 스크립트 (팀장 결정에 따른 v2 쓰기 예외):
아래 4개 그룹에서 bbox 면적이 작은 포인트만 삭제:
 1. 그린광학 p.3 "그린광학 주요 연혁"
 2. BGF리테일 p.2 "그림 1. BGF리테일 분기별 영업실적 추이 및 전망"
 3. BGF리테일 p.2 "표 1. BGF리테일 실적 테이블"
 4. 롯데렌탈 p.2 "표2 롯데렌탈 3Q26 Review"

삭제 전 point_id, element_id, bbox, area 정보를 CSV에 저장:
 - data/migration/dedup_20261117.csv
 - figindex/data/migration/dedup_20261117.csv
"""
import csv
import json
import logging
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dedup_points")

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_CAPTIONS = {
    "그린광학 주요 연혁",
    "그림 1. BGF리테일 분기별 영업실적 추이 및 전망",
    "표 1. BGF리테일 실적 테이블",
    "표2 롯데렌탈 3Q26 Review",
}


def main():
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    collection_name = "figindex_elements_v2"

    scroll_url = f"{qdrant_url}/collections/{collection_name}/points/scroll"
    offset = None
    groups = defaultdict(list)

    logger.info("figindex_elements_v2 포인트 조회 중...")
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
            pl = p.get("payload", {})
            cap = pl.get("caption", "")
            if cap in TARGET_CAPTIONS:
                bbox = pl.get("bbox", [0.0, 0.0, 0.0, 0.0])
                # bbox: [x0, y0, x1, y1]
                area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                key = (pl.get("doc_name"), pl.get("page_number"), cap)
                groups[key].append({
                    "point_id": p["id"],
                    "element_id": pl.get("element_id"),
                    "doc_name": pl.get("doc_name"),
                    "page_number": pl.get("page_number"),
                    "caption": cap,
                    "bbox": bbox,
                    "area": area,
                })
        offset = res.get("next_page_offset")
        if not offset:
            break

    logger.info(f"대상 그룹 {len(groups)}개 발견")
    to_delete = []
    to_keep = []

    for key, pts in groups.items():
        if len(pts) < 2:
            logger.warning(f"그룹 {key}의 포인트 수가 2개 미만입니다 ({len(pts)}개). 건너뜁니다.")
            continue
        # bbox 면적이 작은 순서로 정렬: 0번은 삭제, 1번 이상은 유지
        sorted_pts = sorted(pts, key=lambda x: x["area"])
        smaller = sorted_pts[0]
        larger = sorted_pts[1]
        to_delete.append(smaller)
        to_keep.append(larger)
        logger.info(
            f"그룹 [{key[0]} p.{key[1]} '{key[2]}']\n"
            f"  -> [삭제 대상 (작은 면적)]: point_id={smaller['point_id']}, element_id={smaller['element_id']}, area={smaller['area']:.6f}, bbox={smaller['bbox']}\n"
            f"  -> [유지 대상 (큰 면적)]:   point_id={larger['point_id']}, element_id={larger['element_id']}, area={larger['area']:.6f}, bbox={larger['bbox']}"
        )

    if len(to_delete) != 4:
        raise RuntimeError(f"정리 대상이 정확히 4건이어야 하나 {len(to_delete)}건이 탐지되었습니다.")

    # CSV 기록
    csv_paths = [
        REPO_ROOT / "data" / "migration" / "dedup_20261117.csv",
        REPO_ROOT / "figindex" / "data" / "migration" / "dedup_20261117.csv",
    ]

    fieldnames = ["point_id", "element_id", "doc_name", "page_number", "caption", "bbox", "area", "action"]
    for path in csv_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in to_delete:
                writer.writerow({
                    "point_id": item["point_id"],
                    "element_id": item["element_id"],
                    "doc_name": item["doc_name"],
                    "page_number": item["page_number"],
                    "caption": item["caption"],
                    "bbox": json.dumps(item["bbox"]),
                    "area": f"{item['area']:.6f}",
                    "action": "DELETED",
                })
        logger.info(f"CSV 저장 완료: {path}")

    # Qdrant 삭제 실행
    delete_url = f"{qdrant_url}/collections/{collection_name}/points/delete"
    delete_ids = [item["point_id"] for item in to_delete]
    logger.info(f"Qdrant 삭제 요청 IDs: {delete_ids}")

    req = urllib.request.Request(
        delete_url,
        data=json.dumps({"points": delete_ids}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        del_res = json.loads(resp.read().decode("utf-8"))
    logger.info(f"Qdrant 삭제 응답: {del_res}")

    print("\n" + "=" * 65)
    print(" [중복 4건 정리 완료]")
    for item in to_delete:
        print(f" - 삭제: point_id={item['point_id']} ({item['element_id']}) | {item['doc_name']} p.{item['page_number']} '{item['caption']}' | bbox={item['bbox']} (area={item['area']:.6f})")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
