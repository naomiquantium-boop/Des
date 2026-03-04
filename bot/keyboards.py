from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from urllib.parse import quote
from bot.config import settings

BUY_TEMPLATE = "https://t.me/ThorSolana_bot?start=r-TBw15MO-buy-{mint}"

def configure_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Configure BuyBot", callback_data="cfg:start")
    return kb.as_markup()

def wizard_nav_kb(back: str | None = None, cancel: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if back:
        kb.button(text="⬅️ Back", callback_data=back)
    if cancel:
        kb.button(text="✖️ Cancel", callback_data="cfg:cancel")
    kb.adjust(2)
    return kb.as_markup()

def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Activate", callback_data="cfg:activate")
    kb.button(text="✖️ Cancel", callback_data="cfg:cancel")
    kb.adjust(2)
    return kb.as_markup()

def buy_kb(token_name: str, mint: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"Buy {token_name}", url=BUY_TEMPLATE.format(mint=mint))
    return kb.as_markup()

def ads_duration_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="6H", callback_data="ads:6h")
    kb.button(text="12H", callback_data="ads:12h")
    kb.button(text="24H", callback_data="ads:24h")
    kb.adjust(3)
    return kb.as_markup()

def ads_paid_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ I Paid (send tx)", callback_data="ads:paid")
    kb.button(text="✖️ Cancel", callback_data="ads:cancel")
    kb.adjust(1)
    return kb.as_markup()


def leaderboard_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # button style from your screenshot
    kb.button(text="PumpTools Listing", url=settings.LISTING_URL)
    return kb.as_markup()
