from __future__ import annotations
import asyncio
import time
from typing import Dict, Optional
import aiosqlite

from bot.config import settings
from services.helius_listener import HeliusClient, _find_buy_in_tx, WSOL_MINT
from services.token_meta import fetch_token_meta
from services.ads_service import AdsService
from utils.price import sol_usd
from utils.formatter import build_buy_message_group, build_buy_message_channel
from bot.keyboards import buy_kb

TX_URL = "https://solscan.io/tx/{sig}"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD8M6rjX4jvQ7bF4Y3Pp7k"  # common mainnet mint
STABLE_MINTS = {USDC_MINT, USDT_MINT}


def _safe_float(v) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _token_balance_maps(tx: dict, mint: str):
    meta = tx.get("meta") or {}
    pre = meta.get("preTokenBalances") or []
    post = meta.get("postTokenBalances") or []

    def collect(rows):
        m = {}
        for r in rows:
            if r.get("mint") != mint:
                continue
            owner = r.get("owner") or r.get("accountIndex")
            amt = _safe_float(((r.get("uiTokenAmount") or {}).get("uiAmount")))
            if owner is not None:
                m[owner] = amt
        return m

    return collect(pre), collect(post)


def _all_token_deltas(tx: dict):
    meta = tx.get("meta") or {}
    pre = meta.get("preTokenBalances") or []
    post = meta.get("postTokenBalances") or []
    keys = set()
    for r in pre + post:
        keys.add((r.get("mint"), r.get("owner") or r.get("accountIndex")))
    deltas = {}
    for mint, owner in keys:
        pre_amt = 0.0
        post_amt = 0.0
        for r in pre:
            if r.get("mint") == mint and (r.get("owner") or r.get("accountIndex")) == owner:
                pre_amt = _safe_float(((r.get("uiTokenAmount") or {}).get("uiAmount")))
                break
        for r in post:
            if r.get("mint") == mint and (r.get("owner") or r.get("accountIndex")) == owner:
                post_amt = _safe_float(((r.get("uiTokenAmount") or {}).get("uiAmount")))
                break
        deltas[(mint, owner)] = post_amt - pre_amt
    return deltas


def _signers_and_fee_payer(tx: dict):
    msg = ((tx.get("transaction") or {}).get("message") or {})
    aks = msg.get("accountKeys") or []
    principals = []
    fee_payer = None
    for i, a in enumerate(aks):
        if isinstance(a, str):
            pubkey = a
            signer = (i == 0)
        else:
            pubkey = a.get("pubkey")
            signer = bool(a.get("signer")) or (i == 0)
        if i == 0:
            fee_payer = pubkey
        if signer and pubkey and pubkey not in principals:
            principals.append(pubkey)
    if fee_payer and fee_payer not in principals:
        principals.append(fee_payer)
    return principals, fee_payer, aks


def _native_spend_sol(tx: dict, principals, fee_payer, aks):
    meta = tx.get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    fee = _safe_float(meta.get("fee"))
    spent = 0.0
    for i, a in enumerate(aks):
        pubkey = a if isinstance(a, str) else a.get("pubkey")
        if pubkey not in principals:
            continue
        if i >= len(pre) or i >= len(post):
            continue
        delta_lamports = post[i] - pre[i]
        if delta_lamports < 0:
            dec = -delta_lamports
            if pubkey == fee_payer:
                dec = max(0, dec - fee)
            spent = max(spent, dec / 1_000_000_000)
    return spent


