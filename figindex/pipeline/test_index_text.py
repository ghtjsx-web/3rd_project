"""
figindex/pipeline/test_index_text.py

shared.index_text.build_index_text 함수의 동작을 검증하는 단위 테스트.

검증 항목:
1. table_data 없음: 기존 색인 식(caption, summary, hashtags, doc_title, source_org, entities)과 100% 동일
2. table_data 있음: 열 이름(columns) 및 행 이름(rows[col0])이 순서대로 뒤에 추가됨
3. 숫자만 있는 행 이름('1', '12.5') 및 빈 값은 제외, 열 이름의 연도('2025', '2026E')는 보존
4. 중복 이름은 최초 1회만 반영 (순서 유지)
5. 추출된 이름이 40개를 초과하면 정확히 40개에서 자름 (MAX_TABLE_NAMES = 40)
"""

import os
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIGINDEX_DIR = REPO_ROOT / "figindex"
if str(FIGINDEX_DIR) not in sys.path:
    sys.path.insert(0, str(FIGINDEX_DIR))

from shared.index_text import MAX_TABLE_NAMES, build_index_text


def _legacy_formula(caption: str, summary: str, hashtags: list, doc_title: str, source_org: str, entities: list) -> str:
    """기존 orchestrator.py:724의 텍스트 생성 식"""
    return f"{caption} {summary} {' '.join(hashtags)} {doc_title or ''} {source_org or ''} {' '.join(entities)}"


def test_no_table_data_matches_legacy():
    """1. table_data 없음: 기존 식과 문자열이 글자 하나까지 완전히 일치해야 함"""
    payloads = [
        {
            "caption": "그림 1. 연도별 매출 추이",
            "summary": "2024년부터 2026년까지의 매출 성장 추이",
            "hashtags": ["매출", "성장률"],
            "doc_title": "삼성전자 3Q26 실적 보고서",
            "source_org": "iM증권",
            "entities": ["삼성전자"],
            "table_data": None,
        },
        {
            "caption": "",
            "summary": "다이어그램 요약",
            "hashtags": [],
            "doc_title": None,
            "source_org": "",
            "entities": [],
            "table_data": {},
        },
        {
            "caption": "차트 B",
            "summary": "요약",
            "hashtags": ["차트"],
            "doc_title": None,
            "source_org": "신한투자증권",
            "entities": ["카카오"],
            # table_data 키 자체가 누락된 경우
        },
    ]

    for p in payloads:
        expected = _legacy_formula(
            p.get("caption", ""),
            p.get("summary", ""),
            p.get("hashtags", []),
            p.get("doc_title") or "",
            p.get("source_org") or "",
            p.get("entities", []),
        )
        actual = build_index_text(p)
        assert actual == expected, f"table_data가 없을 때 기존 식과 불일치:\n기대: {expected!r}\n실제: {actual!r}"


def test_table_data_appends_column_and_row_names():
    """2. table_data 있음: 열 이름과 행 이름이 뒤에 붙음 (예: '2025', '2026E', '매출액', '영업이익')"""
    payload = {
        "caption": "표 1. 주요 재무지표",
        "summary": "연간 실적 전망 요약",
        "hashtags": ["실적", "재무"],
        "doc_title": "삼성전자 기업분석",
        "source_org": "iM증권",
        "entities": ["삼성전자"],
        "table_data": {
            "columns": ["구분", "2024", "2025", "2026E"],
            "rows": [
                {"구분": "매출액", "2024": 300000, "2025": 320000, "2026E": 350000},
                {"구분": "영업이익", "2024": 35000, "2025": 40000, "2026E": 50000},
                {"구분": "순이익", "2024": 25000, "2025": 30000, "2026E": 40000},
            ],
        },
    }

    base = _legacy_formula(
        payload["caption"],
        payload["summary"],
        payload["hashtags"],
        payload["doc_title"],
        payload["source_org"],
        payload["entities"],
    )

    actual = build_index_text(payload)
    expected = f"{base} 구분 2024 2025 2026E 매출액 영업이익 순이익"
    assert actual == expected


