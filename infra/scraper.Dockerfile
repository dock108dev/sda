FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libxml2-dev \
        libxslt1-dev \
        libffi-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip uv==0.6.5

COPY scraper/pyproject.toml /app/scraper/pyproject.toml
COPY scraper/uv.lock /app/scraper/uv.lock
COPY api/requirements.txt /app/api/requirements.txt

# Install all dependencies BEFORE copying source code for better caching
WORKDIR /app/scraper
RUN uv export --frozen --no-dev --no-hashes > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir -r /app/api/requirements.txt

RUN mkdir -p /ms-playwright \
    && python -m playwright install --with-deps chromium

# Copy source code LAST so code changes don't invalidate dep cache
COPY scraper /app/scraper
COPY api /app/api

RUN apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --create-home appuser \
    && mkdir -p /app/scraper/game_data \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser

ENV PYTHONPATH="/app/api:/app/scraper"

CMD ["celery", "-A", "sports_scraper.celery_app.app", "worker", "--loglevel=info", "--queues=sports-scraper"]
