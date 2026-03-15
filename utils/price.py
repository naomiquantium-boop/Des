import httpx


async def _fetch_json(url: str, timeout: float = 10.0):
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.json()


async def sol_usd(jupiter_price_url: str) -> float:
    # Try Jupiter first. If that fails, fall back to CoinGecko.
    try:
        data = await _fetch_json(jupiter_price_url)
        return float(data["data"]["SOL"]["price"])
    except Exception:
        pass
    try:
        data = await _fetch_json(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        )
        return float(data["solana"]["usd"])
    except Exception:
        return 0.0
