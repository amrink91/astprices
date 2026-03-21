"""
Генератор изображений для Telegram-постов — Pillow 1280×720.
Карточки сравнения цен, еженедельный дайджест, умная корзина.
"""
from __future__ import annotations

import io
import logging
import textwrap
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger("image_generator")

# ── Пути к ресурсам ────────────────────────────────────────────
ASSETS = Path(__file__).parent / "assets"
FONT_BOLD   = str(ASSETS / "NotoSans-Bold.ttf")
FONT_REGULAR = str(ASSETS / "NotoSans-Regular.ttf")
FONT_FALLBACK = "DejaVuSans"   # если шрифты не найдены

# ── Цветовая схема ─────────────────────────────────────────────
BG_DARK     = (15,  20,  35)     # фон
BG_CARD     = (25,  32,  50)     # карточка товара
BG_CARD2    = (30,  38,  58)     # чередование строк
ACCENT      = (64, 156, 255)     # синий акцент
GREEN       = (46, 213, 115)     # скидка / экономия
RED         = (255,  71,  87)    # рост цены
YELLOW      = (255, 211,  42)    # акция
TEXT_WHITE  = (240, 240, 250)
TEXT_GREY   = (140, 148, 168)
TEXT_DIM    = (90,  98, 118)

W, H = 1280, 720


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        try:
            return ImageFont.truetype(FONT_FALLBACK, size)
        except Exception:
            return ImageFont.load_default()


