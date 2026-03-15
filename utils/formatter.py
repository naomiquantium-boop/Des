from __future__ import annotations
from bot.config import settings
from typing import Optional

RANK_EMOJIS = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}


def short_addr(a: str, left: int = 4, right: int = 4) -> str:
    if not a:
        return "Unknown"
    if len(a) <= left + right + 3:
        return a
    return f"{a[:left]}...{a[-right:]}"


def emoji_bar(emoji: str, count: int = 3) -> str:
    return " ".join([emoji] * max(1, count))


def fmt_num(x: float, decimals: int = 2) -> str:
    try:
        return f"{x:,.{decimals}f}"
    except Exception:
        return str(x)


def fmt_spent_amount(value: float, symbol: str) -> str:
    try:
        v = float(value or 0)
    except Exception:
        v = 0.0
    sym = (symbol or '').upper()
    if sym == 'SOL':
        # Show more precision for SOL so swaps around 1 SOL don't all appear as 1.00.
        if v < 1:
            d = 4
        elif v < 10:
            d = 3
        else:
            d = 2
        return fmt_num(v, d)
    return fmt_num(v, 2)


def _norm_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    u = url.strip()
    if not u:
        return None
    if u.startswith("@"):
        return f"https://t.me/{u[1:]}"
    if u.startswith("t.me/"):
        return "https://" + u
    if u.startswith("http://"):
        return "https://" + u[len("http://"):]
    return u


def _a(label: str, url: Optional[str]) -> str:
    u = _norm_url(url)
    if not u:
        return label
    return f'<a href="{u}">{label}</a>'


def _default_ad_line() -> str:
    return f'ad: <a href="{settings.BOOK_ADS_URL}">Promote here with Pumptools Ads</a>'


def _ad_line(ad_text: str | None, ad_link: str | None = None) -> str:
    if ad_text and ad_text.strip():
        if ad_link:
            return f'ad: <a href="{_norm_url(ad_link)}">{ad_text}</a>'
        return f"ad: {ad_text}"
    return _default_ad_line()


def _build(token_symbol, emoji, spent_sol, spent_usd, got_tokens, buyer, tx_url, price_usd, mcap_usd, tg_url, ad_text, ad_link, chart_url=None, spent_symbol="SOL", spent_value=None):
    title = f'🪐 {_a(token_symbol, tg_url)} Buy!'
    count = max(3, min(12, int(spent_sol * 4) or 3))
    display_value = spent_value if spent_value is not None else spent_sol
    usd_part = f" (${fmt_num(spent_usd, 2)})" if spent_usd > 0 else ""
    lines = [title, "", emoji_bar(emoji, count), ""]
    lines.append(f"💵 {fmt_spent_amount(display_value, spent_symbol)} {spent_symbol}{usd_part}")
    lines.append(f"🔁 {fmt_num(got_tokens, 2)} {_a(token_symbol, tg_url)}")
    lines.append(f"👤 {_a(short_addr(buyer), tx_url)}: New! | {_a('Txn', tx_url)}")
    if price_usd is not None:
        lines.append(f"🏷 Price: ${fmt_num(price_usd, 6)}")
    if mcap_usd is not None:
        lines.append(f"📊 MarketCap: ${fmt_num(mcap_usd, 0)}")
    lines.append("")
    lines.append(f'🤍 {_a("Listing", settings.LISTING_URL)} | 📈 {_a("Chart", chart_url or tx_url)}')
    lines.append("")
    lines.append(_ad_line(ad_text, ad_link))
    return "\n".join(lines)


def build_buy_message_group(**kwargs) -> str:
    return _build(**kwargs)


def build_buy_message_channel(**kwargs) -> str:
    return _build(**kwargs)


def build_leaderboard_message(rows: list[tuple[int, str, str, float, str | None]], footer_handle: str) -> str:
    lines = ["🟢 PUMPTOOLS TRENDING", ""]
    for idx, row in enumerate(rows[:10], start=1):
        rank, label, metric, pct, chart_url = row
        sign = "+" if pct > 0 else ""
        token_part = _a(label, chart_url or settings.LISTING_URL)
        metric_part = _a(metric, chart_url or settings.LISTING_URL)
        lines.append(f'{RANK_EMOJIS.get(rank, str(rank))} {token_part} | {metric_part} | {sign}{pct:.0f}%')
        if idx == 3:
            lines.append("────────────────────")
    lines.append("")
    lines.append(f"<blockquote>💬 To trend add {footer_handle} in your group</blockquote>")
    return "\n".join(lines)
