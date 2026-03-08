from __future__ import annotations
import asyncio
import time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.config import settings
from bot.keyboards import (
    main_menu_kb,
    token_list_kb,
    trending_package_kb,
    advert_duration_kb,
    invoice_kb,
)
from services.payment_verifier import verify_sol_transfer, find_recent_payment
from services.ads_service import AdsService
from services.token_meta import fetch_token_meta
from database.db import DB
from utils.solana_rpc import SolanaRPC

router = Router()


class TrendingFlow(StatesGroup):
    token = State()
    package = State()
    link = State()
    emoji = State()


class AdvertFlow(StatesGroup):
    token = State()
    link = State()
    content = State()
    duration = State()


TREND_PRICES = {
    "1h": (settings.TRENDING_1H_PRICE_SOL, 3600, "1 Hours"),
    "3h": (settings.TRENDING_3H_PRICE_SOL, 3 * 3600, "3 Hours"),
    "6h": (settings.TRENDING_6H_PRICE_SOL, 6 * 3600, "6 Hours"),
    "9h": (settings.TRENDING_9H_PRICE_SOL, 9 * 3600, "9 Hours"),
    "12h": (settings.TRENDING_12H_PRICE_SOL, 12 * 3600, "12 Hours"),
    "24h": (settings.TRENDING_24H_PRICE_SOL, 24 * 3600, "24 Hours"),
}
ADS_PRICES = {
    "1d": (settings.ADS_1D_PRICE_SOL, 86400, "1 Day"),
    "3d": (settings.ADS_3D_PRICE_SOL, 3 * 86400, "3 Days"),
    "7d": (settings.ADS_7D_PRICE_SOL, 7 * 86400, "7 Days"),
}


def _is_owner(msg: Message | CallbackQuery) -> bool:
    user = msg.from_user
    return bool(user and user.id == settings.OWNER_ID)


async def _tokens_for_user(db: DB, user_id: int) -> list[tuple[str, str]]:
    conn = await db.connect()
    cur = await conn.execute("SELECT mint, COALESCE(symbol, name, mint) AS label FROM tracked_tokens ORDER BY created_at DESC LIMIT 50")
    rows = await cur.fetchall()
    await conn.close()
    return [(r["mint"], r["label"]) for r in rows]


async def _create_invoice(db: DB, user_id: int, username: str | None, token_mint: str, kind: str, link: str | None, content: str | None, emoji: str | None, amount_sol: float, duration_sec: int) -> int:
    conn = await db.connect()
    now = int(time.time())
    cur = await conn.execute(
        "INSERT INTO invoices(user_id, username, token_mint, kind, link, content, emoji, amount_sol, duration_sec, wallet, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, username, token_mint, kind, link, content, emoji, amount_sol, duration_sec, settings.PAYMENT_WALLET, now),
    )
    await conn.commit()
    invoice_id = cur.lastrowid
    await conn.close()
    return int(invoice_id)


async def _used_signatures(db: DB) -> set[str]:
    conn = await db.connect()
    cur = await conn.execute("SELECT tx_sig FROM invoices WHERE tx_sig IS NOT NULL")
    rows = await cur.fetchall()
    await conn.close()
    return {r[0] for r in rows if r[0]}


async def _activate_invoice(db: DB, invoice_id: int, sig: str, amount_sol: float):
    conn = await db.connect()
    cur = await conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,))
    inv = await cur.fetchone()
    if not inv or inv["status"] == "paid":
        await conn.close()
        return False
    now = int(time.time())
    await conn.execute("UPDATE invoices SET status='paid', tx_sig=?, verified_at=? WHERE id=?", (sig, now, invoice_id))
    if inv["kind"] == "trending":
        await conn.execute(
            "UPDATE tracked_tokens SET force_trending=1, force_leaderboard=1, trend_until_ts=?, telegram_link=COALESCE(?, telegram_link) WHERE mint=?",
            (now + int(inv["duration_sec"]), inv["link"], inv["token_mint"]),
        )
    elif inv["kind"] == "ad":
        ads = AdsService(conn)
        await ads.create_ad(inv["user_id"], inv["content"] or "", inv["link"], now, now + int(inv["duration_sec"]), sig, amount_sol, "ad")
    await conn.commit()
    await conn.close()
    return True


async def _invoice_text(db: DB, invoice_id: int) -> tuple[str, float]:
    conn = await db.connect()
    cur = await conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,))
    inv = await cur.fetchone()
    await conn.close()
    if not inv:
        return ("Invoice not found.", 0.0)
    title = "Trending" if inv["kind"] == "trending" else "Advert"
    text = (
        f"💱 <b>Invoice</b>\n\n"
        f"Paying for: <b>{title}</b>\n\n"
        f"Wallet:\n<code>{inv['wallet']}</code>\n"
        f"Wallet Balance: 0 SOL\n\n"
        f"⋙ Please send <b>{inv['amount_sol']:g} SOL</b> to the wallet above"
    )
    return text, float(inv["amount_sol"])


