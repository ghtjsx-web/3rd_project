"""검색 재정렬(search_rerank) 테스트."""

import unittest
from types import SimpleNamespace

from app.search_rerank import query_metrics, rerank_bonus, rerank_points

ANNUAL = {"columns": ["구분", "2025", "2026E"], "rows": [{"구분": "매출액(십억원)"}, {"구분": "영업이익(십억원)"}]}
QUARTER = {"columns": ["구분", "1Q25", "2Q25"], "rows": [{"구분": "매출액"}, {"구분": "영업이익"}]}
NO_METRIC = {"columns": ["구분", "2025", "2026E"], "rows": [{"구분": "자산총계"}, {"구분": "부채총계"}]}
TRANSPOSED = {"columns": ["구분", "매출액 (십억원)", "영업이익 (십억원)"], "rows": [{"구분": "2025"}, {"구분": "2026E"}]}
CHANGE = {"columns": ["구분", "2026E_변경전", "2026E_변경후"], "rows": [{"구분": "영업이익"}]}


def point(element_id, table_data=None):
    return SimpleNamespace(payload={"element_id": element_id, "table_data": table_data})


class QueryMetricsTests(unittest.TestCase):
    def test_finds_korean_and_ascii_aliases(self) -> None:
        self.assertEqual(query_metrics("삼성전자 2025년 매출액 영업이익"), ["매출액", "영업이익"])
        self.assertEqual(query_metrics("PER 밸류에이션"), ["PER"])

    def test_ascii_alias_needs_word_boundary(self) -> None:
        # "operation"의 op, "super"의 per는 지표가 아니다
        self.assertEqual(query_metrics("operation super"), [])


class RerankBonusTests(unittest.TestCase):
    q = "삼성전자 2025년 매출액 영업이익"

    def test_annual_table_with_metric_gets_both(self) -> None:
        self.assertEqual(rerank_bonus(self.q, ANNUAL), 2)
        self.assertEqual(rerank_bonus(self.q, TRANSPOSED), 2)

    def test_quarter_table_gets_no_year_bonus(self) -> None:
        # 연간과 분기는 다른 지표 → 연도를 물으면 분기 열은 기간 조건을 못 채운다
        self.assertEqual(rerank_bonus(self.q, QUARTER), 1)
        self.assertEqual(rerank_bonus("삼성전자 분기별 영업이익", QUARTER), 2)
        self.assertEqual(rerank_bonus("삼성전자 분기별 영업이익", ANNUAL), 1)

    def test_change_columns_are_not_periods(self) -> None:
        # 변경 전후 열은 "그 기간의 값"이 아니다 (normalize_period가 거름)
        self.assertEqual(rerank_bonus(self.q, CHANGE), 1)

    def test_no_metric_and_no_table(self) -> None:
        self.assertEqual(rerank_bonus(self.q, NO_METRIC), 1)
        self.assertEqual(rerank_bonus(self.q, None), 0)
        self.assertEqual(rerank_bonus("삼성전자 주가", ANNUAL), 0)


class RerankPointsTests(unittest.TestCase):
    def test_moves_matching_table_forward_and_keeps_order_otherwise(self) -> None:
        points = [point("chart"), point("quarter", QUARTER)] + [point(f"x{i}") for i in range(8)] + [point("annual", ANNUAL)]
        ids = [p.payload["element_id"] for p in rerank_points("삼성전자 2025년 매출액 영업이익", points)]
        # quarter: 1 - 5*1 = -4, chart: 0, annual: 10 - 5*2 = 0 (chart와 같으면 원래 순서대로 chart 먼저)
        self.assertEqual(ids[:3], ["quarter", "chart", "annual"])
        self.assertEqual(ids[3:], [f"x{i}" for i in range(8)])


if __name__ == "__main__":
    unittest.main()
