"""Isolated tests for upload metadata persistence and existing PDF registration."""

import hashlib
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from shared.schemas import Batch, DocStatus, Document
from app.upload_store import persist_batch, register_existing_pdfs


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

    def test_existing_pdf_registration_is_completed_and_idempotent(self) -> None:
        self.pdfs_dir.mkdir()
        (self.pdfs_dir / "old-a.pdf").write_bytes(b"indexed content a")
        (self.pdfs_dir / "old-a-copy.pdf").write_bytes(b"indexed content a")
        (self.pdfs_dir / "old-b.pdf").write_bytes(b"indexed content b")

        first_run = register_existing_pdfs(str(self.db_path), str(self.pdfs_dir))
        second_run = register_existing_pdfs(str(self.db_path), str(self.pdfs_dir))

        self.assertEqual(first_run, (3, 2, 1))
        self.assertEqual(second_run, (3, 0, 3))
        with sqlite3.connect(str(self.db_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                2,
            )
            statuses = {
                row[0]
                for row in connection.execute("SELECT doc_status FROM documents")
            }
        self.assertEqual(statuses, {DocStatus.COMPLETED.value})


if __name__ == "__main__":
    unittest.main()
