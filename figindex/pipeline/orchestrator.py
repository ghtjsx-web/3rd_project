import os
import re
import math
import atexit
import hashlib
import logging
import threading
import unicodedata
import json
import uuid
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

import fitz  # PyMuPDF
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from shared.schemas import (
    ElementType,
    ReviewStatus,
    Document,
    Element,
    ElementSearchPayload,
    DocStatus,
    EntityType,
    PIPELINE_VERSION,
    ENTITY_DICTIONARY_PATH,
)
from shared.sparse import build_sparse_vector, generate_point_id
from shared.index_text import build_index_text
from shared.coords import from_legacy_yxyx

try:
    from cropper import PDFCropper
    from extractor import MultimodalExtractor
    from pdf_text import is_toc_page
    from element_match import matches_existing
except ImportError:
    from pipeline.cropper import PDFCropper
    from pipeline.extractor import MultimodalExtractor
    from pipeline.pdf_text import is_toc_page
    from pipeline.element_match import matches_existing


# 규칙 크롭은 탐지 확률이 없어 고정값을 쓴다 (YOLO 크롭은 모델의 detection_score를 그대로 씀)
RULE_DETECTION_SCORE = 0.92


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


# ---------------------------------------------------------------------------
# 표지 기반 메타데이터 (파일명이 RPT_날짜_종목_증권사 형식이 아니어도 채우기 위함)
# 종목명은 엔티티 사전(entity_name)만 기준으로 한다 (AGENTS.md 5절).
# ---------------------------------------------------------------------------

_ENTITY_INDEX_CACHE: Optional[Dict[str, Dict[str, str]]] = None


