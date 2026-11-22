"""element_match.py (빠진 요소만 추가하는 재색인, 결정 22) 단위 테스트.

실행:
  pytest figindex/pipeline/test_element_match.py -v
"""
import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent
FIGINDEX_DIR = PIPELINE_DIR.parent
for p in (str(PIPELINE_DIR), str(FIGINDEX_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from element_match import (  # noqa: E402
    doc_overrides_from_payload,
    group_bboxes_by_page,
    matches_existing,
    plan_new_candidates,
    single_doc_id,
)

TABLE_BOX = [0.10, 0.20, 0.90, 0.50]          # 저장된 요소 (패딩 포함)
TABLE_CANDIDATE = [0.12, 0.22, 0.88, 0.48]    # 같은 표를 다시 찾은 후보 (패딩 없음)
OTHER_BOX = [0.10, 0.60, 0.90, 0.90]          # 같은 페이지 다른 표


def test_same_table_matches_by_iou():
    assert matches_existing(TABLE_CANDIDATE, [TABLE_BOX])


def test_small_candidate_inside_padded_box_matches():
    small = [0.40, 0.30, 0.50, 0.33]  # IoU는 작지만 후보 전체가 기존 박스 안
    assert matches_existing(small, [TABLE_BOX])


def test_other_table_on_same_page_does_not_match():
    assert not matches_existing(OTHER_BOX, [TABLE_BOX])
    assert not matches_existing(TABLE_CANDIDATE, [])


def test_group_bboxes_by_page_skips_broken_payloads():
    payloads = [
        {"page_number": 2, "bbox": TABLE_BOX},
        {"page_number": 2, "bbox": OTHER_BOX},
        {"page_number": 3, "bbox": [0.1, 0.1]},   # bbox 길이 틀림
        {"bbox": TABLE_BOX},                        # page_number 없음
    ]
    assert group_bboxes_by_page(payloads) == {2: [TABLE_BOX, OTHER_BOX]}


def test_single_doc_id():
    assert single_doc_id([{"doc_id": "d1"}, {"doc_id": "d1"}]) == "d1"
    assert single_doc_id([]) is None
    with pytest.raises(ValueError):
        single_doc_id([{"doc_id": "d1"}, {"doc_id": "d2"}])


def test_plan_counts_only_new_candidates_toward_cap():
    candidates = {
        2: [TABLE_CANDIDATE, OTHER_BOX],   # 1개는 기존, 1개는 새 것
        7: [TABLE_BOX],                     # 새 페이지
        9: [TABLE_BOX, OTHER_BOX],          # 새 페이지, 상한에 걸림
    }
    existing = {2: [TABLE_BOX]}
    plan = plan_new_candidates(candidates, existing, max_elements=3)
    assert plan["new_pages"] == [2, 7, 9]
    assert plan["over_cap_pages"] == [9]
    assert plan["skipped_existing"] == 1


def test_doc_overrides_keep_corrected_metadata():
    payload = {
        "doc_title": "한국타이어 리포트", "doc_type": "REPORT", "source_org": "메리츠증권",
        "publish_date": "2026-11-09", "authors": ["홍길동"], "domain": None,
        "extra_metadata": {"target": "한국타이어앤테크놀로지", "ticker": "161390", "industry": None},
    }
    assert doc_overrides_from_payload(payload) == {
        "doc_title": "한국타이어 리포트", "doc_type": "REPORT", "source_org": "메리츠증권",
        "publish_date": "2026-11-09", "target": "한국타이어앤테크놀로지", "ticker": "161390",
        "analyst": "홍길동",
    }
