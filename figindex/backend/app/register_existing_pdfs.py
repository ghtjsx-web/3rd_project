"""Seed and reconcile metadata.sqlite3 using local PDFs and Qdrant metadata."""

import argparse
import os
from pathlib import Path

from app.upload_store import register_existing_pdfs


def read_qdrant_doc_ids_by_name(client, collection_name: str) -> dict[str, str]:
    """Read doc_name-to-doc_id mappings from Qdrant without modifying it."""
    doc_ids_by_name: dict[str, str] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=200,
            offset=offset,
            with_payload=["doc_name", "doc_id"],
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            doc_name = payload.get("doc_name")
            doc_id = payload.get("doc_id")
            if not isinstance(doc_name, str) or not doc_name:
                continue
            if not isinstance(doc_id, str) or not doc_id:
                continue

            existing_doc_id = doc_ids_by_name.get(doc_name)
            if existing_doc_id is not None and existing_doc_id != doc_id:
                raise ValueError(
                    f"Qdrant has multiple doc_id values for doc_name {doc_name!r}"
                )
            doc_ids_by_name[doc_name] = doc_id

        if offset is None:
            return doc_ids_by_name


def main() -> None:
    default_data_dir = Path(
        os.getenv("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))
    )
    parser = argparse.ArgumentParser(
        description="Register existing PDFs and reconcile their status with Qdrant."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help="Directory containing pdfs/ and metadata.sqlite3 (defaults to DATA_DIR).",
    )
    args = parser.parse_args()

    from app.main import QDRANT_COLLECTION, close_qdrant_client, get_qdrant_client

    client = get_qdrant_client()
    try:
        qdrant_doc_ids = read_qdrant_doc_ids_by_name(client, QDRANT_COLLECTION)
    finally:
        close_qdrant_client()

    scanned_count, registered_count, skipped_duplicate_count = register_existing_pdfs(
        str(args.data_dir / "metadata.sqlite3"),
        str(args.data_dir / "pdfs"),
        qdrant_doc_ids,
    )
    print(
        f"PDF {scanned_count}개 확인, 신규 등록 {registered_count}개, "
        f"이미 등록된 중복 {skipped_duplicate_count}개"
    )


if __name__ == "__main__":
    main()