def _find_buy_in_rpc_tx(tx: dict, mint: str) -> Optional[dict]:
    # Ignore obvious non-buy action labels from parsed transaction.
    meta = tx.get("meta") or {}
    logs = " ".join(meta.get("logMessages") or []).lower()
    if any(x in logs for x in ["remove_liquidity", "withdraw", "claim", "closeposition", "remove liquidity"]):
        return None

    principals, fee_payer, aks = _signers_and_fee_payer(tx)
    pre_t, post_t = _token_balance_maps(tx, mint)
    deltas_tracked = {owner: post_t.get(owner, 0.0) - pre_t.get(owner, 0.0) for owner in set(pre_t) | set(post_t)}

    # Buyer must be one of the signers / fee payer and net receive tracked token.
    buyer = None
    got_tokens = 0.0
    for owner in principals:
        delta = deltas_tracked.get(owner, 0.0)
        if delta > got_tokens:
            got_tokens = delta
            buyer = owner
    if not buyer or got_tokens <= 0:
        return None

    # If signer also net sent out tracked token, treat as sell / other interaction.
    if any(deltas_tracked.get(owner, 0.0) < 0 for owner in principals):
        return None

    token_deltas = _all_token_deltas(tx)
    spent_sol = 0.0
    spent_usd = 0.0
    spent_value = 0.0
    spent_symbol = "SOL"

    for owner in principals:
        wsol_delta = token_deltas.get((WSOL_MINT, owner), 0.0)
        if wsol_delta < 0:
            spent_sol = max(spent_sol, -wsol_delta)
        for stable in STABLE_MINTS:
            sd = token_deltas.get((stable, owner), 0.0)
            if sd < 0:
                spent_usd = max(spent_usd, -sd)

    if spent_sol <= 0 and spent_usd <= 0:
        spent_sol = _native_spend_sol(tx, principals, fee_payer, aks)

    if spent_sol <= 0 and spent_usd <= 0:
        return None

    if spent_usd > 0:
        spent_value = spent_usd
        spent_symbol = "USDC"
    else:
        spent_value = spent_sol
        spent_symbol = "SOL"

    return {
        "buyer": buyer,
        "got_tokens": got_tokens,
        "spent_sol": spent_sol,
        "spent_usd": spent_usd,
        "spent_value": spent_value,
        "spent_symbol": spent_symbol,
        "signature": tx.get("transaction", {}).get("signatures", [None])[0] or tx.get("signature"),
        "timestamp": tx.get("blockTime") or int(time.time()),
    }


