from __future__ import annotations
import httpx
from typing import Any, Dict, List, Optional, Tuple
import time

class HeliusClient:
    def __init__(self, api_key: str, timeout: float = 20.0):
        self.api_key = api_key
        self.base = "https://api.helius.xyz"
        self.client = httpx.AsyncClient(timeout=timeout)

    async def get_address_txs(self, address: str, limit: int = 20, before: str | None = None) -> list[dict]:
        # Enhanced transactions endpoint
        params = {"api-key": self.api_key}
        if before:
            params["before"] = before
        url = f"{self.base}/v0/addresses/{address}/transactions"
        r = await self.client.get(url, params=params, timeout=20.0)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(data["error"])
        # returns list newest->oldest
        return data[:limit]

    async def close(self):
        await self.client.aclose()

def _find_buy_in_tx(tx: dict, mint: str) -> Optional[dict]:
    # Heuristic:
    # - tokenTransfers includes mint transfers to buyer
    # - nativeTransfers shows SOL outflow from buyer
    token_transfers = tx.get("tokenTransfers") or []
    native_transfers = tx.get("nativeTransfers") or []
    # find any token transfer of target mint with positive amount
    for tt in token_transfers:
        if tt.get("mint") != mint:
            continue
        to_user = tt.get("toUserAccount") or tt.get("toTokenAccount")
        from_user = tt.get("fromUserAccount") or tt.get("fromTokenAccount")
        amount = float(tt.get("tokenAmount", 0) or 0)
        if amount <= 0:
            continue
        # estimate SOL spent: sum native transfers *from* to_user
        spent_lamports = 0
        buyer = tt.get("toUserAccount") or to_user
        for nt in native_transfers:
            if nt.get("fromUserAccount") == buyer:
                spent_lamports += int(nt.get("amount", 0))
        spent_sol = spent_lamports / 1_000_000_000 if spent_lamports else 0.0
        if spent_sol <= 0:
            # sometimes wSOL used; keep as unknown (0) but still treat as buy
            spent_sol = 0.0
        return {
            "buyer": buyer,
            "got_tokens": amount,
            "spent_sol": spent_sol,
            "signature": tx.get("signature"),
            "timestamp": tx.get("timestamp") or tx.get("blockTime") or int(time.time()),
        }
    return None
