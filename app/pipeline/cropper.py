import uuid
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import fitz  # PyMuPDF
from PIL import Image

from app.core.config import settings


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
    def is_adjacent(
        box1: Tuple[float, float, float, float],
        box2: Tuple[float, float, float, float],
        vert_thresh_ratio: float = 0.05,
        horiz_overlap_ratio: float = 0.3
    ) -> bool:
        """
        Check if box2 (e.g., caption/footnote) is vertically adjacent to box1 (table/figure),
        and horizontally overlapping. Coordinates are [ymin, xmin, ymax, xmax].
        """
        y1_min, x1_min, y1_max, x1_max = box1
        y2_min, x2_min, y2_max, x2_max = box2

        # Horizontal overlap check
        overlap_xmin = max(x1_min, x2_min)
        overlap_xmax = min(x1_max, x2_max)
        if overlap_xmax <= overlap_xmin:
            return False
        
        horiz_overlap = (overlap_xmax - overlap_xmin) / min(x1_max - x1_min, x2_max - x2_min)
        if horiz_overlap < horiz_overlap_ratio:
            return False

        # Vertical distance check (above or below)
        vert_dist_above = abs(y1_min - y2_max)  # box2 is above box1
        vert_dist_below = abs(y2_min - y1_max)  # box2 is below box1
        return min(vert_dist_above, vert_dist_below) <= vert_thresh_ratio


class PDFCropper:
    def __init__(
        self,
        padding_pt_vert: float = settings.PADDING_PT_TOP_BOTTOM,
        padding_pt_horiz: float = settings.PADDING_PT_LEFT_RIGHT,
        padding_ratio_h: float = settings.PADDING_RATIO_HEIGHT,
        dpi: int = settings.RENDER_DPI
    ):
        self.padding_pt_vert = padding_pt_vert
        self.padding_pt_horiz = padding_pt_horiz
        self.padding_ratio_h = padding_ratio_h
        self.dpi = dpi
        self.zoom = dpi / 72.0  # 72 points per inch in PDF standard

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
        """
        Extract vector text and investigate whether a text layer exists inside the normalized BBox.
        Used for C-4 cross-validation with Vision LLM extracted numbers.
        """
        rect = page.rect
        ymin, xmin, ymax, xmax = bbox_norm
        fitz_rect = fitz.Rect(
            xmin * rect.width,
            ymin * rect.height,
            xmax * rect.width,
            ymax * rect.height
        )
        extracted_text = page.get_text("text", clip=fitz_rect).strip()
        has_vector_text = len(extracted_text) > 0
        return {
            "has_vector_text": has_vector_text,
            "text_content": extracted_text,
            "char_count": len(extracted_text)
        }

    def merge_caption_and_footnotes(
        self,
        main_boxes: List[Tuple[float, float, float, float]],
        auxiliary_boxes: List[Tuple[float, float, float, float]]
    ) -> List[Tuple[float, float, float, float]]:
        """
        Merge table_caption, figure_caption, table_footnote with adjacent main table/figure boxes (C-3).
        """
        merged_boxes = []
        for m_box in main_boxes:
            matched_aux = [m_box]
            for aux in auxiliary_boxes:
                if BBoxHelper.is_adjacent(m_box, aux, vert_thresh_ratio=self.padding_ratio_h * 3):
                    matched_aux.append(aux)
            merged_boxes.append(BBoxHelper.merge_boxes(matched_aux))
        return merged_boxes

    def crop_and_save(
        self,
        doc_path: Path,
        page_num: int,
        bbox: Tuple[float, float, float, float],
        output_dir: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Crop candidate visual element from PDF page with PDF point & ratio-based padding (C-3).
        """
        if output_dir is None:
            output_dir = settings.CROPS_DIR

        doc = fitz.open(str(doc_path))
        page = doc[page_num - 1]
        page_img = self.render_page(doc, page_num)
        text_layer_info = self.extract_text_layer_in_bbox(page, bbox)
        doc.close()

        img_w, img_h = page_img.size
        ymin, xmin, ymax, xmax = bbox

        # Base pixel coordinates
        x0 = int(xmin * img_w)
        y0 = int(ymin * img_h)
        x1 = int(xmax * img_w)
        y1 = int(ymax * img_h)

        # Calculate padding in pixels based on zoom ratio and relative height ratio
        pad_x_px = int(max(self.padding_pt_horiz * self.zoom, img_w * 0.008))
        pad_y_px = int(max(self.padding_pt_vert * self.zoom, img_h * self.padding_ratio_h))

        x0_pad = max(0, x0 - pad_x_px)
        y0_pad = max(0, y0 - pad_y_px)
        x1_pad = min(img_w, x1 + pad_x_px)
        y1_pad = min(img_h, y1 + pad_y_px)

        cropped = page_img.crop((x0_pad, y0_pad, x1_pad, y1_pad))

        element_id = f"fig-{uuid.uuid4().hex[:12]}"
        crop_filename = f"{element_id}_p{page_num}.png"
        crop_file_path = output_dir / crop_filename
        cropped.save(str(crop_file_path), format="PNG", optimize=True)

        return {
            "element_id": element_id,
            "crop_path": crop_file_path,
            "relative_path": f"/static/crops/{crop_filename}",
            "pixel_box": (x0_pad, y0_pad, x1_pad, y1_pad),
            "normalized_box": [
                y0_pad / img_h,
                x0_pad / img_w,
                y1_pad / img_h,
                x1_pad / img_w
            ],
            "text_layer_info": text_layer_info
        }