class BuyWatcher:
    def __init__(self, bot, db, rpc):
        self.bot = bot
        self.db = db
        self.rpc = rpc
        self.helius = HeliusClient(settings.HELIUS_API_KEY) if settings.HELIUS_API_KEY else None
        self._helius_disabled = False
        self._running = False
        self._last_sol_price = 100.0
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

    async def _load_targets(self, conn: aiosqlite.Connection) -> dict:
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
        print("[buy_watcher] started", flush=True)
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                print(f"[buy_watcher] tick failed: {e}", flush=True)
            await asyncio.sleep(settings.POLL_INTERVAL_SEC)

    async def _fetch_events(self, mint: str, last_sig: str | None):
        events = []
        newest_sig = None
        # Prefer Helius if configured and healthy, but permanently fall back to RPC
        # once Helius starts failing or returning no usable data.
        if self.helius and not self._helius_disabled:
            try:
                txs = await self.helius.get_address_txs(mint, limit=10)
                if txs:
                    for tx in txs:
                        sig = tx.get("signature")
                        if not sig:
                            continue
                        if newest_sig is None:
                            newest_sig = sig
                        if sig == last_sig:
                            break
                        ev = _find_buy_in_tx(tx, mint)
                        if ev:
                            events.append(ev)
                    return list(reversed(events)), newest_sig
                else:
                    print(f"[buy_watcher] helius returned empty for {mint}; switching to rpc fallback", flush=True)
                    self._helius_disabled = True
            except Exception as e:
                print(f"[buy_watcher] helius failed for {mint}: {e}; switching to rpc fallback", flush=True)
                self._helius_disabled = True
        # Fallback to plain RPC / Alchemy.
        try:
            print(f"[buy_watcher] using rpc fallback for {mint}", flush=True)
            sigs = await self.rpc.get_signatures_for_address(mint, limit=10)
            collected = []
            for item in sigs:
                sig = item.get("signature")
                if not sig:
                    continue
                if newest_sig is None:
                    newest_sig = sig
                if sig == last_sig:
                    break
                tx = await self.rpc.get_transaction(sig)
                if not tx:
                    continue
                ev = _find_buy_in_rpc_tx(tx, mint)
                if ev:
                    collected.append(ev)
            return list(reversed(collected)), newest_sig
        except Exception as e:
            print(f"[buy_watcher] rpc fallback failed for {mint}: {e}", flush=True)
            return [], newest_sig

    async def tick(self):
        conn = await self.db.connect()
        targets = await self._load_targets(conn)
        ads_svc = AdsService(conn)
        active_ad_text, active_ad_link = await ads_svc.get_active_ad()
        ad_text = active_ad_text or await ads_svc.get_owner_fallback()
        ad_link = active_ad_link if active_ad_text else None
        sol_price = await sol_usd(settings.JUPITER_PRICE_URL)
        if sol_price and sol_price > 0:
            self._last_sol_price = sol_price
        else:
            sol_price = self._last_sol_price

        for mint, tgt in targets.items():
            last_sig = await self._get_last_sig(conn, mint)
            new_events, newest_sig = await self._fetch_events(mint, last_sig)
            if newest_sig and newest_sig != last_sig and not new_events:
                await self._set_last_sig(conn, mint, newest_sig)
            for ev in new_events:
                sig = ev["signature"]
                await self._set_last_sig(conn, mint, sig)
                await self._post_buy(mint, ev, tgt, ad_text, ad_link, sol_price)

        await conn.close()

    async def _post_buy(self, mint: str, ev: dict, tgt: dict, ad_text: str | None, ad_link: str | None, sol_price: float):
        meta = await fetch_token_meta(mint)
        token_name = meta.get("symbol") or meta.get("name") or mint[:6]
        spent_sol = float(ev.get("spent_sol") or 0.0)
        got_tokens = float(ev.get("got_tokens") or 0.0)
        buyer = ev.get("buyer") or "Unknown"
        direct_spent_usd = float(ev.get("spent_usd") or 0.0)
        spent_symbol = ev.get("spent_symbol") or "SOL"
        spent_value = float(ev.get("spent_value") or 0.0)
        spent_usd = direct_spent_usd or ((float(meta.get("priceUsd")) * got_tokens) if meta.get("priceUsd") is not None and got_tokens else (spent_sol * sol_price if sol_price and spent_sol else 0.0))
        effective_spent_sol = spent_sol or ((spent_usd / sol_price) if spent_usd and sol_price else (spent_usd / self._last_sol_price if spent_usd and self._last_sol_price else 0.0))

        # Global default min-buy filter. Token-level min_buy can raise it further below.
        if effective_spent_sol < float(settings.MIN_BUY_DEFAULT_SOL):
            return
        now_ts = int(time.time())
        try:
            conn2 = await self.db.connect()
            if spent_usd and spent_usd > 0:
                await conn2.execute("INSERT INTO buys(mint, usd, ts) VALUES(?,?,?)", (mint, float(spent_usd), now_ts))
            if meta.get("priceUsd") is not None:
                await conn2.execute("INSERT INTO price_snapshots(mint, price_usd, ts) VALUES(?,?,?)", (mint, float(meta.get("priceUsd")), now_ts))
            if meta.get("mcapUsd") is not None:
                await conn2.execute("INSERT INTO mcap_snapshots(mint, mcap_usd, ts) VALUES(?,?,?)", (mint, float(meta.get("mcapUsd")), now_ts))
            await conn2.commit()
            await conn2.close()
        except Exception:
            pass

        tx_url = TX_URL.format(sig=ev["signature"])
        tg_url = None
        token_cfg = {"buy_step": 1, "min_buy": 0.0, "emoji": "🟢", "media_file_id": None, "media_kind": "photo"}
        # pick a default Telegram link for this token from any active group config
        try:
            for _r in tgt.get("groups", []):
                if _r.get("telegram_link"):
                    tg_url = _r.get("telegram_link")
                    break
        except Exception:
            tg_url = None

        # prefer owner-set telegram link for tracked tokens, and load token settings
        try:
            conn_tg = await self.db.connect()
            cur2 = await conn_tg.execute("SELECT telegram_link FROM tracked_tokens WHERE mint=?", (mint,))
            row2 = await cur2.fetchone()
            cur3 = await conn_tg.execute("SELECT buy_step, min_buy, emoji, media_file_id, media_kind FROM token_settings WHERE mint=?", (mint,))
            row3 = await cur3.fetchone()
            await conn_tg.close()
            if row2 and row2[0]:
                tg_url = row2[0]
            if row3:
                token_cfg = {"buy_step": row3[0] or 1, "min_buy": float(row3[1] or 0.0), "emoji": row3[2] or "🟢", "media_file_id": row3[3], "media_kind": row3[4] or "photo"}
        except Exception:
            pass
        # group message uses group settings emoji and tg link (if set)
        _ = build_buy_message_group(
            token_symbol=token_name,
            emoji="🟢",
            spent_sol=effective_spent_sol,
            spent_usd=spent_usd,
            spent_symbol=spent_symbol,
            spent_value=spent_value or (effective_spent_sol if spent_symbol == "SOL" else direct_spent_usd),
            got_tokens=got_tokens,
            buyer=buyer,
            tx_url=tx_url,
            price_usd=meta.get("priceUsd"),
            mcap_usd=meta.get("mcapUsd"),
            tg_url=tg_url,
            ad_text=ad_text,
            ad_link=ad_link,
            chart_url=meta.get("dexUrl"),
        )

        msg_text_channel = build_buy_message_channel(
            token_symbol=token_name,
            emoji="✅",
            spent_sol=effective_spent_sol,
            spent_usd=spent_usd,
            spent_symbol=spent_symbol,
            spent_value=spent_value or (effective_spent_sol if spent_symbol == "SOL" else direct_spent_usd),
            got_tokens=got_tokens,
            buyer=buyer,
            tx_url=tx_url,
            price_usd=meta.get("priceUsd"),
            mcap_usd=meta.get("mcapUsd"),
            tg_url=tg_url,
            ad_text=ad_text,
            ad_link=ad_link,
            chart_url=meta.get("dexUrl"),
        )


        # send to groups (respect group settings, but never below global min)
        for r in tgt["groups"]:
            min_buy = max(float(settings.MIN_BUY_DEFAULT_SOL), float(r["min_buy_sol"] or 0), float(token_cfg.get("min_buy") or 0))
            if effective_spent_sol is None or effective_spent_sol < min_buy:
                continue
            emoji = token_cfg.get("emoji") or r["emoji"] or "🟢"
            tg = tg_url or r["telegram_link"] or None
            media = token_cfg.get("media_file_id") or r["media_file_id"]
            media_kind = token_cfg.get("media_kind") or "photo"
            chat_id = int(r["group_id"])
            ctype = await self._chat_type(chat_id)

            # If this chat is a channel, NEVER attach media.
            # Channel buys must be text-only.
            if ctype == "channel":
                msg_text2 = build_buy_message_channel(
                    token_symbol=token_name,
                    emoji="✅",
                    spent_sol=effective_spent_sol,
                    spent_usd=spent_usd,
                    spent_symbol=spent_symbol,
                    spent_value=spent_value or (effective_spent_sol if spent_symbol == "SOL" else direct_spent_usd),
                    got_tokens=got_tokens,
                    buyer=buyer,
                    tx_url=tx_url,
                    price_usd=meta.get("priceUsd"),
                    mcap_usd=meta.get("mcapUsd"),
                    tg_url=tg,
                    ad_text=ad_text,
                    ad_link=ad_link,
                    chart_url=meta.get("dexUrl"),
                )
                try:
                    await self.bot.send_message(
                        chat_id,
                        msg_text2,
                        reply_markup=buy_kb(mint),
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
                spent_sol=effective_spent_sol,
                spent_usd=spent_usd,
                spent_symbol=spent_symbol,
                spent_value=spent_value or (effective_spent_sol if spent_symbol == "SOL" else direct_spent_usd),
                got_tokens=got_tokens,
                buyer=buyer,
                tx_url=tx_url,
                price_usd=meta.get("priceUsd"),
                mcap_usd=meta.get("mcapUsd"),
                tg_url=tg,
                ad_text=ad_text,
                ad_link=ad_link,
                chart_url=meta.get("dexUrl"),
            )

            try:
                if media:
                    if media_kind == "animation":
                        await self.bot.send_animation(
                        chat_id,
                            media,
                            caption=msg_text2,
                            reply_markup=buy_kb(mint),
                            parse_mode="HTML",
                        )
                    else:
                        if media_kind == "video":
                            await self.bot.send_video(
                                chat_id,
                                media,
                                caption=msg_text2,
                                reply_markup=buy_kb(mint),
                                parse_mode="HTML",
                            )
                        elif media_kind == "document":
                            await self.bot.send_document(
                                chat_id,
                                media,
                                caption=msg_text2,
                                reply_markup=buy_kb(mint),
                                parse_mode="HTML",
                            )
                        else:
                            await self.bot.send_photo(
                                chat_id,
                                media,
                                caption=msg_text2,
                                reply_markup=buy_kb(mint),
                                parse_mode="HTML",
                            )
                else:
                    await self.bot.send_message(
                        chat_id,
                        msg_text2,
                        reply_markup=buy_kb(mint),
                        disable_web_page_preview=True,
                        parse_mode="HTML",
                    )
            except Exception:
                pass

        # Post to channel ONCE if:
        # - channel is configured AND
        # - token is either configured in a group OR owner-added for channel-only mode AND
        # - the buy meets at least the hard channel minimum of 0.25 SOL.
        channel_min_buy = max(0.25, float(settings.MIN_BUY_DEFAULT_SOL), float(token_cfg.get("min_buy") or 0))
        if settings.POST_CHANNEL and (tgt.get("groups") or tgt.get("post_channel")) and effective_spent_sol >= channel_min_buy:
            try:
                await self.bot.send_message(
                    settings.POST_CHANNEL,
                    msg_text_channel,
                    reply_markup=buy_kb(mint),
                    disable_web_page_preview=True,
                    parse_mode="HTML",
                )
            except Exception:
                pass

    async def close(self):
        if self.helius:
            await self.helius.close()
