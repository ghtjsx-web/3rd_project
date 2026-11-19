"""Isolated tests for upload metadata persistence and existing PDF registration."""

import hashlib
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from shared.schemas import Batch, DocStatus, Document
from app.upload_store import persist_batch, register_existing_pdfs
from app.register_existing_pdfs import read_qdrant_doc_ids_by_name


class UploadStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.db_path = self.root_dir / "metadata.sqlite3"
        self.pdfs_dir = self.root_dir / "pdfs"
        self.staged_dir = self.root_dir / "staged"
        self.staged_dir.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_staged_document(
        self,
        batch_id: str,
        doc_name: str,
        content: bytes,
    ) -> tuple[Document, str]:
        doc_id = str(uuid.uuid4())
        staged_path = self.staged_dir / f"{doc_id}.pdf"
        staged_path.write_bytes(content)
        document = Document(
            doc_id=doc_id,
            batch_id=batch_id,
            doc_hash=hashlib.sha256(content).hexdigest(),
            doc_name=doc_name,
        )
        return document, str(staged_path)

    def _persist_batch(
        self,
        batch_id: str,
        staged_documents: list[tuple[Document, str]],
    ) -> list[Document]:
        batch = Batch(batch_id=batch_id, doc_count=len(staged_documents))
        return persist_batch(
            str(self.db_path),
            str(self.pdfs_dir),
            batch,
            staged_documents,
        )

    def test_first_upload_is_uploaded(self) -> None:
        batch_id = str(uuid.uuid4())
        document, staged_path = self._make_staged_document(
            batch_id, "first.pdf", b"first PDF content"
        )

        result = self._persist_batch(batch_id, [(document, staged_path)])

        self.assertEqual(result[0].doc_status, DocStatus.UPLOADED)
        self.assertEqual((self.pdfs_dir / "first.pdf").read_bytes(), b"first PDF content")

    def test_same_content_with_different_name_is_duplicate(self) -> None:
        first_batch_id = str(uuid.uuid4())
        first_document, first_staged_path = self._make_staged_document(
            first_batch_id, "first.pdf", b"same PDF content"
        )
        first_result = self._persist_batch(
            first_batch_id, [(first_document, first_staged_path)]
        )

        second_batch_id = str(uuid.uuid4())
        second_document, second_staged_path = self._make_staged_document(
            second_batch_id, "renamed.pdf", b"same PDF content"
        )
        second_result = self._persist_batch(
            second_batch_id, [(second_document, second_staged_path)]
        )

        self.assertEqual(second_result[0].doc_status, DocStatus.DUPLICATE)
        self.assertEqual(second_result[0].doc_error, first_result[0].doc_id)
        self.assertFalse((self.pdfs_dir / "renamed.pdf").exists())

    def test_same_name_with_different_content_fails_without_overwriting(self) -> None:
        first_batch_id = str(uuid.uuid4())
        first_document, first_staged_path = self._make_staged_document(
            first_batch_id, "same-name.pdf", b"original content"
        )
        self._persist_batch(first_batch_id, [(first_document, first_staged_path)])

        second_batch_id = str(uuid.uuid4())
        second_document, second_staged_path = self._make_staged_document(
            second_batch_id, "same-name.pdf", b"different content"
        )
        second_result = self._persist_batch(
            second_batch_id, [(second_document, second_staged_path)]
        )

        self.assertEqual(second_result[0].doc_status, DocStatus.FAILED)
        self.assertTrue(second_result[0].doc_error)
        self.assertEqual((self.pdfs_dir / "same-name.pdf").read_bytes(), b"original content")

    def test_same_name_twice_in_one_batch_uploads_first_and_fails_second(self) -> None:
        batch_id = str(uuid.uuid4())
        first = self._make_staged_document(batch_id, "same-name.pdf", b"first content")
        second = self._make_staged_document(batch_id, "same-name.pdf", b"second content")

        result = self._persist_batch(batch_id, [first, second])

        self.assertEqual(result[0].doc_status, DocStatus.UPLOADED)
        self.assertEqual(result[1].doc_status, DocStatus.FAILED)
        self.assertEqual((self.pdfs_dir / "same-name.pdf").read_bytes(), b"first content")

    def test_same_content_twice_in_one_batch_uploads_first_and_marks_second_duplicate(
        self,
    ) -> None:
        batch_id = str(uuid.uuid4())
        first = self._make_staged_document(batch_id, "first.pdf", b"same content")
        second = self._make_staged_document(batch_id, "second.pdf", b"same content")

        result = self._persist_batch(batch_id, [first, second])

        self.assertEqual(result[0].doc_status, DocStatus.UPLOADED)
        self.assertEqual(result[1].doc_status, DocStatus.DUPLICATE)
        self.assertEqual(result[1].doc_error, result[0].doc_id)
        self.assertFalse((self.pdfs_dir / "second.pdf").exists())

    def test_existing_pdf_registration_uses_qdrant_ids_and_is_idempotent(self) -> None:
        self.pdfs_dir.mkdir()
        (self.pdfs_dir / "old-a.pdf").write_bytes(b"indexed content a")
        (self.pdfs_dir / "old-a-copy.pdf").write_bytes(b"indexed content a")
        (self.pdfs_dir / "old-b.pdf").write_bytes(b"indexed content b")
        qdrant_doc_id = str(uuid.uuid4())
        qdrant_doc_ids = {"old-a.pdf": qdrant_doc_id}

        first_run = register_existing_pdfs(
            str(self.db_path), str(self.pdfs_dir), qdrant_doc_ids
        )
        second_run = register_existing_pdfs(
            str(self.db_path), str(self.pdfs_dir), qdrant_doc_ids
        )

        self.assertEqual(first_run, (3, 2, 1))
        self.assertEqual(second_run, (3, 0, 3))
        connection = sqlite3.connect(str(self.db_path))
        try:
            connection.row_factory = sqlite3.Row
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                2,
            )
            documents = {
                row["doc_name"]: (row["doc_id"], row["doc_status"])
                for row in connection.execute(
                    "SELECT doc_id, doc_name, doc_status FROM documents"
                )
            }
        finally:
            connection.close()
        self.assertEqual(
            documents["old-a.pdf"], (qdrant_doc_id, DocStatus.COMPLETED.value)
        )
        self.assertEqual(
            documents["old-b.pdf"][1], DocStatus.UPLOADED.value
        )
        self.assertEqual(len(documents), 2)

    def test_qdrant_document_mapping_reads_all_pages_without_writes(self) -> None:
        qdrant_doc_id_a = str(uuid.uuid4())
        qdrant_doc_id_b = str(uuid.uuid4())

        class FakeQdrantClient:
            def __init__(self) -> None:
                self.calls = []

            def scroll(self, **kwargs):
                self.calls.append(kwargs)
                if kwargs["offset"] is None:
                    return [
                        SimpleNamespace(
                            payload={"doc_name": "old-a.pdf", "doc_id": qdrant_doc_id_a}
                        )
                    ], "next-page"
                return [
                    SimpleNamespace(
                        payload={"doc_name": "old-a.pdf", "doc_id": qdrant_doc_id_a}
                    ),
                    SimpleNamespace(
                        payload={"doc_name": "old-b.pdf", "doc_id": qdrant_doc_id_b}
                    ),
                    SimpleNamespace(payload={"caption": "No document metadata"}),
                ], None

        client = FakeQdrantClient()
        result = read_qdrant_doc_ids_by_name(client, "test_collection")

        self.assertEqual(
            result,
            {"old-a.pdf": qdrant_doc_id_a, "old-b.pdf": qdrant_doc_id_b},
        )
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(
            all(call["with_payload"] == ["doc_name", "doc_id"] for call in client.calls)
        )
        self.assertTrue(all(call["with_vectors"] is False for call in client.calls))

    def test_qdrant_document_mapping_rejects_conflicting_doc_ids(self) -> None:
        class FakeQdrantClient:
            def scroll(self, **_kwargs):
                return [
                    SimpleNamespace(payload={"doc_name": "old-a.pdf", "doc_id": "doc-a"}),
                    SimpleNamespace(payload={"doc_name": "old-a.pdf", "doc_id": "doc-b"}),
                ], None

        with self.assertRaises(ValueError):
            read_qdrant_doc_ids_by_name(FakeQdrantClient(), "test_collection")

    def test_existing_registration_reconciles_prior_rows(self) -> None:
        self.pdfs_dir.mkdir()
        (self.pdfs_dir / "indexed.pdf").write_bytes(b"indexed content")
        (self.pdfs_dir / "not-indexed.pdf").write_bytes(b"pending content")

        initial_result = register_existing_pdfs(
            str(self.db_path), str(self.pdfs_dir), {}
        )
        self.assertEqual(initial_result, (2, 2, 0))

        connection = sqlite3.connect(str(self.db_path))
        try:
            connection.execute(
                "UPDATE documents SET doc_name = 'old-' || doc_name, doc_status = ?",
                (DocStatus.COMPLETED.value,),
            )
            original_ids = dict(
                connection.execute("SELECT doc_name, doc_id FROM documents")
            )
            connection.commit()
        finally:
            connection.close()

        qdrant_doc_id = str(uuid.uuid4())
        reconciled_result = register_existing_pdfs(
            str(self.db_path),
            str(self.pdfs_dir),
            {"indexed.pdf": qdrant_doc_id},
        )
        self.assertEqual(reconciled_result, (2, 0, 2))

        connection = sqlite3.connect(str(self.db_path))
        try:
            connection.row_factory = sqlite3.Row
            documents = {
                row["doc_name"]: (row["doc_id"], row["doc_status"])
                for row in connection.execute(
                    "SELECT doc_id, doc_name, doc_status FROM documents"
                )
            }
        finally:
            connection.close()

        self.assertEqual(
            documents["indexed.pdf"], (qdrant_doc_id, DocStatus.COMPLETED.value)
        )
        self.assertEqual(
            documents["not-indexed.pdf"],
            (original_ids["old-not-indexed.pdf"], DocStatus.UPLOADED.value),
        )


    def test_existing_registration_keeps_worker_results_and_processing(self) -> None:
        # 설계서: 작업자가 처리한 문서(도표 0개 포함)는 Qdrant에 없어도 COMPLETED 유지, PROCESSING은 건드리지 않음
        self.pdfs_dir.mkdir()
        (self.pdfs_dir / "text-only.pdf").write_bytes(b"text only report")
        (self.pdfs_dir / "running.pdf").write_bytes(b"being processed")
        register_existing_pdfs(str(self.db_path), str(self.pdfs_dir), {})

        connection = sqlite3.connect(str(self.db_path))
        try:
            connection.execute(
                "UPDATE documents SET doc_status = ?, extra_metadata = ? WHERE doc_name = 'text-only.pdf'",
                (DocStatus.COMPLETED.value, json.dumps({"element_count": 0})),
            )
            connection.execute(
                "UPDATE documents SET doc_status = ? WHERE doc_name = 'running.pdf'",
                (DocStatus.PROCESSING.value,),
            )
            connection.commit()
        finally:
            connection.close()

        register_existing_pdfs(str(self.db_path), str(self.pdfs_dir), {})

        connection = sqlite3.connect(str(self.db_path))
        try:
            statuses = dict(connection.execute("SELECT doc_name, doc_status FROM documents"))
        finally:
            connection.close()
        self.assertEqual(statuses["text-only.pdf"], DocStatus.COMPLETED.value)
        self.assertEqual(statuses["running.pdf"], DocStatus.PROCESSING.value)


if __name__ == "__main__":
    unittest.main()
