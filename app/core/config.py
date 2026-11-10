from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "FigIndex"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # Directories
    DATA_DIR: Path = BASE_DIR / "data"
    SAMPLE_PDFS_DIR: Path = BASE_DIR / "data" / "sample_pdfs"
    CROPS_DIR: Path = BASE_DIR / "data" / "crops"

    # Multimodal Vision Model (환경변수로 분리 교체 가능)
    VISION_MODEL: str = "gemini-3.8-flash"
    GEMINI_API_KEY: Optional[str] = None

    # Embedding Model (1536 dim)
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    OPENAI_API_KEY: Optional[str] = None

    # Vector DB (Qdrant)
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "figindex_elements"

    # Extraction settings (Point / Ratio based padding)
    PADDING_PT_TOP_BOTTOM: float = 10.0
    PADDING_PT_LEFT_RIGHT: float = 5.0
    PADDING_RATIO_HEIGHT: float = 0.015
    RENDER_DPI: int = 200
    CONFIDENCE_THRESHOLD_APPROVED: float = 0.80

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.SAMPLE_PDFS_DIR.mkdir(parents=True, exist_ok=True)
settings.CROPS_DIR.mkdir(parents=True, exist_ok=True)
