import os
import sys
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "figindex_elements")


def init_figindex_collection():
    print(f"[Init] Connecting to Qdrant at {QDRANT_URL}...")
    try:
        client = QdrantClient(url=QDRANT_URL, timeout=10.0)
        collections = [c.name for c in client.get_collections().collections]
    except Exception as e:
        print(f"[Error] Failed to connect to Qdrant at {QDRANT_URL}: {e}")
        sys.exit(1)

    if QDRANT_COLLECTION in collections:
        print(f"[Init] Collection '{QDRANT_COLLECTION}' already exists. Skipping initialization.")
        return

    print(f"[Init] Creating collection '{QDRANT_COLLECTION}' (Dense: 1536 dim Cosine, Sparse: BM25 slot)...")
    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config={
            "dense": qmodels.VectorParams(
                size=1536,
                distance=qmodels.Distance.COSINE
            )
        },
        sparse_vectors_config={
            "sparse": qmodels.SparseVectorParams(
                index=qmodels.SparseIndexParams(on_disk=False)
            )
        }
    )
    print(f"[Init] Collection '{QDRANT_COLLECTION}' created.")

    # Create payload indexes as specified in PRD v0.4
    payload_indices = [
        ("element_type", qmodels.PayloadSchemaType.KEYWORD),
        ("review_status", qmodels.PayloadSchemaType.KEYWORD),
        ("doc_type", qmodels.PayloadSchemaType.KEYWORD),
        ("source_org", qmodels.PayloadSchemaType.KEYWORD),
        ("publish_date", qmodels.PayloadSchemaType.KEYWORD),
        ("entities", qmodels.PayloadSchemaType.KEYWORD),
    ]

    for field_name, schema_type in payload_indices:
        print(f"[Init] Creating payload index: {field_name} ({schema_type})...")
        client.create_payload_index(
            collection_name=QDRANT_COLLECTION,
            field_name=field_name,
            field_schema=schema_type
        )

    print(f"[Success] FigIndex collection '{QDRANT_COLLECTION}' and payload indices are ready!")


if __name__ == "__main__":
    init_figindex_collection()

