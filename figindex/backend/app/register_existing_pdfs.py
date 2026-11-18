"""Seed metadata.sqlite3 with hashes for PDFs that are already indexed."""

import argparse
import os
from pathlib import Path

from app.upload_store import register_existing_pdfs


def main() -> None:
    default_data_dir = Path(
        os.getenv("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))
    )
    parser = argparse.ArgumentParser(
        description="Register existing indexed PDFs in the upload metadata database."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir,
        help="Directory containing pdfs/ and metadata.sqlite3 (defaults to DATA_DIR).",
    )
    args = parser.parse_args()

    scanned_count, registered_count, skipped_duplicate_count = register_existing_pdfs(
        str(args.data_dir / "metadata.sqlite3"),
        str(args.data_dir / "pdfs"),
    )
    print(
        f"PDF {scanned_count}개 확인, 신규 등록 {registered_count}개, "
        f"이미 등록된 중복 {skipped_duplicate_count}개"
    )


if __name__ == "__main__":
    main()
