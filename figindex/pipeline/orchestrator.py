import os
import re
import math
import atexit
import hashlib
import logging
import threading
import unicodedata
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

import fitz  # PyMuPDF
from kiwipiepy import Kiwi
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

try:
    from shared.schemas import VisualElementSchema, ElementType, ReviewStatus
except ImportError:
    from app.schemas import VisualElementSchema, ElementType, ReviewStatus

try:
    from cropper import PDFCropper
    from extractor import MultimodalExtractor
except ImportError:
    from app.pipeline.cropper import PDFCropper
    from app.pipeline.extractor import MultimodalExtractor


DOC_TYPE_CODE_MAP: Dict[str, str] = {
    "RPT": "REPORT",
    "PUB": "PUBLIC_REPORT",
    "PAP": "PAPER",
    "IR": "IR",
}

# 증권사 별칭 -> 정식 명칭 매핑 사전 (known_brokers 20개 + 사명 변경 + 약칭/영문 포함)
BROKER_ALIASES: Dict[str, str] = {
    # 정식 명칭 (기존 known_brokers 20개 및 사명 변경 반영)
    "IBK투자증권": "IBK투자증권",
    "미래에셋증권": "미래에셋증권",
    "신한투자증권": "신한투자증권",
    "키움증권": "키움증권",
    "하나증권": "하나증권",
    "대신증권": "대신증권",
    "KB증권": "KB증권",
    "삼성증권": "삼성증권",
    "NH투자증권": "NH투자증권",
    "유안타증권": "유안타증권",
    "한국투자증권": "한국투자증권",
    "메리츠증권": "메리츠증권",
    "교보증권": "교보증권",
    "현대차증권": "현대차증권",
    "한화투자증권": "한화투자증권",
    "SK증권": "SK증권",
    "유진투자증권": "유진투자증권",
    "DB증권": "DB증권",
    "iM증권": "iM증권",
    "다올투자증권": "다올투자증권",
    # 추가 증권사 정식 명칭
    "LS증권": "LS증권",
    "상상인증권": "상상인증권",
    "신영증권": "신영증권",
    "DS투자증권": "DS투자증권",
    "BNK투자증권": "BNK투자증권",
    "한양증권": "한양증권",
    "부국증권": "부국증권",
    "흥국증권": "흥국증권",
    "케이프투자증권": "케이프투자증권",
    "리딩투자증권": "리딩투자증권",
    # 사명 변경 전 구 명칭 & 약칭 & 별칭
    "DB금융투자": "DB증권",
    "동부증권": "DB증권",
    "하이투자증권": "iM증권",
    "신한금융투자": "신한투자증권",
    "하나금융투자": "하나증권",
    "하나대투증권": "하나증권",
    "미래에셋대우": "미래에셋증권",
    "대우증권": "미래에셋증권",
    "현대증권": "KB증권",
    "KB투자증권": "KB증권",
    "KTB투자증권": "다올투자증권",
    "이베스트투자증권": "LS증권",
    "이베스트증권": "LS증권",
    "동양증권": "유안타증권",
    "한화증권": "한화투자증권",
    "HMC투자증권": "현대차증권",
    "우리투자증권": "NH투자증권",
    "LIG투자증권": "케이프투자증권",
    "한투": "한국투자증권",
    "한투증권": "한국투자증권",
    "한국투자": "한국투자증권",
    "IBK": "IBK투자증권",
    "IBK투자": "IBK투자증권",
    "미래에셋": "미래에셋증권",
    "신한": "신한투자증권",
    "신한투자": "신한투자증권",
    "키움": "키움증권",
    "하나": "하나증권",
    "대신": "대신증권",
    "KB": "KB증권",
    "삼성": "삼성증권",
    "NH": "NH투자증권",
    "NH투자": "NH투자증권",
    "유안타": "유안타증권",
    "메리츠": "메리츠증권",
    "메리츠종금증권": "메리츠증권",
    "교보": "교보증권",
    "현대차": "현대차증권",
    "한화": "한화투자증권",
    "한화투자": "한화투자증권",
    "SK": "SK증권",
    "유진": "유진투자증권",
    "유진투자": "유진투자증권",
    "DB": "DB증권",
    "iM": "iM증권",
    "IM증권": "iM증권",
    "다올": "다올투자증권",
    "다올투자": "다올투자증권",
    "LS": "LS증권",
    "상상인": "상상인증권",
    "신영": "신영증권",
    "DS": "DS투자증권",
}

