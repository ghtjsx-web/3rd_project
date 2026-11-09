from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.schemas import (
    VisualElementSchema,
    SearchQueryRequest,
    SearchResponse,
    ReviewUpdateRequest,
)
from app.services.search import HybridSearchService
from app.pipeline.orchestrator import ExtractionPipelineOrchestrator

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="금융·산업 리서치 리포트 도표·차트 자동 분류 및 멀티모달 색인 시스템 (FigIndex)",
    version="0.3.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for cropped images and sample PDFs
app.mount("/static/crops", StaticFiles(directory=str(settings.CROPS_DIR)), name="crops")
app.mount("/static/pdfs", StaticFiles(directory=str(settings.SAMPLE_PDFS_DIR)), name="pdfs")

# Services
search_service = HybridSearchService()
orchestrator = ExtractionPipelineOrchestrator()


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "version": "0.3.0",
        "vision_model": settings.VISION_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL
    }


@app.post(f"{settings.API_V1_PREFIX}/search", response_model=SearchResponse)
def search_elements(req: SearchQueryRequest):
    """
    하이브리드 검색 엔드포인트:
    - Dense Vector (1536차원 시맨틱 검색)
    - Kiwi 형태소 분석 기반 한국어 BM25
    - Qdrant Payload 필터 (기업명, 종목코드, 증권사, 도표유형 등)
    """
    return search_service.search(req)


@app.post(f"{settings.API_V1_PREFIX}/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """
    PDF 리포트 업로드 및 비동기 색인 파이프라인 트리거
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    save_path = settings.SAMPLE_PDFS_DIR / file.filename
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    # Trigger background indexing
    background_tasks.add_task(orchestrator.process_pdf, save_path)

    return {
        "message": "PDF uploaded successfully. Extraction pipeline started in background.",
        "filename": file.filename,
        "file_size": len(content)
    }


@app.patch(f"{settings.API_V1_PREFIX}/review/{{element_id}}")
def review_element(element_id: str, update_req: ReviewUpdateRequest):
    """
    Human-in-the-Loop 관리자 검수 상태 및 메타데이터 업데이트 (APPROVED / REJECTED)
    """
    # In production, updates RDB and Qdrant payload
    return {
        "element_id": element_id,
        "updated_status": update_req.review_status,
        "message": f"Element {element_id} status updated to {update_req.review_status}."
    }

