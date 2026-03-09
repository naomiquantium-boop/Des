from __future__ import annotations
import httpx
from typing import Any, Dict, List, Optional, Tuple
import time

STABLE_SYMBOLS = {"USDC", "USDT"}
WSOL_MINT = "So11111111111111111111111111111111111111112"

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
    # Heuristic with SOL/WSOL/stablecoin support:
    # - find token transfer of tracked mint to buyer
    # - detect what was spent in native SOL or tokenTransfers (USDC/USDT/WSOL)
    # - support routes where the actual spender is the signer / fee payer, not the final token receiver
    token_transfers = tx.get("tokenTransfers") or []
    native_transfers = tx.get("nativeTransfers") or []
    fee_payer = tx.get("feePayer") or tx.get("signer")
    account_keys = tx.get("accountData") or []

    def candidate_senders(buyer: str) -> list[str]:
        vals = []
        for v in [buyer, fee_payer]:
            if v and v not in vals:
                vals.append(v)
        for item in account_keys:
            try:
                acct = item.get("account") or item.get("pubkey")
            except Exception:
                acct = None
            if acct and acct not in vals:
                vals.append(acct)
        return vals

    def scan_spend(senders: list[str]) -> tuple[float, float, float, str]:
        spent_sol = 0.0
        spent_usd = 0.0
        spent_value = 0.0
        spent_symbol = "SOL"
        spent_lamports = 0
        for nt in native_transfers:
            if nt.get("fromUserAccount") in senders:
                spent_lamports += int(nt.get("amount", 0) or 0)
        if spent_lamports > 0:
            spent_sol = spent_lamports / 1_000_000_000
            spent_value = spent_sol
            spent_symbol = "SOL"
        for ot in token_transfers:
            if (ot.get("fromUserAccount") or ot.get("fromTokenAccount")) not in senders:
                continue
            omint = ot.get("mint")
            if omint == mint:
                continue
            oval = float(ot.get("tokenAmount", 0) or 0)
            if oval <= 0:
                continue
            sym = ((ot.get("tokenSymbol") or ot.get("symbol") or "").upper())
            if sym in STABLE_SYMBOLS:
                if oval > spent_usd:
                    spent_usd = oval
                    spent_value = oval
                    spent_symbol = sym
            elif omint == WSOL_MINT or sym == "WSOL":
                if oval > spent_sol:
                    spent_sol = oval
                    spent_value = spent_sol
                    spent_symbol = "SOL"
        return spent_sol, spent_usd, spent_value, spent_symbol

    for tt in token_transfers:
        if tt.get("mint") != mint:
            continue
        buyer = tt.get("toUserAccount") or tt.get("toTokenAccount")
        amount = float(tt.get("tokenAmount", 0) or 0)
        if not buyer or amount <= 0:
            continue

        senders = candidate_senders(buyer)
        spent_sol, spent_usd, spent_value, spent_symbol = scan_spend(senders)

        # Fallback: use the largest stable/WSOL outflow in the whole tx if sender matching failed.
        if spent_sol <= 0 and spent_usd <= 0:
            for ot in token_transfers:
                omint = ot.get("mint")
                if omint == mint:
                    continue
                oval = float(ot.get("tokenAmount", 0) or 0)
                if oval <= 0:
                    continue
                sym = ((ot.get("tokenSymbol") or ot.get("symbol") or "").upper())
                if sym in STABLE_SYMBOLS and oval > spent_usd:
                    spent_usd = oval
                    spent_value = oval
                    spent_symbol = sym
                elif (omint == WSOL_MINT or sym == "WSOL") and oval > spent_sol:
                    spent_sol = oval
                    spent_value = oval
                    spent_symbol = "SOL"

        if spent_sol <= 0 and spent_usd <= 0:
            return None
        return {
            "buyer": buyer,
            "got_tokens": amount,
            "spent_sol": spent_sol,
            "spent_usd": spent_usd,
            "spent_value": spent_value if spent_value > 0 else (spent_usd or spent_sol),
            "spent_symbol": spent_symbol,
            "signature": tx.get("signature"),
            "timestamp": tx.get("timestamp") or tx.get("blockTime") or int(time.time()),
        }
    return None
