"""
FigIndex 공통 스키마 — 모든 이름의 유일한 기준 (Single Source of Truth)

규칙
- 필드명·상태값·유형명은 이 파일에서만 정의한다. 다른 코드는 import해서 쓴다.
- 문자열 리터럴("APPROVED" 등)을 코드에 직접 쓰지 않는다. Enum을 쓴다.
- 이 파일을 바꾸려면 docs/glossary.md와 함께 PR을 올리고 팀장 승인을 받는다.
- 용어 정의는 docs/glossary.md 참고.
"""
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD: float = 0.80   # 이 값 이상이면 APPROVED
PIPELINE_VERSION: str = "0.1.0"      # 추출 로직(프롬프트·후처리)을 바꾸면 올린다
ENTITY_DICTIONARY_PATH: str = "data/entity_dictionary.csv"


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

class ElementType(str, Enum):
    """요소 유형. 사진·로고·장식은 요소로 저장하지 않는다(노이즈로 제외)."""
    TABLE = "TABLE"      # 표: 행·열로 된 수치/텍스트
    CHART = "CHART"      # 차트: 막대·선·원 등 수치를 그린 그래프
    DIAGRAM = "DIAGRAM"  # 다이어그램: 구조·흐름·관계도 (수치 없음)


class DocStatus(str, Enum):
    """문서 처리 상태 (대량 등록·진행 화면용)."""
    UPLOADED = "UPLOADED"        # 업로드됨: 파일 저장 완료, 처리 대기
    PROCESSING = "PROCESSING"    # 처리 중
    COMPLETED = "COMPLETED"      # 완료: 모든 요소 추출 끝
    FAILED = "FAILED"            # 실패: doc_error에 사유 기록
    DUPLICATE = "DUPLICATE"      # 중복: 같은 doc_hash가 이미 있어 처리하지 않음


class ReviewStatus(str, Enum):
    """요소 검수 상태. 문서 처리 상태(DocStatus)와 섞어 쓰지 않는다."""
    APPROVED = "APPROVED"              # 승인: 검색에 노출
    PENDING_REVIEW = "PENDING_REVIEW"  # 검수 대기: confidence_score < CONFIDENCE_THRESHOLD
    REJECTED = "REJECTED"              # 반려: 검색 제외


class ReviewAction(str, Enum):
    """검수자가 한 행동 (ReviewLog용)."""
    APPROVE = "APPROVE"  # 수정 없이 승인
    EDIT = "EDIT"        # 필드를 고친 뒤 승인
    REJECT = "REJECT"    # 반려


class LayoutClass(str, Enum):
    """DocLayout-YOLO 탐지 클래스 (모델 출력 이름 그대로).

    주의: 사용하는 체크포인트의 model.names와 값이 같은지 1단계에서 확인한다.
    ElementType과의 대응은 LAYOUT_TO_ELEMENT 참고.
    """
    TITLE = "title"
    PLAIN_TEXT = "plain text"
    ABANDON = "abandon"                  # 머리말·꼬리말·쪽번호 등
    FIGURE = "figure"
    FIGURE_CAPTION = "figure_caption"
    TABLE = "table"
    TABLE_CAPTION = "table_caption"
    TABLE_FOOTNOTE = "table_footnote"
    ISOLATE_FORMULA = "isolate_formula"
    FORMULA_CAPTION = "formula_caption"


# 본 박스 → 요소 유형. figure는 CHART/DIAGRAM을 Vision LLM이 정한다(None).
# 여기 없는 클래스는 요소가 되지 않는다(캡션·각주는 본 박스에 병합, 나머지는 버림).
LAYOUT_TO_ELEMENT: Dict[LayoutClass, Optional[ElementType]] = {
    LayoutClass.TABLE: ElementType.TABLE,
    LayoutClass.FIGURE: None,
}

# 본 박스에 병합(Union BBox)하는 클래스
MERGE_CLASSES = {
    LayoutClass.FIGURE_CAPTION,
    LayoutClass.TABLE_CAPTION,
    LayoutClass.TABLE_FOOTNOTE,
}


class EntityType(str, Enum):
    """엔티티 사전의 고유명사 종류."""
    COMPANY = "COMPANY"  # 기업
    ORG = "ORG"          # 기관·협회·정부 부처
    PRODUCT = "PRODUCT"  # 제품·기술명
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# 좌표
# ---------------------------------------------------------------------------
# bbox = [x0, y0, x1, y1], 페이지 크기 대비 0~1 정규화, 좌상단 원점.
# PyMuPDF(pt)·YOLO(px)·화면(px) 간 변환은 app/coords.py 함수로만 한다.
BBox = List[float]


# ---------------------------------------------------------------------------
# 등록 작업 · 문서 · 페이지
# ---------------------------------------------------------------------------

