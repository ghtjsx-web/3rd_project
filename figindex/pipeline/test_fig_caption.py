"""논문식 'Fig. N.' 캡션(그림 아래 캡션) 후보 찾기 테스트 (0.1.3).

드론 논문(Geophysics)이 'Fig. 1.' 캡션만 써서 도표 0개로 끝난 문제(11-19)를 재현한다.
"""
from pathlib import Path

import fitz
import pytest

from cropper import PDFCropper
from shared.schemas import ElementType


def _png_bytes(width: int = 120, height: int = 80) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, (200, 60, 60))
    return pix.tobytes("png")


@pytest.fixture()
def cropper(tmp_path: Path) -> PDFCropper:
    return PDFCropper(crops_dir=tmp_path / "crops")


def _page_with(images, texts):
    """images: [(x0, y0, x1, y1)], texts: [((x, y), 글)] 로 A4 한 쪽짜리 문서를 만든다."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    png = _png_bytes()
    for rect in images:
        page.insert_image(fitz.Rect(*rect), stream=png)
    for point, text in texts:
        page.insert_text(point, text, fontsize=9)
    return doc, page


def test_fig_caption_below_image_becomes_candidate(cropper: PDFCropper) -> None:
    doc, page = _page_with(
        images=[(100, 200, 500, 450)],
        texts=[((100, 470), "Fig. 1. Magnetic survey lines.")],
    )
    candidates = cropper.detect_candidate_boxes(page)
    assert len(candidates) == 1
    ymin, xmin, ymax, xmax = candidates[0]["bbox"]
    # 이미지(위)와 캡션(아래)을 모두 감싼다
    assert ymin <= 200 / 842 + 1e-6
    assert ymax >= 460 / 842
    assert candidates[0]["hint_type"] == ElementType.CHART.value
    assert candidates[0]["caption"].startswith("Fig. 1.")
    doc.close()


def test_stacked_panels_are_one_figure(cropper: PDFCropper) -> None:
    # (a)(b)(c) 세 칸이 위로 쌓인 그림
    doc, page = _page_with(
        images=[(100, 100, 500, 220), (100, 230, 500, 350), (100, 360, 500, 480)],
        texts=[((100, 500), "Fig. 4. Three-component magnetic anomaly maps.")],
    )
    candidates = cropper.detect_candidate_boxes(page)
    assert len(candidates) == 1
    ymin = candidates[0]["bbox"][0]
    assert ymin <= 100 / 842 + 1e-6
    doc.close()


def test_body_reference_is_not_caption(cropper: PDFCropper) -> None:
    # 본문 속 언급은 후보가 아니다
    doc, page = _page_with(
        images=[(100, 200, 500, 450)],
        texts=[((100, 470), "(Fig. 4(a)~4(c)) shows the error before correction.")],
    )
    assert cropper.detect_candidate_boxes(page) == []
    doc.close()


def test_fig_caption_without_image_above_is_skipped(cropper: PDFCropper) -> None:
    # 캡션 위쪽 가까이에 이미지가 없으면 후보를 만들지 않는다
    doc, page = _page_with(
        images=[(100, 600, 500, 750)],
        texts=[((100, 300), "Fig. 2. Comparison of scalar and vector data.")],
    )
    assert cropper.detect_candidate_boxes(page) == []
    doc.close()
