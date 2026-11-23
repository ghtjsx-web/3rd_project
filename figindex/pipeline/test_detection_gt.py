"""detection_gt.py (탐지 정답셋 초안·crop_recall) 단위 테스트.

실행:
  pytest figindex/pipeline/test_detection_gt.py -v
"""
import json
import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent
FIGINDEX_DIR = PIPELINE_DIR.parent
for p in (str(PIPELINE_DIR), str(FIGINDEX_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from detection_gt import (  # noqa: E402
    combine_drafts,
    crop_recall,
    gt_file_name,
    load_gt_files,
    pick_pages,
    yolo_boxes_to_elements,
)
from shared.schemas import ElementType, LayoutClass  # noqa: E402

TABLE = ElementType.TABLE.value
CHART = ElementType.CHART.value


def test_yolo_caption_and_footnote_are_merged_into_main_box():
    detections = [
        (LayoutClass.TABLE.value, [0.10, 0.30, 0.90, 0.60]),
        (LayoutClass.TABLE_CAPTION.value, [0.10, 0.26, 0.60, 0.29]),   # 표 바로 위 제목
        (LayoutClass.TABLE_FOOTNOTE.value, [0.10, 0.61, 0.50, 0.63]),  # 표 바로 아래 출처
        (LayoutClass.PLAIN_TEXT.value, [0.10, 0.70, 0.90, 0.82]),      # 본문: 버림
    ]
    elements = yolo_boxes_to_elements(detections)
    assert elements == [{"element_type": TABLE, "bbox": [0.10, 0.26, 0.90, 0.63]}]


def test_yolo_figure_draft_type_and_far_caption_ignored():
    detections = [
        (LayoutClass.FIGURE.value, [0.10, 0.10, 0.50, 0.40]),
        (LayoutClass.FIGURE_CAPTION.value, [0.60, 0.50, 0.90, 0.53]),  # 가로로 안 겹침
        ("unknown_class", [0.0, 0.0, 1.0, 1.0]),
    ]
    assert yolo_boxes_to_elements(detections) == [{"element_type": CHART, "bbox": [0.10, 0.10, 0.50, 0.40]}]


def test_combine_drafts_unions_same_element_and_hides_source_order():
    rule = [{"element_type": CHART, "bbox": [0.10, 0.50, 0.90, 0.78]},
            {"element_type": TABLE, "bbox": [0.10, 0.10, 0.90, 0.40]}]
    yolo = [{"element_type": TABLE, "bbox": [0.12, 0.12, 0.92, 0.42]},   # rule 표와 같은 요소
            {"element_type": CHART, "bbox": [0.10, 0.85, 0.50, 0.95]}]   # yolo만 찾음
    draft = combine_drafts(rule, yolo)
    assert [d["bbox"] for d in draft] == [
        [0.10, 0.10, 0.92, 0.42],  # 두 방식 박스를 감싼 박스
        [0.10, 0.50, 0.90, 0.78],
        [0.10, 0.85, 0.50, 0.95],
    ]
    assert draft[0]["element_type"] == TABLE


def test_crop_recall_follows_glossary_definition():
    gt = {("a.pdf", 1): [[0.1, 0.1, 0.5, 0.5], [0.6, 0.6, 0.9, 0.9]], ("a.pdf", 2): [[0.1, 0.1, 0.9, 0.3]]}
    pred = {("a.pdf", 1): [[0.1, 0.1, 0.5, 0.48]],      # 첫 정답만 맞춤
            ("a.pdf", 2): [[0.1, 0.25, 0.9, 0.6]]}     # IoU < 0.5
    assert crop_recall(gt, pred) == pytest.approx(1 / 3)
    assert crop_recall({}, pred) is None


def test_load_gt_files_reads_only_reviewed(tmp_path):
    for name, reviewed in (("a.pdf", True), ("b.pdf", False)):
        data = {"doc_name": name, "page_number": 3, "reviewed": reviewed, "elements": []}
        (tmp_path / gt_file_name(name, 3)).write_text(json.dumps(data), encoding="utf-8")
    assert [d["doc_name"] for d in load_gt_files(tmp_path)] == ["a.pdf"]
    assert len(load_gt_files(tmp_path, include_unreviewed=True)) == 2


def test_pick_pages_spreads_kinds_and_limits_docs():
    pages = []
    for i in range(6):
        pages += [(f"RPT_2026110{i}_종목{i}_증권.pdf", p, 2) for p in range(1, 6)]
        pages += [(f"논문_2026_주제{i}.pdf", p, 1) for p in range(1, 6)]
    pages.append(("보고서2025_에너지.pdf", 3, 0))  # 후보 없는 페이지는 제외
    picked = pick_pages(pages, total=20, max_docs=4, per_doc=4)
    docs = {d for d, _ in picked}
    assert len(picked) == 16 and len(docs) == 4      # 4개 문서 × 4페이지
    assert sum(d.startswith("RPT") for d in docs) == 2 and sum(d.startswith("논문") for d in docs) == 2
    assert picked == pick_pages(pages, total=20, max_docs=4, per_doc=4)  # 항상 같은 결과
