from typing import Dict, Any, Optional
from shared.schemas import ReviewStatus, ElementType
from shared.schemas_legacy import TableStructure


class ConfidenceEvaluator:
    """
    Calculates re-normalized weighted sum confidence score from applicable signals (v0.3.1):
    1. DocLayout-YOLO / Table detection score (s1, base weight 0.20)
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

    CONFIDENCE_THRESHOLD = 0.80

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
            s4 = 1.0  # Default neutral/pass when not triggered

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
        if final_score >= self.CONFIDENCE_THRESHOLD:
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
        """Check if structured table data has valid columns, rows, and numbers."""
        if not structured_data:
            return 0.3
        if not structured_data.columns or not structured_data.rows:
            return 0.4
        
        # Check numerical completeness in rows
        valid_rows = 0
        for row in structured_data.rows:
            numeric_cells = sum(1 for v in row.values() if isinstance(v, (int, float)))
            if numeric_cells > 0:
                valid_rows += 1

        ratio = valid_rows / len(structured_data.rows)
        return min(max(ratio, 0.5), 1.0)

    def _check_text_layer_match(self, text_layer_info: Optional[Dict[str, Any]], llm_raw_text: str) -> float:
        """Evaluate text overlap between PDF vector text layer and LLM generated tokens."""
        if not text_layer_info or not text_layer_info.get("has_vector_text"):
            return 0.7
        
        pdf_text = text_layer_info.get("text_content", "")
        if not pdf_text:
            return 0.7

        # Extract numerical strings from pdf_text and llm_raw_text
        import re
        pdf_nums = set(re.findall(r"\b\d+(?:[\.,]\d+)?\b", pdf_text))
        llm_nums = set(re.findall(r"\b\d+(?:[\.,]\d+)?\b", llm_raw_text))

        if not pdf_nums or not llm_nums:
            return 0.8

        overlap = len(pdf_nums.intersection(llm_nums))
        return min(max(overlap / min(len(pdf_nums), len(llm_nums)), 0.6), 1.0)