_BROKER_ALIASES_LOWER: Dict[str, str] = {k.lower(): v for k, v in BROKER_ALIASES.items()}


def normalize_broker_name(source: str) -> str:
    """REPORT 문서의 출처(증권사)를 BROKER_ALIASES 기준으로 정식 명칭으로 변환합니다."""
    cleaned = unicodedata.normalize("NFC", source).strip()
    if cleaned in BROKER_ALIASES:
        return BROKER_ALIASES[cleaned]
    lower_key = cleaned.lower()
    if lower_key in _BROKER_ALIASES_LOWER:
        return _BROKER_ALIASES_LOWER[lower_key]
    msg = f"[Warn] BROKER_ALIASES에 없는 REPORT 출처입니다 (원본 유지): '{cleaned}'"
    logger.warning(msg)
    print(msg)
    return cleaned


# 긴 접두어부터 순서대로 검사하기 위해 (접두어, doc_type) 튜플 리스트로 정의
PREFIX_DOC_TYPE_RULES = [
    ("슬라이드_IR_", "IR"),
    ("통계보도자료_", "PUBLIC_REPORT"),
    ("공공보고서_", "PUBLIC_REPORT"),
    ("보도자료_", "PUBLIC_REPORT"),
    ("보고서_", "PUBLIC_REPORT"),
    ("리포트_", "PUBLIC_REPORT"),
    ("논문_", "PAPER"),
    ("RPT_", DOC_TYPE_CODE_MAP["RPT"]),
    ("PUB_", DOC_TYPE_CODE_MAP["PUB"]),
    ("PAP_", DOC_TYPE_CODE_MAP["PAP"]),
    ("IR_", DOC_TYPE_CODE_MAP["IR"]),
]

# 형식 C: 구분자 없이 "{한글종류}{YYYYMMDD}{제목}_{출처}" 형태로 붙는 접두어 규칙
COMPACT_PREFIX_DOC_TYPE_RULES = [
    ("통계보도자료", "PUBLIC_REPORT"),
    ("공공보고서", "PUBLIC_REPORT"),
    ("보도자료", "PUBLIC_REPORT"),
    ("보고서", "PUBLIC_REPORT"),
    ("리포트", "PUBLIC_REPORT"),
    ("논문", "PAPER"),
]


def _parse_date_digits(date_str: str) -> Optional[date]:
    """4자리(YYYY), 6자리(YYYYMM), 8자리(YYYYMMDD) 숫자 문자열을 date로 변환합니다."""
    if not re.fullmatch(r"\d{4}|\d{6}|\d{8}", date_str):
        return None
    try:
        if len(date_str) == 4:
            return date(int(date_str), 1, 1)
        if len(date_str) == 6:
            return date(int(date_str[:4]), int(date_str[4:6]), 1)
        return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    except ValueError:
        return None


