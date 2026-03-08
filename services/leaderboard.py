from __future__ import annotations
import asyncio, time
from aiogram.exceptions import TelegramBadRequest
from bot.config import settings
from bot.keyboards import leaderboard_kb
from services.token_meta import fetch_token_meta
from utils.formatter import build_leaderboard_message


class LeaderboardUpdater:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self._running = False

    async def _get_kv(self, conn, key: str):
        cur = await conn.execute("SELECT v FROM state_kv WHERE k=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None

    async def _set_kv(self, conn, key: str, val: str):
        await conn.execute("INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, val))
        await conn.commit()

    async def run_forever(self):
        self._running = True
        while self._running:
            try:
                await self.tick()
            except Exception:
                pass
            await asyncio.sleep(settings.LEADERBOARD_INTERVAL_SEC)

    async def tick(self):
        if not settings.POST_CHANNEL:
            return
        conn = await self.db.connect()
        now = int(time.time())
        since = now - 24 * 3600
        cur = await conn.execute(
            "SELECT mint, SUM(usd) as vol FROM buys WHERE ts>=? GROUP BY mint ORDER BY vol DESC LIMIT 20",
            (since,),
        )
        buy_rows = await cur.fetchall()
        cur = await conn.execute("SELECT mint, manual_rank, manual_boost, force_leaderboard FROM tracked_tokens WHERE is_active=1 ORDER BY created_at DESC")
        tracked = await cur.fetchall()
        items: dict[str, dict] = {}
        for r in buy_rows:
            items[r["mint"]] = {"mint": r["mint"], "score": float(r["vol"] or 0), "manual_rank": None, "force": 0}
        for r in tracked:
            item = items.setdefault(r["mint"], {"mint": r["mint"], "score": 0.0, "manual_rank": r["manual_rank"], "force": r["force_leaderboard"]})
            item["score"] += float(r["manual_boost"] or 0)
            item["manual_rank"] = r["manual_rank"]
            item["force"] = r["force_leaderboard"]

        ranked = sorted(items.values(), key=lambda x: ((x["manual_rank"] is None), x["manual_rank"] or 9999, -x["force"], -x["score"]))[:10]
        rows = []
        rank = 1
        for item in ranked:
            meta = await fetch_token_meta(item["mint"])
            rows.append({
                "rank": rank,
                "symbol": (meta.get("symbol") or meta.get("name") or item["mint"][:6]).replace("$", ""),
                "mcap": meta.get("mcapUsd") or item["score"],
                "pct": 0.0,
            })
            rank += 1
        while len(rows) < 10:
            rows.append({"rank": len(rows) + 1, "symbol": "TOKEN", "mcap": 0, "pct": 0.0})

        text = build_leaderboard_message(rows)
        mid = await self._get_kv(conn, "leaderboard_message_id")
        if not mid:
            msg = await self.bot.send_message(settings.POST_CHANNEL, text, reply_markup=leaderboard_kb(), disable_web_page_preview=True)
            await self._set_kv(conn, "leaderboard_message_id", str(msg.message_id))
        else:
            try:
                await self.bot.edit_message_text(text=text, chat_id=settings.POST_CHANNEL, message_id=int(mid), reply_markup=leaderboard_kb(), disable_web_page_preview=True)
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e).lower():
                    msg = await self.bot.send_message(settings.POST_CHANNEL, text, reply_markup=leaderboard_kb(), disable_web_page_preview=True)
                    await self._set_kv(conn, "leaderboard_message_id", str(msg.message_id))
        await conn.close()

    async def close(self):
        self._running = False
