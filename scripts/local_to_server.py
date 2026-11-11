"""
로컬 임베디드 Qdrant(/data/qdrant_local) 데이터를 Qdrant 서버(http://qdrant:6333)로 이전하는 스크립트.

특징:
  - 원본 로컬 폴더(/data/qdrant_local)는 절대 수정하거나 삭제하지 않습니다.
  - 원본 컬렉션 설정(dense 1536 Cosine + sparse)을 읽어 대상 서버에 동일하게 생성합니다.
  - qdrant-client의 migrate()가 지원되면 사용하고, 없으면 scroll + 배치 upsert로 이전합니다.
  - 대상에 이미 컬렉션이 있으면 --force 옵션이 있을 때만 덮어씁니다.
  - 필수 Payload 인덱스(source_org, doc_type, extra_metadata.target, review_status, element_type)를 생성합니다.
  - 이전 완료 후 원본과 대상의 point 개수를 비교해 다르면 오류(종료 코드 1)로 종료합니다.

사용 예:
  docker compose stop backend
  docker compose run --rm pipeline python /scripts/local_to_server.py
  docker compose run --rm pipeline python /scripts/local_to_server.py --force
  docker compose up -d backend
"""

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

load_dotenv()


REQUIRED_KEYWORD_INDEXES = (
    "source_org",
    "doc_type",
    "extra_metadata.target",
    "review_status",
    "element_type",
    "publish_date",
    "entities",
    "doc_name",
)


def extract_vector_configs(source_info: Any) -> tuple[Dict[str, qmodels.VectorParams], Dict[str, qmodels.SparseVectorParams]]:
    """원본 컬렉션 정보에서 dense 및 sparse 벡터 설정을 읽어 대상 생성용 설정으로 변환합니다."""
    params = getattr(getattr(source_info, "config", None), "params", None)
    raw_vectors = getattr(params, "vectors", None)
    raw_sparse = getattr(params, "sparse_vectors", None)

    vectors_config: Dict[str, qmodels.VectorParams] = {}
    if isinstance(raw_vectors, dict) and raw_vectors:
        for name, cfg in raw_vectors.items():
            vectors_config[name] = qmodels.VectorParams(
                size=cfg.size,
                distance=cfg.distance,
            )
    elif raw_vectors is not None and hasattr(raw_vectors, "size"):
        vectors_config["dense"] = qmodels.VectorParams(
            size=raw_vectors.size,
            distance=raw_vectors.distance,
        )
    else:
        vectors_config["dense"] = qmodels.VectorParams(
            size=1536,
            distance=qmodels.Distance.COSINE,
        )

    sparse_vectors_config: Dict[str, qmodels.SparseVectorParams] = {}
    if isinstance(raw_sparse, dict) and raw_sparse:
        for name, cfg in raw_sparse.items():
            idx = getattr(cfg, "index", None)
            on_disk = getattr(idx, "on_disk", False) if idx is not None else False
            sparse_vectors_config[name] = qmodels.SparseVectorParams(
                index=qmodels.SparseIndexParams(on_disk=bool(on_disk))
            )
    else:
        sparse_vectors_config["sparse"] = qmodels.SparseVectorParams(
            index=qmodels.SparseIndexParams(on_disk=False)
        )

    return vectors_config, sparse_vectors_config


def ensure_target_payload_indexes(target_client: QdrantClient, collection_name: str) -> None:
    """대상 서버 컬렉션에 검색/필터용 Payload 키워드 인덱스를 생성합니다."""
    for field_name in REQUIRED_KEYWORD_INDEXES:
        try:
            target_client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
            print(f"  [Index] Created keyword index: {field_name}")
        except Exception as e:
            print(f"  [Index] Skipped/Existing '{field_name}': {e}")


