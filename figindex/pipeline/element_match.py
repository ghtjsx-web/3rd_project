"""
이미 색인된 요소와 새로 찾은 후보 박스를 맞춰 보는 함수 모음 (결정 22: 재색인은 기존 요소 유지, 빠진 요소만 추가).

- PyMuPDF·Qdrant를 쓰지 않는 순수 함수라 Docker 밖에서도 테스트할 수 있다.
- 좌표 계산은 shared.coords 함수만 쓴다 (AGENTS.md 3절).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from shared.coords import iou, overlap_ratio

# 같은 요소로 보는 기준
# - IoU 0.5: 용어집 crop_recall과 같은 기준
# - 후보 넓이의 3/4 이상이 기존 박스 안: 저장 박스는 패딩이 붙어 후보보다 크므로 IoU만으로는 놓칠 수 있다
#   (같은 표면 보통 후보 전체가 저장 박스 안에 들어가 1.0이 나온다)
SAME_ELEMENT_IOU = 0.5
SAME_ELEMENT_INSIDE = 0.75

# 기존 payload에서 새 요소가 물려받을 문서 단위 값 (process_pdf의 doc_metadata 키 이름)
_DOC_LEVEL_KEYS = ("doc_title", "doc_type", "source_org", "publish_date")
_EXTRA_KEYS = ("target", "ticker", "analyst", "industry")


def matches_existing(
    bbox: Sequence[float],
    existing_bboxes: Iterable[Sequence[float]],
    iou_min: float = SAME_ELEMENT_IOU,
    inside_min: float = SAME_ELEMENT_INSIDE,
) -> bool:
    """후보 bbox([x0, y0, x1, y1])가 같은 페이지의 기존 요소 중 하나와 같은 요소로 보이면 True."""
    for old in existing_bboxes:
        if iou(bbox, old) >= iou_min or overlap_ratio(bbox, old) >= inside_min:
            return True
    return False


def group_bboxes_by_page(payloads: Iterable[Dict[str, Any]]) -> Dict[int, List[List[float]]]:
    """기존 요소 payload 목록 → {page_number: [bbox, ...]}. bbox나 page_number가 없는 payload는 건너뛴다."""
    by_page: Dict[int, List[List[float]]] = {}
    for p in payloads:
        page_number = p.get("page_number")
        bbox = p.get("bbox")
        if not isinstance(page_number, int) or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        by_page.setdefault(page_number, []).append([float(v) for v in bbox])
    return by_page


def single_doc_id(payloads: Iterable[Dict[str, Any]]) -> Optional[str]:
    """기존 요소들의 doc_id. 없으면 None, 두 개 이상이면 ValueError (문서가 섞인 상태라 멈춘다)."""
    doc_ids = {p.get("doc_id") for p in payloads if p.get("doc_id")}
    if len(doc_ids) > 1:
        raise ValueError(f"한 문서에 doc_id가 여러 개입니다: {sorted(doc_ids)}")
    return next(iter(doc_ids), None)


def doc_overrides_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """기존 요소 payload에서 문서 단위 값을 꺼내 process_pdf의 doc_metadata 덮어쓰기용 dict로 만든다.

    기존 요소의 메타데이터는 파일명·사전으로 보정된 값일 수 있으므로(fix_metadata_from_filename 등),
    새 요소도 같은 값을 물려받게 한다. 값이 없는 키는 넣지 않는다(새로 추출한 값을 그대로 둔다).
    """
    overrides: Dict[str, Any] = {}
    for key in _DOC_LEVEL_KEYS:
        if payload.get(key) not in (None, ""):
            overrides[key] = payload[key]
    extra = payload.get("extra_metadata") or {}
    for key in _EXTRA_KEYS:
        if extra.get(key) not in (None, ""):
            overrides[key] = extra[key]
    authors = payload.get("authors") or []
    if authors and "analyst" not in overrides:
        overrides["analyst"] = authors[0]
    return overrides


def plan_new_candidates(
    candidates_by_page: Dict[int, List[Sequence[float]]],
    existing_by_page: Dict[int, List[Sequence[float]]],
    max_elements: int,
) -> Dict[str, Any]:
    """페이지별 후보 박스 중 기존 요소와 겹치지 않는 새 후보를 페이지 순서대로 세고 상한을 적용한다.

    process_pdf와 같은 순서(앞 페이지부터, 페이지 안에서는 후보 순서)로 센다.
    반환:
        new_pages: 상한 안에서 처리될 새 후보의 페이지 번호 목록 (후보 하나당 하나, 순서대로)
        over_cap_pages: 상한 때문에 처리되지 않을 새 후보의 페이지 번호 목록
        skipped_existing: 기존 요소와 같아 건너뛸 후보 수
    """
    new_pages: List[int] = []
    over_cap_pages: List[int] = []
    skipped_existing = 0
    for page_number in sorted(candidates_by_page):
        old_boxes = existing_by_page.get(page_number, [])
        for bbox in candidates_by_page[page_number]:
            if matches_existing(bbox, old_boxes):
                skipped_existing += 1
            elif len(new_pages) < max_elements:
                new_pages.append(page_number)
            else:
                over_cap_pages.append(page_number)
    return {
        "new_pages": new_pages,
        "over_cap_pages": over_cap_pages,
        "skipped_existing": skipped_existing,
    }
