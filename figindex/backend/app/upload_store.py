"""SQLite persistence for upload batches and their PDF documents."""

import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Mapping, Sequence, Tuple

from shared.schemas import Batch, Document, DocStatus, ReviewLog
from shared.upload_db import CREATE_SCHEMA, row_to_document


# 스키마와 상태 변경 함수는 백엔드와 작업자가 같이 쓰도록 shared/upload_db.py에 있다.
_CREATE_SCHEMA = CREATE_SCHEMA


def _file_doc_hash(path: Path) -> str:
    doc_hash = hashlib.sha256()
    with path.open("rb") as stored_file:
        while True:
            content = stored_file.read(1024 * 1024)
            if not content:
                break
            doc_hash.update(content)
    return doc_hash.hexdigest()


def register_existing_pdfs(
    db_path: str,
    pdfs_dir: str,
    qdrant_doc_ids: Mapping[str, str],
) -> tuple[int, int, int]:
    """Register and reconcile local PDFs using read-only Qdrant metadata.

    PDFs whose doc_name is present in Qdrant reuse its doc_id and are marked
    COMPLETED. Other PDFs are marked UPLOADED. Existing active rows are also
    reconciled by doc_hash. Returns (scanned_count, registered_count,
    skipped_duplicate_count).
    """
    source_pdfs_dir = Path(pdfs_dir)
    if not source_pdfs_dir.is_dir():
        raise FileNotFoundError(f"PDF directory does not exist: {source_pdfs_dir}")

    pdf_paths = sorted(
        (
            path
            for path in source_pdfs_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda path: path.name.casefold(),
    )
    scanned_count = len(pdf_paths)
    if scanned_count == 0:
        return 0, 0, 0

    hashed_pdfs = [(path, _file_doc_hash(path)) for path in pdf_paths]
    hashed_pdfs.sort(
        key=lambda item: (
            item[1],
            item[0].name not in qdrant_doc_ids,
            item[0].name.casefold(),
        )
    )
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(database_path), timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_CREATE_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        connection.row_factory = sqlite3.Row

        existing_documents = {}
        for row in connection.execute(
            """
            SELECT rowid AS row_id, doc_id, doc_hash, doc_status, extra_metadata
            FROM documents
            WHERE doc_status IN (?, ?, ?)
            """,
            (
                DocStatus.UPLOADED.value,
                DocStatus.PROCESSING.value,
                DocStatus.COMPLETED.value,
            ),
        ):
            if row["doc_hash"] in existing_documents:
                raise ValueError(
                    f"Multiple active documents have doc_hash {row['doc_hash']}"
                )
            existing_documents[row["doc_hash"]] = row

        existing_hashes = set(existing_documents)
        reconciled_hashes: set[str] = set()

        new_pdfs: list[tuple[Path, str, str | None]] = []
        skipped_duplicate_count = 0
        for pdf_path, doc_hash in hashed_pdfs:
            qdrant_doc_id = qdrant_doc_ids.get(pdf_path.name)
            if doc_hash in existing_hashes:
                skipped_duplicate_count += 1
                existing_document = existing_documents.get(doc_hash)
                if (
                    existing_document is not None
                    and doc_hash not in reconciled_hashes
                    # 작업자가 처리 중인 문서는 건드리지 않는다 (설계서: 처리 중 문서 건너뛰기)
                    and existing_document["doc_status"] != DocStatus.PROCESSING.value
                ):
                    doc_id = qdrant_doc_id or existing_document["doc_id"]
                    # 작업자가 처리한 문서(extra_metadata.element_count 있음)는 Qdrant에 없어도 COMPLETED를 유지한다
                    # (도표 0개 문서, 시험 컬렉션에 처리한 문서). 예전 일괄 등록의 COMPLETED는 그대로 UPLOADED로 낮춘다.
                    processed_by_worker = (
                        existing_document["doc_status"] == DocStatus.COMPLETED.value
                        and "element_count" in json.loads(existing_document["extra_metadata"] or "{}")
                    )
                    doc_status = (
                        DocStatus.COMPLETED
                        if qdrant_doc_id or processed_by_worker
                        else DocStatus.UPLOADED
                    )
                    conflicting_document = connection.execute(
                        """
                        SELECT doc_hash
                        FROM documents
                        WHERE doc_id = ? AND rowid <> ?
                        """,
                        (doc_id, existing_document["row_id"]),
                    ).fetchone()
                    if conflicting_document is not None:
                        raise ValueError(
                            f"doc_id {doc_id} is already registered for another document"
                        )
                    connection.execute(
                        """
                        UPDATE documents
                        SET doc_id = ?, doc_name = ?, doc_status = ?
                        WHERE rowid = ?
                        """,
                        (
                            doc_id,
                            pdf_path.name,
                            doc_status.value,
                            existing_document["row_id"],
                        ),
                    )
                    reconciled_hashes.add(doc_hash)
                continue
            existing_hashes.add(doc_hash)
            new_pdfs.append((pdf_path, doc_hash, qdrant_doc_id))

        if not new_pdfs:
            connection.commit()
            return scanned_count, 0, skipped_duplicate_count

        batch = Batch(batch_id=str(uuid.uuid4()), doc_count=len(new_pdfs))
        _insert_batch(connection, batch)
        for pdf_path, doc_hash, qdrant_doc_id in new_pdfs:
            document = Document(
                doc_id=qdrant_doc_id or str(uuid.uuid4()),
                batch_id=batch.batch_id,
                doc_hash=doc_hash,
                doc_name=pdf_path.name,
                doc_status=(
                    DocStatus.COMPLETED
                    if qdrant_doc_id
                    else DocStatus.UPLOADED
                ),
            )
            _insert_document(connection, document)

        connection.commit()
        return scanned_count, len(new_pdfs), skipped_duplicate_count
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


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
        return [row_to_document(row) for row in rows]
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
