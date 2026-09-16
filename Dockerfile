FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EMS_CACHE_DIR=/data/cache

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && mkdir -p /data/cache

EXPOSE 8000
# 검색 하나가 30~90초라 워커 타임아웃을 넉넉히 둔다. 작업자 수(EMS_WORKERS)는 외부 API 한도를 고려해 2~4 권장.
CMD ["sh", "-c", "uvicorn email_search.web:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 120"]
