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
                filtered.append(cand)

        return filtered

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
