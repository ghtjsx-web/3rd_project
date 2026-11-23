"""TARGET_PRICE 근거 표 고르기 테스트 (11-23: 행·열 이름 검사 연결).

실행 (저장소 루트): python -m pytest figindex/compare/test_matcher_target_price.py -q
"""
import sys
from pathlib import Path

FIGINDEX_DIR = Path(__file__).resolve().parent.parent
if str(FIGINDEX_DIR) not in sys.path:
    sys.path.insert(0, str(FIGINDEX_DIR))

from compare.matcher import find_best_table_for_doc, has_target_price_required_labels, score_element_for_metric  # noqa: E402
from compare.metrics import MetricType  # noqa: E402

# 팀장 PC /api/compare/company?company=코스맥스&metric=TARGET_PRICE 응답에서 가져온 표 (11-23)
MERITZ = {
    "columns": ["구분", "2024", "2025", "2026E", "2027E", "2028E"],
    "rows": [
        {"구분": "연결 EPS (원)", "2024": 7560, "2025": 10843, "2026E": 15811, "2027E": 20171, "2028E": 22976},
        {"구분": "적정주당가치 (원)", "2024": "", "2025": "", "2026E": 316000, "2027E": 403000, "2028E": 460000},
        {"구분": "상승여력 (%)", "2024": "", "2025": "", "2026E": 20.2, "2027E": 53.2, "2028E": 74.9},
    ],
}
EUGENE = {
    "columns": ["(십억원, 천주, 원, %)", "계산", "비고"],
    "rows": [
        {"(십억원, 천주, 원, %)": "Target PER(배)", "계산": 18.8, "비고": None},
        {"(십억원, 천주, 원, %)": "적정주가(원)", "계산": 420000, "비고": None},
    ],
}
HANWHA_FINANCIALS = {
    "columns": ["재무정보", "2025", "2026E"],
    "rows": [
        {"재무정보": "매출액", "2025": 2399, "2026E": 3231},
        {"재무정보": "EPS", "2025": 10847, "2026E": 16239},
        {"재무정보": "PER", "2025": 24.2, "2026E": 16.2},
    ],
}


def _el(element_id, caption, table, page_number=1):
    return {"element_id": element_id, "element_type": "TABLE", "caption": caption,
            "table_data": table, "page_number": page_number}


def test_required_labels():
    assert has_target_price_required_labels(MERITZ)        # 적정주당가치 (적용 P/E 줄이 없어도)
    assert has_target_price_required_labels(EUGENE)        # 적정주가 / Target
    assert not has_target_price_required_labels(HANWHA_FINANCIALS)


def test_caption_only_table_without_target_price_row_is_rejected():
    el = _el("fig-hanwha", "코스맥스 목표주가 및 주요 재무정보 전망", HANWHA_FINANCIALS)
    assert score_element_for_metric(el, MetricType.TARGET_PRICE)[0] == 0.0
    result = find_best_table_for_doc([el], MetricType.TARGET_PRICE)
    assert result["matched"] is False


def test_real_valuation_table_still_matched_and_preferred():
    wrong = _el("fig-wrong", "코스맥스 목표주가 및 주요 재무정보 전망", HANWHA_FINANCIALS, 1)
    right = _el("fig-right", "목표주가 산정", EUGENE, 4)
    result = find_best_table_for_doc([wrong, right], MetricType.TARGET_PRICE)
    assert result["matched"] is True and result["element_id"] == "fig-right"
    assert find_best_table_for_doc([_el("fig-m", "코스맥스: P/E Valuation", MERITZ)], MetricType.TARGET_PRICE)["matched"]


def test_other_metrics_unaffected():
    el = _el("fig-q", "분기 실적 Review", HANWHA_FINANCIALS)
    assert score_element_for_metric(el, MetricType.QUARTERLY_RESULT)[0] > 0
