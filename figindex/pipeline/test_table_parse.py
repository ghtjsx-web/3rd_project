"""table_parse.coerce_table_data / is_empty_table_payload 테스트."""
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR))
sys.path.insert(0, str(PIPELINE_DIR.parent))

from table_parse import coerce_table_data, is_empty_table_payload  # noqa: E402
from shared.schemas import ElementType  # noqa: E402


def test_null_period_labels_no_longer_drops_table():
    # 코스맥스 유진투자증권 p.4 Valuation 표에서 실제로 받은 응답 형태 (period_labels: null)
    raw = {"columns": ["구분", "계산", "비고"],
           "rows": [{"구분": "EPS(원)", "계산": 22091, "비고": None},
                    {"구분": "Target PER(배)", "계산": 18.8, "비고": None}],
           "unit": None, "period_labels": None}
    table, note = coerce_table_data(raw)
    assert table is not None, note
    assert table.period_labels == []
    assert len(table.rows) == 2


def test_row_keys_aligned_to_columns():
    raw = {"columns": ["구분", "2026E"],
           "rows": [{"구분": "매출액"}, {"구분": "영업이익", "2026E": 3, "기타": 1}, "잘못된 행"]}
    table, note = coerce_table_data(raw)
    assert table is not None, note
    assert table.rows == [{"구분": "매출액", "2026E": None}, {"구분": "영업이익", "2026E": 3}]
    assert "행 키 맞춤 2개" in note and "버린 행 1개" in note


def test_bad_unit_by_row_is_dropped_not_whole_table():
    raw = {"columns": ["구분", "2026E"], "rows": [{"구분": "매출액", "2026E": 1}],
           "unit_by_row": {"없는행": "%"}}
    table, note = coerce_table_data(raw)
    assert table is not None and table.unit_by_row == {}
    assert "단위 지정 제외" in note


def test_empty_inputs():
    assert coerce_table_data(None)[0] is None
    assert coerce_table_data({"columns": [], "rows": []})[0] is None
    assert coerce_table_data([1, 2])[0] is None


def test_is_empty_table_payload():
    assert is_empty_table_payload({"element_type": ElementType.TABLE.value, "table_data": None})
    assert not is_empty_table_payload({"element_type": ElementType.TABLE.value,
                                       "table_data": {"columns": ["a"], "rows": [{"a": 1}]}})
    assert not is_empty_table_payload({"element_type": ElementType.CHART.value, "table_data": None})
