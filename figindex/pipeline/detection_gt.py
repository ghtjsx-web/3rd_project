"""
탐지 정답셋(data/gt/detection/)과 크롭 재현율(crop_recall) 계산용 순수 함수 (팀원4 4~5단계, 결정 30).

- PyMuPDF·YOLO 없이 테스트할 수 있게 계산만 모았다. 모델 실행은 make_detection_drafts.py, eval_crops.py.
- 좌표는 [x0, y0, x1, y1] 0~1 정규화, 계산은 shared.coords 함수만 쓴다.

정답 박스 기준 (사람이 고칠 때)
- 표·차트 본체에 제목(캡션), 단위, 하단 출처·주석 줄까지 포함한다. 크롭이 잘리지 않아야 하는 범위다.
- 사진·로고·장식·머리말은 넣지 않는다 (용어집 2절). 캡션 하나에 묶인 여러 차트는 1개.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from shared.coords import iou, overlap_ratio, pad_bbox_pt, union_bbox
from shared.schemas import LAYOUT_TO_ELEMENT, MERGE_CLASSES, ElementType, LayoutClass

CROP_RECALL_IOU = 0.5          # 용어집 12절
SAME_BOX_IOU = 0.5             # 두 방식이 같은 요소를 찾았다고 보는 기준 (초안 합치기)
CAPTION_MAX_GAP = 0.03         # 캡션·각주를 본 박스에 붙일 때 허용하는 세로 간격 (페이지 높이 비율)
CAPTION_MIN_X_OVERLAP = 0.5    # 캡션·각주 너비 중 본 박스와 가로로 겹쳐야 하는 비율
DUPLICATE_OVERLAP = 0.7        # 한 본 박스가 다른 본 박스에 이만큼 이상 들어가 있으면 같은 요소로 보고 합친다

# cropper.crop_and_save와 같은 패딩 (가로 max(5pt, 폭 0.8%), 세로 max(10pt, 높이 1.5%))
CROP_PAD_X_PT, CROP_PAD_X_RATIO = 5.0, 0.008
CROP_PAD_Y_PT, CROP_PAD_Y_RATIO = 10.0, 0.015

# YOLO figure는 CHART/DIAGRAM을 모델이 구분하지 못한다 (LAYOUT_TO_ELEMENT = None).
# 초안에는 CHART로 적고 사람이 DIAGRAM이면 고친다. crop_recall은 유형과 상관없이 위치만 본다.
FIGURE_DRAFT_TYPE = ElementType.CHART


def _x_overlap_of(small: Sequence[float], big: Sequence[float]) -> float:
    width = max(float(small[2]) - float(small[0]), 1e-9)
    inter = max(0.0, min(float(small[2]), float(big[2])) - max(float(small[0]), float(big[0])))
    return inter / width


def _vertical_gap(a: Sequence[float], b: Sequence[float]) -> float:
    """세로로 떨어진 거리 (겹치면 0)."""
    return max(0.0, max(float(a[1]), float(b[1])) - min(float(a[3]), float(b[3])))


def yolo_boxes_to_elements(
    detections: Iterable[Sequence[Any]],
) -> List[Dict[str, Any]]:
    """YOLO 탐지 [(layout_class 이름, bbox[, detection_score]), ...] → 요소 후보 [{element_type, bbox[, detection_score]}].

    - LAYOUT_TO_ELEMENT에 있는 클래스(table, figure)만 본 박스가 된다.
    - MERGE_CLASSES(캡션·각주)는 세로로 가깝고 가로로 겹치는 본 박스 하나에 병합한다 (Union BBox).
    - 나머지 클래스는 버린다.
    - 세 번째 값(detection_score)이 있으면 본 박스의 점수를 그대로 넘긴다 (캡션 점수는 쓰지 않음).
    """
    mains: List[Dict[str, Any]] = []
    merges: List[List[float]] = []
    for det in detections:
        layout_class, bbox = det[0], det[1]
        try:
            cls = LayoutClass(layout_class)
        except ValueError:
            continue
        if cls in LAYOUT_TO_ELEMENT:
            element_type = LAYOUT_TO_ELEMENT[cls] or FIGURE_DRAFT_TYPE
            main: Dict[str, Any] = {"element_type": element_type.value, "bbox": [float(v) for v in bbox]}
            if len(det) > 2 and det[2] is not None:
                main["detection_score"] = float(det[2])
            mains.append(main)
        elif cls in MERGE_CLASSES:
            merges.append([float(v) for v in bbox])

    for cap in merges:
        best, best_gap = None, None
        for m in mains:
            if _x_overlap_of(cap, m["bbox"]) < CAPTION_MIN_X_OVERLAP:
                continue
            gap = _vertical_gap(cap, m["bbox"])
            if gap <= CAPTION_MAX_GAP and (best_gap is None or gap < best_gap):
                best, best_gap = m, gap
        if best is not None:
            best["bbox"] = union_bbox([best["bbox"], cap])
    return merge_duplicate_mains(mains)


def merge_duplicate_mains(mains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 표·그림에 YOLO가 본 박스를 두 번 낸 경우 하나로 합친다 (11-24 시험 업로드에서 같은 표가 두 번 크롭됨).

    한 박스 넓이의 DUPLICATE_OVERLAP 이상이 다른 박스와 겹치면(겹침·포함) 같은 요소로 본다.
    박스는 둘을 감싸는 박스로, 유형과 detection_score는 점수가 높은 쪽을 쓴다.
    캡션 하나에 패널 여러 개인 그림을 요소 1개로 세는 규칙(용어집 2절)과도 맞는다.
    """
    ordered = sorted(mains, key=lambda m: m.get("detection_score", 0.0), reverse=True)
    kept: List[Dict[str, Any]] = []
    for cand in ordered:
        for k in kept:
            if (overlap_ratio(cand["bbox"], k["bbox"]) >= DUPLICATE_OVERLAP
                    or overlap_ratio(k["bbox"], cand["bbox"]) >= DUPLICATE_OVERLAP):
                k["bbox"] = union_bbox([k["bbox"], cand["bbox"]])
                break
        else:
            kept.append(dict(cand))
    kept.sort(key=lambda m: (m["bbox"][1], m["bbox"][0]))  # 위→아래, 왼→오른
    return kept


