import os
import re
import json
import time
import random
import hashlib
from datetime import date
from pathlib import Path
from typing import Dict, Any, Optional, List
from google import genai
from PIL import Image

try:
    from shared.schemas import (
        ElementType,
        VisualElementSchema,
        TableStructure,
        ReviewStatus
    )
except ImportError:
    from app.schemas import (
        ElementType,
        VisualElementSchema,
        TableStructure,
        ReviewStatus
    )

try:
    from evaluator import ConfidenceEvaluator
except ImportError:
    from app.pipeline.evaluator import ConfidenceEvaluator


class MultimodalExtractor:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.primary_model = os.getenv("VISION_MODEL", "gemini-3.8-flash")
        # Reliable fallback models in case of 503 high demand spikes or quota exhaustion
        self.fallback_models = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
        
        self.rate_limit_delay = float(os.getenv("RATE_LIMIT_DELAY", "2.0"))
        self.last_call_time = 0.0

        # Local disk cache for Gemini responses
        self.cache_dir = Path(os.getenv("CACHE_DIR", "/data/cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "gemini_cache.json"
        self.cache: Dict[str, Any] = self._load_cache()

        if not self.api_key:
            print("[Warn] GEMINI_API_KEY is not set in environment!")
            self.client = None
        else:
            self.client = genai.Client(api_key=self.api_key)

        self.evaluator = ConfidenceEvaluator()

    def _load_cache(self) -> Dict[str, Any]:
        """Load JSON cache from disk if exists."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Warn] Failed to load cache file: {e}")
        return {}

    def _save_cache(self):
        """Save JSON cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Warn] Failed to save cache file: {e}")

    def get_image_hash(self, img_path: Path) -> str:
        """Compute SHA256 hash of image file for robust caching."""
        try:
            with open(img_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return img_path.name

    def _wait_for_rate_limit(self):
        """Enforce rate limiting delay between consecutive Gemini API requests."""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.rate_limit_delay:
            sleep_duration = self.rate_limit_delay - elapsed
            time.sleep(sleep_duration)

    def _call_gemini_with_backoff(self, prompt: str, img: Image.Image) -> str:
        """
        Executes Gemini API call with exponential backoff, rate limiting, and model fallback.
        """
        if not self.client:
            raise RuntimeError("Gemini Client is not initialized (missing API key).")

        models_to_try = [self.primary_model]
        for fb in self.fallback_models:
            if fb not in models_to_try:
                models_to_try.append(fb)

        max_retries_per_model = 2
        base_delay = 3.0
        max_delay = 15.0

        for model_name in models_to_try:
            delay = base_delay
            for attempt in range(1, max_retries_per_model + 1):
                try:
                    self._wait_for_rate_limit()
                    self.last_call_time = time.time()

                    resp = self.client.models.generate_content(
                        model=model_name,
                        contents=[img, prompt]
                    )
                    if model_name != self.primary_model:
                        print(f"  [Active Model] Promoted responsive model '{model_name}' for faster throughput.")
                        self.primary_model = model_name
                    return resp.text.strip()
                except Exception as e:
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    is_unavailable = "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str

                    if (is_rate_limit or is_unavailable) and attempt < max_retries_per_model:
                        jitter = random.uniform(0.5, 1.5)
                        wait_time = min(max_delay, delay + jitter)
                        print(f"  [RateLimit/Backoff] Model '{model_name}' ({'429 Quota' if is_rate_limit else '503 Demand'}). Retrying in {wait_time:.1f}s (Attempt {attempt}/{max_retries_per_model})...")
                        time.sleep(wait_time)
                        delay = min(max_delay, delay * 2.0)
                    else:
                        print(f"  [Model Switch] Model '{model_name}' issue ({'429 Quota' if is_rate_limit else '503 Demand' if is_unavailable else err_str[:80]}). Switching to next model...")
                        break

        raise RuntimeError("All Gemini model attempts failed after exponential backoff.")

    def build_prompt(self, doc_name: str, page_number: int, doc_metadata: Dict[str, Any], hint_type: str = "TABLE") -> str:
        return f"""당신은 증권사 금융·산업 분석 리포트의 시각 자료(도표/차트) 전문 분석가입니다.
입력된 이미지는 리포트('{doc_name}', {page_number}페이지)에서 크롭된 시각 요소(추정 유형: {hint_type})입니다.
문서 정보: 기업명='{doc_metadata.get("company")}', 증권사='{doc_metadata.get("broker")}', 산업='{doc_metadata.get("industry")}'

다음 지침에 따라 오직 순수 JSON 포맷으로만 답변하세요 (마크다운 코드블록이나 불필요한 서두 없이):

1. element_type:
   - "TABLE": 재무제표, 실적 전망치, 수치 비교표 등 표 형식
   - "CHART": 막대/꺾은선/원형 그래프, 추이 및 비중 시각화
   - "DIAGRAM": 산업 밸류체인 구조도, 공정 흐름도, 아키텍처 다이어그램

2. title_or_caption: 도표 상단/하단에 표기된 제목 (예: '[표 1] 연도별 실적 추이', '그림 2. 분기별 영업이익 추이'). 없을 경우 명확한 제목을 명명하세요.
3. summary: 도표가 전달하는 핵심 메시지와 주요 수치를 한국어로 2~3줄로 명확히 요약하세요.
4. hashtags: 관련 기업명, 핵심 제품/지표, 산업 키워드 (예: ["#BGF리테일", "#편의점", "#실적전망"]) 최소 3개 이상.

5. structured_data (element_type이 'TABLE'인 경우 필수, 그 외는 null):
   {{
     "columns": ["구분", "2023", "2024E", ...],
     "rows": [
       {{"구분": "매출액", "2023": 12000, "2024E": 15000}},
       ...
     ],
     "unit": "억원" 또는 "%" 등,
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
        detection_score: float = 0.92
    ) -> VisualElementSchema:
        """
        Analyze cropped image with Gemini Multimodal model and return VisualElementSchema.
        """
        crop_path = Path(crop_info["crop_path"])
        img_hash = self.get_image_hash(crop_path)

        # Check Cache first
        if img_hash in self.cache:
            parsed = self.cache[img_hash]
            is_schema_valid = True
            print(f"    [Cache Hit] Using cached AI analysis for {crop_path.name}")
        else:
            img = Image.open(str(crop_path))
            prompt = self.build_prompt(
                doc_name=doc_name,
                page_number=page_number,
                doc_metadata=doc_metadata,
                hint_type=crop_info.get("hint_type", "TABLE")
            )

            raw_text = self._call_gemini_with_backoff(prompt, img)

            # Clean JSON fences if present
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json, flags=re.MULTILINE).strip()

            is_schema_valid = True
            try:
                parsed = json.loads(cleaned_json)
            except Exception:
                # Fallback parsing regex
                json_match = re.search(r"\{.*\}", cleaned_json, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(0))
                    except Exception:
                        is_schema_valid = False
                        parsed = {}
                else:
                    is_schema_valid = False
                    parsed = {}

            # Cache the parsed result if valid
            if parsed and is_schema_valid:
                self.cache[img_hash] = parsed
                self._save_cache()

        # Fallback values if JSON keys missing
        if not parsed:
            raw_cap = crop_info.get("caption_hint") or f"도표 (p.{page_number})"
            parsed = {
                "element_type": crop_info.get("hint_type", "TABLE"),
                "title_or_caption": raw_cap,
                "summary": f"{doc_metadata.get('company', '기업')} 리포트 {page_number}페이지 수치 도표입니다.",
                "hashtags": [f"#{doc_metadata.get('company', '기업')}", "#리포트", "#도표"],
                "structured_data": None
            }

        # Validate element_type enum
        el_type_str = str(parsed.get("element_type", "TABLE")).upper()
        if el_type_str not in ("TABLE", "CHART", "DIAGRAM"):
            el_type_str = "TABLE" if crop_info.get("hint_type") == "TABLE" else "CHART"
        element_type = ElementType(el_type_str)

        # Parse structured table data
        structured_data_obj = None
        if parsed.get("structured_data") and isinstance(parsed["structured_data"], dict):
            try:
                structured_data_obj = TableStructure(**parsed["structured_data"])
            except Exception:
                is_schema_valid = False

        # Calculate confidence score
        eval_result = self.evaluator.evaluate_signals(
            element_type=element_type,
            detection_score=detection_score,
            is_schema_valid=is_schema_valid,
            structured_data=structured_data_obj,
            self_consistency_score=None,
            text_layer_info=crop_info.get("text_layer_info"),
            llm_raw_text=raw_text
        )

        pub_date = doc_metadata.get("publish_date")
        if isinstance(pub_date, str):
            try:
                pub_date = date.fromisoformat(pub_date)
            except Exception:
                pub_date = date.today()
        elif not isinstance(pub_date, date):
            pub_date = date.today()

        # Build final VisualElementSchema (v0.4 format)
        entities = list(set([doc_metadata.get("company", "")] + [doc_metadata.get("broker", "")] + parsed.get("hashtags", [])))
        entities = [e.replace("#", "") for e in entities if e]

        element = VisualElementSchema(
            element_id=crop_info["element_id"],
            doc_name=doc_name,
            page_number=page_number,
            bbox=crop_info["normalized_box"],
            element_type=element_type,
            image_path=crop_info["relative_path"],
            title_or_caption=parsed.get("title_or_caption") or crop_info.get("caption_hint") or f"도표 p.{page_number}",
            summary=parsed.get("summary", ""),
            structured_data=structured_data_obj,
            hashtags=parsed.get("hashtags", []),
            confidence_score=eval_result["confidence_score"],
            review_status=eval_result["review_status"],
            doc_title=doc_metadata.get("doc_title", doc_name),
            doc_type="REPORT",
            domain=doc_metadata.get("industry", "금융/산업"),
            source_org=doc_metadata.get("broker", "증권사"),
            authors=[doc_metadata.get("analyst")] if doc_metadata.get("analyst") else [],
            publish_date=pub_date,
            entities=entities,
            extra_metadata={
                "company": doc_metadata.get("company"),
                "ticker": doc_metadata.get("ticker"),
                "broker": doc_metadata.get("broker"),
                "industry": doc_metadata.get("industry"),
                "analyst": doc_metadata.get("analyst")
            }
        )

        return element
