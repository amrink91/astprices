"""Initial schema — все таблицы + pgvector + pg_trgm

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Расширения
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── categories ────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("icon_emoji", sa.String(8), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )

    # ── stores ────────────────────────────────────────────────
    op.create_table(
        "stores",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("slug", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("delivery_cost_tenge", sa.Numeric(10, 2), nullable=True),
        sa.Column("delivery_free_threshold", sa.Numeric(10, 2), nullable=True),
        sa.Column("min_order_tenge", sa.Numeric(10, 2), nullable=True),
        sa.Column("avg_delivery_minutes", sa.Integer(), nullable=True),
        sa.Column("scrape_health_score", sa.Float(), server_default="1.0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("scraper_config", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── products ──────────────────────────────────────────────
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("canonical_name", sa.String(256), nullable=False, unique=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("subcategory", sa.String(128), nullable=True),
        sa.Column("brand", sa.String(128), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("unit_size", sa.Numeric(10, 3), nullable=True),
        sa.Column("normalization_confidence", sa.Float(), server_default="0.0"),
        sa.Column("name_embedding", sa.Text(), nullable=True),  # vector хранится как text
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_products_canonical_name_trgm",
                    "products", ["canonical_name"],
                    postgresql_using="gin",
                    postgresql_ops={"canonical_name": "gin_trgm_ops"})

    # Векторный индекс создаётся отдельно через raw SQL после наполнения данными
    # (HNSW требует данных для построения)

    # ── store_products ────────────────────────────────────────
    op.create_table(
        "store_products",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id"), nullable=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("store_sku", sa.String(128), nullable=False),
        sa.Column("store_url", sa.Text(), nullable=True),
        sa.Column("store_image_url", sa.Text(), nullable=True),
        sa.Column("name_raw", sa.String(512), nullable=False),
        sa.Column("price_tenge", sa.Numeric(12, 2), nullable=False),
        sa.Column("old_price_tenge", sa.Numeric(12, 2), nullable=True),
        sa.Column("in_stock", sa.Boolean(), server_default="true"),
        sa.Column("is_promoted", sa.Boolean(), server_default="false"),
        sa.Column("promo_label", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "store_sku", name="uq_store_sku"),
    )
    op.create_index("ix_store_products_store_id", "store_products", ["store_id"])
    op.create_index("ix_store_products_product_id", "store_products", ["product_id"])

    # ── price_history ─────────────────────────────────────────
    op.create_table(
        "price_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("store_product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("store_products.id"), nullable=False),
        sa.Column("price_tenge", sa.Numeric(12, 2), nullable=False),
        sa.Column("old_price_tenge", sa.Numeric(12, 2), nullable=True),
        sa.Column("in_stock", sa.Boolean(), server_default="true"),
        sa.Column("is_promoted", sa.Boolean(), server_default="false"),
        sa.Column("recorded_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_price_history_sp_recorded",
                    "price_history", ["store_product_id", "recorded_at"])

    # ── scrape_runs ───────────────────────────────────────────
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("products_scraped", sa.Integer(), server_default="0"),
        sa.Column("products_new", sa.Integer(), server_default="0"),
        sa.Column("products_updated", sa.Integer(), server_default="0"),
        sa.Column("products_failed", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    # ── price_anomalies ───────────────────────────────────────
    op.create_table(
        "price_anomalies",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("store_product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("store_products.id"), nullable=False),
        sa.Column("anomaly_type", sa.String(16), nullable=False),
        sa.Column("old_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("new_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("deviation_pct", sa.Numeric(6, 1), nullable=False),
        sa.Column("gemini_explanation", sa.Text(), nullable=True),
        sa.Column("published", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── users ─────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("first_name", sa.String(64), nullable=True),
        sa.Column("last_name", sa.String(64), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("preferences", postgresql.JSONB(), server_default="{}"),
        sa.Column("is_premium", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── telegram_posts ────────────────────────────────────────
    op.create_table(
        "telegram_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("post_type", sa.String(32), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.String(64), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("product_ids", postgresql.ARRAY(postgresql.UUID()), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── Materialized view ──────────────────────────────────────
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS current_prices AS
        SELECT DISTINCT ON (sp.id)
            sp.id           AS store_product_id,
            sp.product_id,
            sp.store_id,
            s.slug          AS store_slug,
            sp.store_sku,
            sp.store_url,
            sp.store_image_url,
            sp.price_tenge,
            sp.old_price_tenge,
            sp.in_stock,
            sp.is_promoted,
            sp.promo_label,
            CASE
                WHEN sp.old_price_tenge > 0 AND sp.old_price_tenge > sp.price_tenge
                THEN ROUND((sp.old_price_tenge - sp.price_tenge)
                           / sp.old_price_tenge * 100, 1)
            END AS discount_pct,
            sp.updated_at
        FROM store_products sp
        JOIN stores s ON s.id = sp.store_id
        WHERE s.is_active = true
        ORDER BY sp.id, sp.updated_at DESC
        WITH DATA
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_current_prices_sp_id
        ON current_prices (store_product_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_current_prices_product_id
        ON current_prices (product_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_current_prices_store_id
        ON current_prices (store_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_current_prices_promoted
        ON current_prices (is_promoted) WHERE is_promoted = true
    """)

    # ── Seed: stores (exec_driver_sql bypasses SA bind param parsing) ──
    conn = op.get_bind()
    conn.exec_driver_sql("""
        INSERT INTO stores (slug, display_name, website_url,
            delivery_cost_tenge, delivery_free_threshold, min_order_tenge,
            avg_delivery_minutes, is_active, scrape_health_score,
            scraper_config)
        VALUES
            ('magnum',  'Magnum',   'https://magnum.kz',
             790,  5000, 1500, 45, true, 1.0, '{"type":"api","city_id":2}'::jsonb),
            ('arbuz',   'Arbuz.kz', 'https://arbuz.kz',
             590,  4000, 2000, 60, true, 1.0, '{"type":"graphql","city_id":2}'::jsonb),
            ('small',   'Small',    'https://small.kz',
             700,  5500, 1000, 30, true, 1.0, '{"type":"playwright"}'::jsonb),
            ('galmart', 'Galmart',  'https://galmart.kz',
             650,  4500, 1500, 50, true, 1.0, '{"type":"playwright","bitrix":true}'::jsonb),
            ('astore',  'A-Store',  'https://a-store.kz',
             800,  6000,  500, 40, true, 1.0, '{"type":"api"}'::jsonb),
            ('anvar',   'Анвар',    'https://www.anvar.kz',
             690,  5000, 1000, 35, true, 1.0, '{"type":"playwright","catalog":"/catalog/"}'::jsonb)
        ON CONFLICT (slug) DO NOTHING
    """)

    # ── Seed: categories ─────────────────────────────────────
    categories_table = sa.table(
        "categories",
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("icon_emoji", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(categories_table, [
        {"name": "Молочные продукты",   "slug": "dairy",      "icon_emoji": "🥛", "sort_order": 1},
        {"name": "Мясо и птица",        "slug": "meat",       "icon_emoji": "🥩", "sort_order": 2},
        {"name": "Рыба и морепродукты", "slug": "fish",       "icon_emoji": "🐟", "sort_order": 3},
        {"name": "Бакалея",             "slug": "grocery",    "icon_emoji": "🌾", "sort_order": 4},
        {"name": "Овощи и фрукты",      "slug": "vegetables", "icon_emoji": "🥦", "sort_order": 5},
        {"name": "Напитки",             "slug": "drinks",     "icon_emoji": "🥤", "sort_order": 6},
        {"name": "Заморозка",           "slug": "frozen",     "icon_emoji": "🧊", "sort_order": 7},
        {"name": "Снеки и сладкое",     "slug": "snacks",     "icon_emoji": "🍫", "sort_order": 8},
        {"name": "Хлеб и выпечка",      "slug": "bakery",     "icon_emoji": "🍞", "sort_order": 9},
        {"name": "Масла и соусы",       "slug": "oils",       "icon_emoji": "🫙", "sort_order": 10},
        {"name": "Бытовая химия",       "slug": "household",  "icon_emoji": "🧹", "sort_order": 11},
        {"name": "Детские товары",      "slug": "baby",       "icon_emoji": "👶", "sort_order": 12},
        {"name": "Другое",              "slug": "other",      "icon_emoji": "📦", "sort_order": 99},
    ])


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS current_prices")
    op.drop_table("telegram_posts")
    op.drop_table("users")
    op.drop_table("price_anomalies")
    op.drop_table("scrape_runs")
    op.drop_table("price_history")
    op.drop_table("store_products")
    op.drop_table("products")
    op.drop_table("stores")
    op.drop_table("categories")
