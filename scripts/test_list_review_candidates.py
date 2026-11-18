"""scripts/list_review_candidates.py 의심 사유 판정 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from list_review_candidates import build_rows, suspicion_reasons  # noqa: E402
from shared.schemas import ElementType, ReviewStatus  # noqa: E402

TABLE_DATA = {"columns": ["구분", "2026E"], "rows": [{"구분": "매출액", "2026E": 1}]}


def _payload(**kw):
    base = {"element_id": "e1", "doc_name": "a.pdf", "page_number": 3,
            "bbox": [0.1, 0.3, 0.9, 0.7], "element_type": ElementType.TABLE.value,
            "table_data": TABLE_DATA, "review_status": ReviewStatus.APPROVED.value,
            "confidence_score": 0.9}
    base.update(kw)
    return base


def test_clean_element_has_no_reason():
    assert suspicion_reasons(_payload()) == []


def test_each_rule():
    assert "검수대기" in suspicion_reasons(_payload(review_status=ReviewStatus.PENDING_REVIEW.value))
    assert "아주작음" in suspicion_reasons(_payload(bbox=[0.1, 0.4, 0.15, 0.45]))
    assert "머리말꼬리말" in suspicion_reasons(_payload(bbox=[0.1, 0.92, 0.9, 0.98]))
    assert "표데이터없음" in suspicion_reasons(_payload(table_data=None))
    assert "유형불일치" in suspicion_reasons(_payload(element_type=ElementType.CHART.value))
    assert "첫페이지그림" in suspicion_reasons(
        _payload(page_number=1, element_type=ElementType.DIAGRAM.value, table_data=None))


def test_sort_more_reasons_first():
    a = _payload(element_id="a", review_status=ReviewStatus.PENDING_REVIEW.value, confidence_score=0.5)
    b = _payload(element_id="b", review_status=ReviewStatus.PENDING_REVIEW.value,
                 confidence_score=0.7, table_data=None)
    rows = build_rows([a, b, _payload(element_id="c")], "http://x", 10)
    assert [r["요소 ID"] for r in rows] == ["b", "a"]
