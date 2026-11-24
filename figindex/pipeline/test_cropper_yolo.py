"""cropper.py YOLO 크롭 연결 테스트 (11-24 결정, 4_크롭.md 6단계).

실제 YOLO 모델 없이 가짜 모델로 확인한다:
- 캡션·각주가 본 박스에 병합되고, 구 버전 후보 형식(ymin, xmin, ymax, xmax)으로 넘어가는지
- detection_score가 모델 점수 그대로 넘어가는지
- YOLO를 못 불러오면 규칙 방식으로 돌아가는지
"""
from __future__ import annotations

from types import SimpleNamespace

import fitz  # PyMuPDF
import pytest
from PIL import Image

from cropper import CROP_METHOD_RULE, CROP_METHOD_YOLO, PDFCropper
from shared.coords import from_legacy_yxyx, to_legacy_yxyx
from shared.schemas import ElementType


class _FakeBoxes:
    def __init__(self, rows):
        # rows: [(x0, y0, x1, y1 픽셀), cls_id, score]
        self.xyxy = SimpleNamespace(tolist=lambda: [list(r[0]) for r in rows])
        self.cls = SimpleNamespace(tolist=lambda: [r[1] for r in rows])
        self.conf = SimpleNamespace(tolist=lambda: [r[2] for r in rows])


class _FakeModel:
    # DocLayout-YOLO DocStructBench 클래스 이름 일부 (LayoutClass 값과 같음)
    names = {1: "plain text", 3: "figure", 5: "table", 6: "table_caption", 7: "table_footnote"}

    def __init__(self, rows):
        self._rows = rows

    def predict(self, img, **kwargs):
        return [SimpleNamespace(boxes=_FakeBoxes(self._rows))]


def _cropper(tmp_path, rows, method=CROP_METHOD_YOLO):
    cropper = PDFCropper(crops_dir=tmp_path, crop_method=method)
    cropper._yolo_model = _FakeModel(rows)
    return cropper


def test_to_legacy_yxyx_round_trip():
    bbox = [0.1, 0.2, 0.7, 0.9]
    assert to_legacy_yxyx(bbox) == [0.2, 0.1, 0.9, 0.7]
    assert from_legacy_yxyx(to_legacy_yxyx(bbox)) == bbox


def test_yolo_candidates_merge_caption_and_keep_score(tmp_path):
    img = Image.new("RGB", (1000, 1000), "white")
    rows = [
        ((100, 200, 900, 600), 5, 0.91),   # table 본 박스
        ((100, 160, 600, 190), 6, 0.77),   # table_caption (바로 위)
        ((100, 610, 500, 640), 7, 0.70),   # table_footnote (바로 아래)
        ((100, 700, 900, 950), 3, 0.66),   # figure
        ((100, 50, 900, 120), 1, 0.99),    # 본문 → 버림
    ]
    cands = _cropper(tmp_path, rows).detect_yolo_candidates(img)

    assert [c["hint_type"] for c in cands] == [ElementType.TABLE.value, ElementType.CHART.value]
    table = cands[0]
    # 캡션·각주까지 병합: x0 0.1, y0 0.16, x1 0.9, y1 0.64 → 구 버전 (ymin, xmin, ymax, xmax)
    assert table["bbox"] == pytest.approx((0.16, 0.1, 0.64, 0.9))
    assert table["detection_score"] == pytest.approx(0.91)
    assert cands[1]["detection_score"] == pytest.approx(0.66)
    assert all(c["caption"] == "" for c in cands)


def test_detect_page_candidates_uses_yolo_and_returns_page_image(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    cropper = _cropper(tmp_path, [((50, 50, 400, 300), 5, 0.9)])

    cands, page_img = cropper.detect_page_candidates(doc, 1)

    assert cropper.active_crop_method == CROP_METHOD_YOLO
    assert page_img is not None and len(cands) == 1
    # crop_and_save가 YOLO 후보를 그대로 받아 크롭한다
    info = cropper.crop_and_save(doc=doc, doc_path=tmp_path / "x.pdf", page_num=1, candidate=cands[0], page_img=page_img)
    assert info["hint_type"] == ElementType.TABLE.value and info["crop_path"].exists()


def test_falls_back_to_rule_when_yolo_cannot_load(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    cropper = PDFCropper(crops_dir=tmp_path, crop_method=CROP_METHOD_YOLO)
    cropper._yolo_load_failed = True  # 패키지 없음·내려받기 실패와 같은 상태

    cands, page_img = cropper.detect_page_candidates(doc, 1)

    assert cropper.active_crop_method == CROP_METHOD_RULE
    assert page_img is None and cands == []  # 빈 페이지라 규칙 방식 후보도 없음


def test_crop_method_from_env_and_unknown_value(tmp_path, monkeypatch):
    monkeypatch.setenv("CROP_METHOD", "rule")
    assert PDFCropper(crops_dir=tmp_path).crop_method == CROP_METHOD_RULE
    monkeypatch.setenv("CROP_METHOD", "something")
    assert PDFCropper(crops_dir=tmp_path).crop_method == CROP_METHOD_YOLO


def test_duplicate_boxes_for_same_table_are_merged(tmp_path):
    """11-24 시험 업로드: 같은 표(Stock Indicator)가 두 번 크롭된 경우."""
    img = Image.new("RGB", (1000, 1000), "white")
    rows = [
        ((100, 100, 500, 300), 5, 0.62),   # 같은 표, 점수 낮은 박스
        ((105, 98, 505, 310), 5, 0.71),    # 같은 표, 점수 높은 박스
        ((100, 500, 900, 810), 3, 0.90),   # 다른 그림
        ((150, 550, 450, 750), 3, 0.40),   # 그림 안 패널 → 그림에 합침
    ]
    cands = _cropper(tmp_path, rows).detect_yolo_candidates(img)

    assert len(cands) == 2
    table, figure = cands
    assert table["detection_score"] == pytest.approx(0.71)
    assert table["bbox"] == pytest.approx((0.098, 0.1, 0.31, 0.505))
    assert figure["hint_type"] == ElementType.CHART.value
    assert figure["bbox"] == pytest.approx((0.5, 0.1, 0.81, 0.9))
