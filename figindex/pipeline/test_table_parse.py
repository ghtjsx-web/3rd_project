"""table_parse.coerce_table_data / is_empty_table_payload 테스트."""
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR))
sys.path.insert(0, str(PIPELINE_DIR.parent))

from table_parse import align_row_keys, coerce_table_data, is_empty_table_payload, parse_cell_value  # noqa: E402
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


def test_parse_cell_value_glossary_rules():
    assert parse_cell_value("1,234") == (1234, False)
    assert parse_cell_value("1,202.2") == (1202.2, False)
    assert parse_cell_value("△1.2") == (-1.2, False)
    assert parse_cell_value("(1.2)") == (-1.2, False)
    assert parse_cell_value("-12.5") == (-12.5, False)
    assert parse_cell_value("59.7%") == (59.7, True)
    assert parse_cell_value("-") == ("-", False)
    assert parse_cell_value("n/a") == ("n/a", False)
    assert parse_cell_value(None) == (None, False)
    assert parse_cell_value(18.8) == (18.8, False)


def test_reextracted_cosmax_strings_become_numbers():
    # 시험 컬렉션 재추출 결과에서 실제로 받은 형태 (숫자가 문자열, 쉼표·% 포함)
    label = "(십억원, 천주, 원, %)"
    raw = {"columns": [label, "계산", "비고"],
           "rows": [{label: "EPS(원)", "계산": "22,091", "비고": ""},
                    {label: "상승여력 (%)", "계산": "59.7%", "비고": ""},
                    {label: "Target PER(배)", "계산": "18.8", "비고": ""}],
           "unit": "십억원, 천주, 원, %", "period_labels": []}
    table, note = coerce_table_data(raw)
    assert table is not None, note
    assert [r["계산"] for r in table.rows] == [22091, 59.7, 18.8]
    assert table.rows[0][label] == "EPS(원)" and table.rows[0]["비고"] == ""
    assert table.unit_for("상승여력 (%)", "계산") == "%"
    assert "숫자로 바꾼 칸 3개" in note


def test_leading_dot_decimal_is_number():
    # 0.1.2: 논문 표의 Fleiss' κ ".802" 같은 표기
    assert parse_cell_value(".802") == (0.802, False)
    assert parse_cell_value("-.5") == (-0.5, False)
    assert parse_cell_value("△.5") == (-0.5, False)
    assert parse_cell_value(".") == (".", False)
    assert parse_cell_value("1.") == ("1.", False)


def test_space_only_key_difference_is_kept():
    # 0.1.2: 코스맥스 메리츠 p.2처럼 행 키 끝에 공백이 붙은 경우
    raw = {"columns": ["구분", "(% diff)"],
           "rows": [{"구분": "매출액", "(% diff) ": "3.2"}, {"구분": "영업이익", "(% diff)": "1.0", "(% diff) ": "9.9"}]}
    table, note = coerce_table_data(raw)
    assert table is not None, note
    assert [r["(% diff)"] for r in table.rows] == [3.2, 1.0]   # 열에 값이 있으면 열 값을 둔다
    assert "공백 차이로 옮긴 값 1개" in note


def test_suffix_key_is_still_dropped():
    raw = {"columns": ["구분", "컨센서스"], "rows": [{"구분": "매출액", "컨센서스": "1", "컨센서스_1": "2"}]}
    table, _ = coerce_table_data(raw)
    assert table.rows == [{"구분": "매출액", "컨센서스": 1}]


def test_ambiguous_space_key_is_not_moved():
    raw = {"columns": ["구분", "A B", "AB"], "rows": [{"구분": "x", "A  B": "1"}]}
    aligned, moved = align_row_keys(raw["rows"][0], raw["columns"])
    assert moved == 0 and aligned == {"구분": "x", "A B": None, "AB": None}
