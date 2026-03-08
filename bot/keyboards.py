from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from bot.config import settings

BUY_TEMPLATE = "https://t.me/ThorSolana_bot?start=r-TBw15MO-buy-{mint}"


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


def lang_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇸 English ✅", callback_data="lang:set:english")
    kb.button(text="🇨🇳 Chinese", callback_data="lang:set:chinese")
    kb.adjust(2)
    return kb.as_markup()


def token_list_kb(tokens: list[tuple[str, str]], prefix: str, back: str = "menu:home") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for mint, label in tokens:
        kb.button(text=f"✏️ {label}", callback_data=f"{prefix}:{mint}")
    kb.button(text="« Return", callback_data=back)
    kb.adjust(1)
    return kb.as_markup()


def token_edit_page_kb(mint: str, page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in (1, 2, 3):
        kb.button(text=("✅ " if p == page else "☑️ ") + f"Page {p}", callback_data=f"editpage:{mint}:{p}")
    kb.adjust(3)
    if page == 1:
        rows = [
            ("ℹ️ Buy Step", "buy_step", "✏️ (1)"),
            ("ℹ️ Min Buy", "min_buy", "✏️ (0)"),
            ("ℹ️ Link", "link", "✏️ ()"),
            ("ℹ️ Emoji", "emoji", "✏️ (🟢)"),
            ("ℹ️ Media", "media", "✏️ (📸)"),
        ]
        for left, key, right in rows:
            kb.button(text=left, callback_data=f"editset:{mint}:{key}")
            kb.button(text=right, callback_data=f"editset:{mint}:{key}")
        kb.adjust(3, 2, 2, 2, 2, 2)
    elif page == 2:
        for label, key in [
            ("🟢 Show Media", "show_media"),
            ("🟢 Show Mcap", "show_mcap"),
            ("🟢 Show Price", "show_price"),
            ("🟢 Show Holders", "show_holders"),
            ("🟢 Show DEX", "show_dex"),
            ("🧨 Delete Token", "delete"),
        ]:
            kb.button(text=label, callback_data=f"editset:{mint}:{key}")
        kb.adjust(3, 1, 1, 1, 1, 1, 1)
    else:
        kb.button(text="— CHART —", callback_data="noop")
        kb.button(text="✅ DexS", callback_data=f"editset:{mint}:chart:DexS")
        kb.button(text="DexT", callback_data=f"editset:{mint}:chart:DexT")
        kb.button(text="GeC", callback_data=f"editset:{mint}:chart:GeC")
        kb.button(text="— BUYBOT LANGUAGE —", callback_data="noop")
        kb.button(text="🇺🇸 English ✅", callback_data=f"editset:{mint}:lang:English")
        kb.button(text="🇷🇺 Russian", callback_data=f"editset:{mint}:lang:Russian")
        kb.button(text="🇨🇳 Chinese", callback_data=f"editset:{mint}:lang:Chinese")
        kb.adjust(3, 1, 3, 1, 2, 1)
    kb.button(text="« Return", callback_data="menu:home")
    kb.adjust(3)
    return kb.as_markup()


def trending_package_kb(selected: str | None = None) -> InlineKeyboardMarkup:
    plans = [("1h", "1 Hours"), ("3h", "3 Hours"), ("6h", "6 Hours"), ("9h", "9 Hours"), ("12h", "12 Hours"), ("24h", "24 Hours")]
    kb = InlineKeyboardBuilder()
    for key, label in plans:
        kb.button(text=("✅ " if selected == key else "☑️ ") + label, callback_data=f"trendpkg:{key}")
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
