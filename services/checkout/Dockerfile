FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic pydantic-settings \
    sqlalchemy[asyncio] asyncpg httpx

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8002

CMD ["uvicorn", "services.checkout.main:app", "--host", "0.0.0.0", "--port", "8002"]