def _entity_key(name: str) -> str:
    """사전 대조용 키: 유니코드 정규화, 공백 제거, 대소문자 무시."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", str(name))).casefold()


def _resolve_entity_dictionary_path() -> Path:
    path = Path(ENTITY_DICTIONARY_PATH)
    if not path.is_absolute() and not path.exists():
        path = Path(__file__).resolve().parent.parent / ENTITY_DICTIONARY_PATH  # figindex/data/...
    return path


def load_company_index(path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """엔티티 사전에서 기업(COMPANY)만 읽어 {'by_ticker': {종목코드: entity_name}, 'by_key': {이름·별칭 키: entity_name}}을 돌려준다."""
    global _ENTITY_INDEX_CACHE
    if path is None and _ENTITY_INDEX_CACHE is not None:
        return _ENTITY_INDEX_CACHE
    import csv

    index: Dict[str, Dict[str, str]] = {"by_ticker": {}, "by_key": {}}
    dict_path = path or _resolve_entity_dictionary_path()
    if not dict_path.exists():
        msg = f"[Warn] 엔티티 사전이 없어 표지에서 종목을 찾지 않습니다: {dict_path}"
        logger.warning(msg)
        print(msg)
    else:
        with open(dict_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                entity_name = (row.get("entity_name") or "").strip()
                if not entity_name or (row.get("entity_type") or "").strip() != EntityType.COMPANY.value:
                    continue
                ticker = (row.get("ticker") or "").strip()
                if ticker:
                    index["by_ticker"][ticker] = entity_name
                names = [entity_name] + [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
                for name in names:
                    index["by_key"].setdefault(_entity_key(name), entity_name)
    if path is None:
        _ENTITY_INDEX_CACHE = index
    return index


def to_company_entity_name(name: Optional[str], index: Dict[str, Dict[str, str]]) -> Optional[str]:
    """종목명 표기(삼전, KTnG, LNF 등)를 사전 entity_name으로 바꾼다. 사전에 없으면 그대로."""
    if not name:
        return name
    return index["by_key"].get(_entity_key(name), name)


def find_company_in_text(text: str, index: Dict[str, Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
    """표지 글에서 종목을 찾는다. (entity_name, 종목코드)를 돌려준다.

    1) 사전에 있는 6자리 종목코드가 처음 나오는 것
    2) 없으면 앞 15줄에서 사전 기업 이름·별칭(2자 이상)이 가장 먼저 나오는 것 (같은 위치면 긴 이름)
    """
    for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", text):
        if m.group(1) in index["by_ticker"]:
            return index["by_ticker"][m.group(1)], m.group(1)
    head = _entity_key("\n".join([line for line in text.split("\n") if line.strip()][:15]))
    best: Optional[Tuple[int, int, str]] = None
    for key, entity_name in index["by_key"].items():
        if len(key) < 2:
            continue
        pos = head.find(key)
        if pos >= 0 and (best is None or pos < best[0] or (pos == best[0] and len(key) > best[1])):
            best = (pos, len(key), entity_name)
    return (best[2], None) if best else (None, None)


def find_broker_in_text(text: str) -> Optional[str]:
    """글에서 증권사 이름이 가장 먼저 나오는 것을 BROKER_ALIASES 정식 명칭으로 돌려준다.

    'SK', 'KB'처럼 짧은 별칭은 종목명(SK하이닉스 등)과 헷갈리므로 '증권'·'투자'가 들어간 표기만 대조한다.
    """
    best: Optional[Tuple[int, int, str]] = None
    for alias, official in BROKER_ALIASES.items():
        if "증권" not in alias and "투자" not in alias:
            continue
        pos = text.find(alias)
        if pos >= 0 and (best is None or pos < best[0] or (pos == best[0] and len(alias) > best[1])):
            best = (pos, len(alias), official)
    return best[2] if best else None


def find_date_in_text(text: str) -> Optional[date]:
    """글에서 처음 나오는 올바른 날짜 (2026.11.18 / 2026-11-18 / 2026/11/18 / 2026. 11. 18 / 2026년 11월 18일)."""
    pattern = r"(20\d{2})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*(?:[.\-/]|월)\s*(\d{1,2})(?!\d)"
    for m in re.finditer(pattern, text):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    return None


def find_date_in_doc_name(name_without_ext: str, today: Optional[date] = None) -> Optional[date]:
    """파일명에서 날짜: YYYYMMDD가 있으면 그것, 없으면 끝의 MMDD(옛 형식)를 올해로 보되 미래면 작년으로."""
    today = today or date.today()
    for m in re.finditer(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", name_without_ext):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    m = re.search(r"(?<!\d)(\d{2})(\d{2})$", name_without_ext)
    if m:
        try:
            parsed = date(today.year, int(m.group(1)), int(m.group(2)))
            return parsed if parsed <= today else date(today.year - 1, parsed.month, parsed.day)
        except ValueError:
            return None
    return None


def parse_rpt_filename(doc_name: str) -> Optional[Dict[str, Any]]:
    """
    RPT_YYYYMMDD_종목_증권사.pdf 파일명에서 publish_date, source_org, company를 파싱합니다.
    파일명 값이 메타데이터 추출의 최우선 기준이 됩니다.
    """
    normalized = unicodedata.normalize("NFC", Path(doc_name).name).strip()
    stem = re.sub(r"\.pdf$", "", normalized, flags=re.IGNORECASE).strip()
    if not stem.upper().startswith("RPT_"):
        return None

    remainder = stem[4:]
    parts = remainder.split("_")
    # 끝에 중복 번호(_2, _3 등)가 붙은 경우 제거
    if len(parts) >= 4 and re.fullmatch(r"\d+", parts[-1].strip()):
        parts = parts[:-1]
    if len(parts) < 3:
        return None

    date_str = parts[0].strip()
    source_raw = parts[-1].strip()
    company = "_".join(p.strip() for p in parts[1:-1]).strip()

    if not company or not source_raw:
        return None

    parsed_date = _parse_date_digits(date_str)
    if not parsed_date:
        return None

    # 증권사 자리가 '미확인'이면 파일명에서 가져오지 않고 None으로 두어 LLM/표지 추출값을 사용하도록 함
    if source_raw in ("미확인", "UNKNOWN", "unknown", ""):
        source_org = None
    else:
        source_org = normalize_broker_name(source_raw)

    return {
        "publish_date": parsed_date,
        "source_org": source_org,
        "target": company,
        "doc_type": "REPORT",
    }


def parse_new_filename(doc_name: str) -> Optional[Dict[str, Any]]:
    """파일명을 해석해 doc_type, publish_date, target, source_org를 반환합니다."""
    # RPT 전용 형식 우선 파싱
    rpt_res = parse_rpt_filename(doc_name)
    if rpt_res:
        return rpt_res

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

        self.qdrant_mode = os.getenv("QDRANT_MODE", "server").lower()
        self.qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.qdrant_local_path = os.getenv("QDRANT_LOCAL_PATH", "/data/qdrant_local")
        self.collection_name = os.getenv("QDRANT_COLLECTION", "figindex_elements_v2")

        # Load doc_id_map for stable document ID assignment
        self.doc_id_map: Dict[str, str] = {}
        for map_path in [
            Path("/data/migration/doc_id_map.json"),
            Path(__file__).resolve().parent.parent / "data" / "migration" / "doc_id_map.json",
            Path("figindex/data/migration/doc_id_map.json"),
            Path("data/migration/doc_id_map.json"),
        ]:
            if map_path.exists():
                try:
                    with open(map_path, "r", encoding="utf-8") as f:
                        self.doc_id_map = json.load(f)
                    break
                except Exception as e:
                    logger.warning(f"Failed to load doc_id_map from {map_path}: {e}")

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
        문서 메타데이터를 한 번 추출한다 (파일명 + 표지 글자). 모든 요소가 이 값을 물려받는다.

        - 파일명이 RPT_날짜_종목_증권사 형식이면 파일명 값을 우선한다 (결정 1).
        - 형식이 아니면 표지에서 찾는다: 종목은 엔티티 사전의 종목코드·이름, 증권사는 BROKER_ALIASES,
          발행일은 표지 날짜 → 파일명 날짜 순. 못 찾으면 None으로 둔다 (오늘 날짜 등으로 채우지 않는다).
        - 종목명은 항상 엔티티 사전 entity_name으로 저장한다.
        """
        cover_text = doc[0].get_text("text") if len(doc) > 0 else ""
        last_text = doc[len(doc) - 1].get_text("text") if len(doc) > 1 else ""
        name_without_ext = re.sub(
            r"\.pdf$",
            "",
            unicodedata.normalize("NFC", Path(doc_name).name),
            flags=re.IGNORECASE,
        ).strip()
        company_index = load_company_index()
        cover_target, cover_ticker = find_company_in_text(cover_text, company_index)

        parsed_fn = parse_new_filename(doc_name)

        if parsed_fn:
            # 파일명 파싱 값을 표지/LLM 추출 값보다 최우선 적용
            target = parsed_fn["target"]
            source_org = parsed_fn.get("source_org")
            pub_date = parsed_fn["publish_date"]
            doc_type = parsed_fn["doc_type"]
            if doc_type == "REPORT":
                target = to_company_entity_name(target, company_index)
                # 파일명 증권사 자리가 미확인(None)인 경우 표지 → 마지막 페이지(고지문)에서 찾기
                if not source_org:
                    source_org = find_broker_in_text(cover_text) or find_broker_in_text(last_text)
        else:
            upper_stem = name_without_ext.upper()
            matched_code = next(
                (code for code in DOC_TYPE_CODE_MAP if upper_stem.startswith(f"{code}_")),
                None,
            )
            if matched_code:
                doc_type = DOC_TYPE_CODE_MAP[matched_code]
                target = cover_target if doc_type == "REPORT" else None
                if not target:
                    msg = f"[Warn] 파일명 형식이 맞지 않아 대상을 비워둡니다 (doc_name='{doc_name}')"
                    logger.warning(msg)
                    print(msg)
            else:
                doc_type = "REPORT"
                target = cover_target
                if not target:
                    # 옛날 형식(예: 'BGF리테일1106.pdf', 'CJ ENM 1106.pdf')만 파일명에서 기업명을 가져온다
                    legacy = re.fullmatch(r"([^_]+?)[\s-]*\d{4}", name_without_ext)
                    if legacy:
                        target = to_company_entity_name(legacy.group(1).strip(), company_index)
                if not target:
                    msg = f"[Warn] 표지와 파일명에서 종목을 찾지 못했습니다 (doc_name='{doc_name}')"
                    logger.warning(msg)
                    print(msg)

            # 증권사: 표지 → 마지막 페이지(고지문) (REPORT일 때만)
            source_org = None
            if doc_type == "REPORT":
                source_org = find_broker_in_text(cover_text) or find_broker_in_text(last_text)

            # 발행일: 표지 → 파일명. 못 찾으면 None
            pub_date = find_date_in_text(cover_text) or find_date_in_doc_name(name_without_ext)

        # REPORT일 때만 표지에서 종목코드·애널리스트·업종 추출
        ticker = None
        analyst = None
        industry = None

        if doc_type == "REPORT":
            ticker = cover_ticker
            if not ticker:
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
        """Kiwi 토큰화 + crc32 고정 해시. 색인과 검색이 같은 토큰 번호를 쓰도록 shared.sparse에 위임한다."""
        return build_sparse_vector(text)

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

    def get_doc_id(self, doc_name: str) -> str:
        """doc_id_map에 존재하는 경우 기존 doc_id를 재사용하고, 없으면 새로 발급합니다."""
        if doc_name in self.doc_id_map:
            return self.doc_id_map[doc_name]
        return uuid.uuid4().hex[:16]

    def index_element_to_qdrant(self, element: ElementSearchPayload):
        """Upsert a single ElementSearchPayload into Qdrant collection."""
        text_to_embed = build_index_text(element.model_dump(mode="json"))
        dense_vec = self.get_dense_embedding(text_to_embed)
        sparse_tokens = build_sparse_vector(text_to_embed)
        sparse_indices = list(sparse_tokens.keys())
        sparse_values = list(sparse_tokens.values())

        payload = element.model_dump(mode="json")
        point_id = generate_point_id(element.doc_id, element.page_number, element.bbox)

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

    def process_pdf(
        self,
        pdf_path: Path,
        max_pages: Optional[int] = 15,
        max_elements_per_pdf: int = 4,
        doc_id: Optional[str] = None,
        skip_toc: bool = True,
        existing_bboxes: Optional[Dict[int, List[List[float]]]] = None,
        doc_overrides: Optional[Dict[str, Any]] = None,
    ) -> List[ElementSearchPayload]:
        """
        Process a single PDF document:
        1. Extract document-level metadata & create Document object
        2. Detect and crop visual elements across pages
        3. Analyze with Gemini Multimodal model to get Element objects
        4. Compose ElementSearchPayload and upsert to Qdrant collection

        - max_pages=None이면 전체 페이지를 본다.
        - doc_id를 주면 그 값을 요소의 doc_id로 쓴다 (업로드 DB의 doc_id와 맞추기, 0.1.3).
        - skip_toc=True이면 목차·표 목차 페이지는 도표를 찾지 않고 건너뛴다 (0.1.3).
        - existing_bboxes({page_number: [bbox, ...]})를 주면 기존 요소와 같은 후보는 크롭·Gemini 분석 없이
          건너뛴다. 빠진 요소만 추가하는 재색인용(결정 22). max_elements_per_pdf는 새 요소만 센다.
        - doc_overrides를 주면 추출한 문서 메타데이터를 그 값으로 덮어쓴다 (기존 요소와 같은 값을 물려받기).
        처리한 문서의 Document는 self.last_document에 남는다 (index_document가 사용).
        """
        doc = fitz.open(str(pdf_path))
        doc_name = pdf_path.name
        total_pages = len(doc) if max_pages is None else min(len(doc), max_pages)

        doc_metadata = self.extract_document_metadata(doc, doc_name)
        if doc_overrides:
            doc_metadata.update(doc_overrides)
        print(f"  -> Extracted Metadata: 유형={doc_metadata['doc_type']}, 대상={doc_metadata.get('target')}, 출처={doc_metadata.get('source_org')}, 발행일={doc_metadata['publish_date']}, 종목={doc_metadata.get('ticker')}")

        # 1회 문서 객체(Document) 생성 (메모리에서만 유지)
        doc_id = doc_id or self.get_doc_id(doc_name)
        try:
            with open(pdf_path, "rb") as f:
                doc_hash = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            doc_hash = hashlib.sha256(doc_name.encode("utf-8")).hexdigest()

        target = doc_metadata.get("target") or doc_metadata.get("company")
        source_org = doc_metadata.get("source_org") or doc_metadata.get("broker")
        doc_type = doc_metadata.get("doc_type", "REPORT")
        doc_title = doc_metadata.get("doc_title", doc_name)
        industry = doc_metadata.get("industry")
        domain = industry or ("금융/산업" if doc_type == "REPORT" else None)
        authors = [doc_metadata["analyst"]] if doc_metadata.get("analyst") else []
        pub_date = doc_metadata.get("publish_date")
        if isinstance(pub_date, str):
            try:
                pub_date = date.fromisoformat(pub_date)
            except Exception:
                pub_date = None
        elif not isinstance(pub_date, date):
            pub_date = None  # 발행일을 못 찾으면 비워 둔다 (오늘 날짜로 채우지 않음)

        extra_metadata = {
            "target": target,
            "company": target if doc_type == "REPORT" else None,
            "ticker": doc_metadata.get("ticker"),
            "broker": source_org if doc_type == "REPORT" else None,
            "industry": industry,
            "analyst": doc_metadata.get("analyst"),
        }

        document = Document(
            doc_id=doc_id,
            doc_hash=doc_hash,
            doc_name=doc_name,
            doc_title=doc_title,
            doc_type=doc_type,
            domain=domain,
            source_org=source_org,
            authors=authors,
            publish_date=pub_date,
            page_count=len(doc),
            doc_status=DocStatus.PROCESSING,
            extra_metadata=extra_metadata,
        )

        pending_payloads: List[ElementSearchPayload] = []
        extracted_count = 0
        toc_pages_skipped: List[int] = []
        skipped_existing = 0
        self.last_document = document

        try:
            for p_idx in range(1, total_pages + 1):
                if extracted_count >= max_elements_per_pdf:
                    break

                page = doc[p_idx - 1]
                if skip_toc and is_toc_page(page):
                    toc_pages_skipped.append(p_idx)
                    print(f"    [P.{p_idx}] 목차 페이지라 건너뜀")
                    continue
                candidates, page_img = self.cropper.detect_page_candidates(doc, p_idx)
                if existing_bboxes is not None:
                    old_boxes = existing_bboxes.get(p_idx, [])
                    new_candidates = [
                        c for c in candidates
                        if not matches_existing(from_legacy_yxyx(c["bbox"]), old_boxes)
                    ]
                    skipped_existing += len(candidates) - len(new_candidates)
                    candidates = new_candidates
                if not candidates:
                    continue

                if page_img is None:
                    page_img = self.cropper.render_page(doc, p_idx)

                for cand in candidates:
                    if extracted_count >= max_elements_per_pdf:
                        break

                    crop_info = self.cropper.crop_and_save(
                        doc=doc,
                        doc_path=pdf_path,
                        page_num=p_idx,
                        candidate=cand,
                        page_img=page_img
                    )

                    print(f"    [P.{p_idx}] Cropped {crop_info['hint_type']}: {crop_info['relative_path']}")

                    # Analyze with Gemini Multimodal -> Element 반환
                    element: Element = self.extractor.analyze_crop(
                        crop_info=crop_info,
                        doc_name=doc_name,
                        page_number=p_idx,
                        doc_metadata=doc_metadata,
                        detection_score=cand.get("detection_score", RULE_DETECTION_SCORE),
                        doc_id=document.doc_id
                    )

                    caption_summary = element.caption[:35] if element.caption else "제목 없음"
                    print(f"    [AI Analyzed] Type: {element.element_type.value} | Title: {caption_summary} | Conf: {element.confidence_score*100:.1f}% ({element.review_status.value})")

                    # ElementSearchPayload 생성 (Qdrant에는 즉시 넣지 않고 모아둠)
                    payload_obj = ElementSearchPayload(
                        **element.model_dump(),
                        doc_name=document.doc_name,
                        doc_title=document.doc_title,
                        doc_type=document.doc_type,
                        domain=document.domain,
                        source_org=document.source_org,
                        authors=document.authors,
                        publish_date=document.publish_date,
                        collection_id=document.collection_id
                    )

                    pending_payloads.append(payload_obj)
                    extracted_count += 1

            # 문서 하나의 모든 도표 처리가 정상 완료된 후에만 Qdrant에 일괄 upsert
            for p_obj in pending_payloads:
                self.index_element_to_qdrant(p_obj)
            indexed_elements = pending_payloads

        except Exception as e:
            # 중간 실패 시 해당 문서의 포인트는 하나도 저장하지 않고 예외 전파
            print(f"    [처리 실패] '{doc_name}' 도표 처리 중 오류 발생 (Qdrant 포인트 미저장): {e}")
            doc.close()
            raise

        doc.close()
        document.extra_metadata["element_count"] = len(indexed_elements)
        document.extra_metadata["toc_pages_skipped"] = toc_pages_skipped
        if existing_bboxes is not None:
            document.extra_metadata["skipped_existing"] = skipped_existing
        return indexed_elements

    def index_document(
        self,
        pdf_path: Path,
        doc_id: str,
        max_pages: Optional[int] = None,
        max_elements_per_pdf: int = 40,
    ) -> Document:
        """업로드한 PDF 1건을 처리하고 문서 메타데이터를 채운 Document를 돌려준다 (작업자용, 0.1.3).

        - 요소는 받은 doc_id로 Qdrant에 저장한다 (업로드 DB와 같은 doc_id).
        - 기본은 전체 페이지, 도표 40개, 목차 건너뛰기.
        - 도표가 0개여도 정상 완료다 (extra_metadata.element_count = 0).
        - 실패하면 예외를 그대로 던지고, Qdrant에는 아무것도 저장하지 않는다.
        """
        self.process_pdf(
            Path(pdf_path),
            max_pages=max_pages,
            max_elements_per_pdf=max_elements_per_pdf,
            doc_id=doc_id,
            skip_toc=True,
        )
        document = self.last_document
        document.doc_status = DocStatus.COMPLETED
        document.doc_error = None
        document.extra_metadata["pipeline_version"] = PIPELINE_VERSION
        return document
