"""scripts/promote_test_to_service.py 반영 계획 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from promote_test_to_service import plan_new_elements, plan_promotion  # noqa: E402
from shared.schemas import ElementType, ReviewStatus  # noqa: E402

TABLE = {"columns": ["구분", "2026E"], "rows": [{"구분": "매출액", "2026E": 1}]}


def _point(pid, eid, etype=ElementType.TABLE.value, table=None):
    return {"id": pid, "payload": {
        "element_id": eid, "doc_id": "d1", "doc_name": "a.pdf", "page_number": 2,
        "bbox": [0.1, 0.2, 0.9, 0.6], "element_type": etype, "image_path": f"/static/crops/{eid}.png",
        "confidence_score": 0.7, "model_name": "m", "review_status": ReviewStatus.APPROVED.value,
        "table_data": table}}


def test_only_filled_same_type_tables_are_promoted():
    service = [_point("s1", "a"), _point("s2", "b"), _point("s3", "c"), _point("s4", "d")]
    test = [_point("t1", "a", table=TABLE),
            _point("t2", "b"),                                   # 여전히 빈 표
            _point("t3", "c", etype=ElementType.DIAGRAM.value),  # 유형 바뀜
            _point("t5", "x", table=TABLE)]                      # 서비스에 없음
    plans, skipped = plan_promotion(test, service, include_unfilled=False)
    assert [(t["id"], s["id"]) for t, s in plans] == [("t1", "s1")]
    reasons = {t["payload"]["element_id"]: r for t, r in skipped}
    assert "비어" in reasons["b"] and "유형" in reasons["c"] and "없음" in reasons["x"]


def test_include_unfilled():
    service = [_point("s2", "b")]
    plans, _ = plan_promotion([_point("t2", "b")], service, include_unfilled=True)
    assert len(plans) == 1


def test_new_only_adds_elements_missing_from_service():
    service = [_point("s1", "a")]
    test = [_point("t1", "a", table=TABLE),                  # 기존 요소 (element_id 같음)
            _point("s1", "y", table=TABLE),                  # 같은 위치 포인트 ID가 이미 있음
            _point("t3", "z", etype=ElementType.CHART.value),  # 새 차트 (표 없어도 추가)
            _point("t4", "w", table=TABLE)]                  # 새 표
    adds, skipped = plan_new_elements(test, service)
    assert [t["id"] for t in adds] == ["t3", "t4"]
    reasons = {t["payload"]["element_id"]: r for t, r in skipped}
    assert "기존" in reasons["a"] and "위치" in reasons["y"]


def test_new_only_skips_invalid_payload():
    broken = _point("t9", "v")
    del broken["payload"]["doc_name"]
    adds, skipped = plan_new_elements([broken], [])
    assert adds == [] and "검증" in skipped[0][1]
