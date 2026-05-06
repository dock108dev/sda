FROM python:3.14.2-slim AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./requirements.txt
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

FROM python:3.14.2-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production

WORKDIR /app

RUN useradd --system --uid 10001 --create-home appuser

COPY --from=builder /install /usr/local
COPY api/app ./app
COPY api/alembic ./alembic
COPY api/alembic.ini ./alembic.ini
COPY api/main.py ./main.py
COPY api/scripts ./scripts
COPY infra/api-entrypoint.sh /usr/local/bin/api-entrypoint

RUN chmod +x /usr/local/bin/api-entrypoint \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["api-entrypoint"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
