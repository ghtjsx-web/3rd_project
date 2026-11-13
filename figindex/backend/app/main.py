import os
import math
import hashlib
import time
import threading
import traceback
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, Query, Header, Depends, Request
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
    ReviewStatus,
)
from shared.schemas_legacy import (
    VisualElementSchema,
    TableStructure,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """앱 수명주기 관리: 종료 시에만 단일 QdrantClient를 정리합니다."""
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
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "figindex_elements")

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
    review_action: Optional[str] = Field(None, description="'APPROVE' 또는 'REJECT' (schemas.py 표준)")
    action: Optional[str] = Field(None, description="'APPROVE' 또는 'REJECT' (하위 호환용)")
    element_type: Optional[str] = None
    caption: Optional[str] = Field(None, description="도표 제목/캡션 (schemas.py 표준)")
    title_or_caption: Optional[str] = Field(None, description="도표 제목/캡션 (하위 호환용)")
    summary: Optional[str] = None
    table_data: Optional[Dict[str, Any]] = Field(None, description="표 구조 데이터 (schemas.py 표준)")
    structured_data: Optional[Dict[str, Any]] = Field(None, description="표 구조 데이터 (하위 호환용)")


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


@app.get("/api/elements", response_model=List[VisualElementSchema])
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
    elements: List[VisualElementSchema] = []

    # Build payload filters if specified
    effective_status = review_status or status or "APPROVED"
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
        with qdrant_call_guard():
            ensure_payload_indexes(client)
            search_response = client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=query_vector,
                using="dense",
                query_filter=query_filter,
                limit=limit
            )
        for hit in search_response.points:
            if hit.payload:
                try:
                    elements.append(VisualElementSchema(**hit.payload))
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
                    elements.append(VisualElementSchema(**rec.payload))
                except Exception as e:
                    print(f"[Warn] Schema parsing error: {e}")

    return elements


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


@app.get("/api/search", response_model=List[VisualElementSchema])
def search_elements_endpoint(
    q: str = Query(..., description="검색 쿼리"),
    element_type: Optional[str] = None,
    limit: int = 20
):
    """시맨틱 하이브리드 검색 전용 엔드포인트"""
    return get_elements(query=q, element_type=element_type, limit=limit)


@app.get("/api/review/elements", response_model=List[VisualElementSchema])
def get_pending_review_elements(limit: int = 50, _auth: None = Depends(verify_admin_password)):
    """
    확신도 0.80 미만 또는 검수 대기(PENDING_REVIEW) 상태인 도표 목록을 반환합니다.
    (관리자 비밀번호 인증 필요: Header 'X-Admin-Password')
    """
    client = get_qdrant_client()
    # Fetch items with review_status == PENDING_REVIEW or confidence_score < 0.80
    with qdrant_call_guard():
        records, _ = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=qmodels.Filter(
                should=[
                    qmodels.FieldCondition(
                        key="review_status",
                        match=qmodels.MatchValue(value="PENDING_REVIEW")
                    ),
                    qmodels.FieldCondition(
                        key="confidence_score",
                        range=qmodels.Range(lt=0.80)
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
        if p.get("review_status") != "REJECTED" and (p.get("review_status") == "PENDING_REVIEW" or float(p.get("confidence_score", 1.0)) < 0.80):
            if p.get("review_status") != "APPROVED":
                try:
                    elements.append(VisualElementSchema(**p))
                except Exception as e:
                    print(f"[Warn] Parsing error in review element: {e}")
    return elements


@app.post("/api/review/{element_id}", response_model=VisualElementSchema)
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

        raw_action = req.review_action or req.action
        if not raw_action:
            raise HTTPException(status_code=400, detail="review_action(또는 action)은 필수입니다.")

        action = raw_action.upper()
        if action == "APPROVE":
            payload["review_status"] = "APPROVED"
            payload["confidence_score"] = 1.0  # 관리자 검수 통과 완료
            if req.element_type:
                payload["element_type"] = req.element_type.upper()
            caption = req.caption if req.caption is not None else req.title_or_caption
            if caption is not None:
                payload["title_or_caption"] = caption
            if req.summary:
                payload["summary"] = req.summary
            table_data = req.table_data if req.table_data is not None else req.structured_data
            if table_data is not None:
                payload["structured_data"] = table_data
        elif action == "REJECT":
            payload["review_status"] = "REJECTED"
        else:
            raise HTTPException(status_code=400, detail="review_action은 'APPROVE' 또는 'REJECT'여야 합니다.")

        # Update in Qdrant
        client.set_payload(
            collection_name=QDRANT_COLLECTION,
            payload=payload,
            points=[point_id]
        )

    return VisualElementSchema(**payload)


@app.get("/api/elements/{element_id}", response_model=VisualElementSchema)
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
        return VisualElementSchema(**results[0].payload)

    raise HTTPException(status_code=404, detail=f"도표 요소 '{element_id}'를 찾을 수 없습니다.")
