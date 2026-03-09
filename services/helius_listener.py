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

    # Collect principal user accounts we treat as the trader.
    principals: list[str] = []
    for v in [fee_payer, tx.get("signer")]:
        if v and v not in principals:
            principals.append(v)
    for item in account_keys:
        acct = item.get("account") or item.get("pubkey")
        if acct and acct not in principals:
            principals.append(acct)

    def _is_principal(acct: str | None) -> bool:
        return bool(acct and acct in principals)

    def _net_token_for_principals(target_mint: str) -> tuple[float, float]:
        incoming = 0.0
        outgoing = 0.0
        for tr in token_transfers:
            if tr.get("mint") != target_mint:
                continue
            amt = _fa(tr.get("tokenAmount") or tr.get("amount"))
            if amt <= 0:
                continue
            if _is_principal(tr.get("toUserAccount") or tr.get("toTokenAccount")):
                incoming += amt
            if _is_principal(tr.get("fromUserAccount") or tr.get("fromTokenAccount")):
                outgoing += amt
        return incoming, outgoing

    def _net_quote_spend() -> tuple[float, float, float, str]:
        # Returns (spent_sol, spent_usd, spent_value, spent_symbol) for quote assets
        native_out = 0
        native_in = 0
        for nt in native_transfers:
            amt = int(nt.get("amount", 0) or 0)
            if amt <= 0:
                continue
            if _is_principal(nt.get("fromUserAccount")):
                native_out += amt
            if _is_principal(nt.get("toUserAccount")):
                native_in += amt
        spent_sol = max(0.0, (native_out - native_in) / 1_000_000_000)
        spent_usd = 0.0
        spent_value = spent_sol
        spent_symbol = "SOL" if spent_sol > 0 else ""

        stable_net = 0.0
        wsol_net = 0.0
        for tr in token_transfers:
            tmint = tr.get("mint")
            if tmint == mint:
                continue
            amt = _fa(tr.get("tokenAmount") or tr.get("amount"))
            if amt <= 0:
                continue
            sym = (tr.get("tokenSymbol") or tr.get("symbol") or "").upper()
            out = _is_principal(tr.get("fromUserAccount") or tr.get("fromTokenAccount"))
            inn = _is_principal(tr.get("toUserAccount") or tr.get("toTokenAccount"))
            delta = (amt if out else 0.0) - (amt if inn else 0.0)
            if sym in STABLE_SYMBOLS:
                stable_net = max(stable_net, delta)
            elif tmint == WSOL_MINT or sym == "WSOL":
                wsol_net = max(wsol_net, delta)
        if stable_net > 0:
            spent_usd = stable_net
            spent_value = stable_net
            spent_symbol = "USDC"
        elif wsol_net > 0 and wsol_net > spent_sol:
            spent_sol = wsol_net
            spent_value = wsol_net
            spent_symbol = "SOL"
        return spent_sol, spent_usd, spent_value, spent_symbol or "SOL"

    # Strong direction check using net flow of the tracked token.
    incoming_mint, outgoing_mint = _net_token_for_principals(mint)
    net_got = incoming_mint - outgoing_mint
    if net_got <= 0:
        return None  # sells / LP removals / internal transfers should not count as buys

    # Prefer enhanced swap event, but only if it matches principal net token direction.
    try:
        token_outputs = swap.get("tokenOutputs") or []
        for item in token_outputs:
            if item.get("mint") != mint:
                continue
            amt = _fa(item.get("tokenAmount") or item.get("amount"))
            buyer = item.get("userAccount") or item.get("toUserAccount") or item.get("toTokenAccount") or fee_payer
            if amt <= 0 or not _is_principal(buyer):
                continue
            spent_sol, spent_usd, spent_value, spent_symbol = _net_quote_spend()
            if spent_sol <= 0 and spent_usd <= 0:
                return None
            return {
                "buyer": buyer,
                "got_tokens": net_got,
                "spent_sol": spent_sol,
                "spent_usd": spent_usd,
                "spent_value": spent_value if spent_value > 0 else (spent_usd or spent_sol),
                "spent_symbol": spent_symbol,
                "signature": tx.get("signature"),
                "timestamp": tx.get("timestamp") or tx.get("blockTime") or int(time.time()),
            }
    except Exception:
        pass

    # Fallback based purely on net transfer direction.
    spent_sol, spent_usd, spent_value, spent_symbol = _net_quote_spend()
    if spent_sol <= 0 and spent_usd <= 0:
        return None
    return {
        "buyer": fee_payer or tx.get("signer") or "Unknown",
        "got_tokens": net_got,
        "spent_sol": spent_sol,
        "spent_usd": spent_usd,
        "spent_value": spent_value if spent_value > 0 else (spent_usd or spent_sol),
        "spent_symbol": spent_symbol,
        "signature": tx.get("signature"),
        "timestamp": tx.get("timestamp") or tx.get("blockTime") or int(time.time()),
    }
