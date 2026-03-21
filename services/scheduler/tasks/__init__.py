"""Celery задачи — импорт всех для авторегистрации."""
from services.scheduler.tasks.scrape_tasks import (  # noqa: F401
    scrape_store,
    refresh_materialized_view,
    detect_anomalies,
    check_scraper_health,
)
from services.scheduler.tasks.publish_tasks import (  # noqa: F401
    publish_daily_deals,
    publish_weekly_digest,
    publish_cart_tip,
    publish_anomalies,
)
