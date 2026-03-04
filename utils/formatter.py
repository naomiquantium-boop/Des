from __future__ import annotations
from typing import Optional
import math

def short_addr(a: str, left: int = 4, right: int = 4) -> str:
    if len(a) <= left + right + 3:
        return a
    return f"{a[:left]}...{a[-right:]}"

def emoji_bar(emoji: str, count: int = 3) -> str:
    return (emoji * count).strip()

def fmt_num(x: float, decimals: int = 2) -> str:
    try:
        return f"{x:,.{decimals}f}"
    except Exception:
        return str(x)

def fmt_int(x: int) -> str:
    try:
        return f"{x:,d}"
    except Exception:
        return str(x)

def build_buy_message(
    token_name: str,
    emoji: str,
    spent_sol: float,
    spent_usd: float,
    got_tokens: float,
    buyer: str,
    tx_url: str,
    price_usd: Optional[float],
    liquidity_usd: Optional[float],
    mcap_usd: Optional[float],
    gt_url: Optional[str],
    dexs_url: Optional[str],
    tg_url: Optional[str],
    ad_text: Optional[str],
) -> str:
    lines = []
    lines.append(f"{token_name} Buy!")
    lines.append("")
    lines.append(emoji_bar(emoji, 3))
    lines.append("")
    usd_part = f" (${fmt_num(spent_usd, 0)})" if spent_usd > 0 else ""
    lines.append(f"Spent: {fmt_num(spent_sol, 2)} SOL{usd_part}")
    lines.append(f"Got: {fmt_num(got_tokens, 2)} {token_name}")
    lines.append("")
    lines.append(f"{short_addr(buyer)} | Txn")
    lines.append("")
    if price_usd is not None:
        lines.append(f"Price: ${fmt_num(price_usd, 6)}")
    if liquidity_usd is not None:
        lines.append(f"Liquidity: ${fmt_num(liquidity_usd, 0)}")
    if mcap_usd is not None:
        lines.append(f"MCap: ${fmt_num(mcap_usd, 0)}")
    lines.append("")
    links = []
    links.append(f"TX")
    if gt_url: links.append("GT")
    if dexs_url: links.append("DexS")
    if tg_url: links.append("Telegram")
    lines.append(" | ".join(links))
    if ad_text:
        lines.append("")
        lines.append(f"ad: {ad_text}")
    return "\n".join(lines)
