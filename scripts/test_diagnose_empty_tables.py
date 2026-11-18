"""scripts/diagnose_empty_tables.py 분류 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diagnose_empty_tables import LEGACY_KEY_TABLE, diagnose, is_empty_table, normalize_legacy_table  # noqa: E402
from shared.schemas import ElementType  # noqa: E402


def _p(**kw):
    base = {"element_id": "e1", "doc_name": "a.pdf", "page_number": 2,
            "element_type": ElementType.TABLE.value, "table_data": None,
            "summary": "요약", "signals": {"schema_valid": 1.0}, "confidence_score": 0.7}
    base.update(kw)
    return base


def test_normalize_fills_missing_and_drops_extra():
    raw = {"columns": ["구분", "2026E"], "rows": [{"구분": "매출액"}, {"구분": "영업이익", "2026E": 3, "x": 1}]}
    fixed, bad = normalize_legacy_table(raw)
    assert bad == 2
    assert fixed["rows"] == [{"구분": "매출액", "2026E": None}, {"구분": "영업이익", "2026E": 3}]


def test_categories():
    legacy = {"columns": ["구분", "2026E"], "rows": [{"구분": "매출액"}]}
    assert diagnose(_p(), legacy)["분류"] == "복원가능"
    assert diagnose(_p(summary="삼성전자 문서 3페이지 수치 도표입니다."), None)["분류"] == "AI실패"
    assert diagnose(_p(signals={"schema_valid": 0.0}), None)["분류"] == "AI실패"
    assert diagnose(_p(), None)["분류"] == "표응답없음"


def test_is_empty_table():
    assert is_empty_table(_p())
    assert not is_empty_table(_p(table_data={"columns": ["a"], "rows": [{"a": 1}]}))
    assert not is_empty_table(_p(element_type=ElementType.CHART.value))


def test_legacy_key_name():
    assert LEGACY_KEY_TABLE == "structured" + "_" + "data"
