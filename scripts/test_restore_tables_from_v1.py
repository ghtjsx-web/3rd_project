"""scripts/restore_tables_from_v1.py 복원 payload 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from restore_tables_from_v1 import build_restored_payload  # noqa: E402
from inspect_gemini_cache import describe_table, table_validation_error  # noqa: E402
from shared.schemas import ElementType, ReviewStatus  # noqa: E402

LEGACY = {"columns": ["구분", "2026E"], "rows": [{"구분": "매출액", "2026E": 10}, {"구분": "영업이익"}]}


def _payload(note=True):
    p = {"element_id": "fig-1", "doc_id": "doc-1", "doc_name": "a.pdf", "page_number": 2,
         "bbox": [0.1, 0.2, 0.9, 0.6], "element_type": ElementType.TABLE.value,
         "image_path": "/static/crops/fig-1.png", "confidence_score": 0.7, "model_name": "m",
         "review_status": ReviewStatus.PENDING_REVIEW.value, "table_data": None,
         "extra_metadata": {"legacy": {"migration_note": "x"}} if note else {}}
    return p


def test_restore_demoted_goes_back_to_approved():
    new, note = build_restored_payload(_payload(True), LEGACY, "2026-11-18")
    assert new is not None, note
    assert new["review_status"] == ReviewStatus.APPROVED.value
    assert new["table_data"]["rows"][1] == {"구분": "영업이익", "2026E": None}
    assert "restore_note" in new["extra_metadata"]["legacy"]


def test_restore_without_note_keeps_status():
    new, _ = build_restored_payload(_payload(False), LEGACY, "2026-11-18")
    assert new["review_status"] == ReviewStatus.PENDING_REVIEW.value


def test_empty_legacy_is_skipped():
    new, note = build_restored_payload(_payload(), {"columns": [], "rows": []}, "2026-11-18")
    assert new is None and note


def test_describe_table():
    assert describe_table(None) == "null"
    assert "rows 2개" in describe_table(LEGACY)
    assert describe_table([1, 2]).startswith("list")


def test_table_validation_error_reports_key_mismatch():
    assert "검증 통과" in table_validation_error({"columns": ["a"], "rows": [{"a": 1}]})
    assert "1/2" in table_validation_error({"columns": ["a"], "rows": [{"a": 1}, {"b": 2}]})
