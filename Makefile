GREEN  := \033[0;32m
YELLOW := \033[1;33m
NC     := \033[0m

.PHONY: help dev stop logs migrate seed scrape publish test clean

help:
	@echo ""
	@echo "$(GREEN)Astana Prices — команды$(NC)"
	@echo ""
	@echo "  $(YELLOW)make dev$(NC)              Запустить всё"
	@echo "  $(YELLOW)make stop$(NC)             Остановить"
	@echo "  $(YELLOW)make migrate$(NC)          Применить миграции БД"
	@echo "  $(YELLOW)make seed$(NC)             Заполнить начальные данные"
	@echo "  $(YELLOW)make scrape$(NC)           Парсинг всех магазинов"
	@echo "  $(YELLOW)make scrape-one STORE=magnum$(NC)  Один магазин"
	@echo "  $(YELLOW)make publish-test$(NC)     Тестовый пост (dry-run → в личку)"
	@echo "  $(YELLOW)make logs$(NC)             Все логи"
	@echo "  $(YELLOW)make logs-scraper$(NC)     Логи парсеров"
	@echo "  $(YELLOW)make status$(NC)           Статус контейнеров"
	@echo "  $(YELLOW)make db-shell$(NC)         PostgreSQL shell"
	@echo "  $(YELLOW)make clean$(NC)            Удалить контейнеры"
	@echo ""

dev:
	docker compose up --build -d
	@echo "$(GREEN)Запущено! API: http://localhost:8000 | Flower: http://localhost:5555$(NC)"

stop:
	docker compose down

restart: stop dev

migrate:
	docker compose run --rm migrator alembic upgrade head

migrate-create:
	docker compose run --rm migrator alembic revision --autogenerate -m "$(MSG)"

seed:
	docker compose exec api python -c "from services.db.seed import run; import asyncio; asyncio.run(run())"

db-shell:
	docker compose exec postgres psql -U ap_user -d astana_prices

scrape:
	docker compose exec celery-scraper celery -A celery_app call tasks.scrape_store --args='["magnum"]'
	docker compose exec celery-scraper celery -A celery_app call tasks.scrape_store --args='["arbuz"]'
	docker compose exec celery-scraper celery -A celery_app call tasks.scrape_store --args='["small"]'
	docker compose exec celery-scraper celery -A celery_app call tasks.scrape_store --args='["galmart"]'
	docker compose exec celery-scraper celery -A celery_app call tasks.scrape_store --args='["astore"]'

scrape-one:
	docker compose exec celery-scraper celery -A celery_app call tasks.scrape_store --args='["$(STORE)"]'

publish-test:
	docker compose exec celery-publish celery -A celery_app call tasks.publish_daily_deals

publish-digest:
	docker compose exec celery-publish celery -A celery_app call tasks.publish_weekly_digest

logs:
	docker compose logs -f --tail=100

logs-api:
	docker compose logs -f api --tail=100

logs-scraper:
	docker compose logs -f scraper-magnum scraper-arbuz scraper-small --tail=50

logs-normalizer:
	docker compose logs -f normalizer --tail=100

logs-celery:
	docker compose logs -f celery-scraper celery-normalize celery-publish celery-beat --tail=50

status:
	docker compose ps

shell:
	docker compose exec $(SERVICE) bash

clean:
	docker compose down --remove-orphans

clean-all:
	@echo "$(YELLOW)ВНИМАНИЕ: удалит данные БД!$(NC)"
	@read -p "Продолжить? (yes/no): " c && [ "$$c" = "yes" ] || exit 1
	docker compose down -v --remove-orphans

ssl-init:
	docker compose run --rm certbot certonly --webroot \
		--webroot-path=/var/www/certbot \
		--email admin@$(DOMAIN) \
		--agree-tos --no-eff-email \
		-d $(DOMAIN) -d www.$(DOMAIN)
