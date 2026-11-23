"""
FigIndex 도표 비교 지표(Metrics) 및 매칭 키워드 정의
"""
from enum import Enum
from typing import Dict, List


class MetricType(str, Enum):
    """도표 비교 대상 지표 유형."""
    TARGET_PRICE = "TARGET_PRICE"          # 목표주가 / 적정주가
    ANNUAL_ESTIMATE = "ANNUAL_ESTIMATE"    # 연간 수익 추정 / 실적 전망
    QUARTERLY_RESULT = "QUARTERLY_RESULT"  # 분기 실적 / Review


# 지표별 캡션 매칭 키워드
METRIC_KEYWORDS: Dict[MetricType, List[str]] = {
    MetricType.TARGET_PRICE: [
        "목표주가",
        "적정주가",
        "산출",
        "산정",
        "Valuation",
    ],
    MetricType.ANNUAL_ESTIMATE: [
        "추정",
        "추정치 변경",
        "수익 추정",
        "실적 전망",
        "Earnings",
        "Forecast",
    ],
    MetricType.QUARTERLY_RESULT: [
        "분기 실적",
        "3Q",
        "4Q",
        "Review",
        "잠정",
    ],
}

# 매칭에서 원천 제외할 캡션 키워드
EXCLUDE_KEYWORDS: List[str] = [
    "COMPANY DATA",
    "STOCK DATA",
    "재무상태표",
    "포괄손익계산서",
    "현금흐름표",
    "변동내역",
    "투자등급",
    "투자의견비율",
    "괴리율",
]

# 동점 시 행 라벨 겹침 판정용 핵심 재무 항목
FINANCIAL_INDICATORS: List[str] = [
    "매출액",
    "영업이익",
    "순이익",
    "당기순이익",
    "세전이익",
    "지배주주순이익",
    "EBITDA",
    "EPS",
]

# TARGET_PRICE 표 행/열 필수 라벨 (하나라도 포함되어야 유효)
TARGET_PRICE_REQUIRED_LABELS: List[str] = [
    "목표주가",
    "적정주가",
    "적정가치",
    "주당가치",       # '적정주당가치 (원)' (11-23 추가, 화면 TargetPriceView와 같은 기준)
    "적용",
    "Target",
]

# TARGET_PRICE 탈락 캡션 키워드
TARGET_PRICE_DISQUALIFY_CAPTION: List[str] = [
    "forecast",
    "earning",
]

# TARGET_PRICE 최우선(1순위) 캡션 키워드
TARGET_PRICE_PRIORITY_KEYWORDS: List[str] = [
    "산출",
    "산정",
    "적정주가",
]
