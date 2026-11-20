"""
scripts/test_reembed_table_vectors.py

reembed_table_vectors.py의 대상 선별 함수 is_reembed_target에 대한 단위 테스트.
Qdrant 및 OpenAI 네트워크 호출 없이 순수하게 로컬 단위 테스트로 검증합니다.
"""

import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
FIGINDEX_DIR = REPO_ROOT / "figindex"
if str(FIGINDEX_DIR) not in sys.path:
    sys.path.insert(0, str(FIGINDEX_DIR))
if Path("/app").exists() and "/app" not in sys.path:
    sys.path.insert(0, "/app")
if Path("/scripts").exists() and "/scripts" not in sys.path:
    sys.path.insert(0, "/scripts")

from shared.schemas import ElementType
from scripts.reembed_table_vectors import is_reembed_target


def test_no_table_data_excluded():
    """1. table_data가 없는 요소(차트, 다이어그램, 사진 등)는 재임베딩 대상에서 제외되어야 함"""
    payloads = [
        {
            "element_id": "fig-chart-1",
            "element_type": ElementType.CHART.value,
            "caption": "차트 1. 영업이익 추이",
            "summary": "연도별 영업이익 상승세 요약",
            "hashtags": ["차트", "실적"],
            "doc_title": "보고서 A",
            "source_org": "미래에셋증권",
            "entities": ["삼성전자"],
            "table_data": None,
        },
        {
            "element_id": "fig-diag-1",
            "element_type": ElementType.DIAGRAM.value,
            "caption": "그림 2. 공정 구조도",
            "summary": "HBM 제조 공정 다이어그램",
            "hashtags": ["공정"],
            "doc_title": "보고서 B",
            "source_org": "SK증권",
            "entities": ["SK하이닉스"],
            # table_data 필드 누락
        },
    ]

    for p in payloads:
        is_target, legacy_txt, new_txt = is_reembed_target(p)
        assert is_target is False, f"차트/다이어그램은 대상이 아니어야 함: {p['element_id']}"
        assert legacy_txt == new_txt


def test_empty_table_data_excluded():
    """2. table_data가 빈 딕셔너리이거나 columns가 비어있는 경우 제외되어야 함"""
    payloads = [
        {
            "element_id": "fig-empty-1",
            "element_type": ElementType.TABLE.value,
            "caption": "빈 표",
            "summary": "내용 없음",
            "hashtags": [],
            "doc_title": "",
            "source_org": "",
            "entities": [],
            "table_data": {},
        },
        {
            "element_id": "fig-empty-2",
            "element_type": ElementType.TABLE.value,
            "caption": "빈 컬럼 표",
            "summary": "컬럼 없음",
            "hashtags": [],
            "doc_title": "",
            "source_org": "",
            "entities": [],
            "table_data": {
                "columns": [],
                "rows": [],
            },
        },
    ]

    for p in payloads:
        is_target, legacy_txt, new_txt = is_reembed_target(p)
        assert is_target is False, f"빈 표는 대상이 아니어야 함: {p['element_id']}"
        assert legacy_txt == new_txt


def test_numeric_only_table_excluded():
    """3. 행 이름이 순수 숫자이고 열 이름도 유효한 텍스트가 없는 경우 대상에서 제외됨"""
    payload = {
        "element_id": "fig-num-1",
        "element_type": ElementType.TABLE.value,
        "caption": "숫자만 있는 표",
        "summary": "요약",
        "hashtags": [],
        "doc_title": "",
        "source_org": "",
        "entities": [],
        "table_data": {
            "columns": ["", "  ", None],
            "rows": [
                {"": "1"},
                {"": "12.5"},
                {"": "-3.0"},
            ],
        },
    }
    is_target, legacy_txt, new_txt = is_reembed_target(payload)
    assert is_target is False
    assert legacy_txt == new_txt


def test_valid_table_data_included():
    """4. 유효한 table_data가 있는 표는 대상(True)으로 선정되고 새 글자에 표 이름이 붙음"""
    payload = {
        "element_id": "fig-valid-1",
        "element_type": ElementType.TABLE.value,
        "caption": "표 1. 주요 실적 요약",
        "summary": "2025~2026E 매출 및 영업이익 요약",
        "hashtags": ["실적"],
        "doc_title": "기업분석",
        "source_org": "iM증권",
        "entities": ["삼성전자"],
        "table_data": {
            "columns": ["구분", "2025", "2026E"],
            "rows": [
                {"구분": "매출액", "2025": 100, "2026E": 120},
                {"구분": "영업이익", "2025": 10, "2026E": 15},
            ],
        },
    }

    is_target, legacy_txt, new_txt = is_reembed_target(payload)
    assert is_target is True
    assert legacy_txt != new_txt
    # 추가된 텍스트 확인
    added = new_txt[len(legacy_txt):].strip()
    assert added == "구분 2025 2026E 매출액 영업이익"