def parse_filename(doc_name: str) -> Optional[Dict[str, Any]]:
    """
    코드 형식(A), 한글 형식(B), 구분자 없는 한글 형식(C) PDF 파일명을 모두 해석합니다.
      (A) {코드}_{날짜}_{대상}_{출처}(_숫자).pdf  (RPT, PUB, PAP, IR)
      (B) {한글종류}_{날짜}_{주제}_{출처}(_숫자).pdf (슬라이드_IR, 통계보도자료, 공공보고서, 보도자료, 보고서, 리포트, 논문)
      (C) {한글종류}{YYYYMMDD}{제목}_{출처}(_숫자).pdf (보고서, 리포트, 논문 등)
    날짜는 4자리(YYYY -> 1월1일), 6자리(YYYYMM -> 1일), 8자리(YYYYMMDD)를 지원합니다.
    반환: {"doc_type", "date", "target", "source"} 또는 None
    """
    normalized = unicodedata.normalize("NFC", Path(doc_name).name).strip()
    stem = re.sub(r"\.pdf$", "", normalized, flags=re.IGNORECASE).strip()

    # 1. 형식 (A), (B): 접두어 뒤에 "_" 구분자가 있는 경우
    matched_doc_type = None
    remainder = None
    for prefix, doc_type in PREFIX_DOC_TYPE_RULES:
        if stem.upper().startswith(prefix.upper()):
            matched_doc_type = doc_type
            remainder = stem[len(prefix):]
            break

    if matched_doc_type and remainder is not None:
        parts = remainder.split("_")
        # 최소 3개 파트(날짜, 대상/주제, 출처). 끝에 중복 번호(_2, _3 등)가 있으면 제거
        if len(parts) >= 4 and re.fullmatch(r"\d+", parts[-1].strip()):
            parts = parts[:-1]

        if len(parts) < 3:
            return None

        date_str = parts[0].strip()
        source = parts[-1].strip()
        target = "_".join(p.strip() for p in parts[1:-1]).strip()

        if not target or not source:
            return None

        parsed_date = _parse_date_digits(date_str)
        if not parsed_date:
            return None

        if matched_doc_type == "REPORT":
            source = normalize_broker_name(source)

        return {
            "doc_type": matched_doc_type,
            "date": parsed_date,
            "target": target,
            "source": source,
        }

    # 2. 형식 (C): "{한글종류}{YYYYMMDD}{제목}_{출처}" (종류와 날짜 사이 구분자 없음)
    for prefix, doc_type in COMPACT_PREFIX_DOC_TYPE_RULES:
        if stem.startswith(prefix):
            compact_rem = stem[len(prefix):]
            if not re.match(r"^\d{8}", compact_rem):
                continue

            date_str = compact_rem[:8]
            parsed_date = _parse_date_digits(date_str)
            if not parsed_date:
                return None

            rest = compact_rem[8:]
            if "_" not in rest:
                return None

            # 끝에 중복 번호(_2, _3 등)가 붙은 경우 마지막 "_" 기준 분리 전에 제거
            if rest.count("_") >= 2:
                base_part, maybe_dup = rest.rsplit("_", 1)
                if re.fullmatch(r"\d+", maybe_dup.strip()):
                    rest = base_part

            target, source = rest.rsplit("_", 1)
            target = target.strip()
            source = source.strip()
            if not target or not source:
                return None

            if doc_type == "REPORT":
                source = normalize_broker_name(source)

            return {
                "doc_type": doc_type,
                "date": parsed_date,
                "target": target,
                "source": source,
            }

    return None


def parse_new_filename(doc_name: str) -> Optional[Dict[str, Any]]:
    """파일명을 해석해 doc_type, publish_date, target, source_org를 반환합니다."""
    res = parse_filename(doc_name)
    if not res:
        return None
    return {
        "doc_type": res["doc_type"],
        "publish_date": res["date"],
        "target": res["target"],
        "source_org": res["source"],
    }


_PIPELINE_QDRANT_CLIENTS: Dict[tuple, QdrantClient] = {}
_PIPELINE_QDRANT_LOCK = threading.Lock()


def get_pipeline_qdrant_client(qdrant_mode: str, qdrant_url: str, qdrant_local_path: str) -> QdrantClient:
    """프로세스 내에서 동일 설정의 QdrantClient를 한 번만 생성해 재사용합니다."""
    mode = (qdrant_mode or "server").lower()
    key = (mode, qdrant_local_path if mode == "local" else qdrant_url)
    with _PIPELINE_QDRANT_LOCK:
        client = _PIPELINE_QDRANT_CLIENTS.get(key)
        if client is None:
            if mode == "local":
                os.makedirs(qdrant_local_path, exist_ok=True)
                client = QdrantClient(path=qdrant_local_path)
            else:
                client = QdrantClient(url=qdrant_url, timeout=10.0)
            _PIPELINE_QDRANT_CLIENTS[key] = client
        return client


