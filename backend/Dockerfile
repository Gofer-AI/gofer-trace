# Gofer Trace backend image. Build context is the repo root so the schema/ directory
# (needed for trace validation) is available alongside backend/.
#
#   docker build -f backend/Dockerfile -t gofer-backend .
#
# Note: backend/requirements.txt pulls torch/transformers for the real Qwen2.5-VL model,
# so the first build is large/slow. For a lightweight local graph demo you can run the
# heuristic-stub path (no GPU) — the image still builds, inference just falls back.
FROM python:3.11-slim

WORKDIR /app

# OpenCV runtime libs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY schema/ ./schema/

WORKDIR /app/backend
EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
