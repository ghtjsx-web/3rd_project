import os
import csv
import re
import math
import hashlib
import time
import threading
import traceback
import tempfile
import unicodedata
import uuid
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
from fastapi import FastAPI, Query, Header, Depends, Request, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import quote
from fastapi.responses import FileResponse, JSONResponse
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from dotenv import load_dotenv
import httpx

load_dotenv()

# Import shared schemas
from shared.schemas import (
    ElementType,
    ReviewAction,
    ReviewStatus,
    Batch,
    Document,
    DocStatus,
    ElementSearchPayload,
    TableData,
    ReviewLog,
    ComparisonResult,
    EntityEntry,
    EntityType,
    CONFIDENCE_THRESHOLD,
    ENTITY_DICTIONARY_PATH,
)
from shared.compare import available_metrics, build_comparison
from shared.normalize import METRIC_ALIASES
from app.upload_store import append_review_log, get_batch_documents, persist_batch


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """앱 수명주기 관리: 시작 시 Kiwi를 미리 불러 첫 검색 지연을 없애고, 종료 시 QdrantClient를 정리합니다."""
    get_sparse_query_vector("워밍업")
    yield
    close_qdrant_client()


app = FastAPI(
    title="FigIndex Backend API",
    description="PDF 문서 도표·차트 자동 분류 및 멀티모달 색인 시스템 (FigIndex)",
    version="0.4.0",
    lifespan=lifespan,
)

# =====================================================================
# Admin Security & Auth Helpers
# =====================================================================
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "0000")

def verify_admin_password(x_admin_password: Optional[str] = Header(None)):
    """Verify admin password from request header. Raises 401 on mismatch."""
    from fastapi import HTTPException
    if not x_admin_password or x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=401,
            detail="관리자 권한이 없습니다. 올바른 비밀번호를 입력해 주세요."
        )


class AdminVerifyRequest(BaseModel):
    password: str = Field(..., description="검증할 관리자 비밀번호")


@app.post("/api/admin/verify")
def verify_admin_endpoint(req: AdminVerifyRequest):
    """관리자 비밀번호 유효성을 확인하는 엔드포인트"""
    from fastapi import HTTPException
    if req.password == ADMIN_PASSWORD:
        return {"status": "ok", "message": "관리자 인증 성공"}
    raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")

# Data Directories
DATA_DIR = os.getenv("DATA_DIR", "/data")
CROPS_DIR = os.getenv("CROPS_DIR", os.path.join(DATA_DIR, "crops"))
PDFS_DIR = os.getenv("PDFS_DIR", os.path.join(DATA_DIR, "pdfs"))
QDRANT_LOCAL_PATH = os.getenv("QDRANT_LOCAL_PATH", os.path.join(DATA_DIR, "qdrant_local"))
CACHE_DIR = os.getenv("CACHE_DIR", os.path.join(DATA_DIR, "cache"))

UPLOAD_DB_PATH = os.path.join(DATA_DIR, "metadata.sqlite3")


@app.post(
    "/api/batches",
    response_model=List[Document],
    status_code=201,
    summary="PDF 묶음 등록",
    description="PDF 여러 개를 등록합니다. 파일 내용이 같은 문서는 DUPLICATE로 기록하며, 파이프라인은 실행하지 않습니다.",
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "examples": {
                        "two_pdfs": {
                            "summary": "PDF 두 개 등록",
                            "description": "Swagger의 files 항목에 PDF 파일 두 개를 첨부합니다.",
                            "value": {"files": ["report_a.pdf", "report_b.pdf"]},
                        }
                    }
                }
            }
        }
    },
)
async def create_batch(files: List[UploadFile] = File(..., description="한 번에 등록할 PDF 파일 목록")):
    if not files:
        raise HTTPException(status_code=400, detail="PDF 파일을 하나 이상 선택해 주세요.")

    os.makedirs(PDFS_DIR, exist_ok=True)
    batch_id = str(uuid.uuid4())
    batch = Batch(batch_id=batch_id, doc_count=len(files))
    temporary_paths: List[str] = []
    staged_documents: List[Tuple[Document, str]] = []

    try:
        for upload in files:
            raw_doc_name = upload.filename or ""
            doc_name = unicodedata.normalize(
                "NFC", os.path.basename(raw_doc_name.replace(chr(92), "/"))
            ).strip()
            if not doc_name or not doc_name.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="PDF 파일만 등록할 수 있습니다.")

            descriptor, staged_path = tempfile.mkstemp(
                prefix=".figindex-upload-", suffix=".tmp", dir=PDFS_DIR
            )
            temporary_paths.append(staged_path)
            doc_hash = hashlib.sha256()
            file_header = bytearray()
            with os.fdopen(descriptor, "wb") as staged_file:
                while True:
                    content = await upload.read(1024 * 1024)
                    if not content:
                        break
                    if len(file_header) < 1024:
                        file_header.extend(content[: 1024 - len(file_header)])
                    staged_file.write(content)
                    doc_hash.update(content)

            if b"%PDF-" not in file_header:
                raise HTTPException(
                    status_code=400,
                    detail="'" + doc_name + "' 파일의 PDF 내용을 확인할 수 없습니다.",
                )

            document = Document(
                doc_id=str(uuid.uuid4()),
                batch_id=batch_id,
                doc_hash=doc_hash.hexdigest(),
                doc_name=doc_name,
                doc_status=DocStatus.UPLOADED,
            )
            staged_documents.append((document, staged_path))

        return persist_batch(UPLOAD_DB_PATH, PDFS_DIR, batch, staged_documents)
    finally:
        for staged_path in temporary_paths:
            try:
                os.remove(staged_path)
            except FileNotFoundError:
                pass


