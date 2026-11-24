"""scripts/check_table_quality.py 순수 함수 테스트 (Qdrant 없이)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_table_quality import is_numeric_cell, label_column_missing, rank_candidates  # noqa: E402

# 11-23 SK하이닉스 iM fig-6086b1030698 (행 이름 열이 빠진 표, 수정 전)
BROKEN = {"columns": ["(십억원, 천주, 원, 배)", "비고"],
          "rows": [{"(십억원, 천주, 원, 배)": v, "비고": ""} for v in ["1,002,994", "2.3", "2,339,243", "2,300,000", "1,398,000", "65%"]]}
NORMAL = {"columns": ["구분", "2025"], "rows": [{"구분": "매출액", "2025": 1}, {"구분": "영업이익", "2025": 2}]}


def test_numeric_cell():
    for v in [1, 2.3, "1,002,994", "65%", "(1.2)", "△12.5", "2.3배", "36,000원"]:
        assert is_numeric_cell(v), v
    for v in ["BPS", "목표주가", "2026E", "", None, True]:
        assert not is_numeric_cell(v), v


def test_label_column_missing():
    assert label_column_missing(BROKEN)[0] is True
    assert label_column_missing(NORMAL)[0] is False
    assert label_column_missing({"columns": ["a"], "rows": [{"a": 1}]})[0] is False  # 한 줄짜리는 판단 안 함
    assert label_column_missing(None)[0] is False


def test_rank_candidates_prefers_matching_table():
    right = {"element_id": "fig-r", "caption": "<표 3-2> 증기 메탄 개질 기술특성치",
             "table_data": {"columns": ["구분", "값"], "rows": [{"구분": "투자비", "값": 1}, {"구분": "운영비", "값": 2}]}}
    wrong = {"element_id": "fig-w", "caption": "<표 3-3> 전해 수소 비용",
             "table_data": {"columns": ["구분", "값"], "rows": [{"구분": "전력단가", "값": 1}]}}
    ranked = rank_candidates("<표 3-2> 증기 메탄 개질 및 탄소포집(블루수소) 기술특성치", ["투자비", "운영비"], [wrong, right])
    assert ranked[0][3]["element_id"] == "fig-r" and ranked[0][2] == 1.0
    assert rank_candidates("x", [], []) == []
