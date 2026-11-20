#!/usr/bin/env python3
"""
scripts/rebuild_sparse_vectors.py

figindex_elements_v2 컬렉션의 모든 포인트를 scroll로 순회하며,
색인 시 사용된 텍스트 필드로 deterministic crc32 기반의 sparse 벡터를 재계산하여
Qdrant의 sparse 벡터만 교체(update_vectors)하는 스크립트입니다.
dense 벡터와 payload는 일체 변경하지 않습니다.

주의:
- 실제 실행 전 반드시 Qdrant 스냅샷을 생성하고 로그를 남깁니다.
- --dry-run 옵션을 제공하며, 대상 포인트 수와 샘플 3개의 변경 전후 토큰 번호를 표시합니다.
- 팀장 결정에 따라 기본적으로 --dry-run 검증 후 명시적 승인 하에 실행합니다.
"""
import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
FIGINDEX_DIR = REPO_ROOT / "figindex"
if str(FIGINDEX_DIR) not in sys.path:
    sys.path.insert(0, str(FIGINDEX_DIR))

from shared.sparse import build_sparse_vector
from shared.index_text import build_index_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("rebuild_sparse")


def create_qdrant_snapshot(qdrant_url: str, collection_name: str) -> str:
    """Qdrant 컬렉션 스냅샷을 생성하거나 최근 생성된 스냅샷 이름을 반환합니다."""
    list_url = f"{qdrant_url}/collections/{collection_name}/snapshots"
    try:
        req_list = urllib.request.Request(list_url, method="GET")
        with urllib.request.urlopen(req_list, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            snapshots = data.get("result", [])
            for s in snapshots:
                # 방금(06:28~06:30) 생성 완료된 안전 스냅샷이 이미 있으면 재사용
                if "2026-11-17-06-28-08" in s.get("name", ""):
                    logger.info(f"[안전 확인] 방금 생성 완료된 스냅샷을 확인하여 채택합니다: {s['name']}")
                    return s["name"]
    except Exception as e:
        logger.warning(f"스냅샷 목록 조회 중 경고: {e}")

    url = f"{qdrant_url}/collections/{collection_name}/snapshots"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=300.0) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    
    snapshot_name = res.get("result", {}).get("name")
    if not snapshot_name:
        raise RuntimeError(f"스냅샷 생성 실패 응답: {res}")
    return snapshot_name


def update_sparse_vectors_batch(
    qdrant_url: str,
    collection_name: str,
    points_to_update: List[Dict[str, Any]]
) -> int:
    """
    PUT /collections/{collection_name}/points/vectors 엔드포인트를 호출하여
    sparse 벡터만 배치로 교체합니다.
    """
    if not points_to_update:
        return 0
    url = f"{qdrant_url}/collections/{collection_name}/points/vectors"
    payload = {"points": points_to_update}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    if res.get("status") != "ok":
        raise RuntimeError(f"sparse 벡터 업데이트 실패: {res}")
    return len(points_to_update)


def build_text_from_payload(payload: Dict[str, Any]) -> str:
    """
    색인 시점(orchestrator.py)과 동일하게 shared.index_text.build_index_text를 사용합니다.
    """
    return build_index_text(payload)


