"""
PDF 텍스트 레이어를 좌표 순서로 정렬하여 읽는 모듈.

증권 리포트 등에서 글자가 그려지는 순서와 시각적 순서가 어긋나는 문제(예: '68.6%' -> '686% .')를
글자 바운딩 박스 좌표 기준으로 재정렬하여 정상 복원합니다.
"""
import json
import logging
import re
from typing import List, Optional, Tuple, Sequence

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from shared.coords import norm_to_pt

logger = logging.getLogger(__name__)


def has_text_layer(page) -> bool:
    """페이지에 실제 추출 가능한 텍스트가 존재하는지 확인합니다.

    스캔본이나 이미지 전용 페이지의 경우 False를 반환합니다.
    """
    if page is None:
        return False
    try:
        # 공백을 제외한 텍스트가 1글자 이상 존재하는지 검사
        text = page.get_text("text")
        return bool(text and text.strip())
    except Exception as e:
        logger.warning(f"텍스트 존재 여부 확인 실패: {e}")
        return False


def read_text_in_bbox(page, bbox: Sequence[float]) -> str:
    """지정된 정규화 bbox([x0, y0, x1, y1]) 영역 안의 글자를 좌표 순서로 정렬하여 읽습니다.

    정렬 규칙:
    1. 같은 줄 판단: 세로 중심 위치(y_mid)가 글자 높이(h)의 절반 이내면 같은 줄로 묶음
    2. 줄 순서: 위 -> 아래
    3. 줄 안 글자 순서: 왼쪽 -> 오른쪽

    Args:
        page: PyMuPDF Page 객체
        bbox: [x0, y0, x1, y1], 0~1 정규화 좌표 (좌상단 원점)

    Returns:
        좌표 순서로 복원된 텍스트 문자열
    """
    if fitz is None:
        raise ImportError("PyMuPDF(fitz) 라이브러리가 필요합니다.")

    if page is None or bbox is None or len(bbox) != 4:
        return ""

    # 페이지 회전 여부 확인 (경고만 기록, 좌표 처리는 PyMuPDF rect 기준)
    if hasattr(page, "rotation") and page.rotation != 0:
        logger.warning(f"페이지가 {page.rotation}도 회전되어 있습니다. 텍스트 추출 좌표가 회전 전 기준일 수 있습니다.")

    page_w = float(page.rect.width)
    page_h = float(page.rect.height)

    # coords.norm_to_pt만 사용하여 pt 좌표로 변환
    pt_x0, pt_y0, pt_x1, pt_y1 = norm_to_pt(bbox, page_w, page_h)
    clip_rect = fitz.Rect(pt_x0, pt_y0, pt_x1, pt_y1)

    # rawjson 포맷으로 글자(char) 단위 바운딩 박스 추출
    try:
        raw_data = json.loads(page.get_text("rawjson", clip=clip_rect))
    except Exception as e:
        logger.warning(f"rawjson 텍스트 추출 실패: {e}")
        return page.get_text("text", clip=clip_rect).strip()

    chars: List[Tuple[str, List[float]]] = []
    for b in raw_data.get("blocks", []):
        if "lines" not in b:
            continue
        for l in b["lines"]:
            for s in l.get("spans", []):
                for c in s.get("chars", []):
                    ch = c.get("c", "")
                    cb = c.get("bbox", [])
                    if not ch or len(cb) != 4:
                        continue
                    # 글자의 중심점이 bbox 영역 안에 완전히 들어있는지 확인
                    cx_mid = (cb[0] + cb[2]) / 2.0
                    cy_mid = (cb[1] + cb[3]) / 2.0
                    if pt_x0 <= cx_mid <= pt_x1 and pt_y0 <= cy_mid <= pt_y1:
                        chars.append((ch, cb))

    if not chars:
        return ""

    # 1. 글자들을 y 중심점 기준으로 1차 정렬
    chars.sort(key=lambda item: (item[1][1] + item[1][3]) / 2.0)

    # 2. 같은 줄 묶기 (세로 위치가 글자 높이의 절반 이내면 같은 줄)
    lines: List[List[Tuple[str, List[float]]]] = []
    current_line: List[Tuple[str, List[float]]] = []
    current_line_y: Optional[float] = None

    for ch, cb in chars:
        y_mid = (cb[1] + cb[3]) / 2.0
        h = max(cb[3] - cb[1], 1.0)

        if current_line_y is None:
            current_line_y = y_mid
            current_line.append((ch, cb))
        elif abs(y_mid - current_line_y) <= (h / 2.0):
            current_line.append((ch, cb))
            # 현재 줄의 평균 y 갱신
            current_line_y = sum((b[1] + b[3]) / 2.0 for _, b in current_line) / len(current_line)
        else:
            lines.append(current_line)
            current_line = [(ch, cb)]
            current_line_y = y_mid

    if current_line:
        lines.append(current_line)

    # 3. 줄 내에서 x0(왼쪽 -> 오른쪽) 순으로 정렬 후 조합
    result_lines: List[str] = []
    for line in lines:
        line.sort(key=lambda item: item[1][0])

        line_chars: List[str] = []
        prev_x1: Optional[float] = None
        prev_char: Optional[str] = None

        for ch, cb in line:
            curr_x0 = cb[0]
            # 이미 공백 문자가 명시적으로 들어있는 경우
            if ch == " ":
                if line_chars and line_chars[-1] != " ":
                    line_chars.append(" ")
                prev_x1 = cb[2]
                prev_char = " "
                continue

            # 이전 글자와 현재 글자 사이에 유의미한 수평 간격이 있는 경우 공백 보충
            if prev_x1 is not None and prev_char != " ":
                gap = curr_x0 - prev_x1
                avg_char_w = cb[2] - cb[0]
                # 글자 폭의 40% 이상 떨어져 있으면 단어 간 공백으로 판단
                if gap > max(avg_char_w * 0.4, 2.5):
                    if line_chars and line_chars[-1] != " ":
                        line_chars.append(" ")

            line_chars.append(ch)
            prev_x1 = cb[2]
            prev_char = ch

        result_lines.append("".join(line_chars).strip())

    return "\n".join(res for res in result_lines if res)



