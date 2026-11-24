import os
import uuid
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import fitz  # PyMuPDF
from PIL import Image
from shared.coords import px_to_norm, pt_to_norm, union_bbox, clip_bbox, to_legacy_yxyx
from shared.schemas import ElementType

try:
    from detection_gt import yolo_boxes_to_elements
except ImportError:
    from pipeline.detection_gt import yolo_boxes_to_elements

# 크롭 방식 (11-24 결정: YOLO 채택. crop_recall 0.361 → 0.951, 10쪽 14.7초)
CROP_METHOD_YOLO = "yolo"
CROP_METHOD_RULE = "rule"
DEFAULT_CROP_METHOD = CROP_METHOD_YOLO
# DocLayout-YOLO 체크포인트 (yolo_trial.py·make_detection_drafts.py·eval_crops.py와 같은 것)
YOLO_REPO = "juliozhao/DocLayout-YOLO-DocStructBench"
YOLO_FILE = "doclayout_yolo_docstructbench_imgsz1024.pt"
YOLO_IMGSZ = 1024
DEFAULT_YOLO_CONF = 0.25  # eval_crops.py 기본값과 같게

# 논문식 캡션 "Fig. 1." — 그림 아래에 붙는다. 블록 맨 앞에서만 인정해 본문 속 "(Fig. 4(a)…)" 언급은 거른다 (0.1.3)
FIG_ABBREV_CAPTION = re.compile(r"^\s*Fig\.\s*\d+[\.\:]", re.IGNORECASE)
# 그림 아래 캡션 위쪽에서 그림으로 볼 이미지: 페이지 면적의 0.5% 이상, 캡션과의 간격 페이지 높이 5% 이내
FIG_MIN_IMAGE_AREA_RATIO = 0.005
FIG_MAX_GAP_RATIO = 0.05
# 여러 칸짜리 그림((a)(b)(c))은 서로 이 간격(페이지 높이 3%) 안에 쌓인 이미지까지 한 그림으로 묶는다
FIG_STACK_GAP_RATIO = 0.03


class BBoxHelper:
    """Bounding Box helper for PDF point and normalized coordinates manipulation."""
    @staticmethod
    def merge_boxes(boxes: List[Tuple[float, float, float, float]]) -> Tuple[float, float, float, float]:
        """Merge a list of [ymin, xmin, ymax, xmax] boxes into a single bounding box."""
        if not boxes:
            return (0.0, 0.0, 0.0, 0.0)
        ymins, xmins, ymaxs, xmaxs = zip(*boxes)
        return (min(ymins), min(xmins), max(ymaxs), max(xmaxs))

    @staticmethod
    def compute_iou(box1: Tuple[float, float, float, float], box2: Tuple[float, float, float, float]) -> float:
        """Compute Intersection over Union between two normalized [ymin, xmin, ymax, xmax] boxes."""
        y1_min, x1_min, y1_max, x1_max = box1
        y2_min, x2_min, y2_max, x2_max = box2

        inter_ymin = max(y1_min, y2_min)
        inter_xmin = max(x1_min, x2_min)
        inter_ymax = min(y1_max, y2_max)
        inter_xmax = min(x1_max, x2_max)

        inter_w = max(0.0, inter_xmax - inter_xmin)
        inter_h = max(0.0, inter_ymax - inter_ymin)
        inter_area = inter_w * inter_h

        area1 = max(0.0, (x1_max - x1_min) * (y1_max - y1_min))
        area2 = max(0.0, (x2_max - x2_min) * (y2_max - y2_min))
        union_area = area1 + area2 - inter_area
        return inter_area / union_area if union_area > 0 else 0.0


