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
    # 1) Prefer Helius events.swap when present (best for Jupiter/aggregator routes)
    # 2) Fallback to token/native transfers matching
    token_transfers = tx.get("tokenTransfers") or []
    native_transfers = tx.get("nativeTransfers") or []
    fee_payer = tx.get("feePayer") or tx.get("signer")
    account_keys = tx.get("accountData") or []

    events = tx.get("events") or {}
    swap = events.get("swap") or {}

    def _fa(v: Any) -> float:
        try:
            return float(v or 0)
        except Exception:
            return 0.0

    def _net_native_spend(senders: list[str]) -> float:
        lamports = 0
        for nt in native_transfers:
            frm = nt.get("fromUserAccount")
            to = nt.get("toUserAccount")
            amt = int(nt.get("amount", 0) or 0)
            if amt <= 0:
                continue
            if frm in senders:
                lamports += amt
            if to in senders:
                lamports -= amt
        return max(0.0, lamports / 1_000_000_000)

    # Helius enhanced swap format
    try:
        token_inputs = swap.get("tokenInputs") or []
        token_outputs = swap.get("tokenOutputs") or []
        native_input = swap.get("nativeInput") or {}
        if token_outputs:
            out = None
            for item in token_outputs:
                if item.get("mint") == mint and _fa(item.get("tokenAmount") or item.get("amount")) > 0:
                    out = item
                    break
            if out is not None:
                buyer = out.get("userAccount") or out.get("toUserAccount") or out.get("toTokenAccount") or fee_payer
                amount = _fa(out.get("tokenAmount") or out.get("amount"))
                spent_sol = 0.0
                spent_usd = 0.0
                spent_value = 0.0
                spent_symbol = "SOL"

                # Prefer exact token inputs first (USDC/USDT/WSOL).
                # For native SOL swaps, use net native transfers before trusting
                # swap.nativeInput because some routes overfund and refund change.
                for item in token_inputs:
                    imint = item.get("mint")
                    if imint == mint:
                        continue
                    sym = ((item.get("tokenSymbol") or item.get("symbol") or "").upper())
                    val = _fa(item.get("tokenAmount") or item.get("amount"))
                    if val <= 0:
                        continue
                    if sym in STABLE_SYMBOLS and val > spent_usd:
                        spent_usd = val
                        spent_value = val
                        spent_symbol = sym
                    elif imint == WSOL_MINT or sym == "WSOL":
                        if val > spent_sol:
                            spent_sol = val
                            spent_value = val
                            spent_symbol = "SOL"

                if spent_usd <= 0 and spent_sol <= 0:
                    net_native = _net_native_spend([buyer, fee_payer] if fee_payer else [buyer])
                    if net_native > 0:
                        spent_sol = net_native
                        spent_value = net_native
                        spent_symbol = "SOL"

                if spent_usd <= 0 and spent_sol <= 0:
                    lamports = _fa(native_input.get("amount"))
                    if lamports > 0:
                        spent_sol = lamports / 1_000_000_000 if lamports > 1_000_000 else lamports
                        spent_value = spent_sol
                        spent_symbol = "SOL"

                if spent_sol > 0 or spent_usd > 0:
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
    except Exception:
        pass

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
        spent_sol = _net_native_spend(senders)
        if spent_sol > 0:
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
