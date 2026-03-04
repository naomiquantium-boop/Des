from __future__ import annotations
from typing import Optional

def short_addr(a: str, left: int = 4, right: int = 4) -> str:
    if not a:
        return "Unknown"
    if len(a) <= left + right + 3:
        return a
    return f"{a[:left]}...{a[-right:]}"

def emoji_bar(emoji: str, count: int = 3) -> str:
    # ensure emoji repeated with spaces for readability
    return " ".join([emoji] * max(1, count))

def fmt_num(x: float, decimals: int = 2) -> str:
    try:
        return f"{x:,.{decimals}f}"
    except Exception:
        return str(x)

def _a(label: str, url: Optional[str]) -> str:
    if not url:
        return label
    # Telegram HTML: <a href="...">label</a>
    return f'<a href="{url}">{label}</a>'

def build_buy_message_group(
    token_symbol: str,
    emoji: str,
    spent_sol: float,
    spent_usd: float,
    got_tokens: float,
    buyer: str,
    tx_url: str,
    price_usd: Optional[float],
    liquidity_usd: Optional[float],
    mcap_usd: Optional[float],
    dexs_url: Optional[str],
    tg_url: Optional[str],
    trending_url: Optional[str],
    ad_text: Optional[str],
    ad_url: Optional[str],
    book_ads_url: Optional[str],
) -> str:
    # Token name clickable to Telegram link
    title = f'{_a(token_symbol, tg_url)} Buy!'
    lines = [title, "", emoji_bar(emoji, 3), ""]
    usd_part = f" (${fmt_num(spent_usd, 0)})" if spent_usd and spent_usd > 0 else ""
    lines.append(f"Spent: {fmt_num(spent_sol, 2)} SOL{usd_part}")
    lines.append(f"Got: {fmt_num(got_tokens, 2)} {token_symbol}")
    lines += ["", f"{short_addr(buyer)} | {_a('Txn', tx_url)}", ""]
    if price_usd is not None:
        lines.append(f"Price: ${fmt_num(price_usd, 6)}")
    if liquidity_usd is not None:
        lines.append(f"Liquidity: ${fmt_num(liquidity_usd, 0)}")
    if mcap_usd is not None:
        lines.append(f"MCap: ${fmt_num(mcap_usd, 0)}")
    lines.append("")
    # Footer links in one row
    footer = " | ".join([
        _a("TX", tx_url),
        _a("DexS", dexs_url),
        _a("Telegram", tg_url),
        _a("Trending", trending_url),
    ])
    lines.append(footer)
    lines.append("")
    if ad_text:
        lines.append(f"ad: {_a(ad_text, ad_url)}")
    else:
        lines.append(f"ad: {_a('Advertise here', book_ads_url)}")
    return "\n".join(lines)

def build_buy_message_channel(
    token_symbol: str,
    emoji: str,
    spent_sol: float,
    spent_usd: float,
    got_tokens: float,
    buyer: str,
    tx_url: str,
    price_usd: Optional[float],
    mcap_usd: Optional[float],
    dexs_url: Optional[str],
    tg_url: Optional[str],
    listing_url: Optional[str],
    buy_url: Optional[str],
    ad_text: Optional[str],
    ad_url: Optional[str],
    book_ads_url: Optional[str],
) -> str:
    # Channel style (like your 2nd screenshot) but WITHOUT holders
    title = f"| {_a(token_symbol, tg_url)} Buy!"
    # more emojis for bigger buys (cap at 26)
    count = 6
    if spent_usd and spent_usd > 0:
        count = max(3, min(26, int(spent_usd // 10) + 3))
    lines = [title, "", emoji_bar(emoji, count), ""]
    usd_part = f" (${fmt_num(spent_usd, 0)})" if spent_usd and spent_usd > 0 else ""
    # keep compact like screenshot
    lines.append(f"Spent: {fmt_num(spent_sol, 2)} SOL{usd_part}")
    lines.append(f"Got: {fmt_num(got_tokens, 2)} {token_symbol}")
    lines.append(f"{_a(short_addr(buyer), tx_url)} | {_a('Txn', tx_url)}")
    if price_usd is not None:
        lines.append(f"💵 Price: ${fmt_num(price_usd, 6)}")
    if mcap_usd is not None:
        lines.append(f"💵 MarketCap: ${fmt_num(mcap_usd, 0)}")
    lines.append("")
    footer = " | ".join([
        _a("💎 Listing", listing_url),
        _a("🐸 Buy", buy_url),
        _a("📊 Chart", dexs_url),
    ])
    lines.append(footer)
    if ad_text:
        lines.append(f"ad: {_a(ad_text, ad_url)}")
    else:
        lines.append(f"ad: {_a('Advertise here', book_ads_url)}")
    return "\n".join(lines)

def build_leaderboard_message(header_handle: str, rows: list[tuple[int,str,float]]) -> str:
    # rows: (rank, symbol, pct_change)
    lines = [f"🟢 {header_handle}"]
    for rank, sym, pct in rows[:3]:
        sign = "+" if pct >= 0 else ""
        lines.append(f"{rank} — ${sym} | {sign}{pct:.0f}%")
    lines.append("______________________________")
    for rank, sym, pct in rows[3:10]:
        sign = "+" if pct >= 0 else ""
        lines.append(f"{rank} — ${sym} | {sign}{pct:.0f}%")
    return "\n".join(lines)
