from __future__ import annotations
import asyncio, time
import aiosqlite
from typing import List, Tuple

from bot.config import settings
from services.token_meta import fetch_token_meta
from utils.formatter import build_leaderboard_message
from bot.keyboards import leaderboard_kb
from aiogram.exceptions import TelegramBadRequest

class LeaderboardUpdater:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self._running = False

    async def _get_kv(self, conn: aiosqlite.Connection, key: str) -> str | None:
        cur = await conn.execute("SELECT v FROM state_kv WHERE k=?", (key,))
        row = await cur.fetchone()
        return row["v"] if row else None

    async def _set_kv(self, conn: aiosqlite.Connection, key: str, val: str):
        await conn.execute(
            "INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, val),
        )
        await conn.commit()

    async def run_forever(self):
        self._running = True
        while self._running:
            try:
                await self.tick()
            except Exception:
                pass
            await asyncio.sleep(30)

    async def tick(self):
        if not settings.POST_CHANNEL:
            return
        conn = await self.db.connect()
        now = int(time.time())
        since = now - 24*3600

        # top 10 by 24h USD volume
        cur = await conn.execute(
            "SELECT mint, SUM(usd) AS vol FROM buys WHERE ts>=? GROUP BY mint ORDER BY vol DESC LIMIT 10",
            (since,),
        )
        rows = await cur.fetchall()

        leaderboard: List[Tuple[int,str,float]] = []
        rank = 1
        for r in rows:
            mint = r["mint"]
            meta = await fetch_token_meta(mint)
            sym = (meta.get("symbol") or meta.get("name") or mint[:6]).replace('$','')
            pct = await self._pct_change_24h(conn, mint, now)
            leaderboard.append((rank, sym, pct))
            rank += 1

        # fill empty slots
        while len(leaderboard) < 10:
            leaderboard.append((len(leaderboard)+1, "SYMBOL", 0.0))

        handle = f"@{settings.POST_CHANNEL.lstrip('@')}"
        text = build_leaderboard_message(handle, leaderboard)

        mid = await self._get_kv(conn, "leaderboard_message_id")
        if not mid:
            msg = await self.bot.send_message(settings.POST_CHANNEL, text, reply_markup=leaderboard_kb(), disable_web_page_preview=True)
            await self._set_kv(conn, "leaderboard_message_id", str(msg.message_id))
        else:
            try:
                await self.bot.edit_message_text(
                    text=text,
                    chat_id=settings.POST_CHANNEL,
                    message_id=int(mid),
                    reply_markup=leaderboard_kb(),
                )
            except Exception:
                # if edit fails (deleted), resend
                msg = await self.bot.send_message(settings.POST_CHANNEL, text, reply_markup=leaderboard_kb(), disable_web_page_preview=True)
                await self._set_kv(conn, "leaderboard_message_id", str(msg.message_id))

        await conn.close()

    async def _pct_change_24h(self, conn: aiosqlite.Connection, mint: str, now: int) -> float:
        # percent change using price_snapshots: earliest >= now-24h vs latest
        since = now - 24*3600
        cur = await conn.execute(
            "SELECT price_usd, ts FROM price_snapshots WHERE mint=? AND ts>=? ORDER BY ts ASC LIMIT 1",
            (mint, since),
        )
        first = await cur.fetchone()
        cur = await conn.execute(
            "SELECT price_usd, ts FROM price_snapshots WHERE mint=? ORDER BY ts DESC LIMIT 1",
            (mint,),
        )
        last = await cur.fetchone()
        if not first or not last:
            return 0.0
        p0 = float(first["price_usd"])
        p1 = float(last["price_usd"])
        if p0 <= 0:
            return 0.0
        return ((p1 - p0) / p0) * 100.0

    async def close(self):
        self._running = False