class Batch(BaseModel):
    """한 번에 올린 PDF 묶음 (등록 작업). 진행률·재시도의 기준 단위."""
    batch_id: str = Field(..., description="등록 작업 고유 ID (UUIDv4)")
    collection_id: Optional[str] = Field(None, description="이 작업으로 등록한 문서가 들어갈 컬렉션")
    doc_count: int = Field(0, ge=0, description="작업에 포함된 문서 수")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # 진행률(완료·실패 수)은 저장하지 않고 소속 문서의 doc_status를 세어 계산한다.


class Collection(BaseModel):
    """문서 묶음 (폴더 개념)."""
    collection_id: str = Field(..., description="컬렉션 고유 ID (UUIDv4)")
    collection_name: str = Field(..., description="컬렉션 이름")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Document(BaseModel):
    """등록된 PDF 1건."""
    doc_id: str = Field(..., description="문서 고유 ID (UUIDv4)")
    batch_id: Optional[str] = Field(None, description="소속 등록 작업 ID")
    doc_hash: str = Field(..., description="파일 내용 SHA-256 (16진수 소문자). 중복 판정 기준")
    doc_name: str = Field(..., description="원본 파일명 (예: 2026_semiconductor.pdf)")
    doc_title: Optional[str] = Field(None, description="문서 제목 (처리 중 추출)")
    doc_type: Optional[str] = Field(None, description="문서 유형 (예: REPORT, PAPER, PUBLIC_REPORT, IR)")
    domain: Optional[str] = Field(None, description="주제 분야 (예: 반도체)")
    source_org: Optional[str] = Field(None, description="발행 기관 (예: 증권사명)")
    authors: List[str] = Field(default_factory=list, description="저자 목록")
    publish_date: Optional[date] = Field(None, description="발행일")
    page_count: Optional[int] = Field(None, description="전체 페이지 수")
    collection_id: Optional[str] = Field(None, description="소속 컬렉션 ID")
    doc_status: DocStatus = Field(default=DocStatus.UPLOADED, description="문서 처리 상태")
    doc_error: Optional[str] = Field(None, description="FAILED일 때 실패 사유, DUPLICATE일 때 기존 doc_id")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="등록 시각 (UTC)")
    extra_metadata: Dict[str, Any] = Field(default_factory=dict, description="도메인별 확장 필드 (예: {'ticker': '000660'})")


class Page(BaseModel):
    """문서의 페이지 1장 정보. 좌표 변환과 확신도 계산에 쓴다."""
    doc_id: str
    page_number: int = Field(..., ge=1, description="PDF 파일상 순서 (1부터)")
    width_pt: float = Field(..., gt=0, description="페이지 너비 (PDF pt)")
    height_pt: float = Field(..., gt=0, description="페이지 높이 (PDF pt)")
    has_text_layer: bool = Field(..., description="추출 가능한 텍스트 레이어가 있는지")


# ---------------------------------------------------------------------------
# 탐지 결과
# ---------------------------------------------------------------------------

class Detection(BaseModel):
    """DocLayout-YOLO가 낸 원시 박스 1개. 크롭 전 단계이며 요소(Element)가 아니다."""
    detection_id: str = Field(..., description="탐지 결과 고유 ID (UUIDv4)")
    doc_id: str
    page_number: int = Field(..., ge=1)
    layout_class: LayoutClass = Field(..., description="모델이 붙인 클래스")
    bbox: BBox = Field(..., min_length=4, max_length=4, description="패딩·병합 전 원래 박스, 0~1 정규화")
    detection_score: float = Field(..., ge=0.0, le=1.0, description="모델 탐지 신뢰도")
    element_id: Optional[str] = Field(None, description="이 박스가 들어간 요소 ID (본 박스·병합된 캡션). 버려졌으면 None")


# ---------------------------------------------------------------------------
# 요소
# ---------------------------------------------------------------------------

CellValue = Union[float, int, str, None]


class TableData(BaseModel):
    """TABLE 요소의 수치 구조화 데이터.

    셀 값 규칙
    - 숫자로 읽히면 숫자로 저장 (쉼표 제거)
    - 음수 표기(△1.2, (1.2) 등)는 음수 숫자로 변환 (-1.2)
    - 단위는 셀에 넣지 않고 unit에만 기록
    - 숫자로 읽을 수 없는 셀(-, n/a, 텍스트)은 원문 문자열 그대로
    """
    columns: List[str] = Field(..., description="열 헤더 목록 (원문 그대로, 예: ['구분', '2024', '2025E'])")
    rows: List[Dict[str, CellValue]] = Field(..., description="행 목록. 키는 columns 값과 정확히 일치")
    unit: Optional[str] = Field(None, description="수치 단위 (예: 억 원, %, 원)")
    period_labels: List[str] = Field(default_factory=list, description="기간 라벨, 원문 그대로 (추정치 E 포함)")