class PDFCropper:
    def __init__(
        self,
        padding_pt_vert: float = 10.0,
        padding_pt_horiz: float = 5.0,
        padding_ratio_h: float = 0.015,
        dpi: int = 200,
        crops_dir: Optional[Path] = None,
        crop_method: Optional[str] = None,
    ):
        # 크롭 방식: 인자 > 환경변수 CROP_METHOD > 기본값(yolo). YOLO를 못 불러오면 규칙 방식으로 돌아간다.
        method = (crop_method or os.getenv("CROP_METHOD", DEFAULT_CROP_METHOD)).strip().lower()
        self.crop_method = method if method in (CROP_METHOD_YOLO, CROP_METHOD_RULE) else DEFAULT_CROP_METHOD
        self.yolo_conf = float(os.getenv("YOLO_CONF", DEFAULT_YOLO_CONF))
        self._yolo_model = None
        self._yolo_load_failed = False
        self.padding_pt_vert = padding_pt_vert
        self.padding_pt_horiz = padding_pt_horiz
        self.padding_ratio_h = padding_ratio_h
        self.dpi = dpi
        self.zoom = dpi / 72.0  # 72 points per inch standard
        self.crops_dir = Path(crops_dir or os.getenv("CROPS_DIR", "/data/crops"))
        self.crops_dir.mkdir(parents=True, exist_ok=True)

    def render_page(self, doc: fitz.Document, page_num: int) -> Image.Image:
        """Render a specific PDF page (1-based) to PIL Image with target DPI."""
        page = doc[page_num - 1]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    def extract_text_layer_in_bbox(
        self,
        page: fitz.Page,
        bbox_norm: Tuple[float, float, float, float]
    ) -> Dict[str, Any]:
        """Extract vector text and check if text layer exists inside normalized bbox [ymin, xmin, ymax, xmax]."""
        rect = page.rect
        ymin, xmin, ymax, xmax = bbox_norm
        fitz_rect = fitz.Rect(
            xmin * rect.width,
            ymin * rect.height,
            xmax * rect.width,
            ymax * rect.height
        )
        extracted_text = page.get_text("text", clip=fitz_rect).strip()
        return {
            "has_vector_text": len(extracted_text) > 0,
            "text_content": extracted_text,
            "char_count": len(extracted_text)
        }

    # ------------------------------------------------------------------
    # YOLO 크롭 (11-24 결정, docs/roles/4_크롭.md 6단계)
    # ------------------------------------------------------------------
    def _get_yolo_model(self):
        """DocLayout-YOLO 모델을 처음 쓸 때 한 번만 불러온다. 실패하면 None (규칙 방식으로 대체)."""
        if self._yolo_model is not None or self._yolo_load_failed:
            return self._yolo_model
        try:
            from doclayout_yolo import YOLOv10
            from huggingface_hub import hf_hub_download

            self._yolo_model = YOLOv10(hf_hub_download(repo_id=YOLO_REPO, filename=YOLO_FILE))
        except Exception as exc:  # 패키지 없음·내려받기 실패 등
            self._yolo_load_failed = True
            print(f"    [크롭] YOLO를 불러오지 못해 규칙 방식으로 크롭합니다: {exc}")
        return self._yolo_model

    @property
    def active_crop_method(self) -> str:
        """실제로 쓰는 크롭 방식 (YOLO를 못 불러왔으면 rule)."""
        if self.crop_method == CROP_METHOD_YOLO and self._get_yolo_model() is not None:
            return CROP_METHOD_YOLO
        return CROP_METHOD_RULE

    def detect_yolo_candidates(self, page_img: Image.Image) -> List[Dict[str, Any]]:
        """YOLO 탐지 → 캡션·각주 병합(MERGE_CLASSES) → crop_and_save가 받는 후보 형식.

        반환: [{'bbox': (ymin, xmin, ymax, xmax), 'hint_type': 'TABLE'|'CHART', 'caption': '', 'detection_score': float}]
        figure는 CHART/DIAGRAM을 모델이 구분하지 못해 CHART로 넘기고, 유형은 Vision LLM이 정한다(LAYOUT_TO_ELEMENT).
        """
        model = self._get_yolo_model()
        if model is None:
            return []
        result = model.predict(page_img, imgsz=YOLO_IMGSZ, conf=self.yolo_conf, device="cpu", verbose=False)[0]
        width_px, height_px = page_img.size
        detections = []
        if result.boxes is not None:
            for xyxy, cls_id, score in zip(
                result.boxes.xyxy.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist()
            ):
                layout_class = str(model.names.get(int(cls_id), ""))
                detections.append((layout_class, clip_bbox(px_to_norm(xyxy, width_px, height_px)), score))
        candidates: List[Dict[str, Any]] = []
        for element in yolo_boxes_to_elements(detections):
            candidates.append({
                "bbox": tuple(to_legacy_yxyx(element["bbox"])),
                "hint_type": element["element_type"],
                "caption": "",
                "detection_score": round(element.get("detection_score", 0.0), 4),
            })
        candidates.sort(key=lambda c: (c["bbox"][0], c["bbox"][1]))  # 위→아래, 왼→오른
        return candidates

    def detect_page_candidates(
        self, doc: fitz.Document, page_num: int
    ) -> Tuple[List[Dict[str, Any]], Optional[Image.Image]]:
        """설정한 크롭 방식으로 한 페이지의 후보를 찾는다. (후보, 렌더링한 페이지 그림 또는 None)

        YOLO는 페이지 그림이 필요하므로 렌더링한 그림을 함께 돌려준다 (crop_and_save에 그대로 넘겨 다시 그리지 않게).
        """
        if self.active_crop_method == CROP_METHOD_YOLO:
            page_img = self.render_page(doc, page_num)
            return self.detect_yolo_candidates(page_img), page_img
        return self.detect_candidate_boxes(doc[page_num - 1]), None

    def detect_candidate_boxes(self, page: fitz.Page) -> List[Dict[str, Any]]:
        """
        Detect visual elements (tables, charts, diagrams) on a single page.
        Returns a list of dicts: {'bbox': (ymin, xmin, ymax, xmax), 'hint_type': 'TABLE'|'CHART', 'caption': str}
        """
        rect = page.rect
        pw, ph = rect.width, rect.height
        candidates: List[Dict[str, Any]] = []

        # 1. Detect Tables using PyMuPDF table finder
        try:
            tables = page.find_tables().tables
        except Exception:
            tables = []

        for t in tables:
            x0, y0, x1, y1 = t.bbox
            tw = x1 - x0
            th = y1 - y0
            # Filter out header/footer tiny elements
            if tw < 100 or th < 35 or y0 < 40 or y1 > ph - 30:
                continue

            # Look for table caption right above table (within 35pt)
            cap_rect = fitz.Rect(max(0, x0 - 20), max(0, y0 - 35), min(pw, x1 + 20), y0 + 5)
            cap_text = page.get_text("text", clip=cap_rect).strip()
            
            # Expand bbox to include caption if present
            if cap_text:
                y0_eff = max(0, y0 - 25)
            else:
                y0_eff = y0

            norm_box = (y0_eff / ph, x0 / pw, y1 / ph, x1 / pw)
            candidates.append({
                "bbox": norm_box,
                "hint_type": "TABLE",
                "caption": cap_text.split("\n")[0] if cap_text else ""
            })

        # 2. Detect Charts / Figures via captions and drawings
        blocks = page.get_text("blocks")
        chart_pattern = re.compile(r"\[?(?:그림|도표|Chart|Figure)\s*[\d]+\]?[\.\:\s]", re.IGNORECASE)

        for b in blocks:
            bx0, by0, bx1, by1, btext = b[:5]
            clean_text = btext.strip()
            match = chart_pattern.search(clean_text)
            if not match and FIG_ABBREV_CAPTION.match(clean_text) and by0 > 50:
                # 논문식 "Fig. N." 캡션: 그림은 캡션 위에 있다. 위쪽 이미지를 묶어 후보로 만든다 (0.1.3)
                fig_box = self._figure_box_above_caption(page, (bx0, by0, bx1, by1))
                if fig_box is not None:
                    candidates.append({
                        "bbox": fig_box,
                        "hint_type": ElementType.CHART.value,
                        "caption": clean_text.split("\n")[0].strip(),
                    })
                continue
            if match and by0 > 50 and by1 < ph - 60:
                caption_line = clean_text.split("\n")[0].strip()

                # Search for drawings or image content around caption
                # Typically chart graphics are located right below or right above caption
                chart_y0 = by0
                chart_y1 = min(ph - 40, by1 + 180.0)  # Standard chart height ~180pt
                chart_x0 = max(40.0, bx0 - 15.0)
                chart_x1 = min(pw - 40.0, max(bx1 + 150.0, bx0 + 240.0))

                norm_box = (chart_y0 / ph, chart_x0 / pw, chart_y1 / ph, chart_x1 / pw)

                # Check overlap with existing table candidates
                overlaps = False
                for c in candidates:
                    if BBoxHelper.compute_iou(norm_box, c["bbox"]) > 0.4:
                        overlaps = True
                        break

                if not overlaps:
                    candidates.append({
                        "bbox": norm_box,
                        "hint_type": "CHART",
                        "caption": caption_line
                    })

        # Filter duplicates / high overlap within candidates
        filtered: List[Dict[str, Any]] = []
        for cand in candidates:
            is_dup = False
            for f in filtered:
                if BBoxHelper.compute_iou(cand["bbox"], f["bbox"]) > 0.6:
                    is_dup = True
                    break
            if not is_dup:
                # 3. [추가 규칙] 출처·주석 줄 합치기 (본 박스 바로 아래 3% 이내 출처/주석 포함)
                cand["bbox"] = self._expand_box_with_source_notes(page, cand["bbox"])
                filtered.append(cand)

        return filtered

    @staticmethod
    def _figure_box_above_caption(
        page: fitz.Page,
        caption_rect_pt: Tuple[float, float, float, float],
    ) -> Optional[Tuple[float, float, float, float]]:
        """캡션 바로 위에 붙은 이미지(여러 칸이면 쌓인 이미지 전부)와 캡션을 감싸는 박스.

        반환은 이 파일의 후보 형식인 (ymin, xmin, ymax, xmax) 정규화 값. 위쪽에 이미지가 없으면 None.
        """
        pw, ph = page.rect.width, page.rect.height
        if pw <= 0 or ph <= 0:
            return None
        cx0, cy0, cx1, cy1 = caption_rect_pt
        min_area = pw * ph * FIG_MIN_IMAGE_AREA_RATIO

        images = []
        for info in page.get_image_info():
            r = fitz.Rect(info.get("bbox", (0, 0, 0, 0)))
            if r.is_empty or r.width * r.height < min_area:
                continue
            # 캡션보다 위에 끝나고(2pt 겹침 허용) 가로로 캡션과 겹치는 이미지만
            if r.y1 > cy0 + 2.0 or r.x1 < cx0 - 20.0 or r.x0 > cx1 + 20.0:
                continue
            images.append(r)
        if not images:
            return None

        # 캡션에 가장 가까운(아래쪽 끝이 가장 낮은) 이미지에서 시작
        images.sort(key=lambda r: r.y1, reverse=True)
        nearest = images[0]
        if cy0 - nearest.y1 > ph * FIG_MAX_GAP_RATIO:
            return None
        group = [nearest]
        top = nearest.y0
        # 위로 쌓인 이미지((a)(b)(c) 칸)를 차례로 묶는다
        changed = True
        while changed:
            changed = False
            for r in images:
                if r in group:
                    continue
                if r.y1 >= top - ph * FIG_STACK_GAP_RATIO:
                    group.append(r)
                    top = min(top, r.y0)
                    changed = True

        boxes = [pt_to_norm(tuple(r), pw, ph) for r in group]
        boxes.append(pt_to_norm(caption_rect_pt, pw, ph))
        x0, y0, x1, y1 = union_bbox(boxes)
        return (y0, x0, y1, x1)

    @staticmethod
    def _horizontal_overlap_ratio(box_x0: float, box_x1: float, line_x0: float, line_x1: float) -> float:
        """텍스트 줄 너비(또는 박스 너비) 대비 본 박스와 가로로 겹치는 비율(0~1)을 계산합니다."""
        inter = max(0.0, min(box_x1, line_x1) - max(box_x0, line_x0))
        line_w = max(line_x1 - line_x0, 1e-6)
        box_w = max(box_x1 - box_x0, 1e-6)
        # 줄 너비 기준 겹침과 박스 너비 기준 겹침 중 큰 값 사용 (짧은 '자료:' 줄도 50% 이상 겹침 판정)
        return max(inter / line_w, inter / box_w)

    def _expand_box_with_source_notes(
        self,
        page: fitz.Page,
        norm_box: Tuple[float, float, float, float],
    ) -> Tuple[float, float, float, float]:
        """
        본 박스 바로 아래(페이지 높이 3% 이내)에서 page.get_text("dict")로 텍스트 줄을 읽어
        본 박스와 가로로 50% 이상 겹치고 "자료", "주:", "주)", "Source" 로 시작하는 줄과
        이어지는 주석 줄까지 박스에 포함시킵니다.
        """
        rect = page.rect
        pw, ph = rect.width, rect.height
        if pw <= 0 or ph <= 0:
            return norm_box

        ymin, xmin, ymax, xmax = norm_box
        bx0, by0, bx1, by1 = xmin * pw, ymin * ph, xmax * pw, ymax * ph

        # page.get_text("dict")에서 모든 텍스트 줄 추출
        text_dict = page.get_text("dict")
        lines = []
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                line_text = "".join(s.get("text", "") for s in spans).strip()
                lx0, ly0, lx1, ly1 = line.get("bbox", (0, 0, 0, 0))
                lines.append({
                    "x0": lx0,
                    "y0": ly0,
                    "x1": lx1,
                    "y1": ly1,
                    "text": line_text,
                })

        # 위에서 아래 순서로 정렬
        lines.sort(key=lambda l: (l["y0"], l["x0"]))

        source_prefix_re = re.compile(r"^(?:자료|주\s*:|주\s*\)|Source\b)", re.IGNORECASE)
        max_gap = ph * 0.03  # 페이지 높이 3% 이내

        found_note = False
        cur_y1 = by1
        cur_x0, cur_x1 = bx0, bx1
        prev_line_h = 12.0

        for line in lines:
            lx0, ly0, lx1, ly1, ltext = line["x0"], line["y0"], line["x1"], line["y1"], line["text"]

            # 본 박스보다 위쪽에 있는 줄은 건너뜀 (미세한 2pt 겹침은 허용)
            if ly0 < by1 - 2.0:
                continue

            overlap_ratio = self._horizontal_overlap_ratio(bx0, xmax * pw, lx0, lx1)

            if not found_note:
                # 아직 시작 줄을 못 찾은 경우: 본 박스 바로 아래 3% 이내 + 가로 50% 이상 겹침 + 출처/주석 접두어
                if ly0 - by1 > max_gap:
                    break
                if not ltext or overlap_ratio < 0.5:
                    continue
                if source_prefix_re.match(ltext):
                    found_note = True
                    cur_y1 = max(cur_y1, ly1)
                    cur_x0 = min(cur_x0, lx0)
                    cur_x1 = max(cur_x1, lx1)
                    prev_line_h = max(ly1 - ly0, 8.0)
            else:
                # 이미 출처/주석 줄이 시작된 뒤 이어지는 줄 검사
                # 1) 빈 줄이면 멈춤
                if not ltext:
                    break
                # 2) 직전 줄과의 세로 간격이 줄 높이의 1.2배(또는 페이지 1.5%)를 초과하면 새 문단/빈 줄로 보고 멈춤
                gap = ly0 - cur_y1
                if gap > max(prev_line_h * 1.2, ph * 0.015):
                    break
                # 3) 가로로 본 박스와 50% 이상 겹치지 않으면 멈춤
                if overlap_ratio < 0.5:
                    break
                # 4) 다음 본문/제목 패턴(예: 숫자 목차나 대제목 등)으로 보이지 않는 연속 줄이면 포함
                cur_y1 = max(cur_y1, ly1)
                cur_x0 = min(cur_x0, lx0)
                cur_x1 = max(cur_x1, lx1)
                prev_line_h = max(ly1 - ly0, 8.0)

        if not found_note:
            return norm_box

        return (
            ymin,
            max(0.0, cur_x0 / pw),
            min(1.0, cur_y1 / ph),
            min(1.0, cur_x1 / pw),
        )

    def crop_and_save(
        self,
        doc: fitz.Document,
        doc_path: Path,
        page_num: int,
        candidate: Dict[str, Any],
        page_img: Optional[Image.Image] = None
    ) -> Dict[str, Any]:
        """
        Crop candidate visual element from PDF page with PDF point & ratio-based padding (C-3).
        """
        page = doc[page_num - 1]
        if page_img is None:
            page_img = self.render_page(doc, page_num)

        bbox = candidate["bbox"]
        text_layer_info = self.extract_text_layer_in_bbox(page, bbox)

        img_w, img_h = page_img.size
        ymin, xmin, ymax, xmax = bbox

        # Base pixel coordinates
        x0 = int(xmin * img_w)
        y0 = int(ymin * img_h)
        x1 = int(xmax * img_w)
        y1 = int(ymax * img_h)

        # Padding in pixels based on zoom ratio and relative height ratio (C-3)
        pad_x_px = int(max(self.padding_pt_horiz * self.zoom, img_w * 0.008))
        pad_y_px = int(max(self.padding_pt_vert * self.zoom, img_h * self.padding_ratio_h))

        x0_pad = max(0, x0 - pad_x_px)
        y0_pad = max(0, y0 - pad_y_px)
        x1_pad = min(img_w, x1 + pad_x_px)
        y1_pad = min(img_h, y1 + pad_y_px)

        cropped = page_img.crop((x0_pad, y0_pad, x1_pad, y1_pad))

        element_id = f"fig-{uuid.uuid4().hex[:12]}"
        crop_filename = f"{element_id}_p{page_num}.png"
        crop_file_path = self.crops_dir / crop_filename
        cropped.save(str(crop_file_path), format="PNG", optimize=True)

        return {
            "element_id": element_id,
            "crop_path": crop_file_path,
            "relative_path": f"/static/crops/{crop_filename}",
            "hint_type": candidate.get("hint_type", "TABLE"),
            "caption_hint": candidate.get("caption", ""),
            "pixel_box": (x0_pad, y0_pad, x1_pad, y1_pad),
            "normalized_box": [
                round(v, 4) for v in px_to_norm([x0_pad, y0_pad, x1_pad, y1_pad], img_w, img_h)
            ],
            "text_layer_info": text_layer_info
        }

