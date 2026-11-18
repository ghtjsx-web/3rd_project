"""SQLite persistence for upload batches and their PDF documents."""

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Sequence, Tuple

from shared.schemas import Batch, Document, DocStatus, ReviewLog


_CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    collection_id TEXT,
    doc_count INTEGER NOT NULL CHECK (doc_count >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    doc_hash TEXT NOT NULL,
    doc_name TEXT NOT NULL,
    doc_title TEXT,
    doc_type TEXT,
    domain TEXT,
    source_org TEXT,
    authors TEXT NOT NULL,
    publish_date TEXT,
    page_count INTEGER,
    collection_id TEXT,
    doc_status TEXT NOT NULL,
    doc_error TEXT,
    created_at TEXT NOT NULL,
    extra_metadata TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS index_documents_batch_id ON documents(batch_id);
CREATE INDEX IF NOT EXISTS index_documents_doc_hash ON documents(doc_hash);

CREATE TABLE IF NOT EXISTS review_logs (
    review_id TEXT PRIMARY KEY,
    element_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    review_action TEXT NOT NULL,
    changed_fields TEXT NOT NULL,
    "before" TEXT NOT NULL,
    "after" TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    reviewed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS index_review_logs_element_id ON review_logs(element_id);
"""


def _file_doc_hash(path: Path) -> str:
    doc_hash = hashlib.sha256()
    with path.open("rb") as stored_file:
        while True:
            content = stored_file.read(1024 * 1024)
            if not content:
                break
            doc_hash.update(content)
    return doc_hash.hexdigest()


def _copy_without_overwrite(staged_path: Path, destination: Path) -> bool:
    """Copy a staged PDF only when the destination does not already exist."""
    created = False
    try:
        with destination.open("xb") as destination_file:
            created = True
            with staged_path.open("rb") as staged_file:
                shutil.copyfileobj(staged_file, destination_file, length=1024 * 1024)
    except FileExistsError:
        return False
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return True


def _insert_batch(connection: sqlite3.Connection, batch: Batch) -> None:
    batch_data = batch.model_dump(mode="json")
    connection.execute(
        """
        INSERT INTO batches (batch_id, collection_id, doc_count, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            batch_data["batch_id"],
            batch_data["collection_id"],
            batch_data["doc_count"],
            batch_data["created_at"],
        ),
    )


def _insert_document(connection: sqlite3.Connection, document: Document) -> None:
    document_data = document.model_dump(mode="json")
    connection.execute(
        """
        INSERT INTO documents (
            doc_id, batch_id, doc_hash, doc_name, doc_title, doc_type, domain,
            source_org, authors, publish_date, page_count, collection_id,
            doc_status, doc_error, created_at, extra_metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_data["doc_id"],
            document_data["batch_id"],
            document_data["doc_hash"],
            document_data["doc_name"],
            document_data["doc_title"],
            document_data["doc_type"],
            document_data["domain"],
            document_data["source_org"],
            json.dumps(document_data["authors"], ensure_ascii=False),
            document_data["publish_date"],
            document_data["page_count"],
            document_data["collection_id"],
            document_data["doc_status"],
            document_data["doc_error"],
            document_data["created_at"],
            json.dumps(document_data["extra_metadata"], ensure_ascii=False),
        ),
    )


def persist_batch(
    db_path: str,
    pdfs_dir: str,
    batch: Batch,
    staged_documents: Sequence[Tuple[Document, str]],
) -> list[Document]:
    """Persist one Batch and its Documents without overwriting existing PDFs."""
    database_path = Path(db_path)
    stored_pdfs_dir = Path(pdfs_dir).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    stored_pdfs_dir.mkdir(parents=True, exist_ok=True)

    schema_connection = sqlite3.connect(str(database_path), timeout=30)
    try:
        schema_connection.execute("PRAGMA foreign_keys = ON")
        schema_connection.executescript(_CREATE_SCHEMA)
    finally:
        schema_connection.close()

    connection = sqlite3.connect(str(database_path), timeout=30)
    connection.execute("PRAGMA foreign_keys = ON")
    created_paths: list[Path] = []
    registered_documents: list[Document] = []

    try:
        connection.execute("BEGIN IMMEDIATE")
        _insert_batch(connection, batch)

        for document, staged_path_value in staged_documents:
            staged_path = Path(staged_path_value)
            existing = connection.execute(
                """
                SELECT doc_id
                FROM documents
                WHERE doc_hash = ? AND doc_status IN (?, ?, ?)
                ORDER BY created_at
                LIMIT 1
                """,
                (
                    document.doc_hash,
                    DocStatus.UPLOADED.value,
                    DocStatus.PROCESSING.value,
                    DocStatus.COMPLETED.value,
                ),
            ).fetchone()

            if existing:
                document = document.model_copy(
                    update={
                        "doc_status": DocStatus.DUPLICATE,
                        "doc_error": existing[0],
                    }
                )
            else:
                if "/" in document.doc_name or chr(92) in document.doc_name:
                    raise ValueError("doc_name must be a safe file name")
                destination = stored_pdfs_dir / document.doc_name
                if destination.exists():
                    if _file_doc_hash(destination) != document.doc_hash:
                        document = document.model_copy(
                            update={
                                "doc_status": DocStatus.FAILED,
                                "doc_error": "같은 이름의 다른 PDF가 이미 저장되어 있습니다.",
                            }
                        )
                else:
                    created = _copy_without_overwrite(staged_path, destination)
                    if created:
                        created_paths.append(destination)
                    elif not destination.exists() or _file_doc_hash(destination) != document.doc_hash:
                        document = document.model_copy(
                            update={
                                "doc_status": DocStatus.FAILED,
                                "doc_error": "같은 이름의 다른 PDF가 이미 저장되어 있습니다.",
                            }
                        )

            _insert_document(connection, document)
            registered_documents.append(document)

        connection.commit()
        return registered_documents
    except Exception:
        connection.rollback()
        for created_path in created_paths:
            created_path.unlink(missing_ok=True)
        raise
    finally:
        connection.close()


def get_batch_documents(db_path: str, batch_id: str) -> list[Document] | None:
    """Return a batch's documents, or None when the batch does not exist."""
    database_path = Path(db_path)
    if not database_path.exists():
        return None

    connection = sqlite3.connect(str(database_path), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        batch = connection.execute(
            "SELECT batch_id FROM batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if batch is None:
            return None

        rows = connection.execute(
            "SELECT * FROM documents WHERE batch_id = ? ORDER BY rowid",
            (batch_id,),
        ).fetchall()
        documents = []
        for row in rows:
            document_data = dict(row)
            document_data["authors"] = json.loads(document_data["authors"])
            document_data["extra_metadata"] = json.loads(document_data["extra_metadata"])
            documents.append(Document.model_validate(document_data))
        return documents
    finally:
        connection.close()


def append_review_log(db_path: str, review_log: ReviewLog) -> None:
    """Append one immutable ReviewLog record to the metadata database."""
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(database_path), timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_CREATE_SCHEMA)
        review_data = review_log.model_dump(mode="json")
        connection.execute(
            """
            INSERT INTO review_logs (
                review_id, element_id, reviewer, review_action, changed_fields,
                "before", "after", confidence_score, reviewed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_data["review_id"],
                review_data["element_id"],
                review_data["reviewer"],
                review_data["review_action"],
                json.dumps(review_data["changed_fields"], ensure_ascii=False),
                json.dumps(review_data["before"], ensure_ascii=False),
                json.dumps(review_data["after"], ensure_ascii=False),
                review_data["confidence_score"],
                review_data["reviewed_at"],
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
