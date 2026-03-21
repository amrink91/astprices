FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-scheduler.txt .
RUN pip install --no-cache-dir -r requirements-scheduler.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV C_FORCE_ROOT=1
