"""
업로드 DB(metadata.sqlite3)의 문서 상태를 바꾸는 함수 (설계서 '업로드→파이프라인 연결 설계', 함수 약속).

백엔드(backend/app/upload_store.py)와 작업자(pipeline/worker.py)가 함께 쓴다.
pipeline 컨테이너는 backend/app을 올리지 않고 shared/만 같이 쓰므로 여기에 둔다.

상태 흐름: UPLOADED → (claim) PROCESSING → COMPLETED | FAILED, FAILED → (retry) UPLOADED
- 상태를 바꾸는 UPDATE는 모두 "지금 상태가 무엇일 때만"이라는 조건을 붙여, 두 곳이 같은 문서를 동시에 바꾸지 않게 한다.
- 트랜잭션은 짧게 한다 (파이프라인을 도는 동안 DB를 잡고 있지 않음).
"""
import json
import sqlite3
from pathlib import Path
from typing import Optional

from shared.schemas import Document, DocStatus

CREATE_SCHEMA = """
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

RESET_NOTE = "작업자 재시작으로 다시 처리"
ACTIVE_STATUSES = (DocStatus.UPLOADED.value, DocStatus.PROCESSING.value, DocStatus.COMPLETED.value)


class RetryNotAllowed(Exception):
    """다시 시도할 수 없는 문서 (FAILED가 아니거나, 같은 내용의 문서가 이미 처리 중·완료)."""


def connect(db_path: str) -> sqlite3.Connection:
    """스키마를 만든 연결을 돌려준다. 행은 이름으로 읽는다."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(CREATE_SCHEMA)
    connection.row_factory = sqlite3.Row
    return connection


def row_to_document(row: sqlite3.Row) -> Document:
    data = dict(row)
    data.pop("row_id", None)
    data["authors"] = json.loads(data["authors"])
    data["extra_metadata"] = json.loads(data["extra_metadata"])
    return Document.model_validate(data)


def _get(connection: sqlite3.Connection, doc_id: str) -> Optional[Document]:
    row = connection.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    return row_to_document(row) if row else None


def claim_next_document(db_path: str) -> Optional[Document]:
    """가장 오래된 UPLOADED 1건을 PROCESSING으로 바꾸고 돌려준다. 없으면 None."""
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT doc_id FROM documents WHERE doc_status = ? ORDER BY created_at, rowid LIMIT 1",
            (DocStatus.UPLOADED.value,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        changed = connection.execute(
            "UPDATE documents SET doc_status = ?, doc_error = NULL WHERE doc_id = ? AND doc_status = ?",
            (DocStatus.PROCESSING.value, row["doc_id"], DocStatus.UPLOADED.value),
        ).rowcount
        document = _get(connection, row["doc_id"]) if changed else None
        connection.commit()
        return document
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def mark_document_completed(db_path: str, document: Document) -> bool:
    """PROCESSING인 문서를 COMPLETED로 바꾸고 처리에서 알아낸 메타데이터를 저장한다.

    문서가 PROCESSING이 아니면(그 사이 누가 바꿈) 아무것도 하지 않고 False.
    """
    data = document.model_dump(mode="json")
    connection = connect(db_path)
    try:
        changed = connection.execute(
            """
            UPDATE documents
            SET doc_title = ?, doc_type = ?, domain = ?, source_org = ?, authors = ?,
                publish_date = ?, page_count = ?, doc_status = ?, doc_error = NULL, extra_metadata = ?
            WHERE doc_id = ? AND doc_status = ?
            """,
            (
                data["doc_title"], data["doc_type"], data["domain"], data["source_org"],
                json.dumps(data["authors"], ensure_ascii=False), data["publish_date"], data["page_count"],
                DocStatus.COMPLETED.value, json.dumps(data["extra_metadata"], ensure_ascii=False),
                data["doc_id"], DocStatus.PROCESSING.value,
            ),
        ).rowcount
        connection.commit()
        return changed == 1
    finally:
        connection.close()


def mark_document_failed(db_path: str, doc_id: str, doc_error: str) -> bool:
    """PROCESSING인 문서를 FAILED로 바꾸고 사유를 남긴다. PROCESSING이 아니면 False."""
    connection = connect(db_path)
    try:
        changed = connection.execute(
            "UPDATE documents SET doc_status = ?, doc_error = ? WHERE doc_id = ? AND doc_status = ?",
            (DocStatus.FAILED.value, doc_error, doc_id, DocStatus.PROCESSING.value),
        ).rowcount
        connection.commit()
        return changed == 1
    finally:
        connection.close()


def reset_processing_documents(db_path: str) -> int:
    """남아 있는 PROCESSING을 모두 UPLOADED로 되돌린다 (작업자가 켜질 때만, 작업자는 하나뿐)."""
    connection = connect(db_path)
    try:
        changed = connection.execute(
            "UPDATE documents SET doc_status = ?, doc_error = ? WHERE doc_status = ?",
            (DocStatus.UPLOADED.value, RESET_NOTE, DocStatus.PROCESSING.value),
        ).rowcount
        connection.commit()
        return changed
    finally:
        connection.close()


def retry_document(db_path: str, doc_id: str) -> Optional[Document]:
    """FAILED 문서를 UPLOADED로 되돌린다. 문서가 없으면 None.

    FAILED가 아니거나, 같은 내용(doc_hash)의 다른 문서가 이미 UPLOADED·PROCESSING·COMPLETED면 RetryNotAllowed.
    """
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        document = _get(connection, doc_id)
        if document is None:
            connection.commit()
            return None
        if document.doc_status != DocStatus.FAILED:
            raise RetryNotAllowed(f"FAILED인 문서만 다시 시도할 수 있습니다 (지금: {document.doc_status.value})")
        same = connection.execute(
            f"SELECT doc_id FROM documents WHERE doc_hash = ? AND doc_id <> ? AND doc_status IN ({','.join('?' * len(ACTIVE_STATUSES))})",
            (document.doc_hash, doc_id, *ACTIVE_STATUSES),
        ).fetchone()
        if same is not None:
            raise RetryNotAllowed(f"같은 내용의 문서가 이미 있습니다 (doc_id={same['doc_id']})")
        connection.execute(
            "UPDATE documents SET doc_status = ?, doc_error = NULL WHERE doc_id = ? AND doc_status = ?",
            (DocStatus.UPLOADED.value, doc_id, DocStatus.FAILED.value),
        )
        updated = _get(connection, doc_id)
        connection.commit()
        return updated
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
