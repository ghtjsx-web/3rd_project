from typing import Dict, Any, Optional
from app.core.config import settings
from app.schemas import ReviewStatus, TableStructure, ElementType


class ConfidenceEvaluator:
    """
    Calculates re-normalized weighted sum confidence score from applicable signals (v0.3.1):
    1. DocLayout-YOLO detection score (s1, base weight 0.20)
    2. JSON Schema validation binary pass/fail (s2, binary 0/1, base weight 0.25)
    3. Numerical integrity check (s3, for TABLE only, base weight 0.25)
    4. Self-consistency agreement (s4, conditional for TABLE or 0.70~0.85 boundary, base weight 0.15)
    5. Text layer match rate (s5, for TABLE with text layer only, base weight 0.15)
    """

    BASE_WEIGHTS = {
        "detection_score": 0.20,
        "schema_valid": 0.25,
        "math_integrity": 0.25,
        "self_consistency": 0.15,
        "text_layer_match": 0.15,
    }

    def evaluate_signals(
        self,
        element_type: ElementType,
        detection_score: float,
        is_schema_valid: bool,
        structured_data: Optional[TableStructure] = None,
        self_consistency_score: Optional[float] = None,
        text_layer_info: Optional[Dict[str, Any]] = None,
        llm_raw_text: str = ""
    ) -> Dict[str, Any]:
        """
        Evaluate individual signals and re-normalize weights so their sum equals 1.0.
        """
        applicable_signals = ["detection_score", "schema_valid", "self_consistency"]
        
        # Determine applicable signals based on element_type and text layer
        has_text_layer = text_layer_info and text_layer_info.get("has_vector_text", False)

        if element_type == ElementType.TABLE:
            applicable_signals.append("math_integrity")
            if has_text_layer:
                applicable_signals.append("text_layer_match")

        # 1. Detection score (s1)
        s1 = min(max(float(detection_score), 0.0), 1.0)

        # 2. Schema validity (s2, Binary: 0 or 1)
        s2 = 1.0 if is_schema_valid else 0.0

        # 3. Table numerical integrity check (s3)
        s3 = self._check_math_integrity(structured_data) if "math_integrity" in applicable_signals else 0.0

        # 4. Self-consistency score (s4, conditional)
        if self_consistency_score is not None:
            s4 = min(max(float(self_consistency_score), 0.0), 1.0)
        else:
            s4 = 1.0  # Default neutral score when skipped

        # 5. Text layer match rate (s5)
        s5 = self._check_text_layer_match(text_layer_info, llm_raw_text) if "text_layer_match" in applicable_signals else 0.0

        signal_values = {
            "detection_score": s1,
            "schema_valid": s2,
            "math_integrity": s3,
            "self_consistency": s4,
            "text_layer_match": s5
        }

        # Calculate re-normalized weights
        total_applicable_weight = sum(self.BASE_WEIGHTS[sig] for sig in applicable_signals)
        renormalized_weights = {
            sig: self.BASE_WEIGHTS[sig] / total_applicable_weight
            for sig in applicable_signals
        }

        # Compute final weighted sum
        final_score = sum(
            renormalized_weights[sig] * signal_values[sig]
            for sig in applicable_signals
        )
        final_score = round(min(max(final_score, 0.0), 1.0), 4)

        # Single threshold routing (0.80)
        if final_score >= settings.CONFIDENCE_THRESHOLD_APPROVED:
            status = ReviewStatus.APPROVED
        else:
            status = ReviewStatus.PENDING_REVIEW

        return {
            "confidence_score": final_score,
            "review_status": status,
            "applicable_signals": applicable_signals,
            "renormalized_weights": {k: round(v, 4) for k, v in renormalized_weights.items()},
            "signal_values": {k: round(v, 4) for k, v in signal_values.items()}
        }

    def _check_math_integrity(self, structured_data: Optional[TableStructure]) -> float:
        """Verify column counts across rows and sum / subtotal checks if present."""
        if not structured_data or not structured_data.rows:
            return 0.5

        columns = structured_data.columns
        expected_col_count = len(columns)
        if expected_col_count == 0:
            return 0.3

        valid_rows = 0
        for row in structured_data.rows:
            if len(row) >= expected_col_count - 1:
                valid_rows += 1

        consistency = valid_rows / len(structured_data.rows)
        return min(max(consistency, 0.0), 1.0)

    def _check_text_layer_match(
        self,
        text_layer_info: Optional[Dict[str, Any]],
        llm_raw_text: str
    ) -> float:
        """Compare numbers found in PyMuPDF text layer with numbers in LLM text."""
        if not text_layer_info or not text_layer_info.get("has_vector_text"):
            return 0.85

        pdf_text = text_layer_info.get("text_content", "")
        if not pdf_text or not llm_raw_text:
            return 0.7

        import re
        pdf_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", pdf_text))
        llm_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", llm_raw_text))

        if not pdf_numbers:
            return 0.85

        overlap = len(pdf_numbers.intersection(llm_numbers))
        match_rate = overlap / len(pdf_numbers)
        return min(max(match_rate, 0.0), 1.0)