def test_numeric_row_names_and_empty_values_filtered():
    """3. 숫자만 있는 행 이름, 빈 값은 빠지고 열 이름의 연도('2025', '2026E')는 보존됨"""
    payload = {
        "caption": "재무 요약",
        "summary": "요약 설명",
        "hashtags": [],
        "doc_title": "",
        "source_org": "",
        "entities": [],
        "table_data": {
            "columns": ["구분", "2025", "2026E", "", None, "  "],
            "rows": [
                {"구분": "매출액"},
                {"구분": "1"},          # 순수 정수 행 이름 -> 제외
                {"구분": "12.5"},       # 순수 실수 행 이름 -> 제외
                {"구분": "-3.0"},       # 순수 음수 행 이름 -> 제외
                {"구분": "1,000"},      # 쉼표 포함 순수 숫자 -> 제외
                {"구분": ""},           # 빈 값 -> 제외
                {"구분": "   "},        # 공백 -> 제외
                {"구분": None},         # None -> 제외
                {"구분": "12M Fwd EPS"}, # 영문/숫자 혼합 계정명 -> 유지
                {"구분": "영업이익"},
            ],
        },
    }

    base = _legacy_formula(
        payload["caption"],
        payload["summary"],
        payload["hashtags"],
        payload["doc_title"],
        payload["source_org"],
        payload["entities"],
    )

    actual = build_index_text(payload)
    # 열 이름에서 '2025', '2026E'는 보존되고 빈 값은 빠짐
    # 행 이름에서 '1', '12.5', '-3.0', '1,000', 빈 값은 빠지고 '매출액', '12M Fwd EPS', '영업이익' 유지
    expected = f"{base} 구분 2025 2026E 매출액 12M Fwd EPS 영업이익"
    assert actual == expected


def test_duplicate_names_deduplicated_preserving_order():
    """4. 중복 이름은 최초 1회만, 원래 순서를 유지해야 함"""
    payload = {
        "caption": "중복 테스트",
        "summary": "설명",
        "hashtags": [],
        "doc_title": "",
        "source_org": "",
        "entities": [],
        "table_data": {
            "columns": ["구분", "2025", "2025", "구분", "2026E"],
            "rows": [
                {"구분": "매출액"},
                {"구분": "영업이익"},
                {"구분": "매출액"},  # 중복 행 이름
                {"구분": "2025"},    # 열 이름과 중복되는 경우 -> 이미 봤으므로 제외
                {"구분": "당기순이익"},
            ],
        },
    }

    base = _legacy_formula(
        payload["caption"],
        payload["summary"],
        payload["hashtags"],
        payload["doc_title"],
        payload["source_org"],
        payload["entities"],
    )

    actual = build_index_text(payload)
    expected = f"{base} 구분 2025 2026E 매출액 영업이익 당기순이익"
    assert actual == expected


def test_max_names_truncated_at_40():
    """5. 이름이 40개를 넘으면 40개에서 자름"""
    columns = ["구분", "2025", "2026E"]  # 3개
    # 50개의 고유한 행 라벨 생성
    rows = [{"구분": f"계정과목_{i:02d}"} for i in range(1, 51)]

    payload = {
        "caption": "긴 재무제표",
        "summary": "50개 행이 있는 긴 표",
        "hashtags": [],
        "doc_title": "",
        "source_org": "",
        "entities": [],
        "table_data": {
            "columns": columns,
            "rows": rows,
        },
    }

    base = _legacy_formula(
        payload["caption"],
        payload["summary"],
        payload["hashtags"],
        payload["doc_title"],
        payload["source_org"],
        payload["entities"],
    )

    actual = build_index_text(payload)
    # 총 고유 이름 53개 중 상위 40개만 반영되어야 함
    expected_names = columns + [f"계정과목_{i:02d}" for i in range(1, 38)]  # 3 + 37 = 40개
    assert len(expected_names) == MAX_TABLE_NAMES == 40
    expected = f"{base} {' '.join(expected_names)}"
    assert actual == expected

    # 41번째 이름은 텍스트에 포함되지 않아야 함
    assert "계정과목_38" not in actual
