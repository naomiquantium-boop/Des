from __future__ import annotations
import time
import aiosqlite
from typing import Optional

class AdsService:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create_ad(self, created_by: int, text: str, start_ts: int, end_ts: int, tx_sig: str, amount_sol: float, url: str | None = None):
        await self.conn.execute(
            "INSERT INTO ads(created_by,text,url,start_ts,end_ts,tx_sig,amount_sol) VALUES(?,?,?,?,?,?,?)",
            (created_by, text, url, start_ts, end_ts, tx_sig, amount_sol),
        )
        await self.conn.commit()

    async def get_active_ad(self, now_ts: Optional[int] = None) -> tuple[str, str | None] | None:
        now_ts = now_ts or int(time.time())
        cur = await self.conn.execute(
            "SELECT text, url FROM ads WHERE start_ts<=? AND end_ts>=? ORDER BY end_ts DESC LIMIT 1",
            (now_ts, now_ts),
        )
        row = await cur.fetchone()
        return (row["text"], row["url"]) if row else None

    async def set_owner_fallback_timed(self, text: str, url: str | None, end_ts: int):
        # store as: end_ts|text|url
        payload = f"{end_ts}|{text}|{url or ''}"
        await self.conn.execute(
            "INSERT INTO state_kv(k,v) VALUES('owner_fallback_ad', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (payload,),
        )
        await self.conn.commit()

    async def get_owner_fallback(self, now_ts: Optional[int] = None) -> tuple[str, str | None] | None:
        now_ts = now_ts or int(time.time())
        cur = await self.conn.execute("SELECT v FROM state_kv WHERE k='owner_fallback_ad'")
        row = await cur.fetchone()
        if not row:
            return None
        try:
            end_ts_s, text, url = row["v"].split("|", 2)
            if int(end_ts_s) < now_ts:
                return None
            return (text, url or None)
        except Exception:
            # legacy plain text
            return (row["v"], None)