async def _watch_invoice(bot, db: DB, rpc: SolanaRPC, chat_id: int, invoice_id: int):
    for _ in range(18):
        await asyncio.sleep(10)
        used = await _used_signatures(db)
        conn = await db.connect()
        cur = await conn.execute("SELECT amount_sol, status FROM invoices WHERE id=?", (invoice_id,))
        inv = await cur.fetchone()
        await conn.close()
        if not inv or inv["status"] == "paid":
            return
        res = await find_recent_payment(rpc, settings.PAYMENT_WALLET, float(inv["amount_sol"]), used)
        if res.ok and res.signature:
            changed = await _activate_invoice(db, invoice_id, res.signature, res.amount_sol)
            if changed:
                await bot.send_message(chat_id, "✅ Payment detected and verified automatically.")
            return


@router.message(Command("start"))
async def start(msg: Message, state: FSMContext, command: CommandObject | None = None):
    await state.clear()
    arg = (command.args or "").strip() if command else ""
    if msg.chat.type != "private":
        return await msg.reply("Hi! Tap Configure to set me up (I must be admin).")
    if arg == "ads":
        await msg.answer("💎 Advertise your token\nPromote your token to millions of users across thousands of groups.\n\nSelect your token to continue.", reply_markup=main_menu_kb())
        return
    await msg.answer("Pumptools main menu", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:home")
async def menu_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.answer("Pumptools main menu", reply_markup=main_menu_kb())
    await cq.answer()


@router.callback_query(F.data == "menu:advert")
async def advert_menu(cq: CallbackQuery, db: DB, state: FSMContext):
    await state.clear()
    tokens = await _tokens_for_user(db, cq.from_user.id)
    if not tokens:
        await cq.message.answer("No tracked tokens yet. Add one with /addtoken <mint> | <telegram_link>")
    else:
        await cq.message.answer(
            "💎 Advertise your token\nPromote your token to millions of users across thousands of groups.\n\nSelect your token to continue.",
            reply_markup=token_list_kb(tokens, "adtoken", back="menu:home"),
        )
    await cq.answer()


@router.callback_query(F.data.startswith("adtoken:"))
async def advert_pick_token(cq: CallbackQuery, state: FSMContext):
    mint = cq.data.split(":", 1)[1]
    await state.set_state(AdvertFlow.link)
    await state.update_data(token_mint=mint)
    await cq.message.answer("💎 Fill in the advert form to finish.\nToken selected.\n\n— FILL FORM —\n\nLink ✏️\nContent ✏️\nDuration ✏️\n\n« Return")
    await cq.message.answer("⬇️ Send your Telegram group/channel link (e.g. https://t.me/pumptools)")
    await cq.answer()


@router.message(AdvertFlow.link)
async def advert_link(msg: Message, state: FSMContext):
    await state.update_data(link=(msg.text or "").strip())
    await state.set_state(AdvertFlow.content)
    await msg.answer("⬇️ Enter your advert text.")


@router.message(AdvertFlow.content)
async def advert_content(msg: Message, state: FSMContext):
    await state.update_data(content=(msg.text or "").strip())
    await state.set_state(AdvertFlow.duration)
    await msg.answer("How many days should this advert run?", reply_markup=advert_duration_kb())


@router.callback_query(F.data.startswith("adpkg:"))
async def advert_duration(cq: CallbackQuery, state: FSMContext, db: DB, rpc: SolanaRPC):
    key = cq.data.split(":", 1)[1]
    if key not in ADS_PRICES:
        return await cq.answer()
    price, seconds, label = ADS_PRICES[key]
    data = await state.get_data()
    invoice_id = await _create_invoice(
        db,
        cq.from_user.id,
        cq.from_user.username,
        data["token_mint"],
        "ad",
        data.get("link"),
        data.get("content"),
        None,
        price,
        seconds,
    )
    text, amount = await _invoice_text(db, invoice_id)
    await cq.message.answer(text, reply_markup=invoice_kb(invoice_id, amount), disable_web_page_preview=True)
    await state.clear()
    asyncio.create_task(_watch_invoice(cq.bot, db, rpc, cq.message.chat.id, invoice_id))
    await cq.answer(f"Invoice created for {label}")


@router.callback_query(F.data == "menu:trending")
async def trending_menu(cq: CallbackQuery, db: DB, state: FSMContext):
    await state.clear()
    tokens = await _tokens_for_user(db, cq.from_user.id)
    if not tokens:
        await cq.message.answer("No tracked tokens yet. Add one with /addtoken <mint> | <telegram_link>")
    else:
        await cq.message.answer(
            "Your token will be shown here:\n@PumpToolsTrending.\nChoose how many hours you want your token to trend.\n\nHi, please select your token below.",
            reply_markup=token_list_kb(tokens, "trendtoken", back="menu:home"),
        )
    await cq.answer()


@router.callback_query(F.data.startswith("trendtoken:"))
async def trending_pick_token(cq: CallbackQuery, state: FSMContext):
    mint = cq.data.split(":", 1)[1]
    meta = await fetch_token_meta(mint)
    token_label = meta.get("symbol") or meta.get("name") or mint[:6]
    await state.set_state(TrendingFlow.package)
    await state.update_data(token_mint=mint, token_label=token_label, package="1h")
    price = TREND_PRICES["1h"][0]
    await cq.message.answer(
        f"📊 Almost done. Choose your Trending package, then provide a link and (optionally) a custom emoji.\n"
        f"Token: {token_label}\nDuration: 1 Hours\nPrice: {price:g} SOL\nLink: —\n\n— CHOOSE PACKAGE —\n\n— MORE —\nLink ✏️\nEmoji (Optional) ✏️",
        reply_markup=trending_package_kb("1h"),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("trendpkg:"))
async def trending_package(cq: CallbackQuery, state: FSMContext, db: DB, rpc: SolanaRPC):
    action = cq.data.split(":", 1)[1]
    data = await state.get_data()
    if action in TREND_PRICES:
        await state.update_data(package=action)
        price, _, label = TREND_PRICES[action]
        await cq.message.answer(
            f"📊 Almost done. Choose your Trending package, then provide a link and (optionally) a custom emoji.\n"
            f"Token: {data.get('token_label', 'Token')}\nDuration: {label}\nPrice: {price:g} SOL\nLink: {data.get('link') or '—'}",
            reply_markup=trending_package_kb(action),
        )
        return await cq.answer()
    if action == "continue":
        if not data.get("link"):
            await state.set_state(TrendingFlow.link)
            await cq.message.answer("⬇️ Send your Telegram group/channel link.")
            return await cq.answer()
        package = data.get("package", "1h")
        price, seconds, _ = TREND_PRICES[package]
        invoice_id = await _create_invoice(
            db,
            cq.from_user.id,
            cq.from_user.username,
            data["token_mint"],
            "trending",
            data.get("link"),
            None,
            data.get("emoji"),
            price,
            seconds,
        )
        text, amount = await _invoice_text(db, invoice_id)
        await cq.message.answer(text, reply_markup=invoice_kb(invoice_id, amount), disable_web_page_preview=True)
        await state.clear()
        asyncio.create_task(_watch_invoice(cq.bot, db, rpc, cq.message.chat.id, invoice_id))
        return await cq.answer("Invoice created")
    await cq.answer()


@router.message(TrendingFlow.link)
async def trending_link(msg: Message, state: FSMContext):
    await state.update_data(link=(msg.text or "").strip())
    await state.set_state(TrendingFlow.emoji)
    await msg.answer("Optional: send a custom emoji or type skip.")


@router.message(TrendingFlow.emoji)
async def trending_emoji(msg: Message, state: FSMContext):
    emoji = (msg.text or "").strip()
    if emoji.lower() == "skip":
        emoji = ""
    await state.update_data(emoji=emoji)
    data = await state.get_data()
    package = data.get("package", "1h")
    price, _, label = TREND_PRICES[package]
    await state.set_state(TrendingFlow.package)
    await msg.answer(
        f"📊 Almost done. Choose your Trending package, then provide a link and (optionally) a custom emoji.\n"
        f"Token: {data.get('token_label', 'Token')}\nDuration: {label}\nPrice: {price:g} SOL\nLink: {data.get('link') or '—'}",
        reply_markup=trending_package_kb(package),
    )


@router.callback_query(F.data.startswith("invoice:refresh:"))
async def invoice_refresh(cq: CallbackQuery, db: DB, rpc: SolanaRPC):
    invoice_id = int(cq.data.rsplit(":", 1)[1])
    conn = await db.connect()
    cur = await conn.execute("SELECT status, amount_sol FROM invoices WHERE id=?", (invoice_id,))
    inv = await cur.fetchone()
    await conn.close()
    if not inv:
        return await cq.answer("Invoice not found.", show_alert=True)
    if inv["status"] == "paid":
        return await cq.answer("Already paid.", show_alert=True)
    used = await _used_signatures(db)
    res = await find_recent_payment(rpc, settings.PAYMENT_WALLET, float(inv["amount_sol"]), used)
    if not res.ok or not res.signature:
        return await cq.answer("Payment not detected yet.", show_alert=True)
    changed = await _activate_invoice(db, invoice_id, res.signature, res.amount_sol)
    if changed:
        await cq.message.answer("✅ Payment verified and campaign activated.")
    await cq.answer()


@router.callback_query(F.data.in_({"menu:lang", "menu:edit", "menu:add", "menu:view", "menu:group"}))
async def placeholder_menu(cq: CallbackQuery):
    labels = {
        "menu:lang": "Language settings will go here.",
        "menu:edit": "Edit flow will go here.",
        "menu:add": "Add Token: use /addtoken <mint> | <telegram_link>",
        "menu:view": "View Tokens: use /tokens",
        "menu:group": "Group settings are managed when the bot is added to a group.",
    }
    await cq.message.answer(labels.get(cq.data, "Coming soon."))
    await cq.answer()


@router.message(Command("tokens"))
async def tokens_cmd(msg: Message, db: DB):
    rows = await _tokens_for_user(db, msg.from_user.id if msg.from_user else 0)
    if not rows:
        return await msg.reply("No tracked tokens.")
    text = "Tracked tokens:\n" + "\n".join([f"• {label} — <code>{mint}</code>" for mint, label in rows])
    await msg.reply(text)


@router.message(Command("addtoken"))
async def addtoken(msg: Message, command: CommandObject, db: DB):
    if not _is_owner(msg):
        return
    if not command.args:
        return await msg.reply("Usage: /addtoken <MINT> | <telegram_link(optional)>")
    raw = command.args.strip()
    parts = [p.strip() for p in raw.split("|", 1)]
    mint = parts[0]
    tg_link = parts[1] if len(parts) > 1 else None
    meta = await fetch_token_meta(mint)
    conn = await db.connect()
    await conn.execute(
        "INSERT INTO tracked_tokens(mint, post_mode, telegram_link, symbol, name, force_trending, force_leaderboard, created_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET post_mode='channel', telegram_link=COALESCE(excluded.telegram_link, tracked_tokens.telegram_link), symbol=excluded.symbol, name=excluded.name",
        (mint, 'channel', tg_link, meta.get('symbol'), meta.get('name'), 0, 0, int(time.time())),
    )
    await conn.commit()
    await conn.close()
    await msg.reply(f"✅ Tracking enabled for {mint}.")


@router.message(Command("forcetrending"))
async def forcetrending(msg: Message, command: CommandObject, db: DB):
    if not _is_owner(msg) or not command.args:
        return
    parts = [p.strip() for p in command.args.split()]
    mint = parts[0]
    hours = int(parts[1]) if len(parts) > 1 else 24
    until = int(time.time()) + hours * 3600
    conn = await db.connect()
    await conn.execute("UPDATE tracked_tokens SET force_trending=1, force_leaderboard=1, trend_until_ts=? WHERE mint=?", (until, mint))
    await conn.commit()
    await conn.close()
    await msg.reply("✅ Token forced into trending.")


@router.message(Command("setad"))
async def setad(msg: Message, command: CommandObject, db: DB):
    if not _is_owner(msg) or not command.args:
        return
    conn = await db.connect()
    ads = AdsService(conn)
    await ads.set_owner_fallback(command.args.strip())
    await conn.close()
    await msg.reply("✅ Fallback ad text updated.")


@router.message(Command("adset"))
async def adset(msg: Message, command: CommandObject, db: DB):
    if not _is_owner(msg) or not command.args:
        return
    parts = [p.strip() for p in command.args.split("|")]
    if len(parts) < 3:
        return await msg.reply("Usage: /adset <duration_hours> | <text> | <link>")
    hours = int(parts[0])
    text = parts[1]
    link = parts[2]
    now = int(time.time())
    conn = await db.connect()
    ads = AdsService(conn)
    await ads.create_ad(settings.OWNER_ID, text, link, now, now + hours * 3600, f"owner:{now}", 0.0, "ad")
    await conn.close()
    await msg.reply("✅ Ad created.")


@router.message(Command("status"))
async def status(msg: Message, db: DB):
    if not _is_owner(msg):
        return
    conn = await db.connect()
    cur = await conn.execute("SELECT COUNT(*) FROM tracked_tokens")
    tokens = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM invoices WHERE status='pending'")
    pending = (await cur.fetchone())[0]
    await conn.close()
    await msg.reply(f"Tracked tokens: {tokens}\nPending invoices: {pending}")