def _close_pipeline_qdrant_clients() -> None:
    """프로세스 종료 시 열려 있는 파이프라인 QdrantClient를 안전하게 닫습니다."""
    with _PIPELINE_QDRANT_LOCK:
        for client in _PIPELINE_QDRANT_CLIENTS.values():
            try:
                client.close()
            except Exception:
                pass
        _PIPELINE_QDRANT_CLIENTS.clear()


atexit.register(_close_pipeline_qdrant_clients)


class ExtractionPipelineOrchestrator:
    def __init__(self):
        self.cropper = PDFCropper()
        self.extractor = MultimodalExtractor()
        self.kiwi = Kiwi()

        self.qdrant_mode = os.getenv("QDRANT_MODE", "server").lower()
        self.qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.qdrant_local_path = os.getenv("QDRANT_LOCAL_PATH", "/data/qdrant_local")
        self.collection_name = os.getenv("QDRANT_COLLECTION", "figindex_elements")

        if self.qdrant_mode == "local":
            warn_msg = (
                f"[Warn] 파이프라인이 QDRANT_MODE=local로 실행됩니다 ({self.qdrant_local_path}). "
                "로컬 모드에서 백엔드 서버가 실행 중일 때 파이프라인을 동시에 실행하면 "
                "Qdrant 로컬 폴더 파일 잠금 충돌이 발생합니다. 백엔드를 중지하거나 QDRANT_MODE=server를 사용하세요."
            )
            logger.warning(warn_msg)
            print(warn_msg)

        self.qdrant_client = get_pipeline_qdrant_client(
            self.qdrant_mode, self.qdrant_url, self.qdrant_local_path
        )

        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.embedding_dim = 1536
        self.openai_client = OpenAI(api_key=self.openai_key) if self.openai_key else None

    def is_document_already_indexed(self, doc_name: str) -> bool:
        """Check if any elements from this PDF document already exist in Qdrant."""
        try:
            results, _ = self.qdrant_client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_name",
                            match=qmodels.MatchValue(value=doc_name)
                        )
                    ]
                ),
                limit=1,
                with_payload=False,
                with_vectors=False
            )
            return len(results) > 0
        except Exception:
            return False

    def extract_document_metadata(self, doc: fitz.Document, doc_name: str) -> Dict[str, Any]:
        """
        Extract document-level metadata once (cover page text layer + file name parsing) (Item 3).
        Inherited by all elements in this report.
        """
        cover_text = doc[0].get_text("text") if len(doc) > 0 else ""
        name_without_ext = re.sub(
            r"\.pdf$",
            "",
            unicodedata.normalize("NFC", Path(doc_name).name),
            flags=re.IGNORECASE,
        ).strip()

        parsed_fn = parse_new_filename(doc_name)

        if parsed_fn:
            target = parsed_fn["target"]
            source_org = parsed_fn["source_org"]
            pub_date = parsed_fn["publish_date"]
            doc_type = parsed_fn["doc_type"]
        else:
            upper_stem = name_without_ext.upper()
            matched_code = next(
                (code for code in DOC_TYPE_CODE_MAP if upper_stem.startswith(f"{code}_")),
                None,
            )
            if matched_code:
                doc_type = DOC_TYPE_CODE_MAP[matched_code]
                target = None
                msg = f"[Warn] 파일명 형식이 맞지 않아 대상을 비워둡니다 (doc_name='{doc_name}')"
                logger.warning(msg)
                print(msg)
            else:
                doc_type = "REPORT"
                # 옛날 형식(예: 'BGF리테일1106.pdf', 'CJ ENM 1106.pdf') -> 기업명을 target으로 추출
                company_candidate = re.sub(r"[\s_-]*\d{4}$", "", name_without_ext).strip()
                target = company_candidate if company_candidate else None

            # 표지에서 증권사(출처) 매칭 (REPORT일 때만)
            source_org = None
            if doc_type == "REPORT":
                broker_candidates = [
                    "IBK투자증권", "미래에셋증권", "신한투자증권", "키움증권", "하나증권",
                    "대신증권", "KB증권", "삼성증권", "NH투자증권", "유안타증권",
                    "한국투자증권", "메리츠증권", "교보증권", "현대차증권", "한화투자증권",
                    "SK증권", "유진투자증권", "DB증권", "DB금융투자", "iM증권", "하이투자증권",
                    "다올투자증권", "LS증권", "상상인증권",
                ]
                for b in broker_candidates:
                    short_b = b.replace("투자증권", "").replace("금융투자", "").replace("증권", "")
                    if b in cover_text or (len(short_b) >= 2 and short_b in cover_text):
                        source_org = normalize_broker_name(b)
                        break

            # 발행일 추출 (표지 우선 -> 파일명 끝 MMdd 대체)
            pub_date = date.today()
            date_match = re.search(r"(202[4-6])[\.\-\/](\d{1,2})[\.\-\/](\d{1,2})", cover_text)
            if date_match:
                try:
                    y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                    pub_date = date(y, m, d)
                except Exception:
                    pub_date = date.today()
            else:
                fn_date_match = re.search(r"(\d{2})(\d{2})$", name_without_ext)
                if fn_date_match:
                    try:
                        m, d = int(fn_date_match.group(1)), int(fn_date_match.group(2))
                        pub_date = date(2025, m, d)
                    except Exception:
                        pub_date = date.today()

        # REPORT일 때만 표지에서 종목코드·애널리스트·업종 추출
        ticker = None
        analyst = None
        industry = None

        if doc_type == "REPORT":
            ticker_match = re.search(r"\((\d{6})\)|\b(\d{6})\b", cover_text)
            if ticker_match:
                ticker = ticker_match.group(1) or ticker_match.group(2)

            analyst_match = re.search(r"([가-힣]{2,4})\s*(?:연구원|애널리스트|위원|RA)", cover_text)
            if analyst_match:
                analyst = analyst_match.group(1)

            lines = [line.strip() for line in cover_text.split("\n") if len(line.strip()) > 5]
            doc_title = f"{target} 리서치 리포트" if target else name_without_ext
            for line in lines[:5]:
                if (target and target in line) or "Review" in line or "전망" in line or "실적" in line:
                    doc_title = line
                    break

            industry = "산업/기업분석"
            for ind in ["반도체", "2차전지", "편의점/유통", "미디어/엔터", "제약/바이오", "에너지", "금융", "통신", "소비재", "화학", "자동차"]:
                if ind in cover_text:
                    industry = ind
                    break
        else:
            # REPORT 이외: 표지 앞쪽 본문/첫 줄 우선, 없으면 target 또는 파일명
            cover_lines = [line.strip() for line in cover_text.split("\n") if line.strip()]
            long_lines = [line for line in cover_lines if len(line) >= 8]
            if long_lines:
                doc_title = max(long_lines[:15], key=len)
            elif cover_lines:
                doc_title = cover_lines[0]
            else:
                doc_title = target or name_without_ext

        return {
            "target": target,
            "source_org": source_org,
            "doc_type": doc_type,
            "publish_date": pub_date,
            "doc_title": doc_title,
            "ticker": ticker,
            "analyst": analyst,
            "industry": industry,
            # 하위 호환용: REPORT일 때만 채우고 나머지 문서 유형은 None
            "company": target if doc_type == "REPORT" else None,
            "broker": source_org if doc_type == "REPORT" else None,
        }

    def tokenize_korean_bm25(self, text: str) -> Dict[int, float]:
        """Tokenize text with Kiwi and return sparse hash frequencies."""
        tokens = self.kiwi.tokenize(text)
        token_counts: Dict[int, float] = {}
        valid_tags = {"NNG", "NNP", "NR", "VV", "VA", "SL"}
        for t in tokens:
            if t.tag in valid_tags and len(t.form) > 1:
                token_hash = abs(hash(t.form)) % (2**31 - 1)
                token_counts[token_hash] = token_counts.get(token_hash, 0.0) + 1.0
        return token_counts

    def get_dense_embedding(self, text: str) -> List[float]:
        """Get 1536 dim dense embedding using OpenAI text-embedding-3-small."""
        if self.openai_client:
            try:
                resp = self.openai_client.embeddings.create(
                    input=text[:4000],
                    model=self.embedding_model
                )
                return resp.data[0].embedding
            except Exception as e:
                print(f"  [Warn] OpenAI embedding failed: {e}. Falling back to deterministic embedding.")

        # Deterministic fallback vector if OpenAI key is not provided or fails
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
        vec = []
        for i in range(self.embedding_dim):
            val = math.sin(seed + i)
            vec.append(val)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def index_element_to_qdrant(self, element: VisualElementSchema):
        """Upsert a single VisualElementSchema into Qdrant collection."""
        text_to_embed = f"{element.title_or_caption} {element.summary} {' '.join(element.hashtags)} {element.doc_title} {element.source_org} {' '.join(element.entities)}"
        dense_vec = self.get_dense_embedding(text_to_embed)
        sparse_tokens = self.tokenize_korean_bm25(text_to_embed)
        sparse_indices = list(sparse_tokens.keys())
        sparse_values = list(sparse_tokens.values())

        payload = element.model_dump(mode="json")
        point_id = abs(hash(element.element_id)) % (2**63 - 1)

        self.qdrant_client.upsert(
            collection_name=self.collection_name,
            points=[
                qmodels.PointStruct(
                    id=point_id,
                    vector={
                        "dense": dense_vec,
                        "sparse": qmodels.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values
                        ) if sparse_indices else None
                    },
                    payload=payload
                )
            ]
        )

    def process_pdf(self, pdf_path: Path, max_pages: int = 15, max_elements_per_pdf: int = 4) -> List[VisualElementSchema]:
        """
        Process a single PDF document:
        1. Extract document-level metadata
        2. Detect and crop visual elements across pages
        3. Analyze with Gemini Multimodal model
        4. Upsert to Qdrant collection
        """
        doc = fitz.open(str(pdf_path))
        doc_name = pdf_path.name
        total_pages = min(len(doc), max_pages)

        doc_metadata = self.extract_document_metadata(doc, doc_name)
        print(f"  -> Extracted Metadata: 유형={doc_metadata['doc_type']}, 대상={doc_metadata.get('target')}, 출처={doc_metadata.get('source_org')}, 발행일={doc_metadata['publish_date']}, 종목={doc_metadata.get('ticker')}")

        indexed_elements: List[VisualElementSchema] = []
        extracted_count = 0

        for p_idx in range(1, total_pages + 1):
            if extracted_count >= max_elements_per_pdf:
                break

            page = doc[p_idx - 1]
            candidates = self.cropper.detect_candidate_boxes(page)
            if not candidates:
                continue

            page_img = self.cropper.render_page(doc, p_idx)

            for cand in candidates:
                if extracted_count >= max_elements_per_pdf:
                    break

                try:
                    crop_info = self.cropper.crop_and_save(
                        doc=doc,
                        doc_path=pdf_path,
                        page_num=p_idx,
                        candidate=cand,
                        page_img=page_img
                    )

                    print(f"    [P.{p_idx}] Cropped {crop_info['hint_type']}: {crop_info['relative_path']}")

                    # Analyze with Gemini Multimodal
                    element = self.extractor.analyze_crop(
                        crop_info=crop_info,
                        doc_name=doc_name,
                        page_number=p_idx,
                        doc_metadata=doc_metadata,
                        detection_score=0.92
                    )

                    print(f"    [AI Analyzed] Type: {element.element_type.value} | Title: {element.title_or_caption[:35]} | Conf: {element.confidence_score*100:.1f}% ({element.review_status.value})")

                    # Upsert to Qdrant
                    self.index_element_to_qdrant(element)
                    indexed_elements.append(element)
                    extracted_count += 1

                except Exception as e:
                    print(f"    [Error] Processing visual element on p.{p_idx}: {e}")

        doc.close()
        return indexed_elements
