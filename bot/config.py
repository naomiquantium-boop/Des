from pydantic import BaseModel
import os

def _get(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v

class Settings(BaseModel):
    BOT_TOKEN: str = _get("BOT_TOKEN")
    OWNER_ID: int = int(_get("OWNER_ID"))
    POST_CHANNEL: str = _get("POST_CHANNEL", "@PumpToolsTrending")
    LISTING_URL: str = _get("LISTING_URL", "https://t.me/PumpToolsListing")
    # Where users book ads. Used for the clickable "Advertise here" line.
    # IMPORTANT: Keep this fixed to avoid misconfiguration via env vars.
    BOOK_ADS_URL: str = "https://t.me/DevAtPumpTools"

    DATABASE_URL: str = _get("DATABASE_URL", "sqlite+aiosqlite:///data/buybot.db")

    SOLANA_RPC: str = _get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
    SOLANA_WS: str = _get("SOLANA_WS", "wss://api.mainnet-beta.solana.com")
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")

    PAYMENT_WALLET: str = _get("PAYMENT_WALLET")
    ADS_6H_PRICE_SOL: float = float(_get("ADS_6H_PRICE_SOL", "1"))
    ADS_12H_PRICE_SOL: float = float(_get("ADS_12H_PRICE_SOL", "1.5"))
    ADS_24H_PRICE_SOL: float = float(_get("ADS_24H_PRICE_SOL", "3"))

    POLL_INTERVAL_SEC: int = int(_get("POLL_INTERVAL_SEC", "4"))
    # Global minimum buy. Any buy smaller than this is ignored (group + channel).
    MIN_BUY_DEFAULT_SOL: float = float(_get("MIN_BUY_DEFAULT_SOL", "0.7"))

    JUPITER_PRICE_URL: str = _get("JUPITER_PRICE_URL", "https://price.jup.ag/v6/price?ids=SOL")

settings = Settings()
