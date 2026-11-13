# 임시 호환용. 프롬프트 4(코드 치환) 완료 후 삭제. 새 코드에서 import 금지.
from datetime import date
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from shared.schemas import ElementType, ReviewStatus


class TableStructure(BaseModel):
    """structured_data 내부 스키마"""
    columns: List[str] = Field(..., description="열 헤더 목록")
    rows: List[Dict[str, Any]] = Field(..., description="행 데이터 목록")
    unit: Optional[str] = Field(None, description="수치 단위 (예: %, 천 명, 백만 달러)")
    period_labels: List[str] = Field(default_factory=list, description="기간 레이블 (예: ['2023', '2024', '2025E'])")


class VisualElementSchema(BaseModel):
    element_id: str = Field(..., description="시각 요소 고유 식별자 (UUIDv4)")
    doc_name: str = Field(..., description="원본 PDF 파일명")
    page_number: int = Field(..., description="해당 요소가 위치한 PDF 페이지 번호 (1-based)")
    bbox: List[float] = Field(..., description="크롭 바운딩 박스 정규 좌표 [ymin, xmin, ymax, xmax]")
    element_type: ElementType = Field(..., description="시각 요소 분류 (TABLE, CHART, DIAGRAM)")
    image_path: str = Field(..., description="크롭된 이미지 저장 경로 (/static/crops/...)")
    title_or_caption: str = Field(..., description="도표 제목 또는 식별 캡션")
    summary: str = Field(..., description="멀티모달 모델이 생성한 핵심 내용 2~3줄 요약")
    structured_data: Optional[TableStructure] = Field(None, description="표 수치 구조화 데이터")
    hashtags: List[str] = Field(default_factory=list, description="연관 검색 태그 및 키워드")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="재정규화 다중 신호 가중합 확신도")
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING_REVIEW, description="검수 상태 (기본값 PENDING_REVIEW, 0.80 이상 시 APPROVED 승격)")

    # 문서 단위 공통 메타데이터 (1회 추출 후 도표에 상속, Qdrant Payload 필터용)
    doc_title: str = Field(..., description="문서 제목")
    doc_type: str = Field(..., description="문서 유형 (예: REPORT, PAPER, PUBLIC_REPORT, IR)")
    domain: Optional[str] = Field(None, description="주제 분야 (예: 에너지, 반도체, 보건)")
    source_org: Optional[str] = Field(None, description="발행 기관/출처 (예: 연구기관, 기업, 학회)")
    authors: List[str] = Field(default_factory=list, description="저자 목록")
    publish_date: Optional[date] = Field(None, description="발행일 (YYYY-MM-DD)")
    entities: List[str] = Field(default_factory=list, description="문서·도표에 등장하는 고유명사 (기관명, 기업명, 제품명 등)")

    # 도메인별 확장 메타데이터 (예: 리포트의 대상 기업·종목코드, 논문의 학회명)
    extra_metadata: Dict[str, Any] = Field(default_factory=dict, description="도메인별 추가 필드")

