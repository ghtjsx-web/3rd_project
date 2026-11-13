"""
FigIndex 공통 좌표 변환 모듈 (figindex/shared/coords.py)

표준 BBox 규격:
- 형식: [x0, y0, x1, y1] (0~1 정규화, 좌상단 원점, x0 < x1, y0 < y1)
- 표준 라이브러리만 사용하여 백엔드·파이프라인 모두 가볍게 import 가능
- 주의: 회전된 페이지(page.rotation != 0)는 호출하는 쪽에서 PyMuPDF 회전 행렬로 먼저 보정해야 함
"""
from typing import List, Sequence


def validate_bbox(bbox: Sequence[float]) -> None:
    """
    정규화 BBox의 유효성을 검사합니다.

    입력:
        bbox: 검사할 좌표 [x0, y0, x1, y1] (0~1 정규화)
    예외:
        ValueError: 길이가 4가 아니거나, 0~1 범위를 벗어나거나, x0>=x1 또는 y0>=y1인 경우
    """
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError(f"bbox의 길이는 4여야 합니다. (입력값: {bbox})")

    x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])

    for i, val in enumerate([x0, y0, x1, y1]):
        if val < 0.0 or val > 1.0:
            coord_names = ["x0", "y0", "x1", "y1"]
            raise ValueError(
                f"좌표 값은 0.0과 1.0 사이여야 합니다. ({coord_names[i]}={val}, bbox={bbox})"
            )

    if x0 >= x1:
        raise ValueError(f"x0는 x1보다 작아야 합니다 (x0 < x1). (x0={x0}, x1={x1})")
    if y0 >= y1:
        raise ValueError(f"y0는 y1보다 작아야 합니다 (y0 < y1). (y0={y0}, y1={y1})")


def clip_bbox(bbox: Sequence[float]) -> List[float]:
    """
    0~1 정규화 범위를 벗어난 BBox 좌표를 0.0~1.0 구간으로 자릅니다.

    입력:
        bbox: [x0, y0, x1, y1] (임의 실수)
    출력:
        [x0, y0, x1, y1] (0.0~1.0 범위로 클리핑된 실수 리스트)
    """
    return [
        max(0.0, min(1.0, float(bbox[0]))),
        max(0.0, min(1.0, float(bbox[1]))),
        max(0.0, min(1.0, float(bbox[2]))),
        max(0.0, min(1.0, float(bbox[3]))),
    ]


def pt_to_norm(rect_pt: Sequence[float], width_pt: float, height_pt: float) -> List[float]:
    """
    PyMuPDF 포인트(pt) 좌표 사각형을 0~1 정규화 좌표로 변환합니다.

    입력:
        rect_pt: [x0_pt, y0_pt, x1_pt, y1_pt] (PDF pt 단위, 좌상단 원점)
        width_pt: 페이지 너비 (PDF pt 단위)
        height_pt: 페이지 높이 (PDF pt 단위)
    출력:
        [x0, y0, x1, y1] (0~1 정규화 좌표)
    """
    if width_pt <= 0.0 or height_pt <= 0.0:
        raise ValueError(f"페이지 크기(pt)는 0보다 커야 합니다. (width={width_pt}, height={height_pt})")

    return [
        float(rect_pt[0]) / width_pt,
        float(rect_pt[1]) / height_pt,
        float(rect_pt[2]) / width_pt,
        float(rect_pt[3]) / height_pt,
    ]


def norm_to_pt(bbox: Sequence[float], width_pt: float, height_pt: float) -> List[float]:
    """
    0~1 정규화 좌표를 PyMuPDF 포인트(pt) 좌표로 변환합니다.

    입력:
        bbox: [x0, y0, x1, y1] (0~1 정규화)
        width_pt: 페이지 너비 (PDF pt 단위)
        height_pt: 페이지 높이 (PDF pt 단위)
    출력:
        [x0_pt, y0_pt, x1_pt, y1_pt] (PDF pt 단위)
    """
    if width_pt <= 0.0 or height_pt <= 0.0:
        raise ValueError(f"페이지 크기(pt)는 0보다 커야 합니다. (width={width_pt}, height={height_pt})")

    return [
        float(bbox[0]) * width_pt,
        float(bbox[1]) * height_pt,
        float(bbox[2]) * width_pt,
        float(bbox[3]) * height_pt,
    ]


def px_to_norm(rect_px: Sequence[float], image_width_px: float, image_height_px: float) -> List[float]:
    """
    YOLO 탐지 결과 및 화면 픽셀(px) 좌표 사각형을 0~1 정규화 좌표로 변환합니다.

    입력:
        rect_px: [x0_px, y0_px, x1_px, y1_px] (렌더링 이미지 픽셀 단위, 좌상단 원점)
        image_width_px: 이미지 가로 픽셀 수 (px)
        image_height_px: 이미지 세로 픽셀 수 (px)
    출력:
        [x0, y0, x1, y1] (0~1 정규화 좌표)
    """
    if image_width_px <= 0.0 or image_height_px <= 0.0:
        raise ValueError(f"이미지 크기(px)는 0보다 커야 합니다. (width={image_width_px}, height={image_height_px})")

    return [
        float(rect_px[0]) / image_width_px,
        float(rect_px[1]) / image_height_px,
        float(rect_px[2]) / image_width_px,
        float(rect_px[3]) / image_height_px,
    ]