class ConfidenceSignals(BaseModel):
    """확신도 계산에 쓴 신호. 적용하지 않은 신호는 None (재정규화에서 제외)."""
    detection_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="신호1: 탐지 신뢰도")
    schema_valid: Optional[float] = Field(None, ge=0.0, le=1.0, description="신호2: 스키마 검증 통과 0 또는 1")
    numeric_consistency: Optional[float] = Field(None, ge=0.0, le=1.0, description="신호3: 합계·열 개수 정합성 (TABLE만)")
    self_consistency: Optional[float] = Field(None, ge=0.0, le=1.0, description="신호4: 2회 추론 일치도 (조건부 실행)")
    text_match: Optional[float] = Field(None, ge=0.0, le=1.0, description="신호5: 텍스트 레이어와 수치 일치율 (TABLE + has_text_layer)")


# 신호별 기본 가중치. 적용한 신호만 골라 합이 1이 되도록 재정규화한다.
SIGNAL_WEIGHTS: Dict[str, float] = {
    "detection_score": 0.20,
    "schema_valid": 0.25,
    "numeric_consistency": 0.25,
    "self_consistency": 0.15,
    "text_match": 0.15,
}


class Element(BaseModel):
    """문서에서 추출한 표·차트·다이어그램 1개. 시스템의 기본 단위."""
    element_id: str = Field(..., description="요소 고유 ID (UUIDv4)")
    doc_id: str = Field(..., description="소속 문서 ID")
    page_number: int = Field(..., ge=1, description="PDF 파일상 페이지 순서 (1부터). 인쇄된 쪽번호 아님")
    bbox: BBox = Field(..., min_length=4, max_length=4, description="[x0, y0, x1, y1], 0~1 정규화, 좌상단 원점, 병합·패딩 포함")
    element_type: ElementType = Field(..., description="요소 유형")
    image_path: str = Field(..., description="크롭 이미지 경로 (/static/crops/{element_id}.png)")
    caption: str = Field("", description="요소 제목 또는 캡션 (원문 그대로, 없으면 빈 문자열)")
    summary: str = Field("", description="AI 생성 요약 2~3줄")
    hashtags: List[str] = Field(default_factory=list, description="검색 태그 ('#' 없이 저장)")
    entities: List[str] = Field(default_factory=list, description="고유명사. 엔티티 사전에 있으면 사전의 entity_name으로 저장")
    table_data: Optional[TableData] = Field(None, description="TABLE일 때만 값이 있음")
    signals: ConfidenceSignals = Field(default_factory=ConfidenceSignals, description="확신도 신호")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="재정규화 가중합 확신도")
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING_REVIEW, description="검수 상태")
    pipeline_version: str = Field(default=PIPELINE_VERSION, description="추출 당시 PIPELINE_VERSION")
    model_name: str = Field(..., description="추출에 쓴 Vision 모델 이름 (VISION_MODEL 값)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    extra_metadata: Dict[str, Any] = Field(default_factory=dict, description="요소별 확장 필드")


class ElementSearchPayload(Element):
    """Qdrant payload: 요소 + 상속된 문서 메타데이터 (검색 필터용)."""
    doc_name: str
    doc_title: Optional[str] = None
    doc_type: Optional[str] = None
    domain: Optional[str] = None
    source_org: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    publish_date: Optional[date] = None
    collection_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 검수 이력
# ---------------------------------------------------------------------------

class ReviewLog(BaseModel):
    """검수 1회의 기록. 지우거나 고치지 않고 쌓기만 한다(검수 학습 재료)."""
    review_id: str = Field(..., description="검수 기록 고유 ID (UUIDv4)")
    element_id: str
    reviewer: str = Field(..., description="검수자 식별자")
    review_action: ReviewAction
    changed_fields: List[str] = Field(default_factory=list, description="고친 필드 이름 (Element 필드명 그대로)")
    before: Dict[str, Any] = Field(default_factory=dict, description="고치기 전 값 (changed_fields만)")
    after: Dict[str, Any] = Field(default_factory=dict, description="고친 뒤 값 (changed_fields만)")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="검수 시점의 확신도")
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 엔티티 사전
# ---------------------------------------------------------------------------

class EntityEntry(BaseModel):
    """엔티티 사전 1행. 파일: ENTITY_DICTIONARY_PATH (CSV, UTF-8).

    CSV 열: entity_name,entity_type,aliases,ticker
    aliases는 '|'로 구분 (예: SK하이닉스|하이닉스|SK hynix)
    """
    entity_name: str = Field(..., description="대표 이름. 검색·저장은 이 이름으로 통일")
    entity_type: EntityType
    aliases: List[str] = Field(default_factory=list, description="다른 표기")
    ticker: Optional[str] = Field(None, description="종목코드 (상장사만)")
