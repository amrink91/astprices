FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir alembic asyncpg sqlalchemy[asyncio] psycopg2-binary pgvector pydantic-settings

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["alembic", "-c", "services/db/alembic.ini", "upgrade", "head"]
