from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
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


def buy_kb(mint: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Metrics", url=BUY_TEMPLATE.format(mint=mint))
    kb.button(text="Listing", url=settings.LISTING_URL)
    kb.adjust(2)
    return kb.as_markup()


def leaderboard_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Listing", url=settings.LISTING_URL)
    return kb.as_markup()


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇸 Language", callback_data="menu:lang")
    kb.button(text="✏️ Edit", callback_data="menu:edit")
    kb.button(text="➕ Add Token", callback_data="menu:add")
    kb.button(text="👀 View Tokens", callback_data="menu:view")
    kb.button(text="⚙️ Group Settings", callback_data="menu:group")
    kb.button(text="📈 Trending", callback_data="menu:trending")
    kb.button(text="💎 advert", callback_data="menu:advert")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def token_list_kb(tokens: list[tuple[str, str]], prefix: str, back: str = "menu:home") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for mint, label in tokens:
        kb.button(text=f"✏️ {label}", callback_data=f"{prefix}:{mint}")
    kb.button(text="« Return", callback_data=back)
    kb.adjust(1)
    return kb.as_markup()


def trending_package_kb(selected: str | None = None) -> InlineKeyboardMarkup:
    plans = [
        ("1h", "1 Hours"),
        ("3h", "3 Hours"),
        ("6h", "6 Hours"),
        ("9h", "9 Hours"),
        ("12h", "12 Hours"),
        ("24h", "24 Hours"),
    ]
    kb = InlineKeyboardBuilder()
    for key, label in plans:
        prefix = "✅ " if selected == key else "☑️ "
        kb.button(text=prefix + label, callback_data=f"trendpkg:{key}")
    kb.button(text="Continue →", callback_data="trendpkg:continue")
    kb.button(text="« Return", callback_data="menu:home")
    kb.adjust(2, 2, 2, 1, 1)
    return kb.as_markup()


def advert_duration_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, label in [("1d", "1 Day"), ("3d", "3 Days"), ("7d", "7 Days")]:
        kb.button(text=label, callback_data=f"adpkg:{key}")
    kb.button(text="« Return", callback_data="menu:home")
    kb.adjust(3, 1)
    return kb.as_markup()


def invoice_kb(invoice_id: int, amount_sol: float) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="« Return", callback_data="menu:home")
    kb.button(text="↻ Refresh", callback_data=f"invoice:refresh:{invoice_id}")
    kb.button(text=f"Pay {amount_sol:g} SOL", url=f"solana:{settings.PAYMENT_WALLET}")
    kb.adjust(2, 1)
    return kb.as_markup()
