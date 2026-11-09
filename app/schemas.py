from datetime import date
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ElementType(str, Enum):
    TABLE = "TABLE"
    CHART = "CHART"
    DIAGRAM = "DIAGRAM"


class ReviewStatus(str, Enum):
    APPROVED = "APPROVED"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"


class TableStructure(BaseModel):
    """structured_data 내부 스키마"""
    columns: List[str] = Field(..., description="열 헤더 목록")
    rows: List[Dict[str, Any]] = Field(..., description="행 데이터 목록")
    unit: Optional[str] = Field(None, description="수치 단위 (예: 십억원, %, 달러)")
    period_labels: List[str] = Field(default_factory=list, description="기간 레이블 (예: ['2023', '2024E', '2025E'])")


class VisualElementSchema(BaseModel):
    element_id: str = Field(..., description="시각 요소 고유 식별자 (UUIDv4)")
    doc_name: str = Field(..., description="원본 PDF 파일명 (예: 20250106_SK하이닉스_삼성증권.pdf)")
    page_number: int = Field(..., description="해당 요소가 위치한 PDF 페이지 번호 (1-based)")
    bbox: List[float] = Field(..., description="크롭 바운딩 박스 정규 좌표 [ymin, xmin, ymax, xmax]")
    element_type: ElementType = Field(..., description="시각 요소 분류 (TABLE, CHART, DIAGRAM)")
    image_path: str = Field(..., description="크롭된 이미지 저장 경로 (/static/crops/...)")
    title_or_caption: str = Field(..., description="도표의 상단 제목 또는 식별 캡션")
    summary: str = Field(..., description="멀티모달 모델이 생성한 핵심 내용 2~3줄 요약")
    structured_data: Optional[TableStructure] = Field(None, description="표 수치 구조화 정형 데이터")
    hashtags: List[str] = Field(default_factory=list, description="연관 검색 태그 및 키워드 목록")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="재정규화 다중 신호 가중합 확신도 (0.0 ~ 1.0)")
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING_REVIEW, description="검수 상태 (기본값 PENDING_REVIEW, 0.80 이상 시 APPROVED 승격)")

    # Qdrant Payload 필터 지원 필드 (문서 단위 1회 추출 후 도표에 상속)
    company: str = Field(..., description="대상 기업명 (예: SK하이닉스)")
    ticker: Optional[str] = Field(None, description="종목코드 (예: 000660)")
    broker: str = Field(..., description="발행 증권사 (예: 삼성증권)")
    publish_date: date = Field(..., description="리포트 발행일자 (YYYY-MM-DD)")
    analyst: Optional[str] = Field(None, description="작성 애널리스트명")
    industry: str = Field(..., description="산업 분류 (예: 반도체)")


class SearchQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="검색 질의어")
    element_type: Optional[ElementType] = Field(None, description="도표 유형 필터")
    company: Optional[str] = Field(None, description="기업명 필터 (Qdrant payload)")
    ticker: Optional[str] = Field(None, description="종목코드 필터 (Qdrant payload)")
    broker: Optional[str] = Field(None, description="증권사 필터 (Qdrant payload)")
    industry: Optional[str] = Field(None, description="산업 필터 (Qdrant payload)")
    limit: int = Field(default=10, ge=1, le=50, description="조회 결과 개수")
    offset: int = Field(default=0, ge=0, description="페이지 오프셋")


class SearchResponse(BaseModel):
    total: int
    items: List[VisualElementSchema]
    execution_time_ms: float


class ReviewUpdateRequest(BaseModel):
    element_type: Optional[ElementType] = None
    title_or_caption: Optional[str] = None
    summary: Optional[str] = None
    hashtags: Optional[List[str]] = None
    review_status: ReviewStatus
