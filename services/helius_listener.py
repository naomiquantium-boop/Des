from __future__ import annotations
import httpx
from typing import Any, Optional
import time

STABLE_SYMBOLS = {"USDC", "USDT"}
WSOL_MINT = "So11111111111111111111111111111111111111112"

class HeliusClient:
    def __init__(self, api_key: str, timeout: float = 20.0):
        self.api_key = api_key
        self.base = "https://api.helius.xyz"
        self.client = httpx.AsyncClient(timeout=timeout)

    async def get_address_txs(self, address: str, limit: int = 20, before: str | None = None) -> list[dict]:
        params = {"api-key": self.api_key}
        if before:
            params["before"] = before
        url = f"{self.base}/v0/addresses/{address}/transactions"
        r = await self.client.get(url, params=params, timeout=20.0)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(data["error"])
        return data[:limit]

    async def close(self):
        await self.client.aclose()


def _find_buy_in_tx(tx: dict, mint: str) -> Optional[dict]:
    """
    Buy detector tuned to stay permissive enough to keep posting buys, while
    ignoring obvious sells. We prefer Helius swap events, then fall back to
    transfer heuristics.
    """
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

    def _acct(item: dict, *keys: str) -> str | None:
        for k in keys:
            v = item.get(k)
            if v:
                return v
        return None

    # ----- Preferred path: Helius enhanced swap -----
    try:
        token_inputs = swap.get("tokenInputs") or []
        token_outputs = swap.get("tokenOutputs") or []
        native_input = swap.get("nativeInput") or {}

        input_mint = any(i.get("mint") == mint and _fa(i.get("tokenAmount") or i.get("amount")) > 0 for i in token_inputs)
        output_item = None
        for item in token_outputs:
            if item.get("mint") == mint and _fa(item.get("tokenAmount") or item.get("amount")) > 0:
                output_item = item
                break

        # obvious sell: token in, no token out
        if input_mint and output_item is None:
            return None

        if output_item is not None:
            buyer = _acct(output_item, "userAccount", "toUserAccount", "toTokenAccount") or fee_payer
            amount = _fa(output_item.get("tokenAmount") or output_item.get("amount"))
            spent_sol = 0.0
            spent_usd = 0.0
            spent_value = 0.0
            spent_symbol = "SOL"

            lamports = _fa(native_input.get("amount"))
            if lamports > 0:
                spent_sol = lamports / 1_000_000_000 if lamports > 1_000_000 else lamports
                spent_value = spent_sol
                spent_symbol = "SOL"

            for item in token_inputs:
                imint = item.get("mint")
                if imint == mint:
                    continue
                sym = (item.get("tokenSymbol") or item.get("symbol") or "").upper()
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

    # ----- Transfer fallback -----
    def candidate_senders(buyer: str | None) -> list[str]:
        vals: list[str] = []
        for v in [buyer, fee_payer, tx.get("signer")]:
            if v and v not in vals:
                vals.append(v)
        for item in account_keys:
            acct = item.get("account") or item.get("pubkey")
            # only include signer-ish accounts; broad inclusion caused missed buys
            if acct and acct not in vals and item.get("signer"):
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
            if _acct(ot, "fromUserAccount", "fromTokenAccount") not in senders:
                continue
            omint = ot.get("mint")
            if omint == mint:
                continue
            oval = _fa(ot.get("tokenAmount") or ot.get("amount"))
            if oval <= 0:
                continue
            sym = (ot.get("tokenSymbol") or ot.get("symbol") or "").upper()
            if sym in STABLE_SYMBOLS and oval > spent_usd:
                spent_usd = oval
                spent_value = oval
                spent_symbol = sym
            elif omint == WSOL_MINT or sym == "WSOL":
                if oval > spent_sol:
                    spent_sol = oval
                    spent_value = spent_sol
                    spent_symbol = "SOL"
        return spent_sol, spent_usd, spent_value, spent_symbol

    # Gather mint in/out counts to reject obvious sells while staying permissive.
    incoming: list[dict] = []
    outgoing_to_check = 0.0
    for tt in token_transfers:
        if tt.get("mint") != mint:
            continue
        amount = _fa(tt.get("tokenAmount") or tt.get("amount"))
        if amount <= 0:
            continue
        to_user = _acct(tt, "toUserAccount", "toTokenAccount")
        from_user = _acct(tt, "fromUserAccount", "fromTokenAccount")
        if to_user:
            incoming.append({"buyer": to_user, "amount": amount, "from_user": from_user})
        if from_user and from_user in {fee_payer, tx.get("signer")}:
            outgoing_to_check += amount

    if not incoming:
        return None

    # choose largest incoming transfer as the bought amount
    best = max(incoming, key=lambda x: x["amount"])
    buyer = best["buyer"]
    amount = best["amount"]

    # obvious sell / remove-liquidity guard: signer sends out much more tracked token than comes in
    if outgoing_to_check > amount * 1.2:
        return None

    senders = candidate_senders(buyer)
    spent_sol, spent_usd, spent_value, spent_symbol = scan_spend(senders)

    # Fallback: use biggest stable/WSOL outflow in whole tx if sender matching missed router pattern.
    if spent_sol <= 0 and spent_usd <= 0:
        for ot in token_transfers:
            omint = ot.get("mint")
            if omint == mint:
                continue
            oval = _fa(ot.get("tokenAmount") or ot.get("amount"))
            if oval <= 0:
                continue
            sym = (ot.get("tokenSymbol") or ot.get("symbol") or "").upper()
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
