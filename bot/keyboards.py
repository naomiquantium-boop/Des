from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from bot.config import settings


def main_menu_kb(is_owner: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇸 Language", callback_data="menu:lang")
    kb.button(text="✏️ Edit", callback_data="menu:edit")
    kb.button(text="➕ Add Token", callback_data="cfg:start")
    kb.button(text="👀 View Tokens", callback_data="menu:view")
    kb.button(text="⚙️ Group Settings", callback_data="menu:group")
    kb.button(text="📈 Trending", callback_data="trend:start")
    kb.button(text="💎 advert", callback_data="ads:start")
    if is_owner:
        kb.button(text="👑 Owner", callback_data="owner:panel")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def configure_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Add Token", callback_data="cfg:start")
    kb.button(text="📈 Trending", callback_data="trend:start")
    kb.button(text="💎 advert", callback_data="ads:start")
    kb.adjust(1, 2)
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
    kb.button(text="CLICK TO CONFIRM", callback_data="cfg:activate")
    kb.button(text="✖️ Cancel", callback_data="cfg:cancel")
    kb.adjust(1)
    return kb.as_markup()


def buy_kb(mint: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Metrics", url=settings.METRICS_URL_TEMPLATE.format(mint=mint))
    kb.button(text="Listing", url=settings.LISTING_URL)
    kb.adjust(2)
    return kb.as_markup()


def leaderboard_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Listing", url=settings.LISTING_URL)
    return kb.as_markup()


def trend_duration_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, label in [("1h", "1 Hours"), ("3h", "3 Hours"), ("6h", "6 Hours"), ("12h", "12 Hours"), ("24h", "24 Hours")]:
        kb.button(text=label, callback_data=f"trend:{key}")
    kb.button(text="« Return", callback_data="menu:home")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def ads_duration_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, label in [("1d", "1 Day"), ("3d", "3 Days"), ("7d", "7 Days")]:
        kb.button(text=label, callback_data=f"ads:{key}")
    kb.button(text="« Return", callback_data="menu:home")
    kb.adjust(3, 1)
    return kb.as_markup()


def owner_panel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Force Add Token", callback_data="owner:forceadd")
    kb.button(text="🔥 Force Trending", callback_data="owner:forcetrending")
    kb.button(text="🏆 Force Leaderboard", callback_data="owner:forceleader")
    kb.button(text="📢 Set Global Ad", callback_data="owner:setad")
    kb.button(text="📊 Status", callback_data="owner:status")
    kb.button(text="« Return", callback_data="menu:home")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()
