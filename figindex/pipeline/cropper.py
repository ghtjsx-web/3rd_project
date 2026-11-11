import os
import uuid
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import fitz  # PyMuPDF
from PIL import Image


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
        crops_dir: Optional[Path] = None
    ):
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
                round(y0_pad / img_h, 4),
                round(x0_pad / img_w, 4),
                round(y1_pad / img_h, 4),
                round(x1_pad / img_w, 4)
            ],
            "text_layer_info": text_layer_info
        }

