from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
import time
from utils.solana_rpc import SolanaRPC

@dataclass
class PaymentResult:
    ok: bool
    reason: str
    amount_sol: float = 0.0
    slot: Optional[int] = None
    timestamp: Optional[int] = None

def _lamports_to_sol(lamports: int) -> float:
    return lamports / 1_000_000_000

async def verify_sol_transfer(
    rpc: SolanaRPC,
    signature: str,
    expected_to: str,
    min_amount_sol: float,
    max_age_sec: int = 3 * 60 * 60,
) -> PaymentResult:
    tx = await rpc.get_transaction(signature)
    if not tx:
        return PaymentResult(False, "Transaction not found (yet). Try again in 10 seconds.")
    block_time = tx.get("blockTime")
    if block_time and int(time.time()) - int(block_time) > max_age_sec:
        return PaymentResult(False, "Transaction is too old.")
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return PaymentResult(False, "Transaction failed on-chain.")
    message = (tx.get("transaction") or {}).get("message") or {}
    instructions = message.get("instructions") or []
    # Look for system transfer to expected_to
    found = False
    amount_sol = 0.0
    for ix in instructions:
        parsed = ix.get("parsed")
        program = ix.get("program")
        if program == "system" and parsed and parsed.get("type") == "transfer":
            info = parsed.get("info") or {}
            dest = info.get("destination")
            lamports = int(info.get("lamports", 0))
            if dest == expected_to:
                amount_sol = _lamports_to_sol(lamports)
                if amount_sol + 1e-9 >= min_amount_sol:
                    found = True
                    break
    if not found:
        return PaymentResult(False, f"Payment not found. Send at least {min_amount_sol} SOL to {expected_to}.", amount_sol=amount_sol, timestamp=block_time)
    return PaymentResult(True, "Payment verified.", amount_sol=amount_sol, timestamp=block_time)
