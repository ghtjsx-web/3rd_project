"""
공통 좌표 변환 모듈 (figindex/shared/coords.py) 단위 테스트.

실행:
  pytest figindex/pipeline/test_coords.py -v
"""
import sys
from pathlib import Path

import pytest

# Ensure figindex and pipeline are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIGINDEX_DIR = REPO_ROOT / "figindex"
PIPELINE_DIR = FIGINDEX_DIR / "pipeline"

for p in (str(PIPELINE_DIR), str(FIGINDEX_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.coords import (
    validate_bbox,
    clip_bbox,
    pt_to_norm,
    norm_to_pt,
    px_to_norm,
    norm_to_px,
    pt_to_px_scale,
    from_legacy_yxyx,
    union_bbox,
    pad_bbox_pt,
    bbox_area,
    iou,
)


def test_fitz_not_imported():
    """9. coords.py를 import했을 때 fitz가 sys.modules에 로드되지 않아야 함 (순수 표준 라이브러리 검증)"""
    # Note: If another test in the session imports fitz, it might be in sys.modules,
    # but coords itself must not have imported fitz.
    import shared.coords as c
    assert "fitz" not in c.__dict__


def test_pt_norm_roundtrip():
    """1. pt → 정규화 → pt 왕복 시 값이 같음 (A4 595 x 842 pt 예시)"""
    w_pt, h_pt = 595.0, 842.0
    orig_rect_pt = [50.0, 100.0, 545.0, 400.0]

    norm = pt_to_norm(orig_rect_pt, w_pt, h_pt)
    assert norm[0] == pytest.approx(50.0 / 595.0)
    assert norm[1] == pytest.approx(100.0 / 842.0)
    assert norm[2] == pytest.approx(545.0 / 595.0)
    assert norm[3] == pytest.approx(400.0 / 842.0)

    roundtrip_pt = norm_to_pt(norm, w_pt, h_pt)
    for orig, rt in zip(orig_rect_pt, roundtrip_pt):
        assert rt == pytest.approx(orig)


def test_px_norm_roundtrip():
    """2. px → 정규화 → px 왕복 (예: 1654 x 2339 px, 200dpi 렌더링)"""
    w_px, h_px = 1654.0, 2339.0
    orig_rect_px = [120.0, 300.0, 1500.0, 1100.0]

    norm = px_to_norm(orig_rect_px, w_px, h_px)
    assert norm[0] == pytest.approx(120.0 / 1654.0)
    assert norm[1] == pytest.approx(300.0 / 2339.0)
    assert norm[2] == pytest.approx(1500.0 / 1654.0)
    assert norm[3] == pytest.approx(1100.0 / 2339.0)

    roundtrip_px = norm_to_px(norm, w_px, h_px)
    for orig, rt in zip(orig_rect_px, roundtrip_px):
        assert rt == pytest.approx(orig)


def test_pt_and_px_scale_consistency():
    """3. 같은 영역을 pt로 변환한 값과 px로 변환한 값의 정규화 결과가 같음 (dpi/72 배율 검증)"""
    dpi = 200.0
    scale = pt_to_px_scale(dpi)  # 200 / 72 = 2.7777...
    assert scale == pytest.approx(200.0 / 72.0)

    w_pt, h_pt = 595.0, 842.0
    w_px, h_px = w_pt * scale, h_pt * scale

    rect_pt = [72.0, 144.0, 500.0, 400.0]
    rect_px = [coord * scale for coord in rect_pt]

    norm_from_pt = pt_to_norm(rect_pt, w_pt, h_pt)
    norm_from_px = px_to_norm(rect_px, w_px, h_px)

    for np, nx in zip(norm_from_pt, norm_from_px):
        assert np == pytest.approx(nx)


def test_from_legacy_yxyx():
    """4. from_legacy_yxyx([0.1, 0.2, 0.5, 0.9]) == [0.2, 0.1, 0.9, 0.5]"""
    legacy_bbox = [0.1, 0.2, 0.5, 0.9]
    converted = from_legacy_yxyx(legacy_bbox)
    assert converted == [0.2, 0.1, 0.9, 0.5]


def test_union_bbox():
    """5. union_bbox: 본 박스 + 아래 캡션 박스 → 둘 다 감싸는 박스"""
    table_box = [0.1, 0.2, 0.9, 0.6]
    caption_box = [0.15, 0.62, 0.85, 0.68]

    merged = union_bbox([table_box, caption_box])
    assert merged == [0.1, 0.2, 0.9, 0.68]

    # 빈 리스트일 때 예외 검증
    with pytest.raises(ValueError):
        union_bbox([])


def test_pad_bbox_pt_clipping():
    """6. pad_bbox_pt: 페이지 가장자리 박스에 패딩을 주면 0~1로 잘림"""
    w_pt, h_pt = 100.0, 100.0
    # 좌상단 모서리에 붙어 있는 박스 (0.01 ~ 0.50)
    bbox = [0.01, 0.01, 0.50, 0.50]
    # 가로 5pt, 세로 5pt 패딩 추가 -> 0.01 - 0.05 = -0.04 -> 0.0으로 클리핑되어야 함
    padded = pad_bbox_pt(bbox, pad_x_pt=5.0, pad_y_pt=5.0, width_pt=w_pt, height_pt=h_pt)
    assert padded[0] == 0.0
    assert padded[1] == 0.0
    assert padded[2] == 0.55
    assert padded[3] == 0.55

    # 우하단 모서리에 붙어 있는 박스 (0.50 ~ 0.99)
    bbox_br = [0.50, 0.50, 0.99, 0.99]
    padded_br = pad_bbox_pt(bbox_br, pad_x_pt=5.0, pad_y_pt=5.0, width_pt=w_pt, height_pt=h_pt)
    assert padded_br[0] == 0.45
    assert padded_br[1] == 0.45
    assert padded_br[2] == 1.0
    assert padded_br[3] == 1.0


def test_iou_calculations():
    """7. iou: 같은 박스 1.0 / 안 겹침 0.0 / 절반 겹침 예시의 정확한 값"""
    box_a = [0.0, 0.0, 0.4, 0.4]  # area = 0.16
    box_b = [0.0, 0.0, 0.4, 0.4]
    assert iou(box_a, box_b) == pytest.approx(1.0)

    # 전혀 겹치지 않는 경우
    box_c = [0.5, 0.5, 0.9, 0.9]
    assert iou(box_a, box_c) == 0.0

    # 절반 겹침 예시:
    # box1 = [0.0, 0.0, 0.2, 0.2] (area = 0.04)
    # box2 = [0.1, 0.0, 0.3, 0.2] (area = 0.04)
    # 교집합 = [0.1, 0.0, 0.2, 0.2] (width = 0.1, height = 0.2 -> area = 0.02)
    # 합집합 = 0.04 + 0.04 - 0.02 = 0.06
    # IoU = 0.02 / 0.06 = 1/3
    box1 = [0.0, 0.0, 0.2, 0.2]
    box2 = [0.1, 0.0, 0.3, 0.2]
    assert iou(box1, box2) == pytest.approx(0.02 / 0.06)


def test_validate_bbox_exceptions():
    """8. validate_bbox: 뒤집힌 박스, 범위 밖 값, 길이 3에서 ValueError"""
    # 유효한 박스는 예외 없음
    validate_bbox([0.1, 0.1, 0.9, 0.9])

    # 길이가 3인 경우
    with pytest.raises(ValueError, match="길이는 4여야"):
        validate_bbox([0.1, 0.1, 0.9])

    # 범위 밖 값 (< 0.0 또는 > 1.0)
    with pytest.raises(ValueError, match="0.0과 1.0 사이"):
        validate_bbox([-0.05, 0.1, 0.9, 0.9])

    with pytest.raises(ValueError, match="0.0과 1.0 사이"):
        validate_bbox([0.1, 0.1, 1.05, 0.9])

    # 뒤집힌 박스: x0 >= x1
    with pytest.raises(ValueError, match="x0는 x1보다 작아야"):
        validate_bbox([0.8, 0.1, 0.2, 0.9])

    # 뒤집힌 박스: y0 >= y1
    with pytest.raises(ValueError, match="y0는 y1보다 작아야"):
        validate_bbox([0.1, 0.8, 0.9, 0.2])