@app.get(
    "/api/batches/{batch_id}",
    response_model=List[Document],
    summary="등록 묶음의 문서 처리 상태 조회",
    description="등록 묶음에 포함된 Document 목록을 반환합니다. 화면은 doc_status로 진행률을 계산합니다.",
)
def get_batch_status(batch_id: str):
    documents = get_batch_documents(UPLOAD_DB_PATH, batch_id)
    if documents is None:
        raise HTTPException(status_code=404, detail=f"등록 묶음 '{batch_id}'를 찾을 수 없습니다.")
    return documents


# CORS Domains
raw_cors = os.getenv(
    "CORS_ORIGINS",
    "https://figindex-frontend.onpod.ai,http://localhost:3000,http://127.0.0.1:3000,*"
)
ALLOWED_CORS_ORIGINS = [origin.strip() for origin in raw_cors.split(",") if origin.strip()]

# CORS Middleware (Frontend communication)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_cors_headers(origin: Optional[str]) -> Dict[str, str]:
    """전역 예외 응답에서도 브라우저가 JSON 에러를 읽을 수 있도록 CORS 헤더를 생성합니다."""
    headers: Dict[str, str] = {
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }
    allow_all = "*" in ALLOWED_CORS_ORIGINS
    if origin and (allow_all or origin in ALLOWED_CORS_ORIGINS):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    elif allow_all:
        headers["Access-Control-Allow-Origin"] = "*"
    return headers


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """처리되지 않은 예외를 전체 traceback 로깅과 함께 CORS 포함 JSON(500)으로 반환합니다."""
    tb_str = traceback.format_exc()
    print(f"[Error] Unhandled exception on {request.method} {request.url.path}:\n{tb_str}")
    origin = request.headers.get("origin")
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc) or exc.__class__.__name__,
            "type": exc.__class__.__name__,
            "path": str(request.url.path),
        },
        headers=_build_cors_headers(origin),
    )

# =====================================================================
# Secure File Serving APIs (No raw directory exposure)
# =====================================================================
@app.api_route("/api/files/pdf/{doc_name}", methods=["GET", "HEAD"])
def get_pdf_file_endpoint(doc_name: str):
    """
    단일 원문 PDF 파일을 안전하게 제공하는 API입니다.
    폴더 전체 공개를 차단하고 상위 경로 탐색(../)을 원천 방지합니다.
    """
    from fastapi import HTTPException
    safe_name = os.path.basename(doc_name)
    pdf_path = os.path.join(PDFS_DIR, safe_name)
    if not os.path.exists(pdf_path) or not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="요청한 PDF 리포트를 찾을 수 없습니다.")

    encoded_filename = quote(safe_name)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=safe_name,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"}
    )


@app.api_route("/api/files/crops/{filename}", methods=["GET", "HEAD"])
@app.api_route("/static/crops/{filename}", methods=["GET", "HEAD"])
def get_crop_image_endpoint(filename: str):
    """
    크롭 이미지 파일을 안전하게 제공하는 API입니다.
    기존 이미지 경로(/static/crops/...) 호환성을 유지하면서 디렉터리 노출을 차단합니다.
    """
    from fastapi import HTTPException
    safe_name = os.path.basename(filename)
    crop_path = os.path.join(CROPS_DIR, safe_name)
    if not os.path.exists(crop_path):
        raise HTTPException(status_code=404, detail="요청한 도표 이미지를 찾을 수 없습니다.")

    return FileResponse(
        path=crop_path,
        media_type="image/png"
    )

# Qdrant Client Configuration (Dual Mode: Server vs Local Embedded)
QDRANT_MODE = os.getenv("QDRANT_MODE", "server").lower()
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "figindex_elements_v2")

# AI & Embedding Model
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


_qdrant_client: Optional[QdrantClient] = None
_qdrant_client_lock = threading.Lock()
_qdrant_op_lock = threading.RLock()