def norm_to_px(bbox: Sequence[float], image_width_px: float, image_height_px: float) -> List[float]:
    """
    0~1 정규화 좌표를 이미지 또는 화면 픽셀(px) 좌표로 변환합니다.

    입력:
        bbox: [x0, y0, x1, y1] (0~1 정규화)
        image_width_px: 이미지 가로 픽셀 수 (px)
        image_height_px: 이미지 세로 픽셀 수 (px)
    출력:
        [x0_px, y0_px, x1_px, y1_px] (픽셀 단위)
    """
    if image_width_px <= 0.0 or image_height_px <= 0.0:
        raise ValueError(f"이미지 크기(px)는 0보다 커야 합니다. (width={image_width_px}, height={image_height_px})")

    return [
        float(bbox[0]) * image_width_px,
        float(bbox[1]) * image_height_px,
        float(bbox[2]) * image_width_px,
        float(bbox[3]) * image_height_px,
    ]


def pt_to_px_scale(dpi: float) -> float:
    """
    DPI 기준 pt에서 px로의 렌더링 확대 배율(scale)을 계산합니다.
    (1 inch = 72 pt 표준)

    입력:
        dpi: 렌더링 DPI (예: 200, 150)
    출력:
        배율 (dpi / 72.0)
    """
    if dpi <= 0.0:
        raise ValueError(f"DPI는 0보다 커야 합니다. (dpi={dpi})")
    return float(dpi) / 72.0


def from_legacy_yxyx(legacy_bbox: Sequence[float]) -> List[float]:
    """
    구 버전 좌표 [ymin, xmin, ymax, xmax]를 신규 표준 [x0, y0, x1, y1]로 변환합니다.

    입력:
        legacy_bbox: [ymin, xmin, ymax, xmax] (0~1 정규화)
    출력:
        [x0, y0, x1, y1] (0~1 정규화)
    """
    if len(legacy_bbox) != 4:
        raise ValueError(f"legacy_bbox 길이는 4여야 합니다. (입력값: {legacy_bbox})")
    ymin, xmin, ymax, xmax = legacy_bbox
    return [float(xmin), float(ymin), float(xmax), float(ymax)]


def union_bbox(bboxes: Sequence[Sequence[float]]) -> List[float]:
    """
    여러 개의 정규화 BBox를 모두 감싸는 최소 바운딩 박스를 계산합니다.
    (본 박스와 캡션·각주 박스 병합 시 사용)

    입력:
        bboxes: BBox들의 시퀀스 [[x0, y0, x1, y1], ...]
    출력:
        [x0, y0, x1, y1] (모든 박스를 포괄하는 정규화 박스)
    """
    if not bboxes:
        raise ValueError("병합할 bbox 목록이 비어 있습니다.")

    x0s = [float(b[0]) for b in bboxes]
    y0s = [float(b[1]) for b in bboxes]
    x1s = [float(b[2]) for b in bboxes]
    y1s = [float(b[3]) for b in bboxes]

    return [min(x0s), min(y0s), max(x1s), max(y1s)]


def pad_bbox_pt(
    bbox: Sequence[float],
    pad_x_pt: float,
    pad_y_pt: float,
    width_pt: float,
    height_pt: float
) -> List[float]:
    """
    0~1 정규화 BBox에 pt 단위의 여백(패딩)을 추가하고 0.0~1.0 범위로 클리핑합니다.

    입력:
        bbox: [x0, y0, x1, y1] (0~1 정규화)
        pad_x_pt: 가로 방향 좌우 확장 pt (기본값 없음, 호출자 지정)
        pad_y_pt: 세로 방향 상하 확장 pt (기본값 없음, 호출자 지정)
        width_pt: 페이지 너비 (PDF pt)
        height_pt: 페이지 높이 (PDF pt)
    출력:
        [x0, y0, x1, y1] (패딩이 적용되고 0~1로 클리핑된 정규화 박스)
    """
    if width_pt <= 0.0 or height_pt <= 0.0:
        raise ValueError(f"페이지 크기(pt)는 0보다 커야 합니다. (width={width_pt}, height={height_pt})")

    norm_pad_x = float(pad_x_pt) / width_pt
    norm_pad_y = float(pad_y_pt) / height_pt

    padded = [
        float(bbox[0]) - norm_pad_x,
        float(bbox[1]) - norm_pad_y,
        float(bbox[2]) + norm_pad_x,
        float(bbox[3]) + norm_pad_y,
    ]
    return clip_bbox(padded)


def bbox_area(bbox: Sequence[float]) -> float:
    """
    BBox의 넓이를 계산합니다.

    입력:
        bbox: [x0, y0, x1, y1]
    출력:
        넓이 (가로 × 세로)
    """
    w = max(0.0, float(bbox[2]) - float(bbox[0]))
    h = max(0.0, float(bbox[3]) - float(bbox[1]))
    return w * h


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """
    두 BBox 간의 IoU (Intersection over Union, 교집합 넓이 / 합집합 넓이)를 계산합니다.

    입력:
        a: [x0, y0, x1, y1]
        b: [x0, y0, x1, y1]
    출력:
        0.0 ~ 1.0 실수 (완전 일치 시 1.0, 겹치지 않으면 0.0)
    """
    inter_x0 = max(float(a[0]), float(b[0]))
    inter_y0 = max(float(a[1]), float(b[1]))
    inter_x1 = min(float(a[2]), float(b[2]))
    inter_y1 = min(float(a[3]), float(b[3]))

    inter_w = max(0.0, inter_x1 - inter_x0)
    inter_h = max(0.0, inter_y1 - inter_y0)
    inter_area = inter_w * inter_h

    area_a = bbox_area(a)
    area_b = bbox_area(b)

    union_area = area_a + area_b - inter_area
    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area