def _gradient_bg(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Плавный градиент от тёмно-синего к почти-чёрному."""
    for y in range(h):
        ratio = y / h
        r = int(BG_DARK[0] + (20 - BG_DARK[0]) * ratio)
        g = int(BG_DARK[1] + (26 - BG_DARK[1]) * ratio)
        b = int(BG_DARK[2] + (45 - BG_DARK[2]) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple,
    radius: int = 16,
    fill: tuple = BG_CARD,
    outline: Optional[tuple] = None,
    outline_width: int = 1,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill,
                           outline=outline, width=outline_width)


def _fmt_price(price: Decimal) -> str:
    p = int(price)
    if p >= 1000:
        return f"{p:,}".replace(",", " ") + " ₸"
    return f"{p} ₸"


def _bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# Card: Дневные акции (до 6 товаров)
# ─────────────────────────────────────────────────────────────

@dataclass
class DealRow:
    emoji: str
    name: str
    price: Decimal
    old_price: Optional[Decimal]
    discount_pct: Optional[float]
    store: str


def generate_deals_card(
    deals: list[DealRow],
    title: str = "🔥 Акции дня в Астане",
    subtitle: str = "",
) -> bytes:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    _gradient_bg(draw, W, H)

    # Заголовок
    f_title   = _load_font(FONT_BOLD, 52)
    f_sub     = _load_font(FONT_REGULAR, 28)
    f_name    = _load_font(FONT_BOLD, 30)
    f_price   = _load_font(FONT_BOLD, 36)
    f_old     = _load_font(FONT_REGULAR, 24)
    f_store   = _load_font(FONT_REGULAR, 22)
    f_badge   = _load_font(FONT_BOLD, 22)

    draw.text((64, 36), title, font=f_title, fill=TEXT_WHITE)
    if subtitle:
        draw.text((64, 100), subtitle, font=f_sub, fill=TEXT_GREY)

    # Сетка карточек: 3 × 2
    card_w, card_h = 372, 238
    cols, rows = 3, 2
    gap_x, gap_y = 22, 18
    start_x, start_y = 64, 145

    for idx, deal in enumerate(deals[: cols * rows]):
        col = idx % cols
        row = idx // cols
        x = start_x + col * (card_w + gap_x)
        y = start_y + row * (card_h + gap_y)

        bg = BG_CARD if row % 2 == 0 else BG_CARD2
        _rounded_rect(draw, (x, y, x + card_w, y + card_h), radius=18,
                      fill=bg, outline=(50, 60, 90), outline_width=1)

        # Emoji
        draw.text((x + 16, y + 14), deal.emoji, font=_load_font(FONT_REGULAR, 34), fill=TEXT_WHITE)

        # Название (2 строки макс)
        name_short = textwrap.shorten(deal.name, width=28, placeholder="…")
        draw.text((x + 60, y + 16), name_short, font=f_name, fill=TEXT_WHITE)

        # Магазин
        draw.text((x + 60, y + 56), deal.store, font=f_store, fill=TEXT_GREY)

        # Цена
        draw.text((x + 16, y + 118), _fmt_price(deal.price), font=f_price, fill=ACCENT)

        # Старая цена (зачёркнутая)
        if deal.old_price:
            old_text = _fmt_price(deal.old_price)
            old_x = x + 16
            old_y = y + 170
            draw.text((old_x, old_y), old_text, font=f_old, fill=TEXT_DIM)
            # зачёркивание
            bbox = draw.textbbox((old_x, old_y), old_text, font=f_old)
            mid_y = (bbox[1] + bbox[3]) // 2
            draw.line([(bbox[0], mid_y), (bbox[2], mid_y)], fill=TEXT_DIM, width=2)

        # Бейдж скидки
        if deal.discount_pct and deal.discount_pct >= 5:
            badge_text = f"−{deal.discount_pct:.0f}%"
            bx = x + card_w - 80
            by = y + 14
            _rounded_rect(draw, (bx, by, bx + 70, by + 34), radius=10, fill=GREEN)
            draw.text((bx + 6, by + 5), badge_text, font=f_badge, fill=(10, 10, 10))

    # Подпись
    f_footer = _load_font(FONT_REGULAR, 22)
    draw.text((64, H - 36), "@astana_prices_channel", font=f_footer, fill=TEXT_DIM)

    return _bytes(img)


# ─────────────────────────────────────────────────────────────
# Card: Умная корзина (split-cart)
# ─────────────────────────────────────────────────────────────

@dataclass
class CartStore:
    name: str
    items: list[str]        # названия товаров
    subtotal: Decimal
    delivery: Decimal


def generate_cart_card(
    stores: list[CartStore],
    total_savings: Decimal,
    total_sum: Decimal,
) -> bytes:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    _gradient_bg(draw, W, H)

    f_title  = _load_font(FONT_BOLD, 50)
    f_sub    = _load_font(FONT_REGULAR, 28)
    f_store  = _load_font(FONT_BOLD, 32)
    f_item   = _load_font(FONT_REGULAR, 24)
    f_price  = _load_font(FONT_BOLD, 30)
    f_save   = _load_font(FONT_BOLD, 40)
    f_footer = _load_font(FONT_REGULAR, 22)

    draw.text((64, 36), "🛒 Умная корзина", font=f_title, fill=TEXT_WHITE)
    draw.text((64, 100), "Оптимальное распределение по магазинам Астаны", font=f_sub, fill=TEXT_GREY)

    # Колонки магазинов
    n = min(len(stores), 3)
    card_w = (W - 128 - (n - 1) * 20) // n
    card_h = 380
    start_x, start_y = 64, 148

    STORE_COLORS = [ACCENT, (255, 159, 67), GREEN, (190, 90, 255)]

    for i, store in enumerate(stores[:n]):
        x = start_x + i * (card_w + 20)
        y = start_y
        color = STORE_COLORS[i % len(STORE_COLORS)]

        _rounded_rect(draw, (x, y, x + card_w, y + card_h), radius=20,
                      fill=BG_CARD, outline=color, outline_width=2)

        # Название магазина
        draw.text((x + 20, y + 18), store.name, font=f_store, fill=color)

        # Линия-разделитель
        draw.line([(x + 20, y + 62), (x + card_w - 20, y + 62)], fill=(50, 60, 90), width=1)

        # Список товаров
        item_y = y + 76
        for item in store.items[:7]:
            short = textwrap.shorten(item, width=24, placeholder="…")
            draw.text((x + 20, item_y), f"• {short}", font=f_item, fill=TEXT_WHITE)
            item_y += 32
        if len(store.items) > 7:
            draw.text((x + 20, item_y), f"  +ещё {len(store.items) - 7}", font=f_item, fill=TEXT_GREY)

        # Цены внизу карточки
        draw.line([(x + 20, y + card_h - 80), (x + card_w - 20, y + card_h - 80)],
                  fill=(50, 60, 90), width=1)
        draw.text((x + 20, y + card_h - 66),
                  f"Товары: {_fmt_price(store.subtotal)}", font=f_price, fill=TEXT_WHITE)
        if store.delivery > 0:
            draw.text((x + 20, y + card_h - 30),
                      f"Доставка: {_fmt_price(store.delivery)}", font=f_item, fill=TEXT_GREY)
        else:
            draw.text((x + 20, y + card_h - 30),
                      "Доставка: БЕСПЛАТНО", font=f_item, fill=GREEN)

    # Итог экономии
    save_y = start_y + card_h + 20
    draw.text((64, save_y), f"💰 Экономия: ", font=f_save, fill=TEXT_WHITE)
    # Считаем ширину первой части
    prefix_w = draw.textlength("💰 Экономия: ", font=f_save)
    draw.text((64 + prefix_w, save_y), _fmt_price(total_savings), font=f_save, fill=GREEN)

    total_text = f"Итого: {_fmt_price(total_sum)}"
    total_w = draw.textlength(total_text, font=f_sub)
    draw.text((W - 64 - total_w, save_y + 8), total_text, font=f_sub, fill=TEXT_GREY)

    draw.text((64, H - 36), "@astana_prices_channel", font=f_footer, fill=TEXT_DIM)

    return _bytes(img)


# ─────────────────────────────────────────────────────────────
# Card: Аномалии цен
# ─────────────────────────────────────────────────────────────

@dataclass
class AnomalyRow:
    name: str
    category_emoji: str
    old_price: Decimal
    new_price: Decimal
    deviation_pct: float


def generate_anomaly_card(anomalies: list[AnomalyRow]) -> bytes:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    _gradient_bg(draw, W, H)

    f_title  = _load_font(FONT_BOLD, 50)
    f_sub    = _load_font(FONT_REGULAR, 26)
    f_name   = _load_font(FONT_BOLD, 28)
    f_price  = _load_font(FONT_REGULAR, 24)
    f_pct    = _load_font(FONT_BOLD, 28)
    f_footer = _load_font(FONT_REGULAR, 22)

    draw.text((64, 36), "📊 Изменения цен", font=f_title, fill=TEXT_WHITE)
    draw.text((64, 100), "Значительные движения за последние часы", font=f_sub, fill=TEXT_GREY)

    row_h = 72
    start_y = 150

    for i, a in enumerate(anomalies[:7]):
        y = start_y + i * (row_h + 8)
        bg = BG_CARD if i % 2 == 0 else BG_CARD2
        _rounded_rect(draw, (64, y, W - 64, y + row_h), radius=14, fill=bg)

        # Emoji
        draw.text((84, y + 18), a.category_emoji, font=_load_font(FONT_REGULAR, 32), fill=TEXT_WHITE)

        # Название
        name_short = textwrap.shorten(a.name, width=40, placeholder="…")
        draw.text((140, y + 20), name_short, font=f_name, fill=TEXT_WHITE)

        # Цена: было → стало
        price_text = f"{_fmt_price(a.old_price)}  →  {_fmt_price(a.new_price)}"
        draw.text((140, y + 46), price_text, font=f_price, fill=TEXT_GREY)

        # Процент изменения
        pct = a.deviation_pct
        pct_text = f"{'↑' if pct > 0 else '↓'} {abs(pct):.0f}%"
        color = RED if pct > 0 else GREEN
        pct_w = draw.textlength(pct_text, font=f_pct)
        draw.text((W - 64 - pct_w - 20, y + 22), pct_text, font=f_pct, fill=color)

    draw.text((64, H - 36), "@astana_prices_channel", font=f_footer, fill=TEXT_DIM)

    return _bytes(img)


# ─────────────────────────────────────────────────────────────
# Card: Еженедельный дайджест (топ-10 скидок)
# ─────────────────────────────────────────────────────────────

def generate_weekly_card(deals: list[DealRow], week_label: str) -> bytes:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    _gradient_bg(draw, W, H)

    f_title  = _load_font(FONT_BOLD, 50)
    f_week   = _load_font(FONT_REGULAR, 26)
    f_rank   = _load_font(FONT_BOLD, 32)
    f_name   = _load_font(FONT_BOLD, 26)
    f_price  = _load_font(FONT_REGULAR, 24)
    f_pct    = _load_font(FONT_BOLD, 26)
    f_footer = _load_font(FONT_REGULAR, 22)

    draw.text((64, 36), "📅 Лучшие акции недели", font=f_title, fill=TEXT_WHITE)
    draw.text((64, 100), week_label, font=f_week, fill=ACCENT)

    # Два столбца: по 5 строк
    top = sorted(deals, key=lambda d: d.discount_pct or 0, reverse=True)[:10]
    col_w = (W - 128 - 20) // 2
    row_h = 66
    start_y = 148
    MEDAL = ["🥇", "🥈", "🥉"] + [""] * 7

    for i, deal in enumerate(top):
        col = i // 5
        row = i % 5
        x = 64 + col * (col_w + 20)
        y = start_y + row * (row_h + 6)

        bg = BG_CARD if i % 2 == 0 else BG_CARD2
        _rounded_rect(draw, (x, y, x + col_w, y + row_h), radius=12, fill=bg)

        # Медаль или номер
        medal = MEDAL[i] or f"#{i+1}"
        draw.text((x + 12, y + 16), medal, font=f_rank, fill=YELLOW if i < 3 else TEXT_DIM)

        offset_x = 60 if MEDAL[i] else 44
        name_short = textwrap.shorten(deal.name, width=26, placeholder="…")
        draw.text((x + offset_x, y + 10), name_short, font=f_name, fill=TEXT_WHITE)
        draw.text((x + offset_x, y + 38),
                  f"{_fmt_price(deal.price)}  •  {deal.store}",
                  font=f_price, fill=TEXT_GREY)

        if deal.discount_pct:
            pct_text = f"−{deal.discount_pct:.0f}%"
            pct_w = draw.textlength(pct_text, font=f_pct)
            draw.text((x + col_w - pct_w - 12, y + 20), pct_text, font=f_pct, fill=GREEN)

    draw.text((64, H - 36), "@astana_prices_channel", font=f_footer, fill=TEXT_DIM)

    return _bytes(img)
