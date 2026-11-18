import os
import re
import json
import time
import random
import hashlib
import threading
from datetime import date
from pathlib import Path
from typing import Dict, Any, Optional, List
from google import genai
from PIL import Image

from shared.schemas import (
    ElementType,
    ReviewStatus,
    Element,
    TableData,
    ConfidenceSignals,
    PIPELINE_VERSION,
    CONFIDENCE_THRESHOLD,
)
from shared.coords import clip_bbox, validate_bbox

try:
    from table_parse import coerce_table_data
except ImportError:
    from pipeline.table_parse import coerce_table_data

try:
    from evaluator import ConfidenceEvaluator
except ImportError:
    from pipeline.evaluator import ConfidenceEvaluator


class GeminiRateLimiter:
    """Gemini API 호출 속도 제한기 (공용 싱글톤: 분당 최대 14회, 최소 호출 간격 약 4.29초)."""

    def __init__(self, max_rpm: float = 14.0):
        self.min_interval = 60.0 / max_rpm
        self.last_call_time = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self.last_call_time
            if elapsed < self.min_interval:
                sleep_duration = self.min_interval - elapsed
                time.sleep(sleep_duration)
            self.last_call_time = time.time()


# 공용 싱글톤 rate limiter (모든 Gemini API 호출이 공유)
SHARED_GEMINI_RATE_LIMITER = GeminiRateLimiter(max_rpm=14.0)


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
        """공용 싱글톤 rate limiter를 호출하여 분당 최대 14회(호출 간 ~4.29초) 한도를 엄격 준수합니다."""
        SHARED_GEMINI_RATE_LIMITER.wait()
        self.last_call_time = time.time()

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
                    self.last_used_model = model_name
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
        doc_type = doc_metadata.get("doc_type", "REPORT")
        doc_desc_map = {
            "REPORT": "증권 리포트(기업·산업 분석 보고서)",
            "PUBLIC_REPORT": "공공·연구기관 보고서(정책·통계·동향 자료)",
            "PAPER": "학술 논문(연구 방법·실험·분석 결과)",
            "IR": "기업 IR·ESG 보고서(실적 발표·경영 전략 자료)",
        }
        doc_desc = doc_desc_map.get(doc_type, "PDF 문서")

        hashtag_example_map = {
            "REPORT": '["기업명", "실적전망", "산업분석"]',
            "PUBLIC_REPORT": '["정책동향", "주요통계", "발행기관"]',
            "PAPER": '["연구주제", "실험결과", "핵심방법론"]',
            "IR": '["분기실적", "사업전략", "ESG"]',
        }
        hashtag_ex = hashtag_example_map.get(doc_type, '["핵심주제", "주요지표", "핵심요약"]')

        target = doc_metadata.get("target") or doc_metadata.get("company") or ""
        source_org = doc_metadata.get("source_org") or doc_metadata.get("broker") or ""

        return f"""당신은 {doc_desc}의 시각 자료(도표/차트/다이어그램) 전문 분석가입니다.
입력된 이미지는 문서('{doc_name}', {page_number}페이지)에서 크롭된 시각 요소(추정 유형: {hint_type})입니다.
문서 정보: 출처='{source_org}', 대상='{target}', 문서유형='{doc_type}'

다음 지침에 따라 오직 순수 JSON 포맷으로만 답변하세요 (마크다운 코드블록이나 불필요한 서두 없이):

1. element_type:
   - "TABLE": 재무제표, 실적 전망치, 통계표, 실험 수치 비교표 등 표 형식
   - "CHART": 막대/꺾은선/원형 그래프, 추이 및 비중 시각화
   - "DIAGRAM": 산업 밸류체인 구조도, 공정 흐름도, 아키텍처 다이어그램, 연구 방법 흐름도, 개념도

2. caption: 도표 상단/하단에 표기된 제목 또는 캡션 (예: '[표 1] 연도별 추이', '그림 2. 주요 지표 비교'). 없을 경우 명확한 제목을 명명하세요.
3. summary: 도표가 전달하는 핵심 메시지와 주요 수치를 한국어로 2~3줄로 명확히 요약하세요.
4. hashtags: 문서의 핵심 주제, 지표, 분야, 출처 키워드 ('#' 없이 단어만) (예: {hashtag_ex}) 최소 3개 이상.

5. table_data (element_type이 'TABLE'인 경우 필수, 그 외는 null):
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
  "caption": "...",
  "summary": "...",
  "hashtags": ["...", "..."],
  "table_data": {{ ... }} | null
}}
"""

    def analyze_crop(
        self,
        crop_info: Dict[str, Any],
        doc_name: str,
        page_number: int,
        doc_metadata: Dict[str, Any],
        detection_score: float = 0.92,
        doc_id: Optional[str] = None
    ) -> Element:
        """
        Analyze cropped image with Gemini Multimodal model and return Element.
        """
        crop_path = Path(crop_info["crop_path"])
        img_hash = self.get_image_hash(crop_path)

        # Check Cache first
        raw_text = ""
        if img_hash in self.cache:
            parsed = self.cache[img_hash]
            is_schema_valid = True
            used_vision_model = "cache"
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
            used_vision_model = getattr(self, "last_used_model", None) or getattr(self, "primary_model", "gemini-2.5-flash")

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
        target = doc_metadata.get("target") or doc_metadata.get("company")
        source_org = doc_metadata.get("source_org") or doc_metadata.get("broker")
        if source_org in ("증권사", "금융분석", ""):
            source_org = None

        if not parsed:
            raw_cap = crop_info.get("caption_hint") or f"도표 (p.{page_number})"
            target_label = target or doc_name
            parsed = {
                "element_type": crop_info.get("hint_type", "TABLE"),
                "caption": raw_cap,
                "summary": f"{target_label} 문서 {page_number}페이지 수치 도표입니다.",
                "hashtags": [target_label, "문서도표", "데이터"],
                "table_data": None
            }

        # Validate element_type enum
        el_type_str = str(parsed.get("element_type", "TABLE")).upper()
        if el_type_str not in ("TABLE", "CHART", "DIAGRAM"):
            el_type_str = "TABLE" if crop_info.get("hint_type") == "TABLE" else "CHART"
        element_type = ElementType(el_type_str)

        # Parse structured table data
        # null 목록 필드·행 키 불일치처럼 형식만 어긋난 표도 살린다 (table_parse.coerce_table_data)
        table_data_raw = parsed.get("table_data")
        table_data_obj = None
        if table_data_raw and isinstance(table_data_raw, dict):
            table_data_obj, table_note = coerce_table_data(table_data_raw)
            if table_data_obj is None:
                is_schema_valid = False
                print(f"    [TableData] {crop_path.name}: {table_note}")

        # Calculate confidence score
        eval_result = self.evaluator.evaluate_signals(
            element_type=element_type,
            detection_score=detection_score,
            is_schema_valid=is_schema_valid,
            table_data=table_data_obj,
            self_consistency_score=None,
            text_layer_info=crop_info.get("text_layer_info"),
            llm_raw_text=raw_text
        )

        # Build entities
        ignored_defaults = {"", "증권사", "금융분석"}
        raw_hashtags = parsed.get("hashtags", [])
        cleaned_hashtags: List[str] = []
        for tag in raw_hashtags:
            if isinstance(tag, str):
                c_tag = tag.lstrip("#").strip()
                if c_tag and c_tag not in cleaned_hashtags:
                    cleaned_hashtags.append(c_tag)

        raw_entities = [target, source_org] + cleaned_hashtags
        entities: List[str] = []
        seen_entities = set()
        for item in raw_entities:
            if not isinstance(item, str):
                continue
            cleaned_ent = item.lstrip("#").strip()
            if not cleaned_ent or cleaned_ent in ignored_defaults or cleaned_ent in seen_entities:
                continue
            seen_entities.add(cleaned_ent)
            entities.append(cleaned_ent)

        doc_type = doc_metadata.get("doc_type", "REPORT")
        if doc_type == "REPORT":
            extra_metadata = {
                "target": target,
                "company": target,
                "ticker": doc_metadata.get("ticker"),
                "broker": source_org,
                "industry": doc_metadata.get("industry"),
                "analyst": doc_metadata.get("analyst"),
                "vision_model": used_vision_model,
            }
        else:
            extra_metadata = {
                "target": target,
                "company": None,
                "ticker": None,
                "broker": None,
                "analyst": None,
                "vision_model": used_vision_model,
            }

        # BBox normalization
        raw_box = crop_info.get("normalized_box", [0.0, 0.0, 1.0, 1.0])
        bbox = clip_bbox(raw_box)
        try:
            validate_bbox(bbox)
        except Exception:
            # 보정
            bbox = [
                min(bbox[0], bbox[2] - 0.001),
                min(bbox[1], bbox[3] - 0.001),
                max(bbox[2], bbox[0] + 0.001),
                max(bbox[3], bbox[1] + 0.001),
            ]
            bbox = clip_bbox(bbox)

        effective_doc_id = (
            doc_id
            or doc_metadata.get("doc_id")
            or hashlib.md5(doc_name.encode("utf-8")).hexdigest()[:16]
        )

        caption_val = (
            parsed.get("caption")
            or crop_info.get("caption_hint")
            or f"도표 p.{page_number}"
        )

        model_name = os.getenv("VISION_MODEL", getattr(self, "primary_model", "gemini-3.8-flash"))
        signals_obj = eval_result.get("signals")
        if not isinstance(signals_obj, ConfidenceSignals):
            signals_obj = ConfidenceSignals()

        review_status_val = eval_result.get("review_status", ReviewStatus.PENDING_REVIEW)
        if isinstance(review_status_val, str):
            try:
                review_status_val = ReviewStatus(review_status_val)
            except ValueError:
                review_status_val = ReviewStatus.PENDING_REVIEW

        element = Element(
            element_id=crop_info["element_id"],
            doc_id=effective_doc_id,
            page_number=page_number,
            bbox=bbox,
            element_type=element_type,
            image_path=crop_info["relative_path"],
            caption=caption_val,
            summary=parsed.get("summary", ""),
            hashtags=cleaned_hashtags,
            entities=entities,
            table_data=table_data_obj,
            signals=signals_obj,
            confidence_score=float(eval_result.get("confidence_score", 1.0)),
            review_status=review_status_val,
            pipeline_version=PIPELINE_VERSION,
            model_name=model_name,
            extra_metadata=extra_metadata,
        )

        return element

        return element
