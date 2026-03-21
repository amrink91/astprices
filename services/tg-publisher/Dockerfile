FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    # Pillow нужны эти библиотеки
    libjpeg-dev zlib1g-dev libfreetype6-dev libffi-dev \
    fonts-noto fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-publisher.txt .
RUN pip install --no-cache-dir -r requirements-publisher.txt

COPY . .

# Создаём директорию для шрифтов
RUN mkdir -p /app/services/tg-publisher/assets

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV C_FORCE_ROOT=1
