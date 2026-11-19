"""scripts/eval_tables.py 채점 규칙 테스트 (Qdrant 없이)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "figindex"))

from shared.schemas import ElementType, ReviewStatus  # noqa: E402
from eval_tables import (  # noqa: E402
    eval_cell_accuracy,
    eval_table_valid_rate,
    load_gt_cells,
    score_table,
)

# 11-19 v2에서 읽은 실제 요소 (한화엔진 iM증권 p.2 표1). 쉼표·%가 붙은 문자열로 저장돼 있다.
HANWHA_T01 = {
    "columns": ["구분", "2024", "2025", "2026E", "2027E", "2028E"],
    "rows": [
        {"구분": "매출", "2024": "1,202.2", "2025": "1,371.1", "2026E": "1,563.6", "2027E": "2,362.1", "2028E": "2,535.0"},
        {"구분": "영업이익", "2024": "71.5", "2025": "130.1", "2026E": "195.6", "2027E": "389.9", "2028E": "421.8"},
        {"구분": "영업이익률", "2024": "6.0%", "2025": "9.5%", "2026E": "12.5%", "2027E": "16.5%", "2028E": "16.6%"},
    ],
    "unit": "십억원, %",
    "unit_by_row": {},
    "unit_by_column": {},
    "period_labels": ["2024", "2025", "2026E", "2027E", "2028E"],
}

APPROVED = ReviewStatus.APPROVED.value
REJECTED = ReviewStatus.REJECTED.value
TABLE = ElementType.TABLE.value
CHART = ElementType.CHART.value


def gt(row_label, column, expected):
    return {"row_label": row_label, "column": column, "expected": expected}


def test_string_values_are_normalized_and_counted_as_rule_violation():
    cells = [gt("매출", "2024", 1202.2), gt("영업이익률", "2028E", 16.6)]
    scored = score_table(cells, HANWHA_T01)
    assert [s["result"] for s in scored] == ["맞음", "맞음"]
    assert all(s["rule_violation"] for s in scored)


def test_wrong_value_and_missing_cell():
    cells = [gt("매출", "2024", 1202.3), gt("순이익", "2024", 10)]
    assert [s["result"] for s in score_table(cells, HANWHA_T01)] == ["값 다름", "칸 없음"]


def test_whitespace_in_labels_is_ignored():
    table = {"columns": ["구분", "2024"], "rows": [{"구분": "EPS (원)", "2024": 8998}]}
    assert score_table([gt("EPS(원)", "2024", 8998)], table)[0]["result"] == "맞음"


def test_transposed_table():
    table = {"columns": ["연도", "매출액"], "rows": [{"연도": "2024", "매출액": 9411.9}]}
    scored = score_table([gt("매출액", "2024", 9411.9)], table)
    assert scored[0]["result"] == "행·열 바뀜 맞음"


def test_duplicate_row_labels_match_in_order():
    table = {"columns": ["구분", "2024"], "rows": [
        {"구분": "증감률", "2024": 1.0}, {"구분": "증감률", "2024": 2.0}]}
    scored = score_table([gt("증감률", "2024", 1.0), gt("증감률", "2024", 2.0)], table)
    assert [s["result"] for s in scored] == ["맞음", "맞음"]


def test_unlinked_skipped_and_wrong_link_counts_all_wrong():
    gt_cells = {"T01": [gt("매출", "2024", 1202.2)], "T02": [gt("a", "b", 1)], "T03": [gt("a", "b", 1)]}
    links = {
        "T01": {"element_id": "fig-1", "link_status": "같은 표"},
        "T02": {"element_id": "", "link_status": "요소 없음"},
    }
    payloads = {"fig-1": {"element_id": "fig-1", "review_status": APPROVED, "table_data": HANWHA_T01}}
    result = eval_cell_accuracy(gt_cells, links, payloads)
    assert result["scored_cells"] == 2 and result["correct_cells"] == 1
    assert result["linked_tables"] == 2
    assert [t["state"] for t in result["per_table"]][2] == "미연결"


def test_table_valid_rate_excludes_rejected_and_counts_empty_as_invalid():
    payloads = [
        {"element_type": TABLE, "review_status": APPROVED, "table_data": HANWHA_T01},
        {"element_type": TABLE, "review_status": APPROVED, "table_data": None},
        {"element_type": TABLE, "review_status": APPROVED, "table_data": {"columns": ["a"], "rows": []}},
        {"element_type": TABLE, "review_status": REJECTED, "table_data": None},
        {"element_type": CHART, "review_status": APPROVED, "table_data": None},
    ]
    result = eval_table_valid_rate(payloads)
    assert result["table_count"] == 3 and result["valid_count"] == 1
    assert result["rule_violation_tables"] == 1


def test_rule_violation_count_by_version():
    clean = {"columns": ["구분", "2024"], "rows": [{"구분": "매출", "2024": 1202.2}, {"구분": "비고", "2024": "n/a"}]}
    payloads = [
        {"element_type": TABLE, "review_status": APPROVED, "pipeline_version": "0.1.0", "table_data": HANWHA_T01},
        {"element_type": TABLE, "review_status": APPROVED, "pipeline_version": "0.1.1", "table_data": clean},
    ]
    by_version = eval_table_valid_rate(payloads)["rule_violation_by_version"]
    assert by_version["0.1.0"] == {"tables": 1, "violating_tables": 1, "violating_cells": 15}
    assert by_version["0.1.1"] == {"tables": 1, "violating_tables": 0, "violating_cells": 0}


def test_gt_file_loads_numeric_cells_only():
    cells = load_gt_cells(Path(__file__).resolve().parent.parent / "figindex/data/gt/table/cells.csv")
    assert len(cells) == 30
    assert len(cells["T01"]) == 15
    assert sum(len(v) for v in cells.values()) == 790
