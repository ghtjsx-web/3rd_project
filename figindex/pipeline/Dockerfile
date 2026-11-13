FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    ENTITY_DICTIONARY_PATH=/data/entity_dictionary.csv

WORKDIR /app

# Install system dependencies: fonts-nanum for Korean rendering, OpenCV & PDF rendering libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-nanum \
    libgl1 \
    libglx-mesa0 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only version (no GPU / CUDA)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install pipeline python dependencies
COPY pipeline/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared schemas
COPY shared/ /app/shared/

# Copy all pipeline scripts
COPY pipeline/*.py ./

CMD ["python", "run_index.py"]

