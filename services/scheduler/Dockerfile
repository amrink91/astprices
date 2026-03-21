FROM python:3.12-slim

# Playwright нужен для scrapers запускаемых через Celery
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates libpq-dev gcc \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-scheduler.txt .
RUN pip install --no-cache-dir -r requirements-scheduler.txt
RUN playwright install chromium --with-deps

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV C_FORCE_ROOT=1