def get_qdrant_client() -> QdrantClient:
    """
    프로세스당 하나의 QdrantClient 인스턴스만 생성해 재사용합니다.
    - 'local': Onpod/단일 컨테이너용 디스크 기반 임베디드 모드
    - 'server': 단독 Qdrant 서버(포트 6333) 네트워크 모드
    """
    global _qdrant_client
    if _qdrant_client is None:
        with _qdrant_client_lock:
            if _qdrant_client is None:
                if QDRANT_MODE == "local":
                    os.makedirs(QDRANT_LOCAL_PATH, exist_ok=True)
                    _qdrant_client = QdrantClient(path=QDRANT_LOCAL_PATH)
                else:
                    _qdrant_client = QdrantClient(url=QDRANT_URL, timeout=5.0)
    return _qdrant_client


def close_qdrant_client() -> None:
    """앱 종료 시 단일 QdrantClient 연결과 로컬 파일 잠금을 정리합니다."""
    global _qdrant_client
    with _qdrant_client_lock:
        if _qdrant_client is not None:
            try:
                _qdrant_client.close()
            except Exception as e:
                print(f"[Warn] Failed to close QdrantClient cleanly: {e}")
            finally:
                _qdrant_client = None


@contextmanager
def qdrant_call_guard():
    """
    로컬 모드(QDRANT_MODE=local)에서는 멀티스레드 동시 접근 안전을 위해 Lock으로 감싸고,
    서버 모드(QDRANT_MODE=server)에서는 잠금 없이 실행합니다.
    """
    if QDRANT_MODE == "local":
        with _qdrant_op_lock:
            yield
    else:
        yield


@lru_cache(maxsize=512)
def _cached_embedding_tuple(text: str) -> tuple:
    """Helper to cache embeddings as immutable tuple."""
    if OPENAI_API_KEY:
        try:
            with httpx.Client(timeout=4.0) as client:
                res = client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={"input": text[:1000], "model": EMBEDDING_MODEL}
                )
                if res.status_code == 200:
                    data = res.json()
                    return tuple(data["data"][0]["embedding"])
        except Exception as e:
            print(f"[Warn] OpenAI query embedding error: {e}")

    # Deterministic fast fallback (< 1ms)
    seed = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
    vec = []
    for i in range(EMBEDDING_DIM):
        val = math.sin(seed + i)
        vec.append(val)
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return tuple(x / norm for x in vec)


def get_dense_query_embedding(text: str) -> List[float]:
    """Get 1536 dim dense vector with caching for < 100ms search speed."""
    return list(_cached_embedding_tuple(text.strip().lower()))


class ReviewActionRequest(BaseModel):
    review_action: str = Field(..., description="'APPROVE' 또는 'REJECT' (schemas.py 표준)")
    element_type: Optional[ElementType] = None
    caption: Optional[str] = Field(None, description="도표 제목/캡션 (schemas.py 표준)")
    summary: Optional[str] = None
    table_data: Optional[TableData] = Field(None, description="표 구조 데이터 (schemas.py 표준)")


@app.get("/api/version")
def get_api_version():
    """
    백엔드 API 버전, Git 커밋 및 필터 스키마 버전을 반환합니다.
    """
    return {
        "api_version": app.version,
        "git_commit": os.getenv("GIT_COMMIT", "unknown"),
        "filter_schema": "source_target",
    }


@app.get("/health")
def health_check():
    """
    서버 상태, Qdrant 연결 여부, 컬렉션 존재 여부 및 총 포인트 수를 반환합니다.
    """
    qdrant_connected = False
    collection_exists = False
    total_elements = 0
    error_message = None

    try:
        client = get_qdrant_client()
        with qdrant_call_guard():
            collections = client.get_collections().collections
            qdrant_connected = True
            collection_exists = any(c.name == QDRANT_COLLECTION for c in collections)
            if collection_exists:
                info = client.get_collection(QDRANT_COLLECTION)
                total_elements = info.points_count
    except Exception as e:
        error_message = str(e)

    return {
        "status": "ok",
        "service": "backend",
        "qdrant_mode": QDRANT_MODE,
        "qdrant_url": QDRANT_LOCAL_PATH if QDRANT_MODE == "local" else QDRANT_URL,
        "qdrant_connected": qdrant_connected,
        "collection_name": QDRANT_COLLECTION,
        "collection_exists": collection_exists,
        "total_elements": total_elements,
        "error": error_message
    }


@app.get("/health/memory")
def memory_health_check():
    """
    백엔드 프로세스 및 시스템 메모리 사용량을 실측하여 반환합니다.
    """
    import resource
    import shutil
    
    # Process RSS Memory (Linux cgroup/proc)
    rss_bytes = 0
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    # Format: VmRSS:     95400 kB
                    parts = line.split()
                    rss_bytes = int(parts[1]) * 1024
                    break
    except Exception:
        # Fallback to getrusage (KB in Linux)
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024

    # System Disk / Data Storage Check
    total, used, free = shutil.disk_usage(DATA_DIR if os.path.exists(DATA_DIR) else "/")

    # bge-m3 Model Specs (568M params)
    bge_m3_fp32_mb = 2270  # ~2.27 GB
    bge_m3_fp16_mb = 1140  # ~1.14 GB

    current_rss_mb = round(rss_bytes / (1024 * 1024), 2)

    return {
        "status": "ok",
        "current_backend_rss_mb": current_rss_mb,
        "current_backend_rss_gb": round(current_rss_mb / 1024, 3),
        "bge_m3_loading_simulation": {
            "model_name": "BAAI/bge-m3",
            "parameters": "568M",
            "estimated_with_fp32_total_mb": round(current_rss_mb + bge_m3_fp32_mb, 2),
            "estimated_with_fp16_total_mb": round(current_rss_mb + bge_m3_fp16_mb, 2),
            "estimated_with_fp16_total_gb": round((current_rss_mb + bge_m3_fp16_mb) / 1024, 2),
            "onpod_recommended_ram": "4GB RAM 이상 (최소 2GB는 FP16 시 OOM 위험)"
        },
        "disk_free_gb": round(free / (1024 ** 3), 2)
    }


