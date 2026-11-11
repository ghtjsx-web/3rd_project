import os
import sys
import shutil
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "figindex_elements")
CROPS_DIR = Path(os.getenv("CROPS_DIR", "/data/crops"))


def clean_crops_directory():
    """Clear test crops in crops directory, preserving .gitkeep"""
    if CROPS_DIR.exists():
        for item in CROPS_DIR.iterdir():
            if item.name == ".gitkeep":
                continue
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                print(f"[Warn] Could not delete {item}: {e}")
        print(f"[Init] Cleaned test files in {CROPS_DIR} (preserved .gitkeep).")


def init_figindex_collection(reset: bool = False):
    print(f"[Init] Connecting to Qdrant at {QDRANT_URL}...")
    try:
        client = QdrantClient(url=QDRANT_URL, timeout=10.0)
        collections = [c.name for c in client.get_collections().collections]
    except Exception as e:
        print(f"[Error] Failed to connect to Qdrant at {QDRANT_URL}: {e}")
        sys.exit(1)

    if QDRANT_COLLECTION in collections:
        if reset or "--reset" in sys.argv:
            print(f"[Init] Existing collection '{QDRANT_COLLECTION}' found. Deleting for clean initialization...")
            client.delete_collection(collection_name=QDRANT_COLLECTION)
        else:
            print(f"[Init] Collection '{QDRANT_COLLECTION}' already exists. Skipping recreation (use --reset to recreate).")
            return

    clean_crops_directory()

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
        ("extra_metadata.target", qmodels.PayloadSchemaType.KEYWORD),
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
    reset_flag = "--reset" in sys.argv
    init_figindex_collection(reset=reset_flag)
