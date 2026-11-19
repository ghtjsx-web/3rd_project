"""shared/upload_db.py 테스트 (작업자·다시 시도 상태 흐름)."""
import sqlite3
import tempfile
from contextlib import closing
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from shared.schemas import Batch, DocStatus, Document
from shared import upload_db
from app.upload_store import _insert_batch, _insert_document


class UploadDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "metadata.sqlite3")
        connection = upload_db.connect(self.db)
        self.batch = Batch(batch_id="b1", doc_count=3)
        _insert_batch(connection, self.batch)
        base = datetime(2026, 11, 19, 12, 0, 0)
        for i, (name, h, status) in enumerate([("a.pdf", "h1", DocStatus.UPLOADED), ("b.pdf", "h2", DocStatus.UPLOADED),
                                               ("c.pdf", "h3", DocStatus.FAILED)]):
            _insert_document(connection, Document(doc_id=f"d{i + 1}", batch_id="b1", doc_hash=h, doc_name=name,
                                                  doc_status=status, created_at=base + timedelta(minutes=i)))
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def sql(self, query: str, params=()):
        """sqlite3의 with는 연결을 닫지 않아 Windows에서 임시 폴더를 못 지우므로 closing으로 닫는다."""
        with closing(sqlite3.connect(self.db)) as c:
            rows = c.execute(query, params).fetchall()
            c.commit()
            return rows

    def status(self, doc_id: str) -> str:
        return self.sql("SELECT doc_status FROM documents WHERE doc_id = ?", (doc_id,))[0][0]

    def test_claim_takes_oldest_uploaded_once(self) -> None:
        first = upload_db.claim_next_document(self.db)
        second = upload_db.claim_next_document(self.db)
        self.assertEqual((first.doc_id, first.doc_status), ("d1", DocStatus.PROCESSING))
        self.assertEqual(second.doc_id, "d2")
        self.assertIsNone(upload_db.claim_next_document(self.db))

    def test_completed_saves_metadata_only_when_processing(self) -> None:
        doc = upload_db.claim_next_document(self.db)
        done = doc.model_copy(update={"doc_title": "제목", "page_count": 12,
                                      "extra_metadata": {"element_count": 0}})
        self.assertTrue(upload_db.mark_document_completed(self.db, done))
        self.assertEqual(self.status("d1"), DocStatus.COMPLETED.value)
        row = self.sql("SELECT doc_title, page_count, extra_metadata FROM documents WHERE doc_id='d1'")[0]
        self.assertEqual(row, ("제목", 12, '{"element_count": 0}'))
        self.assertFalse(upload_db.mark_document_completed(self.db, done))   # 이미 COMPLETED

    def test_failed_and_reset(self) -> None:
        upload_db.claim_next_document(self.db)
        upload_db.claim_next_document(self.db)
        self.assertTrue(upload_db.mark_document_failed(self.db, "d1", "RuntimeError: 503"))
        self.assertFalse(upload_db.mark_document_failed(self.db, "d3", "x"))   # PROCESSING이 아님
        self.assertEqual(upload_db.reset_processing_documents(self.db), 1)     # d2만
        self.assertEqual(self.status("d2"), DocStatus.UPLOADED.value)
        self.assertEqual(self.status("d1"), DocStatus.FAILED.value)

    def test_retry_rules(self) -> None:
        retried = upload_db.retry_document(self.db, "d3")
        self.assertEqual((retried.doc_status, retried.doc_error), (DocStatus.UPLOADED, None))
        self.assertIsNone(upload_db.retry_document(self.db, "없음"))
        with self.assertRaises(upload_db.RetryNotAllowed):
            upload_db.retry_document(self.db, "d1")   # UPLOADED는 다시 시도 대상 아님

    def test_retry_refused_when_same_content_is_active(self) -> None:
        self.sql("UPDATE documents SET doc_hash = 'h1' WHERE doc_id = 'd3'")
        with self.assertRaises(upload_db.RetryNotAllowed):
            upload_db.retry_document(self.db, "d3")


if __name__ == "__main__":
    unittest.main()