_PAYLOAD_INDEXES_ENSURED = False
_IGNORED_FILTER_VALUES = {"증권사", "금융분석", "출처미상"}
_DOC_TYPE_ORDER = ("REPORT", "PUBLIC_REPORT", "PAPER", "IR")


def ensure_payload_indexes(client: QdrantClient) -> None:
    """source_org, doc_type, extra_metadata.target 페이로드 키워드 인덱스를 한 번만 보장합니다."""
    global _PAYLOAD_INDEXES_ENSURED
    if _PAYLOAD_INDEXES_ENSURED:
        return
    index_fields = ("doc_type", "source_org", "extra_metadata.target")
    with qdrant_call_guard():
        if _PAYLOAD_INDEXES_ENSURED:
            return
        for field_name in index_fields:
            try:
                client.create_payload_index(
                    collection_name=QDRANT_COLLECTION,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                # 이미 존재하거나 로컬 모드 제한 시 무시하고 계속 진행
                pass
        _PAYLOAD_INDEXES_ENSURED = True


@lru_cache(maxsize=1)
def load_entity_dictionary() -> List[EntityEntry]:
    """엔티티 사전(docs/glossary.md 10절)을 읽는다. 파일이 없으면 빈 목록 → 엔티티 필터 없이 검색."""
    if not os.path.exists(ENTITY_DICTIONARY_PATH):
        print(f"[Warn] 엔티티 사전 없음: {ENTITY_DICTIONARY_PATH}")
        return []
    with open(ENTITY_DICTIONARY_PATH, encoding="utf-8", newline="") as f:
        return [
            EntityEntry(
                entity_name=row["entity_name"].strip(),
                entity_type=row["entity_type"].strip(),
                aliases=[a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()],
                ticker=(row.get("ticker") or "").strip() or None,
            )
            for row in csv.DictReader(f)
        ]


def _contains_name(query: str, name: str) -> bool:
    """영문·숫자 이름(GS, HBM 등)은 단어 경계가 있을 때만, 한글 이름은 부분 문자열로 찾는다.

    ponytail: 영문 뒤 한글은 경계로 보지 않아 'KDI의'는 잡히지만 'GS리테일'도 GS로 잡힘.
    사전에 없는 회사가 문제 되면 형태소 분석(Kiwi)으로 바꾼다.
    """
    if re.fullmatch(r"[A-Za-z0-9&.\- ]+", name):
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", query, re.IGNORECASE) is not None
    return name in query


def match_entities(query: str) -> List[EntityEntry]:
    """검색어에 나온 별칭·대표 이름을 사전의 entity_name으로 바꾼다 ("하이닉스" → SK하이닉스)."""
    return [
        entry for entry in load_entity_dictionary()
        if any(_contains_name(query, name) for name in [entry.entity_name, *entry.aliases])
    ]


def build_entity_filter(entries: List[EntityEntry]) -> Optional[qmodels.Filter]:
    """찾은 엔티티 중 하나라도 entities 또는 extra_metadata.target에 있는 요소만 남기는 조건.

    저장 쪽 entities가 아직 entity_name으로 통일되지 않아 별칭까지 같이 비교한다
    (예: target에 'CJENM', 'KTnG'). 저장 쪽이 통일되면 entity_name만 남기면 된다.
    """
    if not entries:
        return None
    names = sorted({name for e in entries for name in [e.entity_name, *e.aliases]})
    return qmodels.Filter(should=[
        qmodels.FieldCondition(key="entities", match=qmodels.MatchAny(any=names)),
        qmodels.FieldCondition(key="extra_metadata.target", match=qmodels.MatchAny(any=names)),
    ])


HYBRID_PREFETCH_LIMIT = 50  # dense·sparse 각각 이만큼 후보를 뽑은 뒤 RRF로 합친다


def get_sparse_query_vector(text: str) -> Optional[qmodels.SparseVector]:
    """검색어 sparse 벡터. 색인과 같은 shared.sparse.build_sparse_vector를 써야 토큰 번호가 맞는다.
    Kiwi가 없거나 토큰이 없으면 None → dense만으로 검색."""
    try:
        from shared.sparse import build_sparse_vector
        tokens = build_sparse_vector(text)
    except (ImportError, RuntimeError) as e:
        print(f"[Warn] sparse 검색어 생성 실패, dense만 사용: {e}")
        return None
    if not tokens:
        return None
    return qmodels.SparseVector(indices=list(tokens.keys()), values=list(tokens.values()))


def hybrid_query(client: QdrantClient, dense_vector: List[float], sparse_vector: Optional[qmodels.SparseVector],
                 query_filter: Optional[qmodels.Filter], limit: int):
    """dense + sparse 후보를 각각 뽑아 RRF로 합친다. sparse가 없으면 dense만."""
    if sparse_vector is None:
        return client.query_points(collection_name=QDRANT_COLLECTION, query=dense_vector, using="dense",
                                   query_filter=query_filter, limit=limit)
    prefetch_limit = max(limit, HYBRID_PREFETCH_LIMIT)
    return client.query_points(
        collection_name=QDRANT_COLLECTION,
        prefetch=[
            qmodels.Prefetch(query=dense_vector, using="dense", filter=query_filter, limit=prefetch_limit),
            qmodels.Prefetch(query=sparse_vector, using="sparse", filter=query_filter, limit=prefetch_limit),
        ],
        query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
        limit=limit,
    )


@app.get("/api/elements", response_model=List[ElementSearchPayload])
def get_elements(
    query: Optional[str] = Query(None, description="자연어 문장 검색어 (Qdrant 시맨틱 벡터 검색)"),
    element_type: Optional[str] = Query(None, description="요소 유형 필터 (TABLE, CHART, DIAGRAM)"),
    doc_type: Optional[str] = Query(None, description="문서 유형 필터 (REPORT, PUBLIC_REPORT, PAPER, IR)"),
    source_org: Optional[str] = Query(None, description="출처 필터 (증권사, 발행기관, 학회·기관, 기업)"),
    target: Optional[str] = Query(None, description="대상 필터 (기업명, 주제, 논문 제목, 보고서명)"),
    publish_date: Optional[str] = Query(None, description="발행일 필터"),
    review_status: Optional[str] = Query(None, description="검수 상태 필터 (schemas.py 표준)"),
    status: Optional[str] = Query(None, description="검수 상태 필터 (하위 호환용, 미지정 시 APPROVED)"),
    limit: int = Query(60, ge=1, le=200, description="최대 조회 개수")
):
    """
    Qdrant DB에서 실제 색인된 도표·차트 요소를 검색하거나 최신순으로 가져옵니다.
    - 자연어 문장 검색: Qdrant dense vector cosine similarity
    - 메타데이터 필터: Qdrant payload Must filter (doc_type, source_org, extra_metadata.target 등)
    - 검색 결과: 승인(APPROVED)된 도표만 기본 노출 (검수 통과 시 즉시 반영)
    - 검색 응답 목표: 1초 이내 고속 응답
    """
    client = get_qdrant_client()
    elements: List[ElementSearchPayload] = []

    # Build payload filters if specified
    effective_status = review_status or status or ReviewStatus.APPROVED.value
    must_filters = []
    if effective_status and effective_status.upper() != "ALL":
        must_filters.append(
            qmodels.FieldCondition(
                key="review_status",
                match=qmodels.MatchValue(value=effective_status.upper())
            )
        )
    if element_type:
        must_filters.append(
            qmodels.FieldCondition(
                key="element_type",
                match=qmodels.MatchValue(value=element_type.upper())
            )
        )
    if doc_type:
        must_filters.append(
            qmodels.FieldCondition(
                key="doc_type",
                match=qmodels.MatchValue(value=doc_type.upper())
            )
        )
    if source_org:
        must_filters.append(
            qmodels.FieldCondition(
                key="source_org",
                match=qmodels.MatchValue(value=source_org)
            )
        )
    if target:
        must_filters.append(
            qmodels.FieldCondition(
                key="extra_metadata.target",
                match=qmodels.MatchValue(value=target)
            )
        )
    if publish_date:
        must_filters.append(
            qmodels.FieldCondition(
                key="publish_date",
                match=qmodels.MatchValue(value=publish_date)
            )
        )

    query_filter = qmodels.Filter(must=must_filters) if must_filters else None

    if query and query.strip():
        query_vector = get_dense_query_embedding(query.strip())
        sparse_vector = get_sparse_query_vector(query.strip())
        # 기업만 필터로 건다. 기관·제품은 저장 쪽 entities가 entity_name으로 통일되지 않아
        # (예: KDI 요소의 entities가 'KDIEconPolicy') 정답을 막는다. 통일되면 이 조건을 뺀다.
        entity_filter = build_entity_filter(
            [e for e in match_entities(query.strip()) if e.entity_type == EntityType.COMPANY]
        )
        with qdrant_call_guard():
            ensure_payload_indexes(client)
            search_response = hybrid_query(
                client, query_vector, sparse_vector,
                qmodels.Filter(must=[*must_filters, entity_filter]) if entity_filter else query_filter,
                limit,
            )
            # 엔티티 조건으로 하나도 안 나오면(저장 쪽 entities 누락 등) 엔티티 조건 없이 다시 찾는다
            if entity_filter and not search_response.points:
                search_response = hybrid_query(client, query_vector, sparse_vector, query_filter, limit)
        for hit in search_response.points:
            if hit.payload:
                try:
                    elements.append(ElementSearchPayload(**hit.payload))
                except Exception as e:
                    print(f"[Warn] Schema parsing error: {e}")
    else:
        with qdrant_call_guard():
            ensure_payload_indexes(client)
            records, _ = client.scroll(
                collection_name=QDRANT_COLLECTION,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False
            )
        for rec in records:
            if rec.payload:
                try:
                    elements.append(ElementSearchPayload(**rec.payload))
                except Exception as e:
                    print(f"[Warn] Schema parsing error: {e}")

    return elements


def _scroll_target_tables(target: str) -> List[Dict[str, Any]]:
    """대상(extra_metadata.target)의 승인된 TABLE 요소 payload를 모두 가져옵니다."""
    client = get_qdrant_client()
    scroll_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(key="extra_metadata.target", match=qmodels.MatchValue(value=target)),
            qmodels.FieldCondition(key="element_type", match=qmodels.MatchValue(value=ElementType.TABLE.value)),
            qmodels.FieldCondition(key="review_status", match=qmodels.MatchValue(value=ReviewStatus.APPROVED.value)),
        ]
    )
    payloads: List[Dict[str, Any]] = []
    next_offset = None
    with qdrant_call_guard():
        ensure_payload_indexes(client)
        while True:
            records, next_offset = client.scroll(
                collection_name=QDRANT_COLLECTION,
                scroll_filter=scroll_filter,
                limit=200,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            payloads.extend(rec.payload for rec in records if rec.payload)
            if next_offset is None:
                break
    return payloads


@app.get("/api/compare/metrics")
def get_compare_metrics(
    target: str = Query(..., description="비교 대상 (예: 롯데쇼핑). /api/filter-options의 targets 값"),
):
    """대상의 승인된 표에서 비교할 수 있는 지표와, 그 지표를 가진 문서 수를 돌려줍니다.

    문서 수가 2 이상인 지표만 실제 비교가 됩니다.
    """
    metrics = available_metrics(_scroll_target_tables(target))
    return {"target": target, "metrics": metrics}


@app.get("/api/compare", response_model=ComparisonResult)
def get_comparison(
    target: str = Query(..., description="비교 대상 (예: 롯데쇼핑)"),
    metric: str = Query(..., description="대표 지표명 (예: 영업이익). 목록은 /api/compare/metrics"),
    unit: Optional[str] = Query(None, description="원화 환산 단위 (원, 천원, 백만원, 억원, 십억원, 조원). 비우면 가장 많이 쓰인 단위"),
):
    """같은 대상의 여러 문서 표에서 같은 지표 × 같은 기간 값을 모아 돌려줍니다.

    - 원화 금액은 한 단위로 환산하고, 원문 값·단위는 raw_value·raw_unit에 그대로 둡니다.
    - 비율(%)·배수(배)는 환산하지 않습니다. 이름이 같아도 계산 기준이 다를 수 있으니 raw_row_label을 함께 보여 주세요.
    """
    from fastapi import HTTPException

    if metric not in METRIC_ALIASES:
        raise HTTPException(status_code=400, detail=f"알 수 없는 지표입니다: {metric}. 가능한 값: {list(METRIC_ALIASES)}")
    return build_comparison(_scroll_target_tables(target), target, metric, unit)


@app.get("/api/filter-options")
def get_filter_options():
    """
    드롭다운에 사용할 문서 유형별 출처(source_org), 대상(target), 발행일 목록을
    Qdrant 전체 포인트를 순회하여 동적으로 집계·반환합니다.
    """
    client = get_qdrant_client()

    doc_types_found = set()
    source_orgs_by_type: Dict[str, set] = {}
    targets_by_type: Dict[str, set] = {}
    dates = set()

    with qdrant_call_guard():
        ensure_payload_indexes(client)

        offset = None
        while True:
            records, next_offset = client.scroll(
                collection_name=QDRANT_COLLECTION,
                limit=300,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )

            for r in records:
                p = r.payload or {}
                dtype = str(p.get("doc_type") or "REPORT").strip().upper()
                if not dtype:
                    continue
                doc_types_found.add(dtype)
                source_orgs_by_type.setdefault(dtype, set())
                targets_by_type.setdefault(dtype, set())

                src = p.get("source_org")
                if isinstance(src, str):
                    src_clean = src.strip()
                    if src_clean and src_clean not in _IGNORED_FILTER_VALUES:
                        source_orgs_by_type[dtype].add(src_clean)

                extra = p.get("extra_metadata") or {}
                tgt = extra.get("target")
                if isinstance(tgt, str):
                    tgt_clean = tgt.strip()
                    if tgt_clean and tgt_clean not in _IGNORED_FILTER_VALUES:
                        targets_by_type[dtype].add(tgt_clean)

                pub_date = p.get("publish_date")
                if pub_date:
                    dates.add(str(pub_date))

            if next_offset is None:
                break
            offset = next_offset

    ordered_doc_types = [t for t in _DOC_TYPE_ORDER if t in doc_types_found]
    ordered_doc_types.extend(sorted(doc_types_found - set(_DOC_TYPE_ORDER)))

    return {
        "doc_types": ordered_doc_types,
        "source_orgs": {dt: sorted(source_orgs_by_type.get(dt, set())) for dt in ordered_doc_types},
        "targets": {dt: sorted(targets_by_type.get(dt, set())) for dt in ordered_doc_types},
        "publish_dates": sorted(dates, reverse=True),
        "element_types": ["TABLE", "CHART", "DIAGRAM"]
    }


@app.get("/api/search", response_model=List[ElementSearchPayload])
def search_elements_endpoint(
    q: str = Query(..., description="검색 쿼리"),
    element_type: Optional[str] = None,
    doc_type: Optional[str] = Query(None, description="문서 유형 필터 (REPORT, PUBLIC_REPORT, PAPER, IR)", examples=["REPORT"]),
    source_org: Optional[str] = Query(None, description="출처 필터 (증권 리포트면 증권사)", examples=["대신증권"]),
    publish_date: Optional[str] = Query(None, description="발행일 필터 (YYYY-MM-DD)", examples=["2026-10-30"]),
    limit: int = 20
):
    """시맨틱 하이브리드 검색 전용 엔드포인트"""
    # get_elements를 함수로 직접 부르면 FastAPI가 기본값(Query 객체)을 채우지 않으므로 나머지 인자를 None으로 넘긴다.
    return get_elements(
        query=q, element_type=element_type, doc_type=doc_type, source_org=source_org, target=None,
        publish_date=publish_date, review_status=None, status=None, limit=limit,
    )


@app.get("/api/review/elements", response_model=List[ElementSearchPayload])
def get_pending_review_elements(limit: int = 50, _auth: None = Depends(verify_admin_password)):
    """
    확신도 CONFIDENCE_THRESHOLD 미만 또는 검수 대기(PENDING_REVIEW) 상태인 도표 목록을 반환합니다.
    (관리자 비밀번호 인증 필요: Header 'X-Admin-Password')
    """
    client = get_qdrant_client()
    # Fetch items with review_status == PENDING_REVIEW or confidence_score < CONFIDENCE_THRESHOLD
    with qdrant_call_guard():
        records, _ = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=qmodels.Filter(
                should=[
                    qmodels.FieldCondition(
                        key="review_status",
                        match=qmodels.MatchValue(value=ReviewStatus.PENDING_REVIEW.value)
                    ),
                    qmodels.FieldCondition(
                        key="confidence_score",
                        range=qmodels.Range(lt=CONFIDENCE_THRESHOLD)
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
    elements = []
    for r in records:
        p = r.payload or {}
        # Exclude already approved or rejected
        if p.get("review_status") != ReviewStatus.REJECTED.value and (p.get("review_status") == ReviewStatus.PENDING_REVIEW.value or float(p.get("confidence_score", 1.0)) < CONFIDENCE_THRESHOLD):
            if p.get("review_status") != ReviewStatus.APPROVED.value:
                try:
                    elements.append(ElementSearchPayload(**p))
                except Exception as e:
                    print(f"[Warn] Parsing error in review element: {e}")
    return elements


@app.post("/api/review/{element_id}", response_model=ElementSearchPayload)
def submit_review_decision(element_id: str, req: ReviewActionRequest, _auth: None = Depends(verify_admin_password)):
    """
    관리자가 도표의 유형·제목·표 값을 수정한 뒤 승인(APPROVED) 또는 반려(REJECTED)합니다.
    (관리자 비밀번호 인증 필요: Header 'X-Admin-Password')
    승인 즉시 Qdrant DB의 review_status가 APPROVED로 변경되어 갤러리 검색 결과에 실시간 반영됩니다.
    """
    from fastapi import HTTPException
    client = get_qdrant_client()

    with qdrant_call_guard():
        results, _ = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="element_id",
                        match=qmodels.MatchValue(value=element_id)
                    )
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False
        )
        if not results or not results[0].payload:
            raise HTTPException(status_code=404, detail=f"도표 '{element_id}'를 찾을 수 없습니다.")

        point_id = results[0].id
        payload = dict(results[0].payload)
        before_payload = dict(payload)

        raw_action = req.review_action
        if not raw_action:
            raise HTTPException(status_code=400, detail="review_action은 필수입니다.")

        normalized_review_action = raw_action.upper()
        review_action: ReviewAction
        if normalized_review_action in ("APPROVE", ReviewStatus.APPROVED.value):
            review_action = ReviewAction.APPROVE
            payload["review_status"] = ReviewStatus.APPROVED.value
            payload["confidence_score"] = 1.0  # 관리자 검수 통과 완료
            if req.element_type:
                payload["element_type"] = req.element_type.value if hasattr(req.element_type, "value") else str(req.element_type).upper()
            if req.caption is not None:
                payload["caption"] = req.caption
            if req.summary:
                payload["summary"] = req.summary
            if req.table_data is not None:
                payload["table_data"] = req.table_data.model_dump() if hasattr(req.table_data, "model_dump") else (req.table_data.dict() if hasattr(req.table_data, "dict") else req.table_data)
        elif normalized_review_action in ("REJECT", ReviewStatus.REJECTED.value):
            review_action = ReviewAction.REJECT
            payload["review_status"] = ReviewStatus.REJECTED.value
        else:
            raise HTTPException(status_code=400, detail="review_action은 'APPROVE' 또는 'REJECT'여야 합니다.")

        review_fields = (
            "review_status",
            "confidence_score",
            "element_type",
            "caption",
            "summary",
            "table_data",
        )
        changed_fields = [
            field_name
            for field_name in review_fields
            if before_payload.get(field_name) != payload.get(field_name)
        ]
        if review_action == ReviewAction.APPROVE and any(
            field_name in changed_fields
            for field_name in ("element_type", "caption", "summary", "table_data")
        ):
            review_action = ReviewAction.EDIT

        # Update in Qdrant
        client.set_payload(
            collection_name=QDRANT_COLLECTION,
            payload=payload,
            points=[point_id]
        )

    review_log = ReviewLog(
        review_id=str(uuid.uuid4()),
        element_id=element_id,
        reviewer="admin",
        review_action=review_action,
        changed_fields=changed_fields,
        before={field_name: before_payload.get(field_name) for field_name in changed_fields},
        after={field_name: payload.get(field_name) for field_name in changed_fields},
        confidence_score=float(before_payload.get("confidence_score") or 0.0),
    )
    try:
        append_review_log(UPLOAD_DB_PATH, review_log)
    except Exception as error:
        print(f"[Error] ReviewLog 저장 실패 (element_id={element_id}): {error}")
        raise HTTPException(
            status_code=500,
            detail="검수 결과는 반영됐지만 검수 기록을 저장하지 못했습니다.",
        )

    return ElementSearchPayload(**payload)


@app.get("/api/elements/{element_id}", response_model=ElementSearchPayload)
def get_element_by_id(element_id: str):
    """
    단일 도표·차트 요소 상세 정보를 조회합니다.
    """
    from fastapi import HTTPException
    client = get_qdrant_client()
    with qdrant_call_guard():
        results, _ = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="element_id",
                        match=qmodels.MatchValue(value=element_id)
                    )
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False
        )
    if results and results[0].payload:
        return ElementSearchPayload(**results[0].payload)

    raise HTTPException(status_code=404, detail=f"도표 요소 '{element_id}'를 찾을 수 없습니다.")


