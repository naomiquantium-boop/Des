from __future__ import annotations
import time
import aiosqlite
from typing import Optional

class AdsService:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create_ad(self, created_by: int, text: str, start_ts: int, end_ts: int, tx_sig: str, amount_sol: float):
        await self.conn.execute(
            "INSERT INTO ads(created_by,text,start_ts,end_ts,tx_sig,amount_sol) VALUES(?,?,?,?,?,?)",
            (created_by, text, start_ts, end_ts, tx_sig, amount_sol),
        )
        await self.conn.commit()

    async def get_active_ad_text(self, now_ts: Optional[int] = None) -> Optional[str]:
        now_ts = now_ts or int(time.time())
        cur = await self.conn.execute(
            "SELECT text FROM ads WHERE start_ts<=? AND end_ts>=? ORDER BY end_ts DESC LIMIT 1",
            (now_ts, now_ts),
        )
        row = await cur.fetchone()
        return row["text"] if row else None

    async def set_owner_fallback(self, text: str):
        await self.conn.execute("INSERT INTO state_kv(k,v) VALUES('owner_fallback_ad', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (text,))
        await self.conn.commit()

    async def get_owner_fallback(self) -> Optional[str]:
        cur = await self.conn.execute("SELECT v FROM state_kv WHERE k='owner_fallback_ad'")
        row = await cur.fetchone()
        return row["v"] if row else None
