FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    QDRANT_MODE=local \
    DATA_DIR=/data \
    CROPS_DIR=/data/crops \
    PDFS_DIR=/data/pdfs \
    QDRANT_LOCAL_PATH=/data/qdrant_local \
    CACHE_DIR=/data/cache \
    ENTITY_DICTIONARY_PATH=/data/entity_dictionary.csv \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

# 1. 의존성 패키지 복사 및 설치 (huggingface_hub 포함)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt huggingface_hub

# 2. bge-m3 모델 빌드 시점 사전 다운로드 (사용자 요청: BAAI/bge-m3)
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3')"

# 3. 사전 처리된 데이터 디렉토리 복사 (/data)
COPY data/crops /data/crops
COPY data/pdfs /data/pdfs
COPY data/qdrant_local /data/qdrant_local
COPY data/cache /data/cache

# 혹시 남아있을 수 있는 qdrant 로컬 lock 파일 제거
RUN rm -f /data/qdrant_local/.lock

# 4. 애플리케이션 및 공용 스키마 복사
COPY shared/ /app/shared/
COPY backend/app/ /app/app/

# Onpod 동적 포트(PORT) 지원
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
