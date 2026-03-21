FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-publisher.txt .
RUN pip install --no-cache-dir -r requirements-publisher.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Publisher is invoked by Celery tasks, stays idle
CMD ["python", "-c", "import time; print('TG Publisher ready (invoked by Celery)'); time.sleep(999999)"]
