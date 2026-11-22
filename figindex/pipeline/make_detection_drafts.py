"""
탐지 정답셋 초안 만들기 (팀원4 4단계, docs/roles/4_크롭.md).

사람이 처음부터 네모를 그리지 않도록, 페이지마다 후보 박스를 그린 그림과 JSON 초안을 만든다.
사람은 그림을 보고 JSON에서 틀린 것만 고친 뒤 "reviewed": true로 바꾼다.

공정성 (중요)
- 초안 박스는 지금 방식(cropper.py 규칙)과 YOLO 결과를 **합친 것**이다. 같은 요소면 두 박스를 감싸는 박스로 합친다.
- 그림과 JSON에는 어느 방식에서 나온 박스인지 표시하지 않는다. 한쪽 결과로만 초안을 만들면
  사람이 그 박스를 대체로 그대로 두기 때문에 그 방식의 crop_recall이 부풀려진다.
- 페이지도 두 방식 중 하나라도 후보가 있는 페이지에서 고른다 (한쪽 방식만 찾은 페이지도 들어감).

결과 (figindex/data/gt/detection/)
- {doc_name}_p{page_number}.json : 초안. 이미 있으면 덮어쓰지 않는다 (사람이 고친 내용 보호).
- _images/{doc_name}_p{page_number}.png : 번호가 붙은 박스 그림 (JSON elements 순서와 같은 번호)

실행 (figindex 폴더)
    # 자동으로 50페이지 고르기 (서로 다른 PDF 15개, 문서 종류 골고루)
    docker compose --profile index run --rm pipeline python make_detection_drafts.py --pick 50
    # 페이지 직접 지정
    docker compose --profile index run --rm pipeline python make_detection_drafts.py \\
        --page RPT_20261109_한화엔진_iM증권.pdf:2 --page 논문_2026_스마트농업_AgriExtension.pdf:11
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

from cropper import PDFCropper
from detection_gt import choose_docs, combine_drafts, gt_file_name, pick_pages, yolo_boxes_to_elements
from pdf_text import is_toc_page
from shared.coords import clip_bbox, from_legacy_yxyx, norm_to_px, px_to_norm
from shared.schemas import ElementType

YOLO_REPO = "juliozhao/DocLayout-YOLO-DocStructBench"           # yolo_trial.py와 같은 체크포인트
YOLO_FILE = "doclayout_yolo_docstructbench_imgsz1024.pt"
BOX_COLOR = (220, 38, 38)
GRID_COLOR = (148, 163, 184)
GRID_STEP = 0.1  # 박스를 고치거나 추가할 때 좌표를 읽기 쉽게 0.1 간격 눈금


def load_yolo():
    from doclayout_yolo import YOLOv10
    from huggingface_hub import hf_hub_download

    return YOLOv10(hf_hub_download(repo_id=YOLO_REPO, filename=YOLO_FILE))


def yolo_elements(model, page_img: Image.Image, conf: float) -> List[Dict[str, Any]]:
    """YOLO 탐지 → 캡션·각주 병합한 요소 후보 [{element_type, bbox}]."""
    result = model.predict(page_img, imgsz=1024, conf=conf, device="cpu", verbose=False)[0]
    width_px, height_px = page_img.size
    detections: List[Tuple[str, List[float]]] = []
    if result.boxes is not None:
        for xyxy, cls_id in zip(result.boxes.xyxy.tolist(), result.boxes.cls.tolist()):
            layout_class = str(model.names.get(int(cls_id), ""))
            detections.append((layout_class, clip_bbox(px_to_norm(xyxy, width_px, height_px))))
    return yolo_boxes_to_elements(detections)


def rule_elements(cropper: PDFCropper, page) -> List[Dict[str, Any]]:
    """지금 방식(cropper.py 규칙) 후보 → [{element_type, bbox}]."""
    return [
        {"element_type": c.get("hint_type", ElementType.TABLE.value), "bbox": from_legacy_yxyx(c["bbox"])}
        for c in cropper.detect_candidate_boxes(page)
    ]


def draw_numbered(page_img: Image.Image, elements: List[Dict[str, Any]]) -> Image.Image:
    """번호 붙은 박스 + 0.1 간격 눈금 (눈금 숫자 = bbox 좌표값)."""
    img = page_img.copy()
    draw = ImageDraw.Draw(img)
    width_px, height_px = img.size
    steps = int(round(1 / GRID_STEP))
    for i in range(1, steps):
        value = round(i * GRID_STEP, 1)
        x = int(width_px * value)
        y = int(height_px * value)
        draw.line([(x, 0), (x, height_px)], fill=GRID_COLOR, width=1)
        draw.line([(0, y), (width_px, y)], fill=GRID_COLOR, width=1)
        draw.text((x + 3, 3), f"{value}", fill=GRID_COLOR)
        draw.text((3, y + 3), f"{value}", fill=GRID_COLOR)
    for number, element in enumerate(elements, start=1):
        x0, y0, x1, y1 = (int(v) for v in norm_to_px(element["bbox"], float(width_px), float(height_px)))
        draw.rectangle([x0, y0, x1, y1], outline=BOX_COLOR, width=4)
        label = f"{number} {element['element_type']}"
        draw.rectangle([x0, max(0, y0 - 24), x0 + 12 * len(label) + 10, y0], fill=BOX_COLOR)
        draw.text((x0 + 5, max(0, y0 - 21)), label, fill=(255, 255, 255))
    return img


def find_pdf(pdfs_dir: Path, doc_name: str) -> Path:
    target = unicodedata.normalize("NFC", doc_name)
    for path in pdfs_dir.rglob("*.pdf"):
        if unicodedata.normalize("NFC", path.name) == target:
            return path
    raise SystemExit(f"PDF를 찾지 못했습니다: {doc_name} ({pdfs_dir})")


def page_draft(doc, page_number: int, cropper: PDFCropper, model, conf: float) -> List[Dict[str, Any]]:
    page = doc[page_number - 1]
    page_img = cropper.render_page(doc, page_number)
    return combine_drafts(rule_elements(cropper, page), yolo_elements(model, page_img, conf))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="탐지 정답셋 초안 (지금 방식 + YOLO 합집합, 출처 숨김)")
    parser.add_argument("--pick", type=int, default=0, help="자동으로 고를 페이지 수 (예: 50)")
    parser.add_argument("--page", action="append", default=[], help="직접 지정: 파일명.pdf:페이지번호")
    parser.add_argument("--max-docs", type=int, default=15, help="자동 고르기: 문서 수 (역할 문서 10~15개)")
    parser.add_argument("--per-doc", type=int, default=4, help="자동 고르기: 문서당 최대 페이지")
    parser.add_argument("--scan-pages", type=int, default=40, help="자동 고르기: 문서마다 앞에서부터 살펴볼 페이지 수")
    parser.add_argument("--conf", type=float, default=0.25, help="YOLO 최소 detection_score (yolo_trial.py와 같음)")
    parser.add_argument("--pdfs-dir", default="/data/pdfs")
    parser.add_argument("--gt-dir", default="/data/gt/detection")
    args = parser.parse_args()
    if not args.pick and not args.page:
        raise SystemExit("--pick 50 또는 --page 파일명.pdf:페이지 를 지정해 주세요.")

    pdfs_dir, gt_dir = Path(args.pdfs_dir), Path(args.gt_dir)
    image_dir = gt_dir / "_images"
    image_dir.mkdir(parents=True, exist_ok=True)
    cropper = PDFCropper()
    print("YOLO 모델 불러오는 중 (/root/.cache)...")
    model = load_yolo()

    targets: List[Tuple[str, int]] = []
    for spec in args.page:
        doc_name, _, page_text = spec.rpartition(":")
        targets.append((unicodedata.normalize("NFC", doc_name), int(page_text)))

    drafts: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}  # 그림은 메모리에 쌓지 않고 쓸 때 다시 그린다
    if args.pick:
        all_docs = sorted({unicodedata.normalize("NFC", p.name) for p in pdfs_dir.rglob("*.pdf")})
        scan_docs = choose_docs(all_docs, args.max_docs + 5)  # 후보 없는 문서가 있을 수 있어 조금 더 살펴본다
        counts: List[Tuple[str, int, int]] = []
        for doc_name in scan_docs:
            with fitz.open(str(find_pdf(pdfs_dir, doc_name))) as doc:
                for page_number in range(1, min(len(doc), args.scan_pages) + 1):
                    if is_toc_page(doc[page_number - 1]):
                        continue
                    draft = page_draft(doc, page_number, cropper, model, args.conf)
                    counts.append((doc_name, page_number, len(draft)))
                    if draft:
                        drafts[(doc_name, page_number)] = draft
            print(f"  살펴봄: {doc_name}")
        targets += pick_pages(counts, total=args.pick, max_docs=args.max_docs, per_doc=args.per_doc)

    written, kept = 0, 0
    for doc_name, page_number in targets:
        json_path = gt_dir / gt_file_name(doc_name, page_number)
        if json_path.exists():
            kept += 1
            print(f"  그대로 둠 (이미 있음): {json_path.name}")
            continue
        with fitz.open(str(find_pdf(pdfs_dir, doc_name))) as doc:
            if (doc_name, page_number) not in drafts:
                drafts[(doc_name, page_number)] = page_draft(doc, page_number, cropper, model, args.conf)
            page_img = cropper.render_page(doc, page_number)
        draft = drafts[(doc_name, page_number)]
        draw_numbered(page_img, draft).save(image_dir / f"{doc_name}_p{page_number}.png")
        data = {"doc_name": doc_name, "page_number": page_number, "reviewed": False, "memo": "", "elements": draft}
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1
        print(f"  초안: {json_path.name} (박스 {len(draft)}개)")

    print(f"초안 {written}개 만듦, 기존 {kept}개 그대로 둠 → {gt_dir}")
    print("다음: _images 그림을 보고 JSON에서 틀린 박스만 고친 뒤 \"reviewed\": true 로 바꾸세요. "
          "다 끝나면 python eval_crops.py 로 두 방식의 crop_recall을 계산합니다.")


if __name__ == "__main__":
    main()
