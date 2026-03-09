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
    """Classify a tx as a BUY only when the tracked mint is received by the user
    and the user spends SOL/WSOL/stablecoin. Reject sells/liquidity ops.
    """
    token_transfers = tx.get("tokenTransfers") or []
    native_transfers = tx.get("nativeTransfers") or []
    fee_payer = tx.get("feePayer") or tx.get("signer")
    signer = tx.get("signer") or fee_payer
    account_keys = tx.get("accountData") or []
    desc = ((tx.get("description") or "") + " " + (tx.get("type") or "")).lower()
    if any(k in desc for k in ["sell", "remove liquidity", "position close", "liquidity remove", "fees claim"]):
        return None

    def _fa(v: Any) -> float:
        try:
            return float(v or 0)
        except Exception:
            return 0.0

    # Prefer enhanced swap event if present.
    events = tx.get("events") or {}
    swap = events.get("swap") or {}
    try:
        token_inputs = swap.get("tokenInputs") or []
        token_outputs = swap.get("tokenOutputs") or []
        # If tracked mint is an input, user sold it.
        if any((i.get("mint") == mint and _fa(i.get("tokenAmount") or i.get("amount")) > 0) for i in token_inputs):
            return None
        out = None
        for item in token_outputs:
            if item.get("mint") == mint and _fa(item.get("tokenAmount") or item.get("amount")) > 0:
                out = item
                break
        if out is not None:
            buyer = out.get("userAccount") or out.get("toUserAccount") or signer or fee_payer
            amount = _fa(out.get("tokenAmount") or out.get("amount"))
            spent_sol = 0.0
            spent_usd = 0.0
            spent_value = 0.0
            spent_symbol = "SOL"
            native_input = swap.get("nativeInput") or {}
            lamports = _fa(native_input.get("amount"))
            if lamports > 0:
                spent_sol = lamports / 1_000_000_000 if lamports > 1_000_000 else lamports
                spent_value = spent_sol
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
            if amount > 0 and (spent_sol > 0 or spent_usd > 0):
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

    def candidate_senders() -> list[str]:
        vals = []
        for v in [signer, fee_payer]:
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

    senders = candidate_senders()

    # Do not classify as buy if signer/funder is sending out tracked mint.
    for ot in token_transfers:
        if ot.get("mint") == mint and ((ot.get("fromUserAccount") or ot.get("fromTokenAccount")) in senders):
            if _fa(ot.get("tokenAmount")) > 0:
                return None

    # Find tracked mint received by signer/funder. Ignore pool/internal recipients.
    candidate_receipts = []
    for tt in token_transfers:
        if tt.get("mint") != mint:
            continue
        to_user = tt.get("toUserAccount") or tt.get("toTokenAccount")
        amount = _fa(tt.get("tokenAmount"))
        if amount <= 0:
            continue
        if to_user in senders:
            candidate_receipts.append((to_user, amount))
    if not candidate_receipts:
        return None
    buyer, amount = max(candidate_receipts, key=lambda x: x[1])

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
    for ot in token_transfers:
        from_acct = ot.get("fromUserAccount") or ot.get("fromTokenAccount")
        if from_acct not in senders:
            continue
        omint = ot.get("mint")
        if omint == mint:
            continue
        oval = _fa(ot.get("tokenAmount"))
        if oval <= 0:
            continue
        sym = ((ot.get("tokenSymbol") or ot.get("symbol") or "").upper())
        if sym in STABLE_SYMBOLS and oval > spent_usd:
            spent_usd = oval
            spent_value = oval
            spent_symbol = sym
        elif omint == WSOL_MINT or sym == "WSOL":
            if oval > spent_sol:
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
