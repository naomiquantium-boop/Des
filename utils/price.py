import httpx

async def sol_usd(jupiter_price_url: str) -> float:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(jupiter_price_url)
            r.raise_for_status()
            data = r.json()
            # { data: { SOL: { price: ... } } }
            return float(data["data"]["SOL"]["price"])
    except Exception:
        return 0.0