# ---------------------------------------------------------------------------
# 목차 페이지 판단 (0.1.3, 설계서 '색인 한도와 목차 거르기')
# ---------------------------------------------------------------------------


# 페이지 위쪽에 나오면 목차로 보는 제목 (공백을 뺀 소문자로 비교)
TOC_HEADINGS = ("목차", "차례", "표목차", "그림목차", "contents", "tableofcontents", "listoftables", "listoffigures")
# 점선 뒤 쪽번호로 끝나는 줄: '서론 ........ 3', '<표 3-2> 기술특성치 ··· 34'
_TOC_LEADER_LINE = re.compile(r"(\.{3,}|·{3,}|…+|‥+|ㆍ{3,}|∙{3,}|•{3,}|-{4,}|_{4,})\s*\d{1,4}\s*$")
# 쪽번호로 끝나는 줄 (점선 없이 띄어쓰기만 있는 목차용)
_ENDS_WITH_PAGE_NO = re.compile(r"\D\s+\d{1,4}\s*$")
# 목차 항목처럼 시작하는 줄: '2.3. 제약식', '제5장 결론', '<표 3-17>', '[그림 2]', '부록', '참고문헌'
# (연도로 시작하는 표 행 '2024 8998 …'은 장·절 번호 뒤 점이 없어 걸리지 않음)
_TOC_ENTRY_START = re.compile(r"^(\d{1,2}(\.\d{1,2})*\.\s|제\s*\d+\s*장|[<\[〈]\s*(표|그림)|부록|참고문헌)")


def is_toc_text(text: str) -> bool:
    """페이지 글자로 목차·표 목차·그림 목차 페이지인지 판단합니다.

    - 점선 + 쪽번호로 끝나는 줄이 5줄 이상이고 전체 줄의 40% 이상이면 목차
    - 위쪽 5줄 안에 목차 제목이 있고, 쪽번호로 끝나는 줄이 5줄 이상·전체의 50% 이상이면 목차
    - 제목·점선이 없어도(이어지는 목차 페이지, 점선을 선으로 그린 목차) 쪽번호로 끝나는 줄이 8줄 이상·전체의 80% 이상이고
      장·절 번호나 '<표 …>'로 시작하는 줄이 전체의 50% 이상이면 목차
    표의 숫자 행은 점선·제목이 없고, 소수·쉼표 숫자로 끝나거나 장·절 번호로 시작하지 않으므로 걸리지 않게 했습니다.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 5:
        return False
    leader = sum(1 for ln in lines if _TOC_LEADER_LINE.search(ln))
    if leader >= 5 and leader / len(lines) >= 0.4:
        return True
    numbered = sum(1 for ln in lines if _ENDS_WITH_PAGE_NO.search(ln))
    head = "".join("".join(ln.split()).lower() for ln in lines[:5])
    if any(h in head for h in TOC_HEADINGS):
        return numbered >= 5 and numbered / len(lines) >= 0.5
    entries = sum(1 for ln in lines if _TOC_ENTRY_START.search(ln))
    return numbered >= 8 and numbered / len(lines) >= 0.8 and entries / len(lines) >= 0.5


def is_toc_page(page) -> bool:
    """PyMuPDF 페이지가 목차 페이지인지. 텍스트 레이어가 없으면 False (판단하지 않음)."""
    if not has_text_layer(page):
        return False
    return is_toc_text(read_text_in_bbox(page, [0.0, 0.0, 1.0, 1.0]))
