from __future__ import annotations
import asyncio
import re
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
    lang_kb,
    token_action_kb,
)
from services.payment_verifier import find_recent_payment
from services.ads_service import AdsService
from services.token_meta import fetch_token_meta
from database.db import DB
from utils.solana_rpc import SolanaRPC

router = Router()
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class TrendingFlow(StatesGroup):
    package = State()
    link = State()
    emoji = State()


class AdvertFlow(StatesGroup):
    link = State()
    content = State()
    duration = State()


class AddTokenFlow(StatesGroup):
    mint = State()
    tg = State()


class EditTokenFlow(StatesGroup):
    tg = State()


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


def _norm_tg(v: str | None) -> str | None:
    if not v:
        return None
    t = v.strip()
    if not t or t.lower() == "skip":
        return None
    if t.startswith("@"):
        return f"https://t.me/{t[1:]}"
    if t.startswith("t.me/"):
        return f"https://{t}"
    if t.startswith("http://"):
        return f"https://{t[7:]}"
    return t


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


async def _upsert_tracked_token(db: DB, mint: str, telegram_link: str | None = None):
    meta = await fetch_token_meta(mint)
    conn = await db.connect()
    await conn.execute(
        "INSERT INTO tracked_tokens(mint, post_mode, telegram_link, symbol, name, force_trending, force_leaderboard, created_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(mint) DO UPDATE SET telegram_link=COALESCE(excluded.telegram_link, tracked_tokens.telegram_link), symbol=excluded.symbol, name=excluded.name",
        (mint, "channel", telegram_link, meta.get("symbol"), meta.get("name"), 0, 0, int(time.time())),
    )
    await conn.commit()
    await conn.close()
    return meta


async def _group_status_text(db: DB, group_id: int) -> str:
    conn = await db.connect()
    cur = await conn.execute("SELECT * FROM group_settings WHERE group_id=?", (group_id,))
    row = await cur.fetchone()
    await conn.close()
    if not row:
        return "⚙️ Group Settings\n\nNo token is active in this group yet.\nUse ➕ Add Token to set one up."
    return (
        "⚙️ Group Settings\n\n"
        f"Token: <code>{row['token_mint']}</code>\n"
        f"Min Buy: {row['min_buy_sol']:g} SOL\n"
        f"Emoji: {row['emoji']}\n"
        f"Telegram: {row['telegram_link'] or '—'}"
    )