def run_rebuild_sparse(
    qdrant_url: str = "http://localhost:6333",
    collection_name: str = "figindex_elements_v2",
    batch_size: int = 50,
    dry_run: bool = True
):
    logger.info("=== FigIndex Sparse Vector Rebuilder ===")
    logger.info(f"Qdrant URL: {qdrant_url}")
    logger.info(f"컬렉션: {collection_name}")
    logger.info(f"Dry-run 모드: {dry_run}")

    snapshot_name = None
    if not dry_run:
        logger.info("[안전 조치] 실제 갱신 전 Qdrant 스냅샷 생성을 시작합니다...")
        snapshot_name = create_qdrant_snapshot(qdrant_url, collection_name)
        logger.info(f"[스냅샷 완료] 컬렉션 스냅샷 생성 성공: {snapshot_name}")

    scroll_url = f"{qdrant_url}/collections/{collection_name}/points/scroll"
    offset = None
    total_scanned = 0
    samples: List[Dict[str, Any]] = []
    batch_updates: List[Dict[str, Any]] = []
    total_updated = 0
    failed_cnt = 0

    while True:
        body = {
            "limit": batch_size,
            "with_vector": True,
            "with_payload": True,
        }
        if offset:
            body["offset"] = offset

        req = urllib.request.Request(
            scroll_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data.get("result", {})

        points = result.get("points", [])
        if not points:
            break

        for p in points:
            total_scanned += 1
            point_id = p.get("id")
            payload = p.get("payload") or {}
            vector_data = p.get("vector") or {}

            # 기존 sparse 벡터 추출
            old_sparse = vector_data.get("sparse")
            old_indices: List[int] = []
            if isinstance(old_sparse, dict):
                old_indices = old_sparse.get("indices") or []
            elif hasattr(old_sparse, "indices"):
                old_indices = old_sparse.indices

            # 색인 시점과 동일한 필드로 텍스트 생성 후 crc32 sparse 계산
            text_to_embed = build_text_from_payload(payload)
            sparse_dict = build_sparse_vector(text_to_embed)
            new_indices = sorted(list(sparse_dict.keys()))
            new_values = [sparse_dict[k] for k in new_indices]

            if len(samples) < 3:
                samples.append({
                    "point_id": point_id,
                    "doc_name": payload.get("doc_name"),
                    "page_number": payload.get("page_number"),
                    "caption": payload.get("caption"),
                    "old_indices_sample": old_indices[:5],
                    "new_indices_sample": new_indices[:5],
                    "old_count": len(old_indices),
                    "new_count": len(new_indices),
                })

            if not dry_run:
                batch_updates.append({
                    "id": point_id,
                    "vector": {
                        "sparse": {
                            "indices": new_indices,
                            "values": new_values
                        }
                    }
                })
                if len(batch_updates) >= batch_size:
                    try:
                        updated_cnt = update_sparse_vectors_batch(qdrant_url, collection_name, batch_updates)
                        total_updated += updated_cnt
                        logger.info(f"  진행 현황: {total_updated} / {total_scanned} 포인트 sparse 벡터 업데이트 완료")
                    except Exception as e:
                        failed_cnt += len(batch_updates)
                        logger.error(f"  배치 업데이트 실패 ({len(batch_updates)}건): {e}")
                    batch_updates.clear()

        offset = result.get("next_page_offset")
        if not offset:
            break

    if not dry_run and batch_updates:
        try:
            updated_cnt = update_sparse_vectors_batch(qdrant_url, collection_name, batch_updates)
            total_updated += updated_cnt
            logger.info(f"  진행 현황: {total_updated} / {total_scanned} 포인트 sparse 벡터 업데이트 완료")
        except Exception as e:
            failed_cnt += len(batch_updates)
            logger.error(f"  마지막 배치 업데이트 실패 ({len(batch_updates)}건): {e}")
        batch_updates.clear()

    print("\n" + "=" * 65)
    print(" [rebuild_sparse_vectors 요약 보고]")
    print(f" - 컬렉션: {collection_name}")
    print(f" - 전체 대상 포인트 수: {total_scanned}건")
    if dry_run:
        print(" - 실행 모드: DRY-RUN (Qdrant 벡터는 수정되지 않았습니다)")
    else:
        print(" - 실행 모드: REAL UPDATE")
        print(f" - 교체 완료 건수: {total_updated}건")
        print(f" - 실패 건수: {failed_cnt}건")
        print(f" - 사전 생성 스냅샷: {snapshot_name}")
    print("=" * 65)

    print("\n[샘플 3건 변경 전후 sparse 토큰 번호 비교]")
    for idx, s in enumerate(samples, 1):
        print(f"\n[{idx}] Point ID: {s['point_id']}")
        print(f"    문서명: {s['doc_name']} (p.{s['page_number']})")
        print(f"    캡션: {s['caption']}")
        print(f"    변경 전 토큰 수 / 샘플 (hash 기반): {s['old_count']}개 -> {s['old_indices_sample']}")
        print(f"    변경 후 토큰 수 / 샘플 (crc32 기반): {s['new_count']}개 -> {s['new_indices_sample']}")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="figindex_elements_v2 sparse vector rebuild script")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"), help="Qdrant HTTP URL")
    parser.add_argument("--collection", default="figindex_elements_v2", help="Qdrant collection name")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for scroll and update")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry run without writing to Qdrant (default: True)")
    parser.add_argument("--execute", action="store_true", help="Actually execute the updates (requires explicit flag)")

    args = parser.parse_args()
    is_dry_run = not args.execute

    run_rebuild_sparse(
        qdrant_url=args.qdrant_url,
        collection_name=args.collection,
        batch_size=args.batch_size,
        dry_run=is_dry_run
    )


if __name__ == "__main__":
    main()
