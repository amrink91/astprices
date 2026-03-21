-- ================================================================
-- PostgreSQL инициализация — выполняется один раз при старте
-- ================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ================================================================
-- SEED: Магазины Астаны
-- delivery_cost_tenge | free_threshold | min_order | avg_minutes
-- ================================================================
INSERT INTO stores (
    id, slug, display_name, base_url,
    delivery_cost_tenge, delivery_free_threshold, min_order_tenge,
    avg_delivery_minutes, is_active, scrape_health_score,
    scraper_config, created_at, updated_at
) VALUES
    (gen_random_uuid(), 'magnum',  'Magnum',   'https://magnum.kz',
     790,  5000, 1500, 45, true, 1.0, '{"type":"api","city_id":2}',        NOW(), NOW()),
    (gen_random_uuid(), 'arbuz',   'Arbuz.kz', 'https://arbuz.kz',
     590,  4000, 2000, 60, true, 1.0, '{"type":"graphql","city_id":2}',    NOW(), NOW()),
    (gen_random_uuid(), 'small',   'Small',    'https://small.kz',
     700,  5500, 1000, 30, true, 1.0, '{"type":"playwright"}',             NOW(), NOW()),
    (gen_random_uuid(), 'galmart', 'Galmart',  'https://galmart.kz',
     650,  4500, 1500, 50, true, 1.0, '{"type":"playwright","bitrix":true}', NOW(), NOW()),
    (gen_random_uuid(), 'astore',  'A-Store',  'https://a-store.kz',
     800,  6000,  500, 40, true, 1.0, '{"type":"api"}',                    NOW(), NOW()),
    (gen_random_uuid(), 'anvar',   'Анвар',    'https://www.anvar.kz',
     690,  5000, 1000, 35, true, 1.0, '{"type":"playwright","catalog":"/catalog/"}', NOW(), NOW())
ON CONFLICT (slug) DO NOTHING;

-- ================================================================
-- SEED: Базовые категории (Gemini расширит подкатегории)
-- ================================================================
INSERT INTO categories (id, name_ru, slug, icon_emoji, sort_order, created_at, updated_at)
VALUES
    (gen_random_uuid(), 'Молочные продукты',   'dairy',      '🥛', 1,  NOW(), NOW()),
    (gen_random_uuid(), 'Мясо и птица',        'meat',       '🥩', 2,  NOW(), NOW()),
    (gen_random_uuid(), 'Рыба и морепродукты', 'fish',       '🐟', 3,  NOW(), NOW()),
    (gen_random_uuid(), 'Бакалея',             'grocery',    '🌾', 4,  NOW(), NOW()),
    (gen_random_uuid(), 'Овощи и фрукты',      'vegetables', '🥦', 5,  NOW(), NOW()),
    (gen_random_uuid(), 'Напитки',             'drinks',     '🥤', 6,  NOW(), NOW()),
    (gen_random_uuid(), 'Заморозка',           'frozen',     '🧊', 7,  NOW(), NOW()),
    (gen_random_uuid(), 'Снеки и сладкое',     'snacks',     '🍫', 8,  NOW(), NOW()),
    (gen_random_uuid(), 'Хлеб и выпечка',      'bakery',     '🍞', 9,  NOW(), NOW()),
    (gen_random_uuid(), 'Масла и соусы',       'oils',       '🫙', 10, NOW(), NOW()),
    (gen_random_uuid(), 'Бытовая химия',       'household',  '🧹', 11, NOW(), NOW()),
    (gen_random_uuid(), 'Детские товары',      'baby',       '👶', 12, NOW(), NOW()),
    (gen_random_uuid(), 'Другое',              'other',      '📦', 99, NOW(), NOW())
ON CONFLICT (slug) DO NOTHING;

-- ================================================================
-- Материализованное представление: ТЕКУЩИЕ ЦЕНЫ
-- Обновляется каждые 30 минут через Celery
-- ================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS current_prices AS
SELECT DISTINCT ON (sp.id)
    sp.id                AS store_product_id,
    sp.product_id,
    sp.store_id,
    s.slug               AS store_slug,
    s.display_name       AS store_name,
    sp.store_sku,
    sp.store_url,
    sp.store_image_url,
    sp.name_raw,
    sp.price_tenge,
    sp.old_price_tenge,
    sp.price_per_unit,
    sp.in_stock,
    sp.is_promoted,
    sp.promo_label,
    sp.updated_at        AS price_updated_at,
    CASE
        WHEN sp.old_price_tenge IS NOT NULL AND sp.old_price_tenge > 0
        THEN ROUND((sp.old_price_tenge - sp.price_tenge) / sp.old_price_tenge * 100, 1)
        ELSE NULL
    END AS discount_pct
FROM store_products sp
JOIN stores s ON s.id = sp.store_id
WHERE sp.in_stock = true
ORDER BY sp.id, sp.updated_at DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_current_prices_pk     ON current_prices (store_product_id);
CREATE INDEX IF NOT EXISTS idx_current_prices_product       ON current_prices (product_id);
CREATE INDEX IF NOT EXISTS idx_current_prices_store         ON current_prices (store_id);
CREATE INDEX IF NOT EXISTS idx_current_prices_promoted      ON current_prices (is_promoted) WHERE is_promoted = true;
