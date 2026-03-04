from __future__ import annotations
import httpx
from typing import Optional

DEX_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"

async def fetch_token_meta(mint: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(DEX_TOKEN_URL.format(mint=mint))
        r.raise_for_status()
        data = r.json()
    pairs = data.get("pairs") or []
    if not pairs:
        return {"name": mint[:6], "symbol": mint[:6], "priceUsd": None, "liquidityUsd": None, "fdv": None, "dexUrl": None}
    # pick most liquid pair
    pairs.sort(key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)
    p = pairs[0]
    base = p.get("baseToken") or {}
    name = base.get("name") or base.get("symbol") or mint[:6]
    symbol = base.get("symbol") or name
    price = p.get("priceUsd")
    liq = (p.get("liquidity") or {}).get("usd")
    fdv = p.get("fdv")
    dex_url = p.get("url")
    return {
        "name": name,
        "symbol": symbol,
        "priceUsd": float(price) if price is not None else None,
        "liquidityUsd": float(liq) if liq is not None else None,
        "mcapUsd": float(fdv) if fdv is not None else None,
        "dexUrl": dex_url,
        "gtUrl": None,  # placeholder if you want to add geckoterminal
    }
