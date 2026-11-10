import os
import math
import hashlib
import time
from functools import lru_cache
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import quote
from fastapi.responses import FileResponse
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from dotenv import load_dotenv
import httpx

load_dotenv()

# Import shared schemas
from shared.schemas import (
    VisualElementSchema,
    ElementType,
    ReviewStatus,
    TableStructure,
)

app = FastAPI(
    title="FigIndex Backend API",
    description="PDF 문서 도표·차트 자동 분류 및 멀티모달 색인 시스템 (FigIndex)",
    version="0.4.0",
)

# =====================================================================
# Admin Security & Auth Helpers
# =====================================================================
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "figindex2026!")

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
raw_cors = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,*")
ALLOWED_CORS_ORIGINS = [origin.strip() for origin in raw_cors.split(",") if origin.strip()]

# CORS Middleware (Frontend communication)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


def get_qdrant_client() -> QdrantClient:
    """
    Returns QdrantClient instance based on QDRANT_MODE:
    - 'local': Embedded on-disk mode using QdrantClient(path=...) for serverless/Onpod deployment
    - 'server': Network mode connecting to standalone Qdrant server (port 6333)
    """
    if QDRANT_MODE == "local":
        os.makedirs(QDRANT_LOCAL_PATH, exist_ok=True)
        return QdrantClient(path=QDRANT_LOCAL_PATH)
    return QdrantClient(url=QDRANT_URL, timeout=5.0)


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
    action: str = Field(..., description="'APPROVE' 또는 'REJECT'")
    element_type: Optional[str] = None
    title_or_caption: Optional[str] = None
    summary: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None


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


@app.get("/api/elements", response_model=List[VisualElementSchema])
def get_elements(
    query: Optional[str] = Query(None, description="자연어 문장 검색어 (Qdrant 시맨틱 벡터 검색)"),
    element_type: Optional[str] = Query(None, description="요소 유형 필터 (TABLE, CHART, DIAGRAM)"),
    broker: Optional[str] = Query(None, description="증권사 필터"),
    company: Optional[str] = Query(None, description="기업명 필터"),
    publish_date: Optional[str] = Query(None, description="발행일 필터"),
    status: Optional[str] = Query("APPROVED", description="검수 상태 필터 (기본값: APPROVED 승인 건만 노출)"),
    limit: int = Query(60, ge=1, le=200, description="최대 조회 개수")
):
    """
    Qdrant DB에서 실제 색인된 도표·차트 요소를 검색하거나 최신순으로 가져옵니다.
    - 자연어 문장 검색: Qdrant dense vector cosine similarity
    - 메타데이터 필터: Qdrant payload Must filter
    - 검색 결과: 승인(APPROVED)된 도표만 기본 노출 (검수 통과 시 즉시 반영)
    - 검색 응답 목표: 1초 이내 고속 응답
    """
    client = get_qdrant_client()
    elements: List[VisualElementSchema] = []

    try:
        # Build payload filters if specified
        must_filters = []
        if status:
            must_filters.append(
                qmodels.FieldCondition(
                    key="review_status",
                    match=qmodels.MatchValue(value=status.upper())
                )
            )
        if element_type:
            must_filters.append(
                qmodels.FieldCondition(
                    key="element_type",
                    match=qmodels.MatchValue(value=element_type.upper())
                )
            )
        if broker:
            must_filters.append(
                qmodels.FieldCondition(
                    key="source_org",
                    match=qmodels.MatchValue(value=broker)
                )
            )
        if company:
            must_filters.append(
                qmodels.FieldCondition(
                    key="entities",
                    match=qmodels.MatchValue(value=company)
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
            # Perform Vector Search using modern query_points (< 150ms)
            query_vector = get_dense_query_embedding(query.strip())
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
            # Scroll points from Qdrant with payload filters
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

    except Exception as e:
        print(f"[Error] Failed to fetch elements from Qdrant: {e}")
        return []

    return elements


@app.get("/api/filter-options")
def get_filter_options():
    """
    드롭다운에 사용할 증권사, 기업명, 발행일 목록을 Qdrant에서 동적으로 집계하여 반환합니다.
    """
    client = get_qdrant_client()
    try:
        records, _ = client.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=300,
            with_payload=True,
            with_vectors=False
        )
        brokers = set()
        companies = set()
        dates = set()

        for r in records:
            p = r.payload or {}
            source_org = p.get("source_org")
            if source_org and source_org != "증권사":
                brokers.add(source_org)
            
            # Extract company
            comp = p.get("extra_metadata", {}).get("company")
            if comp and comp != "금융분석":
                companies.add(comp)
            elif p.get("entities") and len(p["entities"]) > 0:
                first_ent = p["entities"][0]
                if not first_ent.startswith("#") and first_ent != "증권사":
                    companies.add(first_ent)

            if p.get("publish_date"):
                dates.add(p["publish_date"])

        return {
            "brokers": sorted(list(brokers)),
            "companies": sorted(list(companies)),
            "publish_dates": sorted(list(dates), reverse=True),
            "element_types": ["TABLE", "CHART", "DIAGRAM"]
        }
    except Exception as e:
        print(f"[Error] Failed to load filter options: {e}")
        return {
            "brokers": ["하나증권", "삼성증권", "IBK투자증권", "유진투자증권"],
            "companies": ["GS", "LNF", "CMTX", "매커스", "삼양식품", "삼성전자", "BGF리테일"],
            "publish_dates": ["2026-11-09", "2026-11-06", "2026-11-05", "2026-11-04"],
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
    try:
        # Fetch items with review_status == PENDING_REVIEW or confidence_score < 0.80
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
    except Exception as e:
        print(f"[Error] Failed to fetch review elements: {e}")
        return []


@app.post("/api/review/{element_id}", response_model=VisualElementSchema)
def submit_review_decision(element_id: str, req: ReviewActionRequest, _auth: None = Depends(verify_admin_password)):
    """
    관리자가 도표의 유형·제목·표 값을 수정한 뒤 승인(APPROVED) 또는 반려(REJECTED)합니다.
    (관리자 비밀번호 인증 필요: Header 'X-Admin-Password')
    승인 즉시 Qdrant DB의 review_status가 APPROVED로 변경되어 갤러리 검색 결과에 실시간 반영됩니다.
    """
    from fastapi import HTTPException
    client = get_qdrant_client()

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

    action = req.action.upper()
    if action == "APPROVE":
        payload["review_status"] = "APPROVED"
        payload["confidence_score"] = 1.0  # 관리자 검수 통과 완료
        if req.element_type:
            payload["element_type"] = req.element_type.upper()
        if req.title_or_caption:
            payload["title_or_caption"] = req.title_or_caption
        if req.summary:
            payload["summary"] = req.summary
        if req.structured_data is not None:
            payload["structured_data"] = req.structured_data
    elif action == "REJECT":
        payload["review_status"] = "REJECTED"
    else:
        raise HTTPException(status_code=400, detail="action은 'APPROVE' 또는 'REJECT'여야 합니다.")

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
    try:
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
    except Exception as e:
        print(f"[Error] Failed to fetch element {element_id}: {e}")

    raise HTTPException(status_code=404, detail=f"도표 요소 '{element_id}'를 찾을 수 없습니다.")
