"""pdf_text.is_toc_text 테스트 (0.1.3 목차 거르기)."""
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR))
sys.path.insert(0, str(PIPELINE_DIR.parent))

from pdf_text import is_toc_text  # noqa: E402

TOC = "목 차\n제1장 서론 ........................ 1\n1. 연구 배경 ...................... 1\n2. 연구 목적 ...................... 3\n제2장 현황 ........................ 5\n1. 국내 현황 ...................... 7"
TABLE_TOC_NO_LEADERS = "표 목차\n<표 3-1> 증기 메탄 개질 기술특성치  33\n<표 3-2> 블루수소 기술특성치  34\n<표 3-3> 권역별 표본  43\n<표 4-1> 수출등록말소 현황  114\n<표 4-5> 승용차 현황  124"
CONTINUED_TOC = "\n".join(f"{i}. 절 제목 {i} ··········· {i * 3}" for i in range(1, 9))
FIN_TABLE = "구분 2024 2025 2026E\n매출 1,202.2 1,371.1 1,563.6\n영업이익 71.5 130.1 195.6\n영업이익률 6.0% 9.5% 12.5%\n순이익 50 80 120\nEPS 1200 1500 1800"
BODY = "본 연구는 수소 공급 믹스를 분석한다.\n분석 결과 비용은 2030년 이후 하락한다.\n이는 탄소포집 비용 감소 때문이다.\n<표 3-2> 참조\n결론은 다음과 같다.\n정책 제언 3가지를 제시한다."
ONE_COLUMN_TABLE = "구분 값\n매출액(억원) 1563\n영업이익(억원) 195\n순이익(억원) 120\n부채비율(%) 37\n직원 수(명) 840"


def test_toc_pages_are_detected():
    assert is_toc_text(TOC)
    assert is_toc_text(TABLE_TOC_NO_LEADERS)
    assert is_toc_text(CONTINUED_TOC)       # 제목 없는 이어지는 목차 페이지


def test_tables_and_body_are_not_toc():
    assert not is_toc_text(FIN_TABLE)
    assert not is_toc_text(BODY)
    assert not is_toc_text(ONE_COLUMN_TABLE)   # 쪽번호처럼 끝나도 목차 제목이 없으면 아님
    assert not is_toc_text("")
    assert not is_toc_text("목차\n1. 서론 1\n2. 본론 5")   # 줄이 너무 적음
