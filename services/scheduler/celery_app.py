"""Celery приложение — центр управления всеми задачами"""
from celery import Celery
from celery.schedules import crontab
from shared.config import settings

app = Celery("astana_prices")

app.config_from_object({
    "broker_url": settings.celery_broker_url,
    "result_backend": settings.redis_celery_results,
    "task_serializer": "json",
    "result_serializer": "json",
    "accept_content": ["json"],
    "timezone": "Asia/Almaty",
    "enable_utc": True,
    "worker_concurrency": settings.celery_worker_concurrency,
    "task_soft_time_limit": settings.celery_task_soft_time_limit,
    "task_time_limit": settings.celery_task_time_limit,
    "task_acks_late": True,
    "worker_prefetch_multiplier": 1,
    "task_routes": {
        "tasks.scrape_store":           {"queue": "scrape"},
        "tasks.normalize_batch":        {"queue": "normalize"},
        "tasks.publish_daily_deals":    {"queue": "publish"},
        "tasks.publish_weekly_digest":  {"queue": "publish"},
        "tasks.publish_cart_tip":       {"queue": "publish"},
        "tasks.publish_anomalies":      {"queue": "publish"},
        "tasks.*":                      {"queue": "default"},
    },
})

# ================================================================
# РАСПИСАНИЕ (все UTC, Астана = UTC+5)
# 07:00 AST = 02:00 UTC
# ================================================================
app.conf.beat_schedule = {

    # Парсинг каждые 4ч со сдвигом 15 мин между магазинами
    "scrape-magnum":  {"task": "tasks.scrape_store", "schedule": crontab(minute=0,  hour="2,6,10,14,18"), "args": ("magnum",)},
    "scrape-arbuz":   {"task": "tasks.scrape_store", "schedule": crontab(minute=15, hour="2,6,10,14,18"), "args": ("arbuz",)},
    "scrape-small":   {"task": "tasks.scrape_store", "schedule": crontab(minute=30, hour="2,6,10,14,18"), "args": ("small",)},
    "scrape-galmart": {"task": "tasks.scrape_store", "schedule": crontab(minute=45, hour="2,6,10,14,18"), "args": ("galmart",)},
    "scrape-astore":  {"task": "tasks.scrape_store", "schedule": crontab(minute=10, hour="3,7,11,15,19"), "args": ("astore",)},
    "scrape-anvar":   {"task": "tasks.scrape_store", "schedule": crontab(minute=25, hour="3,7,11,15,19"), "args": ("anvar",)},

    # Telegram публикации
    # 12:00 AST = 07:00 UTC
    "daily-deals":    {"task": "tasks.publish_daily_deals",   "schedule": crontab(minute=0, hour=7)},
    # Понедельник 09:00 AST = 04:00 UTC
    "weekly-digest":  {"task": "tasks.publish_weekly_digest", "schedule": crontab(minute=0, hour=4, day_of_week=1)},
    # Вт/Чт/Сб 10:00 AST = 05:00 UTC
    "cart-tip":       {"task": "tasks.publish_cart_tip",      "schedule": crontab(minute=0, hour=5, day_of_week="2,4,6")},
    # Аномалии каждые 20 мин
    "anomalies":      {"task": "tasks.publish_anomalies",     "schedule": crontab(minute="*/20")},

    # Обслуживание
    "refresh-view":   {"task": "tasks.refresh_materialized_view", "schedule": crontab(minute="*/30")},
    "detect-anomaly": {"task": "tasks.detect_anomalies",          "schedule": crontab(minute="*/15")},
    "health-check":   {"task": "tasks.check_scraper_health",      "schedule": crontab(minute="*/30")},
}

app.autodiscover_tasks(["services.scheduler.tasks"])
