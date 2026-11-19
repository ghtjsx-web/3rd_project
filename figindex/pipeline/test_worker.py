"""worker.run_once 테스트 (DB·Qdrant·Gemini 없이 가짜 함수로)."""
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR))
sys.path.insert(0, str(PIPELINE_DIR.parent))

from shared.schemas import DocStatus, Document  # noqa: E402
import hashlib  # noqa: E402

from worker import run_once  # noqa: E402

PDF = b"%PDF-1.4 test"
PDF_HASH = hashlib.sha256(PDF).hexdigest()


def make_doc(doc_name="a.pdf"):
    return Document(doc_id="11111111-2222-3333-4444-555555555555", batch_id="b1", doc_hash=PDF_HASH,
                    doc_name=doc_name, doc_status=DocStatus.PROCESSING, extra_metadata={"from_upload": 1})


def recorder():
    log = {"completed": [], "failed": []}
    return log, (lambda d: log["completed"].append(d)), (lambda i, r: log["failed"].append((i, r)))


def test_nothing_to_do(tmp_path):
    log, complete, fail = recorder()
    assert run_once(lambda: None, None, complete, fail, tmp_path) is None
    assert log == {"completed": [], "failed": []}


def test_completed_keeps_doc_id_and_merges_metadata(tmp_path):
    (tmp_path / "a.pdf").write_bytes(PDF)
    doc = make_doc()

    def index(path, doc_id):
        assert path == tmp_path / "a.pdf" and doc_id == doc.doc_id
        return doc.model_copy(update={"doc_title": "제목", "page_count": 12, "doc_status": DocStatus.COMPLETED,
                                      "extra_metadata": {"element_count": 0, "pipeline_version": "0.1.3"}})

    log, complete, fail = recorder()
    assert run_once(lambda: doc, index, complete, fail, tmp_path) == DocStatus.COMPLETED.value
    done = log["completed"][0]
    assert done.doc_id == doc.doc_id and done.batch_id == "b1" and done.doc_title == "제목"
    assert done.extra_metadata == {"from_upload": 1, "element_count": 0, "pipeline_version": "0.1.3"}   # 도표 0개도 완료
    assert log["failed"] == []


def test_missing_file_fails_without_calling_pipeline(tmp_path):
    called = []
    log, complete, fail = recorder()
    assert run_once(lambda: make_doc("없는.pdf"), lambda p, i: called.append(1), complete, fail, tmp_path) == DocStatus.FAILED.value
    assert called == [] and "PDF 파일 없음" in log["failed"][0][1]


def test_pipeline_error_is_recorded_and_shortened(tmp_path):
    (tmp_path / "a.pdf").write_bytes(PDF)

    def index(path, doc_id):
        raise RuntimeError("503 " + "x" * 1000)

    log, complete, fail = recorder()
    assert run_once(lambda: make_doc(), index, complete, fail, tmp_path) == DocStatus.FAILED.value
    doc_id, reason = log["failed"][0]
    assert reason.startswith("RuntimeError: 503") and len(reason) <= 300 and log["completed"] == []


def test_changed_doc_id_is_a_failure(tmp_path):
    (tmp_path / "a.pdf").write_bytes(PDF)
    doc = make_doc()
    log, complete, fail = recorder()
    out = run_once(lambda: doc, lambda p, i: doc.model_copy(update={"doc_id": "other"}), complete, fail, tmp_path)
    assert out == DocStatus.FAILED.value and "doc_id가 바뀜" in log["failed"][0][1]


def test_different_file_content_fails(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 another report")
    called = []
    log, complete, fail = recorder()
    out = run_once(lambda: make_doc(), lambda p, i: called.append(1), complete, fail, tmp_path)
    assert out == DocStatus.FAILED.value and called == [] and "doc_hash 불일치" in log["failed"][0][1]
