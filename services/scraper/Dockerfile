FROM python:3.12-slim

# Playwright зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-scraper.txt .
RUN pip install --no-cache-dir -r requirements-scraper.txt

# Устанавливаем Playwright браузеры
RUN playwright install chromium --with-deps

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "services.scraper.run"]
