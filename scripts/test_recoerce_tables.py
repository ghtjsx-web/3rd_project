"""scripts/recoerce_tables.py 계획 단계 테스트 (Qdrant 없이)."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "figindex"))

from shared.schemas import ElementType, ReviewStatus  # noqa: E402
from recoerce_tables import plan  # noqa: E402
from test_eval_tables import HANWHA_T01  # noqa: E402

TABLE = ElementType.TABLE.value
APPROVED = ReviewStatus.APPROVED.value
REJECTED = ReviewStatus.REJECTED.value


def point(table_data, review_status=APPROVED, element_type=TABLE, version="0.1.0"):
    return {"id": "p1", "vector": {"dense": [0.1]},
            "payload": {"element_id": "fig-1", "element_type": element_type, "review_status": review_status,
                        "pipeline_version": version, "table_data": copy.deepcopy(table_data)}}


def test_hanwha_table_is_normalized_and_vector_kept():
    to_write, skipped, cells = plan([point(HANWHA_T01)])
    assert not skipped and len(to_write) == 1
    written = to_write[0]
    assert written["vector"] == {"dense": [0.1]}
    rows = written["payload"]["table_data"]["rows"]
    assert rows[0]["2024"] == 1202.2 and rows[2]["2028E"] == 16.6
    assert written["payload"]["table_data"]["unit_by_row"] == {"영업이익률": "%"}
    assert written["payload"]["pipeline_version"] == "0.1.0"
    assert cells == {"0.1.0": 15}


def test_clean_rejected_and_non_table_are_ignored():
    clean = {"columns": ["구분", "2024"], "rows": [{"구분": "매출", "2024": 1.0}]}
    points = [point(clean), point(HANWHA_T01, review_status=REJECTED),
              point(HANWHA_T01, element_type=ElementType.CHART.value)]
    to_write, skipped, _ = plan(points)
    assert to_write == [] and skipped == []


def test_extra_key_with_value_is_skipped():
    table = {"columns": ["구분", "2024"], "rows": [{"구분": "매출", "2024": "1,000", "2025": "2,000"}]}
    to_write, skipped, _ = plan([point(table)])
    assert to_write == [] and "columns에 없는 키" in skipped[0][1]


def test_lost_unit_by_row_is_skipped():
    # unit_by_row 키가 행 라벨에 없으면 coerce가 단위 지정을 빼고 검증한다 → 정보 손실이라 건너뜀
    table = {"columns": ["구분", "2024"], "rows": [{"구분": "매출", "2024": "1,000"}],
             "unit_by_row": {"매출액": "억원"}}
    to_write, skipped, _ = plan([point(table)])
    assert to_write == [] and "unit_by_row" in skipped[0][1]


def test_space_only_key_is_recovered_and_leading_dot_counted():
    # 코스맥스 메리츠 p.2처럼 행 키 끝에 공백, 논문 표처럼 '.802'
    table = {"columns": ["구분", "(% diff)", "κ"],
             "rows": [{"구분": "매출액", "(% diff) ": "3.2", "κ": ".802"}]}
    to_write, skipped, cells = plan([point(table)])
    assert not skipped and len(to_write) == 1
    assert to_write[0]["payload"]["table_data"]["rows"][0] == {"구분": "매출액", "(% diff)": 3.2, "κ": 0.802}