# =====================================================================
# Document Table Comparison API
# =====================================================================
try:
    from compare.metrics import MetricType
    from compare.service import compare_company_metric
except ImportError:
    try:
        from figindex.compare.metrics import MetricType
        from figindex.compare.service import compare_company_metric
    except ImportError:
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
        from compare.metrics import MetricType
        from compare.service import compare_company_metric


class MatchedDocComparison(BaseModel):
    doc_name: str
    source_org: Optional[str] = None
    publish_date: Optional[str] = None
    matched: bool
    element_id: Optional[str] = None
    page_number: Optional[int] = None
    caption: Optional[str] = None
    match_score: float = 0.0
    second_candidate_element_id: Optional[str] = None
    table_data: Optional[TableData] = None
    match_status: str = "not_found"
    match_rule: Optional[str] = None


class AlignedComparisonRow(BaseModel):
    row_label: str
    raw_labels: Dict[str, str] = {}
    values: Dict[str, Dict[str, Any]] = {}


class CompareApiResponse(BaseModel):
    company: str
    metric: str
    documents: List[MatchedDocComparison]
    aligned_rows: List[AlignedComparisonRow]


# /api/compare는 비교 화면이 쓰는 shared.compare 엔진(glossary 14절)이다.
# 이 엔드포인트는 종목·지표 매칭 엔진(figindex/compare) 1차로, 경로를 나눠 함께 둔다.
@app.get("/api/compare/company", response_model=CompareApiResponse)
def get_compare_endpoint(
    company: str = Query(..., description="비교 대상 기업/종목명 (예: 카카오, 삼성전자)"),
    metric: MetricType = Query(..., description="비교 대상 지표 (TARGET_PRICE, ANNUAL_ESTIMATE, QUARTERLY_RESULT)"),
):
    """
    동일 종목 리포트 그룹 내에서 같은 지표의 TABLE을 매칭하고 행을 나란히 정렬하여 반환합니다.
    """
    res = compare_company_metric(
        company=company,
        metric=metric,
        qdrant_url=QDRANT_URL,
        collection_name=QDRANT_COLLECTION,
    )
    return res

