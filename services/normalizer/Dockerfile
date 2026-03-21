FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-normalizer.txt .
RUN pip install --no-cache-dir -r requirements-normalizer.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV C_FORCE_ROOT=1
