"""
PDF 텍스트 레이어 좌표 순서 정렬(read_text_in_bbox) 및 has_text_layer 단위 테스트.

테스트 케이스:
1. 일부러 뒤섞인 순서로 그린 '6', '8', '.', '6', '%' -> 기본 get_text는 꼬임 확인, read_text_in_bbox는 '68.6%' 복원
2. 두 줄짜리 텍스트가 줄 순서(위 -> 아래)대로 정렬되어 반환
3. bbox 영역 밖의 글자는 결과에서 제외
4. 글자가 없는 페이지(빈 페이지 또는 이미지만 있는 페이지)에서 has_text_layer는 False
"""
import os
import sys
from pathlib import Path
import pytest

# 경로 설정
current_dir = Path(__file__).resolve().parent
repo_root = current_dir.parent.parent if current_dir.name == "pipeline" and current_dir.parent.name == "figindex" else current_dir.parent
for candidate in [
    current_dir.parent,           # figindex/ (shared/ 포함)
    current_dir,                  # /app (Docker)
    Path("/app"),                 # Docker root
    repo_root / "figindex",       # 호스트 figindex
]:
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    import fitz
except ImportError:
    fitz = None

from pdf_text import has_text_layer, read_text_in_bbox


def test_case_1_scrambled_number_percentage():
    """1. 뒤섞인 순서로 그려진 '6', '8', '.', '6', '%' 복원 검증"""
    if fitz is None:
        pytest.skip("PyMuPDF(fitz) 라이브러리가 필요합니다.")

    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    font_size = 12

    # 의도적으로 뒤섞인 순서로 텍스트 삽입 (시각적 x좌표는 50, 57, 64, 67.5, 74.5)
    # 삽입 순서: '6' -> '%' -> '8' -> '.' -> '6'
    page.insert_text(fitz.Point(50.0, 100.0), "6", fontsize=font_size)
    page.insert_text(fitz.Point(74.5, 100.0), "%", fontsize=font_size)
    page.insert_text(fitz.Point(57.0, 100.0), "8", fontsize=font_size)
    page.insert_text(fitz.Point(64.0, 100.0), ".", fontsize=font_size)
    page.insert_text(fitz.Point(67.5, 100.0), "6", fontsize=font_size)

    # 1. 기본 PyMuPDF get_text는 삽입 순서 때문에 꼬여있음을 확인
    raw_text = page.get_text("text").replace("\n", "").strip()
    assert raw_text != "68.6%", f"재현 실패: 기본 get_text가 꼬이지 않고 {raw_text}로 나옴"

    # 2. read_text_in_bbox로 읽으면 정확히 '68.6%'로 정렬되어 복원됨
    # bbox: [0.0, 0.0, 1.0, 1.0] (전체 페이지)
    extracted = read_text_in_bbox(page, [0.0, 0.0, 1.0, 1.0])
    assert extracted == "68.6%"


def test_case_2_multiline_order():
    """2. 위->아래 두 줄짜리 텍스트 순서 정렬 검증 (아래 줄을 먼저 삽입해도 줄 순서 보존)"""
    if fitz is None:
        pytest.skip("PyMuPDF(fitz) 라이브러리가 필요합니다.")

    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    font_size = 12

    # 아래 줄(Line 2, y=150)을 먼저 그리고, 윗 줄(Line 1, y=80)을 나중에 그림
    page.insert_text(fitz.Point(50.0, 150.0), "Second Line", fontsize=font_size)
    page.insert_text(fitz.Point(50.0, 80.0), "First Line", fontsize=font_size)

    # 기본 get_text는 그리기 순서대로 Second Line이 먼저 나옴
    assert page.get_text("text").strip().startswith("Second Line")

    # read_text_in_bbox는 y좌표 정렬로 First Line이 먼저 나옴
    extracted = read_text_in_bbox(page, [0.0, 0.0, 1.0, 1.0])
    lines = extracted.split("\n")
    assert lines == ["First Line", "Second Line"]


def test_case_3_bbox_clipping():
    """3. bbox 영역 밖의 글자는 결과에서 제외되는지 검증"""
    if fitz is None:
        pytest.skip("PyMuPDF(fitz) 라이브러리가 필요합니다.")

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)

    # 타겟 영역 안 글자: pt (25, 50) -> x는 약 25~85 사이 (bbox x범위 20~120 안에 완전 포함)
    page.insert_text(fitz.Point(25.0, 50.0), "Inside Target", fontsize=10)

    # 타겟 영역 밖 글자: pt (150, 150) -> bbox 밖
    page.insert_text(fitz.Point(150.0, 150.0), "Outside Target", fontsize=10)

    # bbox는 [0.1, 0.1, 0.6, 0.6] -> pt [20, 20, 120, 120]
    extracted = read_text_in_bbox(page, [0.1, 0.1, 0.6, 0.6])
    assert "Inside Target" in extracted
    assert "Outside Target" not in extracted


def test_case_4_has_text_layer():
    """4. 텍스트 레이어 유무(has_text_layer) 검증"""
    if fitz is None:
        pytest.skip("PyMuPDF(fitz) 라이브러리가 필요합니다.")

    doc = fitz.open()

    # 1. 텍스트가 있는 페이지
    p_text = doc.new_page(width=100, height=100)
    p_text.insert_text(fitz.Point(20, 20), "Sample Text", fontsize=10)
    assert has_text_layer(p_text) is True

    # 2. 빈 페이지 (텍스트 없음)
    p_empty = doc.new_page(width=100, height=100)
    assert has_text_layer(p_empty) is False

    # 3. 공백만 있는 페이지
    p_space = doc.new_page(width=100, height=100)
    p_space.insert_text(fitz.Point(20, 20), "   \n\t  ", fontsize=10)
    assert has_text_layer(p_space) is False
