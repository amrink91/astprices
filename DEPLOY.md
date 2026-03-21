# Деплой Astana Prices

## 1. Подготовка сервера

```bash
# Установка Docker + Compose
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin

# Клонирование проекта
git clone <repo> /opt/astana-prices
cd /opt/astana-prices
```

## 2. Конфигурация

```bash
cp .env.example .env
nano .env   # Заполнить: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY_1, GEMINI_API_KEY_2,
            #            POSTGRES_PASSWORD, SECRET_KEY
```

## 3. SSL сертификат

```bash
# Сначала запустить nginx без SSL для получения сертификата
docker compose up -d nginx
docker compose run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    -d astana-prices.kz -d www.astana-prices.kz \
    --email admin@astana-prices.kz --agree-tos

# Потом включить SSL блок в nginx.conf и перезапустить
docker compose restart nginx
```

## 4. Первый запуск

```bash
# Миграции и seed данных
docker compose up -d postgres redis
docker compose run --rm migrator

# Запуск всех сервисов
docker compose up -d

# Проверка статуса
docker compose ps
docker compose logs -f api
```

## 5. Мониторинг

- **Flower** (Celery): http://localhost:5555
- **Grafana**: http://localhost:3001  (admin / из .env)
- **Prometheus**: http://localhost:9090

## 6. Проверка парсеров вручную

```bash
# Запустить парсинг Magnum немедленно
docker compose exec celery-scraper \
    celery -A services.scheduler.celery_app call tasks.scrape_store \
    --args='["magnum"]'

# Тест публикации (DRY_RUN=true → в личку)
docker compose exec celery-publish \
    celery -A services.scheduler.celery_app call tasks.publish_daily_deals
```

## 7. Telegram-бот

1. Создать бота через @BotFather
2. Добавить бота в канал как **администратора** с правом публикации
3. Установить `TELEGRAM_CHANNEL_ID=@astana_prices_channel` в .env
4. Через 2 недели переключить `TELEGRAM_DRY_RUN=false`

## 8. Структура файлов

```
astana-prices/
├── docker-compose.yml
├── .env.example
├── shared/           ← общий код: config, db, models, scrapers
├── services/
│   ├── api/          ← FastAPI backend (порт 8000)
│   ├── scraper/      ← 6 парсеров (Playwright + httpx)
│   ├── normalizer/   ← Gemini нормализация
│   ├── scheduler/    ← Celery Beat + задачи
│   ├── optimizer/    ← Алгоритм умной корзины
│   ├── tg-publisher/ ← Telegram постинг + Pillow карточки
│   ├── checkout/     ← Генерация URL корзин магазинов
│   ├── frontend/     ← Next.js 15 сайт
│   └── db/           ← Alembic миграции + init.sql
├── infra/nginx/      ← nginx.conf + SSL
└── monitoring/       ← Prometheus + Grafana
```
