import os
from datetime import date
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from qdrant_client import QdrantClient
from dotenv import load_dotenv

# Load environment variables
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

# CORS Middleware (Frontend communication)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files mount for cropped images if /data/crops exists
crops_dir = os.getenv("CROPS_DIR", "/data/crops")
if os.path.exists(crops_dir):
    app.mount("/static/crops", StaticFiles(directory=crops_dir), name="crops")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "figindex_elements")


@app.get("/health")
def health_check():
    """
    서버 상태, Qdrant 연결 여부, 컬렉션 존재 여부를 반환합니다.
    """
    qdrant_connected = False
    collection_exists = False
    error_message = None

    try:
        client = QdrantClient(url=QDRANT_URL, timeout=3.0)
        collections = client.get_collections().collections
        qdrant_connected = True
        collection_exists = any(c.name == QDRANT_COLLECTION for c in collections)
    except Exception as e:
        error_message = str(e)

    return {
        "status": "ok",
        "service": "backend",
        "qdrant_url": QDRANT_URL,
        "qdrant_connected": qdrant_connected,
        "collection_name": QDRANT_COLLECTION,
        "collection_exists": collection_exists,
        "error": error_message
    }


@app.get("/api/elements", response_model=List[VisualElementSchema])
def get_mock_elements():
    """
    프론트엔드 개발용 목업 데이터 2건을 반환합니다.
    - 1번: TABLE (수치 실적/전망 표)
    - 2번: CHART (발전 비중 추이 그래프)
    """
    mock_1 = VisualElementSchema(
        element_id="fig-mock-001-table",
        doc_name="2025_energy_outlook.pdf",
        page_number=14,
        bbox=[0.15, 0.10, 0.45, 0.90],
        element_type=ElementType.TABLE,
        image_path="/static/crops/fig_mock_001.png",
        title_or_caption="[표 1] 연도별 재생에너지 발전 비중 전망",
        summary="태양광 발전 비중이 꾸준히 늘어 2025년 전체의 55%를 상회할 것으로 전망되며, 풍력 역시 완만한 성장세를 보임.",
        structured_data=TableStructure(
            columns=["구분", "2023", "2024", "2025E"],
            rows=[
                {"구분": "태양광", "2023": 42, "2024": 48, "2025E": 55},
                {"구분": "풍력", "2023": 30, "2024": 33, "2025E": 35},
                {"구분": "기타", "2023": 28, "2024": 19, "2025E": 10},
                {"구분": "합계", "2023": 100, "2024": 100, "2025E": 100}
            ],
            unit="%",
            period_labels=["2023", "2024", "2025E"]
        ),
        hashtags=["#에너지전망", "#태양광", "#신재생"],
        confidence_score=0.92,
        review_status=ReviewStatus.APPROVED,
        doc_title="2025 글로벌 에너지 시장 전망 보고서",
        doc_type="REPORT",
        domain="에너지",
        source_org="한국에너지경제연구원",
        authors=["김연구", "이분석"],
        publish_date=date(2025, 1, 15),
        entities=["에너지경제연구원", "태양광", "풍력"],
        extra_metadata={"report_code": "KEEI-2025-01"}
    )

    mock_2 = VisualElementSchema(
        element_id="fig-mock-002-chart",
        doc_name="2025_semiconductor_market.pdf",
        page_number=8,
        bbox=[0.50, 0.10, 0.85, 0.90],
        element_type=ElementType.CHART,
        image_path="/static/crops/fig_mock_002.png",
        title_or_caption="[그림 2] 글로벌 HBM 세대별 출하 비중 추이",
        summary="2024년 HBM3 중심에서 2025년 이후 HBM3E 및 HBM4로의 급격한 세대 전환이 예상됨.",
        structured_data=None,
        hashtags=["#반도체", "#HBM3E", "#AI메모리"],
        confidence_score=0.88,
        review_status=ReviewStatus.APPROVED,
        doc_title="차세대 AI 반도체 및 메모리 산업 동향",
        doc_type="REPORT",
        domain="반도체",
        source_org="미래에셋증권",
        authors=["박반도"],
        publish_date=date(2025, 2, 1),
        entities=["SK하이닉스", "HBM3E", "NVIDIA"],
        extra_metadata={"ticker": "000660", "target_price": "260000"}
    )

    return [mock_1, mock_2]

