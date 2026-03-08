from __future__ import annotations
import time


class AdsService:
    def __init__(self, conn):
        self.conn = conn

    async def create_ad(self, created_by: int, text: str, start_ts: int, end_ts: int, tx_sig: str, amount_sol: float, token_mint: str | None = None, link: str | None = None, scope: str = "global"):
        await self.conn.execute(
            "INSERT INTO ads(created_by, token_mint, text, link, scope, start_ts, end_ts, tx_sig, amount_sol) VALUES(?,?,?,?,?,?,?,?,?)",
            (created_by, token_mint, text, link, scope, start_ts, end_ts, tx_sig, amount_sol),
        )
        await self.conn.commit()

    async def get_active_ad(self, token_mint: str | None = None) -> tuple[str | None, str | None]:
        now = int(time.time())
        if token_mint:
            cur = await self.conn.execute(
                "SELECT text, link FROM ads WHERE scope='token' AND token_mint=? AND start_ts<=? AND end_ts>=? ORDER BY id DESC LIMIT 1",
                (token_mint, now, now),
            )
            row = await cur.fetchone()
            if row:
                return row[0], row[1]
        cur = await self.conn.execute(
            "SELECT text, link FROM ads WHERE scope IN ('global','trending') AND start_ts<=? AND end_ts>=? ORDER BY id DESC LIMIT 1",
            (now, now),
        )
        row = await cur.fetchone()
        if row:
            return row[0], row[1]
        cur = await self.conn.execute("SELECT v FROM state_kv WHERE k='owner_fallback_ad'")
        row = await cur.fetchone()
        return (row[0], None) if row else (None, None)

    async def set_owner_fallback(self, text: str):
        await self.conn.execute(
            "INSERT INTO state_kv(k,v) VALUES('owner_fallback_ad', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (text,),
        )
        await self.conn.commit()
