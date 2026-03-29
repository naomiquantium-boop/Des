from pydantic import BaseModel
import os
from typing import List


def _get(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item and item.strip()]


def _rpc_list() -> list[str]:
    urls: list[str] = []
    # New preferred multi-endpoint vars
    for key in ("SOLANA_RPC_PRIMARY", "SOLANA_RPC_SECONDARY", "SOLANA_RPC_FALLBACK"):
        value = os.getenv(key, "").strip()
        if value and value not in urls:
            urls.append(value)

    # Optional comma-separated pool
    for value in _csv_env("SOLANA_RPC_POOL"):
        if value not in urls:
            urls.append(value)

    # Backward compatibility with existing single-endpoint envs
    for key in ("SOLANA_RPC_URL", "SOLANA_RPC"):
        value = os.getenv(key, "").strip()
        if value and value not in urls:
            urls.append(value)

    if not urls:
        urls.append("https://api.mainnet-beta.solana.com")
    return urls


def _ws_list() -> list[str]:
    urls: list[str] = []
    for key in ("SOLANA_WS_PRIMARY", "SOLANA_WS_SECONDARY", "SOLANA_WS_FALLBACK"):
        value = os.getenv(key, "").strip()
        if value and value not in urls:
            urls.append(value)

    for value in _csv_env("SOLANA_WS_POOL"):
        if value not in urls:
            urls.append(value)

    for key in ("SOLANA_WS_URL", "SOLANA_WS"):
        value = os.getenv(key, "").strip()
        if value and value not in urls:
            urls.append(value)

    if not urls:
        urls.append("wss://api.mainnet-beta.solana.com")
    return urls


class Settings(BaseModel):
    BOT_TOKEN: str = _get("BOT_TOKEN")
    OWNER_ID: int = int(_get("OWNER_ID"))
    BOT_USERNAME: str = _get("BOT_USERNAME", "PumpToolsBuyBot")
    POST_CHANNEL: str = _get("POST_CHANNEL", "@PumpToolsTrending")
    LISTING_URL: str = _get("LISTING_URL", "https://t.me/PumpToolsListing")
    TRENDING_URL: str = _get("TRENDING_URL", "https://t.me/PumpToolsTrending")
    LEADERBOARD_MESSAGE_ID: int = int(_get("LEADERBOARD_MESSAGE_ID", "0"))

    DATABASE_URL: str = _get("DATABASE_URL", "sqlite+aiosqlite:///data/buybot.db")

    SOLANA_RPCS: List[str] = _rpc_list()
    SOLANA_RPC: str = SOLANA_RPCS[0]
    SOLANA_WSS: List[str] = _ws_list()
    SOLANA_WS: str = SOLANA_WSS[0]
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")

    PAYMENT_WALLET: str = _get("PAYMENT_WALLET")
    TRENDING_1H_PRICE_SOL: float = float(_get("TRENDING_1H_PRICE_SOL", "0.5"))
    TRENDING_3H_PRICE_SOL: float = float(_get("TRENDING_3H_PRICE_SOL", "1.5"))
    TRENDING_6H_PRICE_SOL: float = float(_get("TRENDING_6H_PRICE_SOL", "2.5"))
    TRENDING_9H_PRICE_SOL: float = float(_get("TRENDING_9H_PRICE_SOL", "3.5"))
    TRENDING_12H_PRICE_SOL: float = float(_get("TRENDING_12H_PRICE_SOL", "4.5"))
    TRENDING_24H_PRICE_SOL: float = float(_get("TRENDING_24H_PRICE_SOL", "7.5"))

    ADS_1D_PRICE_SOL: float = float(_get("ADS_1D_PRICE_SOL", "2"))
    ADS_3D_PRICE_SOL: float = float(_get("ADS_3D_PRICE_SOL", "4.8"))
    ADS_7D_PRICE_SOL: float = float(_get("ADS_7D_PRICE_SOL", "10"))

    POLL_INTERVAL_SEC: int = int(_get("POLL_INTERVAL_SEC", "2"))
    MIN_BUY_DEFAULT_SOL: float = float(_get("MIN_BUY_DEFAULT_SOL", "0.25"))

    JUPITER_PRICE_URL: str = _get("JUPITER_PRICE_URL", "https://price.jup.ag/v6/price?ids=SOL")

    @property
    def BOOK_ADS_URL(self) -> str:
        return f"https://t.me/{self.BOT_USERNAME}?start=ads"


settings = Settings()