@router.message(Command("start"))
async def start(msg: Message, state: FSMContext, command: CommandObject | None = None):
    await state.clear()
    arg = (command.args or "").strip() if command else ""
    if msg.chat.type != "private":
        return await msg.reply("Pumptools main menu", reply_markup=main_menu_kb())
    if arg == "ads":
        await msg.answer("💎 Advertise your token\nPromote your token to millions of users across thousands of groups.\n\nSelect your token to continue.", reply_markup=main_menu_kb())
        return
    await msg.answer("Pumptools main menu", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:home")
async def menu_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.answer("Pumptools main menu", reply_markup=main_menu_kb())
    await cq.answer()


@router.callback_query(F.data == "menu:lang")
async def menu_lang(cq: CallbackQuery):
    await cq.message.answer("Choose your buybot language.", reply_markup=lang_kb())
    await cq.answer()


@router.callback_query(F.data.startswith("lang:set:"))
async def lang_set(cq: CallbackQuery):
    label = cq.data.split(":", 2)[2]
    await cq.message.answer(f"✅ Language set to {label.title()}.")
    await cq.answer()


@router.callback_query(F.data == "menu:add")
async def menu_add(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AddTokenFlow.mint)
    await state.update_data(source_chat_id=cq.message.chat.id, source_chat_type=cq.message.chat.type)
    await cq.message.answer("⬇️ Paste the token contract address")
    await cq.answer()


@router.message(AddTokenFlow.mint)
async def add_token_mint(msg: Message, state: FSMContext, db: DB):
    mint = (msg.text or "").strip()
    if not MINT_RE.match(mint):
        return await msg.reply("Send a valid Solana token mint.")
    meta = await _upsert_tracked_token(db, mint)
    await state.update_data(token_mint=mint, token_label=meta.get("symbol") or meta.get("name") or mint[:6])
    if msg.chat.type in ("group", "supergroup"):
        conn = await db.connect()
        await conn.execute(
            "INSERT INTO group_settings(group_id, token_mint, min_buy_sol, emoji, telegram_link, media_file_id, is_active, created_at) VALUES(?,?,?,?,?,?,1,?) "
            "ON CONFLICT(group_id) DO UPDATE SET token_mint=excluded.token_mint, is_active=1",
            (msg.chat.id, mint, float(settings.MIN_BUY_DEFAULT_SOL), "🟢", None, None, int(time.time())),
        )
        await conn.commit()
        await conn.close()
        await state.clear()
        return await msg.answer(
            f"✅ Token Added\n• Token: {meta.get('name') or meta.get('symbol') or mint[:6]}\n• Symbol: {meta.get('symbol') or '—'}\n\nNow posting buys automatically for this group.\nUse Edit to customize token settings.",
            reply_markup=main_menu_kb(),
        )
    await state.set_state(AddTokenFlow.tg)
    await msg.answer(
        f"Token Details\nName: <b>{meta.get('name') or meta.get('symbol') or mint[:6]}</b>\nSymbol: <b>{meta.get('symbol') or '—'}</b>\n\nSend token Telegram link or type <code>skip</code>.",
        parse_mode="HTML",
    )


@router.message(AddTokenFlow.tg)
async def add_token_tg(msg: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    mint = data["token_mint"]
    tg = _norm_tg(msg.text)
    conn = await db.connect()
    await conn.execute("UPDATE tracked_tokens SET telegram_link=COALESCE(?, telegram_link) WHERE mint=?", (tg, mint))
    await conn.commit()
    await conn.close()
    await state.clear()
    await msg.answer("✅ Token saved.", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:view")
async def menu_view(cq: CallbackQuery, db: DB):
    tokens = await _tokens_for_user(db, cq.from_user.id)
    if not tokens:
        await cq.message.answer("No tracked tokens yet.")
    else:
        await cq.message.answer("👀 Select a token below.", reply_markup=token_list_kb(tokens, "viewtoken", back="menu:home"))
    await cq.answer()


@router.callback_query(F.data.startswith("viewtoken:"))
async def view_token(cq: CallbackQuery, db: DB):
    mint = cq.data.split(":", 1)[1]
    conn = await db.connect()
    cur = await conn.execute("SELECT * FROM tracked_tokens WHERE mint=?", (mint,))
    row = await cur.fetchone()
    await conn.close()
    if not row:
        return await cq.answer("Token not found", show_alert=True)
    await cq.message.answer(
        f"Token Details\nName: <b>{row['name'] or row['symbol'] or mint[:6]}</b>\nSymbol: <b>{row['symbol'] or '—'}</b>\nMint: <code>{mint}</code>\nTelegram: {row['telegram_link'] or '—'}",
        parse_mode="HTML",
        reply_markup=token_action_kb(mint),
    )
    await cq.answer()


@router.callback_query(F.data == "menu:edit")
async def menu_edit(cq: CallbackQuery, db: DB):
    tokens = await _tokens_for_user(db, cq.from_user.id)
    if not tokens:
        await cq.message.answer("No tracked tokens yet.")
    else:
        await cq.message.answer("✏️ Select the token you want to edit.", reply_markup=token_list_kb(tokens, "edittoken", back="menu:home"))
    await cq.answer()


@router.callback_query(F.data.startswith("edittoken:"))
async def edit_token(cq: CallbackQuery, state: FSMContext):
    mint = cq.data.split(":", 1)[1]
    await state.set_state(EditTokenFlow.tg)
    await state.update_data(edit_mint=mint)
    await cq.message.answer("⬇️ Send the new Telegram link for this token, or type skip to keep the current one.")
    await cq.answer()


@router.message(EditTokenFlow.tg)
async def edit_token_tg(msg: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    mint = data["edit_mint"]
    tg = _norm_tg(msg.text)
    if tg:
        conn = await db.connect()
        await conn.execute("UPDATE tracked_tokens SET telegram_link=? WHERE mint=?", (tg, mint))
        await conn.commit()
        await conn.close()
    await state.clear()
    await msg.answer("✅ Token updated.", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:group")
async def menu_group(cq: CallbackQuery, db: DB):
    if cq.message.chat.type not in ("group", "supergroup"):
        await cq.message.answer("⚙️ Group settings work inside a group where the bot is added as admin.")
    else:
        await cq.message.answer(await _group_status_text(db, cq.message.chat.id), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data == "menu:advert")
async def advert_menu(cq: CallbackQuery, db: DB, state: FSMContext):
    await state.clear()
    tokens = await _tokens_for_user(db, cq.from_user.id)
    if not tokens:
        await cq.message.answer("No tracked tokens yet. Use ➕ Add Token first.")
    else:
        await cq.message.answer(
            "💎 Advertise your token\nPromote your token to millions of users across thousands of groups.\n\nSelect your token to continue.",
            reply_markup=token_list_kb(tokens, "adtoken", back="menu:home"),
        )
    await cq.answer()


@router.callback_query(F.data.startswith("adtoken:"))
async def advert_pick_token(cq: CallbackQuery, state: FSMContext, db: DB):
    mint = cq.data.split(":", 1)[1]
    meta = await fetch_token_meta(mint)
    label = meta.get("symbol") or meta.get("name") or mint[:6]
    await state.set_state(AdvertFlow.link)
    await state.update_data(token_mint=mint, token_label=label)
    await cq.message.answer(
        f"💎 Fill in the advert form to finish.\nToken: <b>{label}</b>",
        parse_mode="HTML",
    )
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
    invoice_id = await _create_invoice(db, cq.from_user.id, cq.from_user.username, data["token_mint"], "ad", data.get("link"), data.get("content"), None, price, seconds)
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
        await cq.message.answer("No tracked tokens yet. Use ➕ Add Token first.")
    else:
        await cq.message.answer(
            "<blockquote>Your token will be shown here:\n@PumpToolsTrending.\nChoose how many hours you want your token to trend.</blockquote>\n\n🎉 Hi, please select your token below.",
            parse_mode="HTML",
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
        f"Token: {token_label}\nDuration: 1 Hours\nPrice: {price:g} SOL\nLink: —",
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
        invoice_id = await _create_invoice(db, cq.from_user.id, cq.from_user.username, data["token_mint"], "trending", data.get("link"), None, data.get("emoji"), price, seconds)
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


@router.message(Command("tokens"))
async def tokens_cmd(msg: Message, db: DB):
    rows = await _tokens_for_user(db, msg.from_user.id if msg.from_user else 0)
    if not rows:
        return await msg.reply("No tracked tokens.")
    text = "Tracked tokens:\n" + "\n".join([f"• {label} — <code>{mint}</code>" for mint, label in rows])
    await msg.reply(text, parse_mode="HTML")


@router.message(Command("forceadd"))
async def forceadd(msg: Message, command: CommandObject, db: DB):
    if not _is_owner(msg) or not command.args:
        return
    parts = [p.strip() for p in command.args.split("|", 1)]
    mint = parts[0]
    tg = _norm_tg(parts[1]) if len(parts) > 1 else None
    meta = await _upsert_tracked_token(db, mint, tg)
    await msg.reply(f"✅ Token added: {meta.get('symbol') or meta.get('name') or mint[:6]}")


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


@router.message(Command("forceleaderboard"))
async def forceleaderboard(msg: Message, command: CommandObject, db: DB):
    if not _is_owner(msg) or not command.args:
        return
    mint = command.args.strip().split()[0]
    conn = await db.connect()
    await conn.execute("UPDATE tracked_tokens SET force_leaderboard=1 WHERE mint=?", (mint,))
    await conn.commit()
    await conn.close()
    await msg.reply("✅ Token forced into leaderboard.")


@router.message(Command("setglobalad"))
async def setglobalad(msg: Message, command: CommandObject, db: DB):
    if not _is_owner(msg) or not command.args:
        return
    conn = await db.connect()
    ads = AdsService(conn)
    await ads.set_owner_fallback(command.args.strip())
    await conn.close()
    await msg.reply("✅ Fallback ad text updated.")


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
