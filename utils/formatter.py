from __future__ import annotations
from html import escape
from typing import Optional
from bot.config import settings


def short_addr(a: str, left: int = 4, right: int = 4) -> str:
    if not a:
        return "Unknown"
    if len(a) <= left + right + 3:
        return a
    return f"{a[:left]}...{a[-right:]}"


def fmt_num(x: float | int | None, decimals: int = 2) -> str:
    if x is None:
        return "0"
    try:
        return f"{float(x):,.{decimals}f}"
    except Exception:
        return str(x)


def compact_num(value: float | int | None) -> str:
    if value is None:
        return "0"
    x = float(value)
    for suffix, div in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(x) >= div:
            out = x / div
            if out >= 100:
                return f"{out:.0f}{suffix}"
            if out >= 10:
                return f"{out:.1f}{suffix}".replace('.0', '')
            return f"{out:.2f}{suffix}".replace('.00', '').replace('.0', '')
    return f"{x:.0f}" if x >= 100 else f"{x:.2f}".replace('.00', '').replace('.0', '')


def emoji_bar(emoji: str, spent_usd: float = 0.0, base: int = 4) -> str:
    count = base
    if spent_usd > 0:
        count = max(base, min(12, int(spent_usd // 10) + 1))
    return " ".join([emoji] * count)


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
    text = escape(label)
    if not u:
        return text
    return f'<a href="{escape(u)}">{text}</a>'


def ad_line(text: str | None, link: str | None = None) -> str:
    safe = text.strip() if text else settings.DEFAULT_AD_TEXT
    return f"ad: {_a(safe, link or settings.BOOK_ADS_URL)}"


def build_buy_message_group(
    token_name: str,
    dex_name: str,
    emoji: str,
    spent_sol: float,
    spent_usd: float,
    got_tokens: float,
    buyer: str,
    tx_url: str,
    price_usd: Optional[float],
    mcap_usd: Optional[float],
    listing_url: Optional[str],
    chart_url: Optional[str],
    ad_text: Optional[str],
    ad_link: Optional[str],
) -> str:
    lines = [f"🪐 {escape(token_name)} Buy! —", escape(dex_name), "", emoji_bar(emoji, spent_usd), ""]
    lines.append(f"💵 {fmt_num(spent_sol, 2)} SOL (${fmt_num(spent_usd, 2)})")
    lines.append(f"🔁 {fmt_num(got_tokens, 2)} {escape(token_name.split()[0][:12].upper())}")
    lines.append(f"👤 {_a(short_addr(buyer), tx_url)}: New! | {_a('Txn', tx_url)}")
    if price_usd is not None:
        lines.append(f"🏷 Price: ${fmt_num(price_usd, 6)}")
    if mcap_usd is not None:
        lines.append(f"📊 MarketCap: ${fmt_num(mcap_usd, 0)}")
    lines.append("")
    lines.append(f"🤍 {_a('Listing', listing_url)} | 📈 {_a('Chart', chart_url)}")
    lines.append("")
    lines.append(ad_line(ad_text, ad_link))
    return "\n".join(lines)


def build_buy_message_channel(
    token_name: str,
    emoji: str,
    spent_sol: float,
    spent_usd: float,
    got_tokens: float,
    buyer: str,
    tx_url: str,
    price_usd: Optional[float],
    mcap_usd: Optional[float],
    listing_url: Optional[str],
    chart_url: Optional[str],
    ad_text: Optional[str],
    ad_link: Optional[str],
    rank_text: Optional[str] = None,
) -> str:
    lines = [f"🪐 {_a(token_name, listing_url)} Buy!", "", emoji_bar(emoji, spent_usd, base=5), ""]
    lines.append(f"💵 {fmt_num(spent_sol, 2)} SOL (${fmt_num(spent_usd, 2)})")
    lines.append(f"🔁 {fmt_num(got_tokens, 2)} {escape(token_name.split()[0][:12].upper())}")
    lines.append(f"👤 {_a(short_addr(buyer), tx_url)}: New! | {_a('Txn', tx_url)}")
    if price_usd is not None:
        lines.append(f"🏷 Price: ${fmt_num(price_usd, 6)}")
    if mcap_usd is not None:
        lines.append(f"📊 MarketCap: ${fmt_num(mcap_usd, 0)}")
    lines.append("")
    lines.append(f"🤍 {_a('Listing', listing_url)} | 📈 {_a('Chart', chart_url)}")
    if rank_text:
        lines.append("")
        lines.append(f"🔥 {escape(rank_text)}")
    lines.append("")
    lines.append(ad_line(ad_text, ad_link))
    return "\n".join(lines)


def build_leaderboard_message(rows: list[dict]) -> str:
    lines = ["🟢 PUMPTOOLS TRENDING", ""]
    for item in rows[:10]:
        rank = item["rank"]
        sym = escape(item["symbol"])
        mcap = compact_num(item.get("mcap") or 0)
        pct = item.get("pct") or 0
        medal = ""
        if rank == 1:
            medal = "🥇 "
        elif rank == 2:
            medal = "🥈 "
        elif rank == 3:
            medal = "🥉 "
        lines.append(f"{medal}{rank} {sym} | {mcap} | {pct:.0f}%")
    lines += ["", f"💬 {escape(settings.LEADERBOARD_FOOTER)}"]
    return "\n".join(lines)
