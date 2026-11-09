import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, Any, Optional
import google.generativeai as genai
from PIL import Image

from app.core.config import settings
from app.schemas import (
    ElementType,
    VisualElementSchema,
    TableStructure,
)
from app.pipeline.evaluator import ConfidenceEvaluator


class MultimodalExtractor:
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.VISION_MODEL
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(self.model_name)
        self.evaluator = ConfidenceEvaluator()

    def build_prompt(self, doc_name: str, page_number: int, doc_metadata: Dict[str, Any]) -> str:
        return f"""당신은 증권사 금융·산업 분석 리포트의 시각 자료(도표/차트) 전문 분석가입니다.
입력된 이미지는 리포트('{doc_name}', {page_number}페이지)에서 크롭된 시각 요소입니다.
리포트 기본 정보: 대상기업='{doc_metadata.get("company")}', 증권사='{doc_metadata.get("broker")}', 산업='{doc_metadata.get("industry")}'

다음 지침에 따라 JSON 포맷으로만 답변하세요 (마크다운 코드블록 없이 순수 JSON):

1. element_type:
   - "TABLE": 재무제표, 실적 전망치, 수치 비교표 등 행/열 표
   - "CHART": 막대그래프, 꺾은선그래프, 파이차트, 영역차트 등 추이/비율 시각화
   - "DIAGRAM": 산업 밸류체인 구조도, 공정 흐름도, 조직도, 기술 아키텍처 다이어그램

2. title_or_caption: 도표 상단 또는 하단에 표기된 고유 제목 (예: '[표 3] 글로벌 HBM 세대별 수요 전망'). 제목이 없을 경우 내용을 대변하는 명확한 제목을 부여하세요.
3. summary: 도표가 전달하는 핵심 메시지와 주요 수치를 2~3줄로 명확하게 한국어로 요약하세요.
4. hashtags: 관련 기업명, 핵심 제품/지표, 산업 키워드 (예: ["#SK하이닉스", "#HBM3E", "#반도체"]) 최소 3개 이상.

5. structured_data (element_type이 'TABLE'인 경우 필수, 그 외 null):
   {{
     "columns": ["구분", "2023", "2024E", ...],
     "rows": [
       {{"구분": "매출액", "2023": 12000, "2024E": 15000}},
       ...
     ],
     "unit": "십억원",
     "period_labels": ["2023", "2024E"]
   }}

출력 JSON 스키마:
{{
  "element_type": "TABLE" | "CHART" | "DIAGRAM",
  "title_or_caption": "...",
  "summary": "...",
  "hashtags": ["...", "..."],
  "structured_data": {{ ... }} | null
}}
"""

    def analyze_crop(
        self,
        crop_info: Dict[str, Any],
        doc_name: str,
        page_number: int,
        doc_metadata: Dict[str, Any],
        detection_score: float = 0.90
    ) -> VisualElementSchema:
        """
        Analyze cropped image with Gemini Multimodal model and return VisualElementSchema.
        Inherits document-level metadata (Item 3).
        """
        crop_path = Path(crop_info["crop_path"])
        img = Image.open(str(crop_path))

        prompt = self.build_prompt(doc_name, page_number, doc_metadata)

        response = self.model.generate_content([prompt, img])
        raw_text = response.text.strip()

        # Clean JSON markdown fences if present
        cleaned_json = re.sub(r"^```(?:json)?\s*", "", raw_text)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

        is_schema_valid = True
        try:
            parsed = json.loads(cleaned_json)
        except Exception:
            is_schema_valid = False
            parsed = {
                "element_type": "CHART",
                "title_or_caption": f"도표 (p.{page_number})",
                "summary": "도표 수치 파싱 중 오류가 발생하여 검수가 필요합니다.",
                "hashtags": ["#금융리포트"],
                "structured_data": None
            }

        element_type = ElementType(parsed.get("element_type", "CHART").upper())

        # Parse structured table data
        structured_data_obj = None
        if parsed.get("structured_data"):
            try:
                structured_data_obj = TableStructure(**parsed["structured_data"])
            except Exception:
                is_schema_valid = False

        # Conditional Self-consistency: TABLE or boundary cases (Item 5)
        self_consistency_score = None
        # In full production, if element_type == ElementType.TABLE: run 2nd call to evaluate agreement

        # Calculate re-normalized confidence score (Item 1)
        eval_result = self.evaluator.evaluate_signals(
            element_type=element_type,
            detection_score=detection_score,
            is_schema_valid=is_schema_valid,
            structured_data=structured_data_obj,
            self_consistency_score=self_consistency_score,
            text_layer_info=crop_info.get("text_layer_info"),
            llm_raw_text=raw_text
        )

        # Parse pub_date from doc_metadata
        pub_date = doc_metadata.get("publish_date", date.today())
        if isinstance(pub_date, str):
            try:
                pub_date = date.fromisoformat(pub_date)
            except Exception:
                pub_date = date.today()

        # Build final VisualElementSchema with inherited document-level metadata (Item 3)
        element = VisualElementSchema(
            element_id=crop_info["element_id"],
            doc_name=doc_name,
            page_number=page_number,
            bbox=crop_info["normalized_box"],
            element_type=element_type,
            image_path=crop_info["relative_path"],
            title_or_caption=parsed.get("title_or_caption", f"도표 p.{page_number}"),
            summary=parsed.get("summary", ""),
            structured_data=structured_data_obj,
            hashtags=parsed.get("hashtags", []),
            confidence_score=eval_result["confidence_score"],
            review_status=eval_result["review_status"],
            company=doc_metadata.get("company", "미분류"),
            ticker=doc_metadata.get("ticker"),
            broker=doc_metadata.get("broker", "증권사"),
            publish_date=pub_date,
            analyst=doc_metadata.get("analyst"),
            industry=doc_metadata.get("industry", "일반")
        )

        return element
