FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bake the embedding model into the image so runtime loads from local cache
# (HF_HUB_OFFLINE=1) instead of hitting the Hub on every cold boot.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
COPY app ./app
COPY public ./public
COPY data/runbooks ./data/runbooks
COPY docker ./docker
EXPOSE 4000
# Run as non-root; compose/k8s can override with a mounted model cache.
RUN useradd -m -u 10001 opsmind && chown -R opsmind:opsmind /app
USER opsmind
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health', timeout=2)"
CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "4000"]