def combine_drafts(*box_lists: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """여러 방식의 후보를 하나의 초안으로 합친다 (어느 방식에서 왔는지는 남기지 않는다).

    - 이미 담은 박스와 IoU ≥ 0.5이면 같은 요소로 보고 두 박스를 감싸는 박스로 합친다.
      한쪽 방식의 박스를 그대로 정답으로 쓰면 그 방식의 crop_recall이 부풀기 때문이다.
    - 유형이 다르면 TABLE을 남긴다 (사람이 확인).
    - 위에서 아래, 왼쪽에서 오른쪽 순서로 정렬해 번호가 출처를 드러내지 않게 한다.
    """
    merged: List[Dict[str, Any]] = []
    for boxes in box_lists:
        for item in boxes:
            bbox = [float(v) for v in item["bbox"]]
            for m in merged:
                if iou(bbox, m["bbox"]) >= SAME_BOX_IOU:
                    m["bbox"] = union_bbox([m["bbox"], bbox])
                    if item["element_type"] == ElementType.TABLE.value:
                        m["element_type"] = ElementType.TABLE.value
                    break
            else:
                merged.append({"element_type": item["element_type"], "bbox": bbox})
    merged.sort(key=lambda m: (round(m["bbox"][1], 3), round(m["bbox"][0], 3)))
    return [{"element_type": m["element_type"], "bbox": [round(v, 4) for v in m["bbox"]]} for m in merged]


def matched_gt_count(gt_bboxes: Sequence[Sequence[float]], pred_bboxes: Sequence[Sequence[float]]) -> int:
    """정답 박스 중 IoU ≥ 0.5인 예측 박스가 하나라도 있는 정답 수 (용어집 12절 crop_recall의 분자)."""
    return sum(1 for g in gt_bboxes if any(iou(g, p) >= CROP_RECALL_IOU for p in pred_bboxes))


def crop_recall(
    gt_by_page: Dict[Any, Sequence[Sequence[float]]],
    pred_by_page: Dict[Any, Sequence[Sequence[float]]],
) -> Optional[float]:
    """crop_recall = 맞춘 정답 수 ÷ 정답 요소 수. 정답 요소가 0개면 None."""
    total = sum(len(v) for v in gt_by_page.values())
    if total == 0:
        return None
    hit = sum(matched_gt_count(gt, pred_by_page.get(key, [])) for key, gt in gt_by_page.items())
    return hit / total


def padded_like_cropper(bbox: Sequence[float], width_pt: float, height_pt: float) -> List[float]:
    """후보 박스에 cropper.crop_and_save와 같은 패딩을 붙여 실제 크롭 영역으로 만든다 (두 방식에 똑같이 적용)."""
    pad_x = max(CROP_PAD_X_PT, width_pt * CROP_PAD_X_RATIO)
    pad_y = max(CROP_PAD_Y_PT, height_pt * CROP_PAD_Y_RATIO)
    return pad_bbox_pt(bbox, pad_x, pad_y, width_pt, height_pt)


def choose_docs(doc_names: Sequence[str], count: int) -> List[str]:
    """문서 종류(파일명 앞부분)를 돌아가며 count개 문서를 고른다. 같은 입력이면 항상 같은 결과."""
    kinds: Dict[str, List[str]] = {}
    for doc_name in sorted(doc_names):
        kinds.setdefault(_doc_kind(doc_name), []).append(doc_name)
    chosen: List[str] = []
    depth = 0
    while len(chosen) < count and any(depth < len(v) for v in kinds.values()):
        for kind in sorted(kinds):
            if depth < len(kinds[kind]) and len(chosen) < count:
                chosen.append(kinds[kind][depth])
        depth += 1
    return chosen


def _doc_kind(doc_name: str) -> str:
    head = doc_name.split("_")[0]
    for prefix in ("통계보도자료", "보도자료", "보고서", "리포트", "논문"):
        if head.startswith(prefix):
            return prefix
    return head


def parse_page_spec(spec: str) -> Tuple[str, int]:
    """'파일명.pdf:쪽' → (doc_name NFC, page_number). 쪽 번호는 PDF 뷰어 기준(1부터)."""
    doc_name, sep, page_text = spec.strip().rpartition(":")
    if not sep or not doc_name or not page_text.strip().isdigit() or int(page_text) < 1:
        raise ValueError(f"'파일명.pdf:쪽' 형식이 아닙니다: {spec!r}")
    return unicodedata.normalize("NFC", doc_name.strip()), int(page_text)


def read_page_list(path: Path) -> List[Tuple[str, int]]:
    """한 줄에 '파일명.pdf:쪽' 하나. 빈 줄과 '#' 뒤 설명은 무시한다 (예: data/gt/crop_cut_cases.txt)."""
    pages: List[Tuple[str, int]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            pages.append(parse_page_spec(line))
    return pages


def group_pages_by_doc(pages: Iterable[Tuple[str, int]]) -> Dict[str, List[int]]:
    """[(doc_name, page_number), ...] → {doc_name: [page_number 오름차순, 중복 제거]} (입력 문서 순서 유지)."""
    grouped: Dict[str, List[int]] = {}
    for doc_name, page_number in pages:
        grouped.setdefault(doc_name, [])
        if page_number not in grouped[doc_name]:
            grouped[doc_name].append(page_number)
    return {doc_name: sorted(nums) for doc_name, nums in grouped.items()}


def gt_file_name(doc_name: str, page_number: int) -> str:
    """정답 파일 이름: {doc_name}_p{page_number}.json (역할 문서 4단계)."""
    return f"{doc_name}_p{page_number}.json"


def load_gt_files(gt_dir: Path, include_unreviewed: bool = False) -> List[Dict[str, Any]]:
    """정답 JSON 목록. 기본은 사람이 확인을 끝낸("reviewed": true) 파일만."""
    files = []
    for path in sorted(Path(gt_dir).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not include_unreviewed and data.get("reviewed") is not True:
            continue
        files.append(data)
    return files


def pick_pages(
    pages: Sequence[Tuple[str, int, int]],
    total: int,
    max_docs: int = 15,
    per_doc: int = 4,
) -> List[Tuple[str, int]]:
    """정답셋에 넣을 페이지 고르기 (역할 문서: 서로 다른 PDF 10~15개에서 50페이지).

    입력 pages: [(doc_name, page_number, 후보 박스 수), ...]
    1) 문서 종류(파일명 앞부분: RPT, 논문, 보고서 …)를 돌아가며 문서를 max_docs개까지 고른다.
    2) 고른 문서를 돌아가며 페이지를 한 개씩 뽑는다. 문서마다 최대 per_doc 페이지, 후보가 많은 페이지부터.
    같은 입력이면 항상 같은 결과다 (무작위 없음).
    """
    by_doc: Dict[str, List[Tuple[int, int]]] = {}
    for doc_name, page_number, n_boxes in pages:
        if n_boxes > 0:
            by_doc.setdefault(doc_name, []).append((page_number, n_boxes))
    for doc_name in by_doc:
        by_doc[doc_name] = sorted(by_doc[doc_name], key=lambda x: (-x[1], x[0]))[:per_doc]

    kinds: Dict[str, List[str]] = {}
    for doc_name in sorted(by_doc, key=lambda d: (-len(by_doc[d]), d)):  # 페이지가 많은 문서부터
        kinds.setdefault(_doc_kind(doc_name), []).append(doc_name)

    chosen: List[str] = []
    depth = 0
    while len(chosen) < max_docs and any(depth < len(v) for v in kinds.values()):
        for kind in sorted(kinds):
            if depth < len(kinds[kind]) and len(chosen) < max_docs:
                chosen.append(kinds[kind][depth])
        depth += 1

    picked: List[Tuple[str, int]] = []
    for round_index in range(per_doc):
        for doc_name in chosen:
            if len(picked) >= total:
                return picked
            if round_index < len(by_doc[doc_name]):
                picked.append((doc_name, by_doc[doc_name][round_index][0]))
    return picked
