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
    BOT_USERNAME: str = _get("BOT_USERNAME", "PumpToolsBuyBot")
    POST_CHANNEL: str = _get("POST_CHANNEL", "@PumpToolsTrending")
    LISTING_URL: str = _get("LISTING_URL", "https://t.me/PumpToolsListing")

    DATABASE_URL: str = _get("DATABASE_URL", "sqlite+aiosqlite:///data/buybot.db")

    SOLANA_RPC: str = _get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
    SOLANA_WS: str = _get("SOLANA_WS", "wss://api.mainnet-beta.solana.com")
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

    POLL_INTERVAL_SEC: int = int(_get("POLL_INTERVAL_SEC", "4"))
    MIN_BUY_DEFAULT_SOL: float = float(_get("MIN_BUY_DEFAULT_SOL", "0.25"))

    JUPITER_PRICE_URL: str = _get("JUPITER_PRICE_URL", "https://price.jup.ag/v6/price?ids=SOL")

    @property
    def BOOK_ADS_URL(self) -> str:
        return f"https://t.me/{self.BOT_USERNAME}?start=ads"


settings = Settings()
