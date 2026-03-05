from __future__ import annotations
import asyncio
import time
from typing import Dict, List, Optional, Tuple
import aiosqlite

from bot.config import settings
from services.helius_listener import HeliusClient, _find_buy_in_tx
from services.token_meta import fetch_token_meta
from services.ads_service import AdsService
from utils.price import sol_usd
from utils.formatter import build_buy_message_group, build_buy_message_channel
from bot.keyboards import buy_kb

TX_URL = "https://solscan.io/tx/{sig}"

class BuyWatcher:
    def __init__(self, bot, db, rpc):
        self.bot = bot
        self.db = db
        self.rpc = rpc
        self.helius = HeliusClient(settings.HELIUS_API_KEY) if settings.HELIUS_API_KEY else None
        self._running = False
        # cache chat types so we don't call get_chat repeatedly
        self._chat_type_cache: Dict[int, str] = {}

    async def _chat_type(self, chat_id: int) -> str:
        """Return Telegram chat type (group/supergroup/channel/private)."""
        if chat_id in self._chat_type_cache:
            return self._chat_type_cache[chat_id]
        try:
            chat = await self.bot.get_chat(chat_id)
            ctype = getattr(chat, "type", "") or ""
        except Exception:
            ctype = ""
        self._chat_type_cache[chat_id] = ctype
        return ctype

    async def _load_targets(self, conn: aiosqlite.Connection) -> dict:
        # returns mint -> {groups:[(group_id, settings)], post_channel:bool}
        cur = await conn.execute("SELECT * FROM group_settings WHERE is_active=1")
        rows = await cur.fetchall()
        m = {}
        for r in rows:
            mint = r["token_mint"]
            m.setdefault(mint, {"groups": [], "post_channel": False})
            m[mint]["groups"].append(r)

        cur = await conn.execute("SELECT mint, post_mode FROM tracked_tokens")
        rows2 = await cur.fetchall()
        for r in rows2:
            mint = r["mint"]
            m.setdefault(mint, {"groups": [], "post_channel": False})
            if r["post_mode"] == "channel":
                m[mint]["post_channel"] = True
        return m

    async def _get_last_sig(self, conn: aiosqlite.Connection, mint: str) -> str | None:
        cur = await conn.execute("SELECT v FROM state_kv WHERE k=?", (f"last_sig:{mint}",))
        row = await cur.fetchone()
        return row["v"] if row else None

    async def _set_last_sig(self, conn: aiosqlite.Connection, mint: str, sig: str):
        await conn.execute(
            "INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (f"last_sig:{mint}", sig),
        )
        await conn.commit()

    async def run_forever(self):
        self._running = True
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                # keep running
                pass
            await asyncio.sleep(settings.POLL_INTERVAL_SEC)

    async def tick(self):
        conn = await self.db.connect()
        targets = await self._load_targets(conn)
        ads_svc = AdsService(conn)
        ad_text = await ads_svc.get_active_ad_text() or await ads_svc.get_owner_fallback()
        sol_price = await sol_usd(settings.JUPITER_PRICE_URL)

        for mint, tgt in targets.items():
            if not self.helius:
                continue  # require helius for reliable detection in this starter
            last_sig = await self._get_last_sig(conn, mint)
            txs = await self.helius.get_address_txs(mint, limit=10)
            # txs are newest first
            new_events = []
            for tx in txs:
                sig = tx.get("signature")
                if not sig:
                    continue
                if sig == last_sig:
                    break
                ev = _find_buy_in_tx(tx, mint)
                if ev:
                    new_events.append(ev)
            # process oldest -> newest
            for ev in reversed(new_events):
                sig = ev["signature"]
                await self._set_last_sig(conn, mint, sig)
                await self._post_buy(mint, ev, tgt, ad_text, sol_price)

        await conn.close()

    async def _post_buy(self, mint: str, ev: dict, tgt: dict, ad_text: str | None, sol_price: float):
        meta = await fetch_token_meta(mint)
        token_name = meta.get("symbol") or meta.get("name") or mint[:6]
        spent_sol = float(ev.get("spent_sol") or 0.0)
        got_tokens = float(ev.get("got_tokens") or 0.0)
        buyer = ev.get("buyer") or "Unknown"
        spent_usd = spent_sol * sol_price if sol_price and spent_sol else 0.0

        # Global min-buy filter for BOTH group + channel.
        # Any event below this is ignored (reduces spam and blocks sells that come through as 0.00 SOL).
        if spent_sol < float(settings.MIN_BUY_DEFAULT_SOL):
            return
        now_ts = int(time.time())
        try:
            conn2 = await self.db.connect()
            if spent_usd and spent_usd > 0:
                await conn2.execute("INSERT INTO buys(mint, usd, ts) VALUES(?,?,?)", (mint, float(spent_usd), now_ts))
            if meta.get("priceUsd") is not None:
                await conn2.execute("INSERT INTO price_snapshots(mint, price_usd, ts) VALUES(?,?,?)", (mint, float(meta.get("priceUsd")), now_ts))
            await conn2.commit()
            await conn2.close()
        except Exception:
            pass

        tx_url = TX_URL.format(sig=ev["signature"])
        dexs_url = meta.get("dexUrl")
        tg_url = None
        # pick a default Telegram link for this token from any active group config
        try:
            for _r in tgt.get("groups", []):
                if _r.get("telegram_link"):
                    tg_url = _r.get("telegram_link")
                    break
        except Exception:
            tg_url = None

        # prefer owner-set telegram link for tracked tokens
        try:
            conn_tg = await self.db.connect()
            cur2 = await conn_tg.execute("SELECT telegram_link FROM tracked_tokens WHERE mint=?", (mint,))
            row2 = await cur2.fetchone()
            await conn_tg.close()
            if row2 and row2[0]:
                tg_url = row2[0]
        except Exception:
            pass
        trending_url = None
        # trending channel link (clickable)
        if settings.POST_CHANNEL:
            ch = settings.POST_CHANNEL.lstrip("@")
            trending_url = f"https://t.me/{ch}"

        # group message uses group settings emoji and tg link (if set)
        msg_text = build_buy_message_group(
            token_symbol=token_name,
            emoji="🟢",
            spent_sol=spent_sol,
            spent_usd=spent_usd,
            got_tokens=got_tokens,
            buyer=buyer,
            tx_url=tx_url,
            price_usd=meta.get("priceUsd"),
            liquidity_usd=meta.get("liquidityUsd"),
            mcap_usd=meta.get("mcapUsd"),
            dexs_url=dexs_url,
            tg_url=tg_url,
            trending_url=trending_url,
            ad_text=ad_text,
        )

        msg_text_channel = build_buy_message_channel(
            token_symbol=token_name,
            emoji="✅",
            spent_sol=spent_sol,
            spent_usd=spent_usd,
            got_tokens=got_tokens,
            buyer=buyer,
            tx_url=tx_url,
            price_usd=meta.get("priceUsd"),
            mcap_usd=meta.get("mcapUsd"),
            dexs_url=dexs_url,
            tg_url=tg_url,
            trending_url=trending_url,
            ad_text=ad_text,
        )


        # send to groups (respect group settings, but never below global min)
        for r in tgt["groups"]:
            min_buy = max(float(settings.MIN_BUY_DEFAULT_SOL), float(r["min_buy_sol"]))
            if spent_sol is None or spent_sol < min_buy:
                continue
            emoji = r["emoji"]
            tg = r["telegram_link"] or None
            media = r["media_file_id"]
            chat_id = int(r["group_id"])
            ctype = await self._chat_type(chat_id)

            # If this chat is a channel, NEVER attach media.
            # Channel buys must be text-only.
            if ctype == "channel":
                msg_text2 = build_buy_message_channel(
                    token_symbol=token_name,
                    emoji="✅",
                    spent_sol=spent_sol,
                    spent_usd=spent_usd,
                    got_tokens=got_tokens,
                    buyer=buyer,
                    tx_url=tx_url,
                    price_usd=meta.get("priceUsd"),
                    mcap_usd=meta.get("mcapUsd"),
                    dexs_url=dexs_url,
                    tg_url=tg,
                    trending_url=trending_url,
                    ad_text=ad_text,
                )
                try:
                    await self.bot.send_message(
                        chat_id,
                        msg_text2,
                        reply_markup=buy_kb(token_name, mint),
                        disable_web_page_preview=True,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                continue

            # rebuild message with group preferences
            msg_text2 = build_buy_message_group(
                token_symbol=token_name,
                emoji=emoji,
                spent_sol=spent_sol,
                spent_usd=spent_usd,
                got_tokens=got_tokens,
                buyer=buyer,
                tx_url=tx_url,
                price_usd=meta.get("priceUsd"),
                liquidity_usd=meta.get("liquidityUsd"),
                mcap_usd=meta.get("mcapUsd"),
                dexs_url=dexs_url,
                tg_url=tg,
                trending_url=trending_url,
                ad_text=ad_text,
            )

            try:
                if media:
                    await self.bot.send_photo(
                        chat_id,
                        media,
                        caption=msg_text2,
                        reply_markup=buy_kb(token_name, mint),
                        parse_mode="HTML",
                    )
                else:
                    await self.bot.send_message(
                        chat_id,
                        msg_text2,
                        reply_markup=buy_kb(token_name, mint),
                        disable_web_page_preview=True,
                        parse_mode="HTML",
                    )
            except Exception:
                pass

        # Post to channel ONCE if:
        # - channel is configured AND
        # - token is either configured in a group OR owner-added for channel-only mode.
        if settings.POST_CHANNEL and (tgt.get("groups") or tgt.get("post_channel")):
            try:
                await self.bot.send_message(
                    settings.POST_CHANNEL,
                    msg_text_channel,
                    reply_markup=buy_kb(token_name, mint),
                    disable_web_page_preview=True,
                    parse_mode="HTML",
                )
            except Exception:
                pass

    async def close(self):
        if self.helius:
            await self.helius.close()
