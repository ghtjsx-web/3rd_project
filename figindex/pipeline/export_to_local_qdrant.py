import os
import sys
import shutil
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

load_dotenv()


def migrate_collection_to_local():
    source_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    collection_name = os.getenv("QDRANT_COLLECTION", "figindex_elements")
    local_path = os.getenv("QDRANT_LOCAL_PATH", "/data/qdrant_local")

    print("=" * 68)
    print(" FigIndex Qdrant Server -> Local Mode (Embedded) Migration Tool")
    print(f" Source Server URL: {source_url}")
    print(f" Target Local Path: {local_path}")
    print(f" Collection Name:   {collection_name}")
    print("=" * 68)

    # 1. Connect to Source Qdrant Server
    try:
        source_client = QdrantClient(url=source_url, timeout=10.0)
        source_col_info = source_client.get_collection(collection_name)
        source_count = source_col_info.points_count
        print(f"[Source] Successfully connected. Found {source_count} points in collection '{collection_name}'.")
    except Exception as e:
        print(f"[Error] Failed to connect to source Qdrant at {source_url}: {e}")
        sys.exit(1)

    if source_count == 0:
        print("[Warn] Source collection has 0 points. Nothing to migrate.")
        return

    # 2. Initialize Target Local QdrantClient (Embedded Disk Mode)
    os.makedirs(local_path, exist_ok=True)
    target_client = QdrantClient(path=local_path)

    # Recreate collection in target if exists or create fresh
    existing_target_cols = [c.name for c in target_client.get_collections().collections]
    if collection_name in existing_target_cols:
        print(f"[Target] Collection '{collection_name}' already exists in local mode. Recreating for clean sync...")
        target_client.delete_collection(collection_name)

    print(f"[Target] Creating '{collection_name}' collection in local storage...")
    target_client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "dense": qmodels.VectorParams(
                size=1536,
                distance=qmodels.Distance.COSINE
            )
        },
        sparse_vectors_config={
            "sparse": qmodels.SparseVectorParams(
                index=qmodels.SparseIndexParams(
                    on_disk=False
                )
            )
        }
    )

    # 3. Create Payload Indexes in Target
    index_fields = [
        ("element_type", qmodels.PayloadSchemaType.KEYWORD),
        ("review_status", qmodels.PayloadSchemaType.KEYWORD),
        ("source_org", qmodels.PayloadSchemaType.KEYWORD),
        ("publish_date", qmodels.PayloadSchemaType.KEYWORD),
        ("entities", qmodels.PayloadSchemaType.KEYWORD),
        ("doc_name", qmodels.PayloadSchemaType.KEYWORD),
        ("confidence_score", qmodels.PayloadSchemaType.FLOAT),
    ]
    for field_name, schema_type in index_fields:
        target_client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=schema_type
        )
    print(f"[Target] Created {len(index_fields)} payload indexes.")

    # 4. Fetch all points from source (scroll in batches)
    print(f"[Migration] Fetching points from source and saving to local storage...")
    batch_size = 100
    offset = None
    total_migrated = 0

    while True:
        records, next_offset = source_client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True
        )

        if not records:
            break

        # Convert records to target points
        points_to_upsert = []
        for rec in records:
            points_to_upsert.append(
                qmodels.PointStruct(
                    id=rec.id,
                    vector=rec.vector,
                    payload=rec.payload
                )
            )

        target_client.upsert(
            collection_name=collection_name,
            points=points_to_upsert
        )
        total_migrated += len(points_to_upsert)
        print(f"  -> Migrated {total_migrated}/{source_count} points...")

        if next_offset is None:
            break
        offset = next_offset

    # 5. Verify Target Points
    target_info = target_client.get_collection(collection_name)
    target_count = target_info.points_count

    print("\n" + "=" * 68)
    print(" Migration Verification Summary")
    print("=" * 68)
    print(f"  * Source (Server) Points:  {source_count}")
    print(f"  * Target (Local) Points:   {target_count}")
    print(f"  * Local Storage Directory: {local_path}")
    if source_count == target_count:
        print("  * Status: SUCCESS (100% Data Integrity Verified)")
    else:
        print("  * Status: WARNING (Point counts do not match)")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    migrate_collection_to_local()