def migrate_via_scroll_upsert(
    source_client: QdrantClient,
    target_client: QdrantClient,
    source_collection: str,
    target_collection: str,
    vectors_config: Dict[str, qmodels.VectorParams],
    sparse_vectors_config: Dict[str, qmodels.SparseVectorParams],
    force: bool,
    batch_size: int,
    source_count: int,
) -> None:
    """qdrant-client.migrate() 미지원 환경 또는 별칭 컬렉션 테스트용 scroll + batch upsert 이전."""
    existing_cols = [c.name for c in target_client.get_collections().collections]
    if target_collection in existing_cols:
        if force:
            print(f"[Target] --force 지정으로 기존 컬렉션 '{target_collection}' 삭제 후 재생성합니다...")
            target_client.delete_collection(target_collection)
        else:
            raise RuntimeError(f"대상 컬렉션 '{target_collection}'이 이미 존재합니다.")

    print(f"[Target] 컬렉션 '{target_collection}' 생성 중 (vectors={list(vectors_config.keys())}, sparse={list(sparse_vectors_config.keys())})...")
    target_client.create_collection(
        collection_name=target_collection,
        vectors_config=vectors_config,
        sparse_vectors_config=sparse_vectors_config,
    )

    offset = None
    migrated = 0
    while True:
        records, next_offset = source_client.scroll(
            collection_name=source_collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not records:
            break

        points: List[qmodels.PointStruct] = [
            qmodels.PointStruct(id=rec.id, vector=rec.vector, payload=rec.payload)
            for rec in records
        ]
        target_client.upsert(collection_name=target_collection, points=points)
        migrated += len(points)
        print(f"  -> {migrated}/{source_count} points 이전 완료...")

        if next_offset is None:
            break
        offset = next_offset


def run_migration(
    local_path: str,
    qdrant_url: str,
    source_collection: str,
    target_collection: str,
    force: bool = False,
    batch_size: int = 100,
) -> int:
    print("=" * 68)
    print(" FigIndex Qdrant Local -> Server 데이터 이전")
    print(f" - 원본 (Local):  {local_path} [{source_collection}]")
    print(f" - 대상 (Server): {qdrant_url} [{target_collection}]")
    print(f" - 덮어쓰기(--force): {force}")
    print("=" * 68)

    if not os.path.exists(local_path):
        print(f"[Error] 원본 로컬 Qdrant 폴더가 존재하지 않습니다: {local_path}")
        return 1

    source_client: Optional[QdrantClient] = None
    target_client: Optional[QdrantClient] = None

    try:
        target_client = QdrantClient(url=qdrant_url, timeout=30.0)
        existing_target_cols = [c.name for c in target_client.get_collections().collections]

        if target_collection in existing_target_cols and not force:
            existing_info = target_client.get_collection(target_collection)
            print(
                f"[Skip] 대상 서버에 컬렉션 '{target_collection}'이 이미 존재합니다 "
                f"(현재 {existing_info.points_count} points)."
            )
            print("[Skip] 기존 서버 데이터를 보호하기 위해 덮어쓰지 않고 종료합니다. 덮어쓰려면 --force 옵션을 지정하세요.")
            return 0

        source_client = QdrantClient(path=local_path)
        source_cols = [c.name for c in source_client.get_collections().collections]
        if source_collection not in source_cols:
            print(f"[Error] 원본 로컬 저장소에 컬렉션 '{source_collection}'이 없습니다.")
            return 1

        source_info = source_client.get_collection(source_collection)
        source_count = source_info.points_count
        vectors_config, sparse_vectors_config = extract_vector_configs(source_info)
        print(
            f"[Source] 확인 완료: {source_count} points | "
            f"dense={ {k: (v.size, str(v.distance)) for k, v in vectors_config.items()} } | "
            f"sparse={list(sparse_vectors_config.keys())}"
        )

        use_builtin_migrate = (
            source_collection == target_collection
            and hasattr(source_client, "migrate")
        )

        if use_builtin_migrate:
            print("[Migration] qdrant_client.migrate() 메서드를 사용하여 이전을 시작합니다...")
            source_client.migrate(
                dest_client=target_client,
                collection_names=[source_collection],
                batch_size=batch_size,
                recreate_on_collision=force,
            )
        else:
            print("[Migration] scroll + batch upsert 방식으로 이전을 시작합니다...")
            migrate_via_scroll_upsert(
                source_client=source_client,
                target_client=target_client,
                source_collection=source_collection,
                target_collection=target_collection,
                vectors_config=vectors_config,
                sparse_vectors_config=sparse_vectors_config,
                force=force,
                batch_size=batch_size,
                source_count=source_count,
            )

        print("[Indexes] 대상 컬렉션 Payload 인덱스를 확인/생성합니다...")
        ensure_target_payload_indexes(target_client, target_collection)

        target_info = target_client.get_collection(target_collection)
        target_count = target_info.points_count

        print("\n" + "=" * 68)
        print(" 이전 결과 검증")
        print(f" - 원본(Local) point 수:  {source_count}")
        print(f" - 대상(Server) point 수: {target_count}")
        if source_count != target_count:
            print("[FAIL] 원본과 대상의 point 개수가 일치하지 않습니다!")
            print("=" * 68)
            return 1

        print("[SUCCESS] point 개수 일치 확인 완료 (원본 로컬 폴더는 변경되지 않았습니다).")
        print("=" * 68)
        return 0

    except Exception as e:
        print(f"[Error] 데이터 이전 중 오류 발생: {e}")
        return 1
    finally:
        if source_client is not None:
            try:
                source_client.close()
            except Exception:
                pass
        if target_client is not None:
            try:
                target_client.close()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Qdrant local embedded data to Qdrant server")
    parser.add_argument(
        "--local-path",
        default=os.getenv("QDRANT_LOCAL_PATH", "/data/qdrant_local"),
        help="원본 로컬 Qdrant 폴더 경로 (기본: /data/qdrant_local)",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("QDRANT_URL", "http://qdrant:6333"),
        help="대상 Qdrant 서버 URL (기본: http://qdrant:6333)",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("QDRANT_COLLECTION", "figindex_elements"),
        help="컬렉션 이름 (기본: figindex_elements)",
    )
    parser.add_argument(
        "--target-collection",
        default=None,
        help="대상 컬렉션 이름 (미지정 시 --collection과 동일)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="배치 크기 (기본: 100)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="대상에 컬렉션이 이미 존재할 경우 덮어쓰기",
    )
    args = parser.parse_args()
    target_col = args.target_collection or args.collection
    sys.exit(
        run_migration(
            local_path=args.local_path,
            qdrant_url=args.url,
            source_collection=args.collection,
            target_collection=target_col,
            force=args.force,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    main()

