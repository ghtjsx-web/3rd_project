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
# 11-19 check_toc_filter.py --dump에서 못 거른 실제 페이지 (점선이 선으로 그려져 글자로 안 읽히고, 제목 없는 이어지는 목차)
CONTINUED_NO_LEADERS = "2.3. 제약식 38\n2.4. 구석 해 완화를 위한 가정 39\n제4장 수소공급 시나리오 분석 43\n1. 시나리오 분석 개요 43\n1.1. 시나리오의 구성 43\n2. 정책 목표 시나리오 분석 결과 45\n2.1. 수소공급 믹스 45\n2.2. 수소공급 비용 46\n3. 기준 시나리오 분석 결과 51\n3.1. 수소공급 믹스 51"
SHORT_LAST_TOC_PAGE = "3.3. 주요 재자원화원료의 재자원화체계 구축 방향 120\n3.4. 철스크랩(e-scrap)의 해외 유출 방지 122\n4. 산업 기반 조성을 위한 지원 123\n4.1. 생산비(운영비) 절감을 위한 기술개발 방향 123\n4.2. 핵심광물 재자원화 기반 조성 사업 추진 필요 125\n4.3. 자발적 재생원료 사용 목표제 도입 127\n4.4. 재자원화 목표 설정 및 재자원화율 산정방법 개선 128\n제5장 결론 133\n1. 주요 연구결과 요약 133\n2. 의의 및 한계점 136\n참고문헌 137\n부록 145\niii"
CONTINUED_TABLE_LIST = "\n".join(f"<표 3-{i}> 재자원화 분석 항목 {50 + i}" for i in range(17, 30)) + "\n<표 3-22> 줄이 넘어가는 표 제목 RD&D\n우선순위 및 효과 70"
YEAR_ROWS_TABLE = "연도 매출액 영업이익 EPS\n2024 9412 1762 8998\n2025 21202 1841 8795\n2026E 22155 2255 10040\n2027E 23559 2515 12788\n2028E 24935 2799 14500\n2029E 25100 2810 14600\n2030E 25300 2850 14700\n2031E 25400 2860 14800"
ONE_COLUMN_TABLE = "구분 값\n매출액(억원) 1563\n영업이익(억원) 195\n순이익(억원) 120\n부채비율(%) 37\n직원 수(명) 840"


def test_toc_pages_are_detected():
    assert is_toc_text(TOC)
    assert is_toc_text(TABLE_TOC_NO_LEADERS)
    assert is_toc_text(CONTINUED_TOC)       # 제목 없는 이어지는 목차 페이지
    assert is_toc_text(CONTINUED_NO_LEADERS)
    assert is_toc_text(SHORT_LAST_TOC_PAGE)
    assert is_toc_text(CONTINUED_TABLE_LIST)


def test_tables_and_body_are_not_toc():
    assert not is_toc_text(FIN_TABLE)
    assert not is_toc_text(BODY)
    assert not is_toc_text(ONE_COLUMN_TABLE)
    assert not is_toc_text(YEAR_ROWS_TABLE)     # 연도로 시작하는 숫자 행   # 쪽번호처럼 끝나도 목차 제목이 없으면 아님
    assert not is_toc_text("")
    assert not is_toc_text("목차\n1. 서론 1\n2. 본론 5")   # 줄이 너무 적음
