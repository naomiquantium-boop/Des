from __future__ import annotations
import asyncio, time
from typing import Dict

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
        self._chat_type_cache: Dict[int, str] = {}

    async def _chat_type(self, chat_id: int) -> str:
        if chat_id in self._chat_type_cache:
            return self._chat_type_cache[chat_id]
        try:
            chat = await self.bot.get_chat(chat_id)
            ctype = getattr(chat, "type", "") or ""
        except Exception:
            ctype = ""
        self._chat_type_cache[chat_id] = ctype
        return ctype

    async def _load_targets(self, conn):
        cur = await conn.execute("SELECT * FROM group_settings WHERE is_active=1")
        rows = await cur.fetchall()
        data = {}
        for r in rows:
            data.setdefault(r["token_mint"], {"groups": [], "post_channel": False})
            data[r["token_mint"]]["groups"].append(r)
        cur = await conn.execute("SELECT * FROM tracked_tokens WHERE is_active=1")
        rows = await cur.fetchall()
        for r in rows:
            data.setdefault(r["mint"], {"groups": [], "post_channel": False})
            if r["post_mode"] == "channel" or r["force_trending"]:
                data[r["mint"]]["post_channel"] = True
        return data

    async def _get_last_sig(self, conn, mint: str):
        cur = await conn.execute("SELECT v FROM state_kv WHERE k=?", (f"last_sig:{mint}",))
        row = await cur.fetchone()
        return row[0] if row else None

    async def _set_last_sig(self, conn, mint: str, sig: str):
        await conn.execute("INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (f"last_sig:{mint}", sig))
        await conn.commit()

    async def run_forever(self):
        self._running = True
        while self._running:
            try:
                await self.tick()
            except Exception:
                pass
            await asyncio.sleep(settings.POLL_INTERVAL_SEC)

    async def tick(self):
        if not self.helius:
            return
        conn = await self.db.connect()
        targets = await self._load_targets(conn)
        ads_svc = AdsService(conn)
        sol_price = await sol_usd(settings.JUPITER_PRICE_URL)
        for mint, tgt in targets.items():
            last_sig = await self._get_last_sig(conn, mint)
            txs = await self.helius.get_address_txs(mint, limit=10)
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
            for ev in reversed(new_events):
                await self._set_last_sig(conn, mint, ev["signature"])
                await self._post_buy(mint, ev, tgt, ads_svc, sol_price)
        await conn.close()

    async def _post_buy(self, mint: str, ev: dict, tgt: dict, ads_svc: AdsService, sol_price: float):
        meta = await fetch_token_meta(mint)
        token_name = meta.get("name") or meta.get("symbol") or mint[:6]
        spent_sol = float(ev.get("spent_sol") or 0.0)
        if spent_sol < float(settings.MIN_BUY_DEFAULT_SOL):
            return
        got_tokens = float(ev.get("got_tokens") or 0.0)
        buyer = ev.get("buyer") or "Unknown"
        spent_usd = spent_sol * sol_price if sol_price else 0.0
        tx_url = TX_URL.format(sig=ev["signature"])
        chart_url = meta.get("dexUrl") or settings.METRICS_URL_TEMPLATE.format(mint=mint)

        conn = await self.db.connect()
        await conn.execute("INSERT INTO buys(mint, usd, ts) VALUES(?,?,?)", (mint, float(spent_usd), int(time.time())))
        if meta.get("priceUsd") is not None:
            await conn.execute("INSERT INTO price_snapshots(mint, price_usd, mcap_usd, ts) VALUES(?,?,?,?)", (mint, float(meta.get("priceUsd")), float(meta.get("mcapUsd") or 0), int(time.time())))
        cur = await conn.execute("SELECT telegram_link, force_trending FROM tracked_tokens WHERE mint=?", (mint,))
        tracked_row = await cur.fetchone()
        tracked_tg = tracked_row[0] if tracked_row else None
        force_trending = bool(tracked_row[1]) if tracked_row else False
        await conn.commit(); await conn.close()

        ad_text, ad_link = await ads_svc.get_active_ad(mint)
        listing_url = tracked_tg or next((r["telegram_link"] for r in tgt.get("groups", []) if r["telegram_link"]), None) or settings.LISTING_URL

        group_msg = build_buy_message_group(
            token_name=token_name,
            dex_name="Pump.fun" if "pump" in (chart_url or "").lower() else "Solana",
            emoji="🟢",
            spent_sol=spent_sol,
            spent_usd=spent_usd,
            got_tokens=got_tokens,
            buyer=buyer,
            tx_url=tx_url,
            price_usd=meta.get("priceUsd"),
            mcap_usd=meta.get("mcapUsd"),
            listing_url=listing_url,
            chart_url=chart_url,
            ad_text=ad_text,
            ad_link=ad_link,
        )
        channel_msg = build_buy_message_channel(
            token_name=token_name,
            emoji="🟢",
            spent_sol=spent_sol,
            spent_usd=spent_usd,
            got_tokens=got_tokens,
            buyer=buyer,
            tx_url=tx_url,
            price_usd=meta.get("priceUsd"),
            mcap_usd=meta.get("mcapUsd"),
            listing_url=listing_url,
            chart_url=chart_url,
            ad_text=ad_text,
            ad_link=ad_link,
            rank_text=None,
        )

        for r in tgt.get("groups", []):
            min_buy = max(float(settings.MIN_BUY_DEFAULT_SOL), float(r["min_buy_sol"] or 0))
            if spent_sol < min_buy:
                continue
            msg = build_buy_message_group(
                token_name=r["token_name"] or token_name,
                dex_name="Pump.fun" if "pump" in (chart_url or "").lower() else "Solana",
                emoji=r["emoji"] or "🟢",
                spent_sol=spent_sol,
                spent_usd=spent_usd,
                got_tokens=got_tokens,
                buyer=buyer,
                tx_url=tx_url,
                price_usd=meta.get("priceUsd") if r["show_price"] else None,
                mcap_usd=meta.get("mcapUsd") if r["show_mcap"] else None,
                listing_url=r["telegram_link"] or listing_url,
                chart_url=chart_url if r["show_dex"] else None,
                ad_text=ad_text,
                ad_link=ad_link,
            )
            try:
                if r["media_file_id"] and r["show_media"] and await self._chat_type(int(r["group_id"])) != "channel":
                    await self.bot.send_photo(int(r["group_id"]), r["media_file_id"], caption=msg, parse_mode="HTML", reply_markup=buy_kb(mint))
                else:
                    await self.bot.send_message(int(r["group_id"]), msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=buy_kb(mint))
            except Exception:
                pass

        if settings.POST_CHANNEL and (tgt.get("post_channel") or force_trending or tgt.get("groups")):
            try:
                await self.bot.send_message(settings.POST_CHANNEL, channel_msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=buy_kb(mint))
            except Exception:
                pass

    async def close(self):
        if self.helius:
            await self.helius.close()
