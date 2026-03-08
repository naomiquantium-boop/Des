from __future__ import annotations
import re, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.config import settings
from bot.keyboards import main_menu_kb, owner_panel_kb, trend_duration_kb, ads_duration_kb
from services.payment_verifier import verify_sol_transfer
from services.ads_service import AdsService
from services.token_meta import fetch_token_meta
from database.db import DB
from utils.solana_rpc import SolanaRPC

router = Router()
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

class OwnerFlow(StatesGroup):
    forceadd = State()
    forcetrending = State()
    forceleader = State()
    setad = State()

class TrendFlow(StatesGroup):
    token = State()
    link = State()
    emoji = State()
    tx = State()

class AdsFlow(StatesGroup):
    token = State()
    link = State()
    content = State()
    tx = State()


def _is_owner_id(user_id: int | None) -> bool:
    return bool(user_id and user_id == settings.OWNER_ID)


def _trending_price(key: str) -> tuple[float, int]:
    return {
        "1h": (settings.TRENDING_1H_PRICE_SOL, 3600),
        "3h": (settings.TRENDING_3H_PRICE_SOL, 3 * 3600),
        "6h": (settings.TRENDING_6H_PRICE_SOL, 6 * 3600),
        "12h": (settings.TRENDING_12H_PRICE_SOL, 12 * 3600),
        "24h": (settings.TRENDING_24H_PRICE_SOL, 24 * 3600),
    }[key]


def _ads_price(key: str) -> tuple[float, int]:
    return {
        "1d": (settings.ADS_1D_PRICE_SOL, 86400),
        "3d": (settings.ADS_3D_PRICE_SOL, 3 * 86400),
        "7d": (settings.ADS_7D_PRICE_SOL, 7 * 86400),
    }[key]


async def _tracked_token_lines(db: DB) -> str:
    conn = await db.connect()
    cur = await conn.execute("SELECT token_name, mint FROM tracked_tokens WHERE is_active=1 ORDER BY created_at DESC LIMIT 15")
    rows = await cur.fetchall()
    await conn.close()
    if not rows:
        return "No tokens yet."
    return "\n".join([f"• {(r['token_name'] or r['mint'][:6])} — <code>{r['mint']}</code>" for r in rows])


async def _upsert_token(db: DB, mint: str, tg: str | None = None, force_trending: int = 0, force_leaderboard: int = 0):
    meta = await fetch_token_meta(mint)
    conn = await db.connect()
    await conn.execute(
        """INSERT INTO tracked_tokens(mint, token_name, telegram_link, post_mode, force_trending, force_leaderboard, created_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(mint) DO UPDATE SET
          token_name=COALESCE(excluded.token_name, tracked_tokens.token_name),
          telegram_link=COALESCE(excluded.telegram_link, tracked_tokens.telegram_link),
          is_active=1,
          force_trending=MAX(tracked_tokens.force_trending, excluded.force_trending),
          force_leaderboard=MAX(tracked_tokens.force_leaderboard, excluded.force_leaderboard)
        """,
        (mint, meta.get("name") or meta.get("symbol") or mint[:6], tg, "channel", force_trending, force_leaderboard, int(time.time())),
    )
    await conn.commit()
    await conn.close()


@router.message(Command("start"))
async def start(msg: Message):
    await msg.answer("Pumptools main menu", reply_markup=main_menu_kb(_is_owner_id(msg.from_user.id if msg.from_user else None)))


@router.callback_query(F.data == "menu:home")
async def menu_home(cq: CallbackQuery):
    await cq.message.answer("Pumptools main menu", reply_markup=main_menu_kb(_is_owner_id(cq.from_user.id)))
    await cq.answer()


@router.callback_query(F.data == "menu:view")
async def menu_view(cq: CallbackQuery, db: DB):
    await cq.message.answer(await _tracked_token_lines(db))
    await cq.answer()


@router.callback_query(F.data.in_({"menu:lang", "menu:edit", "menu:group"}))
async def placeholder_menu(cq: CallbackQuery):
    text = {
        "menu:lang": "EN / Chinese post templates are enabled in the code. Add more languages in formatter.py if needed.",
        "menu:edit": "Use Add Token inside a group to update token settings for that group.",
        "menu:group": "Add the bot as admin in your group, then tap Add Token there.",
    }[cq.data]
    await cq.message.answer(text)
    await cq.answer()


@router.callback_query(F.data == "owner:panel")
async def owner_panel(cq: CallbackQuery):
    if not _is_owner_id(cq.from_user.id):
        return await cq.answer()
    await cq.message.answer("Owner panel", reply_markup=owner_panel_kb())
    await cq.answer()


@router.callback_query(F.data == "owner:status")
async def owner_status_cb(cq: CallbackQuery, db: DB):
    if not _is_owner_id(cq.from_user.id):
        return await cq.answer()
    await _send_status(cq.message, db)
    await cq.answer()


@router.callback_query(F.data == "owner:forceadd")
async def owner_forceadd_cb(cq: CallbackQuery, state: FSMContext):
    if not _is_owner_id(cq.from_user.id):
        return await cq.answer()
    await state.set_state(OwnerFlow.forceadd)
    await cq.message.answer("Send token mint. Optional format: <mint> | <telegram link>")
    await cq.answer()


@router.callback_query(F.data == "owner:forcetrending")
async def owner_forcetrending_cb(cq: CallbackQuery, state: FSMContext):
    if not _is_owner_id(cq.from_user.id):
        return await cq.answer()
    await state.set_state(OwnerFlow.forcetrending)
    await cq.message.answer("Send token mint to force post in trending channel")
    await cq.answer()


@router.callback_query(F.data == "owner:forceleader")
async def owner_forceleader_cb(cq: CallbackQuery, state: FSMContext):
    if not _is_owner_id(cq.from_user.id):
        return await cq.answer()
    await state.set_state(OwnerFlow.forceleader)
    await cq.message.answer("Send token mint to force into leaderboard")
    await cq.answer()


@router.callback_query(F.data == "owner:setad")
async def owner_setad_cb(cq: CallbackQuery, state: FSMContext):
    if not _is_owner_id(cq.from_user.id):
        return await cq.answer()
    await state.set_state(OwnerFlow.setad)
    await cq.message.answer("Send the new global ad text")
    await cq.answer()


@router.message(OwnerFlow.forceadd)
async def owner_forceadd_msg(msg: Message, state: FSMContext, db: DB):
    raw = (msg.text or "").strip()
    parts = [p.strip() for p in raw.split("|")]
    mint = parts[0]
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid token mint")
    tg = parts[1] if len(parts) > 1 else None
    await _upsert_token(db, mint, tg=tg)
    await state.clear()
    await msg.answer(f"✅ Force added {mint}")


@router.message(OwnerFlow.forcetrending)
async def owner_forcetrending_msg(msg: Message, state: FSMContext, db: DB):
    mint = (msg.text or "").strip()
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid token mint")
    await _upsert_token(db, mint, force_trending=1)
    await state.clear()
    await msg.answer(f"✅ {mint} now force-posts to trending")


@router.message(OwnerFlow.forceleader)
async def owner_forceleader_msg(msg: Message, state: FSMContext, db: DB):
    mint = (msg.text or "").strip()
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid token mint")
    await _upsert_token(db, mint, force_leaderboard=1)
    await state.clear()
    await msg.answer(f"✅ {mint} forced into leaderboard")


@router.message(OwnerFlow.setad)
async def owner_setad_msg(msg: Message, state: FSMContext, db: DB):
    text = (msg.text or "").strip()
    conn = await db.connect(); svc = AdsService(conn); await svc.set_owner_fallback(text); await conn.close(); await state.clear()
    await msg.answer("✅ Global ad text updated")


@router.callback_query(F.data == "trend:start")
async def trend_start(cq: CallbackQuery):
    await cq.message.answer("Choose how many hours you want your token to trend.", reply_markup=trend_duration_kb())
    await cq.answer()


@router.callback_query(F.data.startswith("trend:"))
async def trend_pick(cq: CallbackQuery, state: FSMContext):
    key = cq.data.split(":", 1)[1]
    if key == "start":
        return await cq.answer()
    price, seconds = _trending_price(key)
    await state.clear()
    await state.update_data(duration=key, price=price, seconds=seconds)
    await state.set_state(TrendFlow.token)
    await cq.message.answer(f"Send token mint for trending.\nDuration: {key}\nPrice: {price} SOL")
    await cq.answer()


@router.message(TrendFlow.token)
async def trend_token(msg: Message, state: FSMContext):
    mint = (msg.text or "").strip()
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid token mint")
    await state.update_data(token_mint=mint)
    await state.set_state(TrendFlow.link)
    await msg.answer("Send your Telegram group/channel link")


@router.message(TrendFlow.link)
async def trend_link(msg: Message, state: FSMContext):
    await state.update_data(link=(msg.text or "").strip())
    await state.set_state(TrendFlow.emoji)
    await msg.answer("Send custom emoji or type skip")


@router.message(TrendFlow.emoji)
async def trend_emoji(msg: Message, state: FSMContext):
    emoji = (msg.text or "").strip()
    if emoji.lower() == "skip":
        emoji = None
    await state.update_data(emoji=emoji)
    data = await state.get_data()
    await state.set_state(TrendFlow.tx)
    await msg.answer(f"Invoice\n\nPaying for: Trending\nWallet:\n<code>{settings.PAYMENT_WALLET}</code>\n\nPlease send {data['price']} SOL to the wallet above, then send the tx signature.")


@router.message(TrendFlow.tx)
async def trend_tx(msg: Message, state: FSMContext, db: DB, rpc: SolanaRPC):
    sig = (msg.text or "").strip()
    data = await state.get_data()
    res = await verify_sol_transfer(rpc, sig, settings.PAYMENT_WALLET, float(data['price']))
    if not res.ok:
        return await msg.reply(f"❌ {res.reason}")
    now = int(time.time())
    conn = await db.connect()
    await conn.execute(
        "INSERT INTO trending_campaigns(user_id, token_mint, link, emoji, start_ts, end_ts, tx_sig, amount_sol) VALUES(?,?,?,?,?,?,?,?)",
        (msg.from_user.id, data['token_mint'], data.get('link'), data.get('emoji'), now, now + int(data['seconds']), sig, res.amount_sol),
    )
    await conn.execute(
        """INSERT INTO tracked_tokens(mint, telegram_link, post_mode, force_trending, created_at, manual_boost)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(mint) DO UPDATE SET telegram_link=COALESCE(excluded.telegram_link, tracked_tokens.telegram_link), force_trending=1, is_active=1, manual_boost=tracked_tokens.manual_boost+1000
        """,
        (data['token_mint'], data.get('link'), 'channel', 1, now, 1000),
    )
    await conn.commit(); await conn.close(); await state.clear()
    await msg.answer("✅ Trending activated.")


@router.callback_query(F.data == "ads:start")
async def ads_start(cq: CallbackQuery):
    await cq.message.answer("Choose advert duration.", reply_markup=ads_duration_kb())
    await cq.answer()


@router.callback_query(F.data.startswith("ads:"))
async def ads_pick(cq: CallbackQuery, state: FSMContext):
    key = cq.data.split(":", 1)[1]
    if key == "start":
        return await cq.answer()
    price, seconds = _ads_price(key)
    await state.clear(); await state.update_data(duration=key, price=price, seconds=seconds)
    await state.set_state(AdsFlow.token)
    await cq.message.answer(f"Send token mint for advert.\nDuration: {key}\nPrice: {price} SOL")
    await cq.answer()


@router.message(AdsFlow.token)
async def ads_token(msg: Message, state: FSMContext):
    mint = (msg.text or "").strip()
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid token mint")
    await state.update_data(token_mint=mint)
    await state.set_state(AdsFlow.link)
    await msg.answer("Send your Telegram group/channel link")


@router.message(AdsFlow.link)
async def ads_link(msg: Message, state: FSMContext):
    await state.update_data(link=(msg.text or "").strip())
    await state.set_state(AdsFlow.content)
    await msg.answer("Enter your advert text")


@router.message(AdsFlow.content)
async def ads_content(msg: Message, state: FSMContext):
    await state.update_data(text=(msg.text or "").strip())
    data = await state.get_data()
    await state.set_state(AdsFlow.tx)
    await msg.answer(f"Invoice\n\nPaying for: Advert\nWallet:\n<code>{settings.PAYMENT_WALLET}</code>\n\nPlease send {data['price']} SOL to the wallet above, then send the tx signature.")


@router.message(AdsFlow.tx)
async def ads_tx(msg: Message, state: FSMContext, db: DB, rpc: SolanaRPC):
    sig = (msg.text or "").strip()
    data = await state.get_data()
    res = await verify_sol_transfer(rpc, sig, settings.PAYMENT_WALLET, float(data['price']))
    if not res.ok:
        return await msg.reply(f"❌ {res.reason}")
    now = int(time.time())
    conn = await db.connect(); svc = AdsService(conn)
    try:
        await svc.create_ad(msg.from_user.id, data['text'], now, now + int(data['seconds']), sig, res.amount_sol, token_mint=data['token_mint'], link=data.get('link'), scope='global')
    except Exception:
        await conn.close(); return await msg.reply("❌ Could not activate ad.")
    await conn.close(); await state.clear()
    await msg.answer("✅ Advert activated.")


async def _send_status(msg: Message, db: DB):
    conn = await db.connect()
    g = await (await conn.execute("SELECT COUNT(*) FROM group_settings WHERE is_active=1")).fetchone()
    t = await (await conn.execute("SELECT COUNT(*) FROM tracked_tokens WHERE is_active=1")).fetchone()
    a = await (await conn.execute("SELECT COUNT(*) FROM ads WHERE end_ts>=?", (int(time.time()),))).fetchone()
    await conn.close()
    await msg.answer(f"Active groups: {g[0]}\nActive tokens: {t[0]}\nActive ads: {a[0]}")


@router.message(Command("forceadd"))
async def forceadd_cmd(msg: Message, command: CommandObject, db: DB):
    if not _is_owner_id(msg.from_user.id if msg.from_user else None):
        return
    if not command.args:
        return await msg.reply("Usage: /forceadd <mint> | <telegram link>")
    parts = [p.strip() for p in command.args.split("|")]
    mint = parts[0]
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid token mint")
    await _upsert_token(db, mint, tg=parts[1] if len(parts) > 1 else None)
    await msg.answer(f"✅ Force added {mint}")


@router.message(Command("forcetrending"))
async def forcetrending_cmd(msg: Message, command: CommandObject, db: DB):
    if not _is_owner_id(msg.from_user.id if msg.from_user else None):
        return
    if not command.args:
        return await msg.reply("Usage: /forcetrending <mint>")
    mint = command.args.strip()
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid token mint")
    await _upsert_token(db, mint, force_trending=1)
    await msg.answer(f"✅ {mint} now force-posts to trending")


@router.message(Command("forceleaderboard"))
async def forceleaderboard_cmd(msg: Message, command: CommandObject, db: DB):
    if not _is_owner_id(msg.from_user.id if msg.from_user else None):
        return
    if not command.args:
        return await msg.reply("Usage: /forceleaderboard <mint>")
    mint = command.args.strip()
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid token mint")
    await _upsert_token(db, mint, force_leaderboard=1)
    await msg.answer(f"✅ {mint} forced into leaderboard")


@router.message(Command("setglobalad"))
async def setglobalad_cmd(msg: Message, command: CommandObject, db: DB):
    if not _is_owner_id(msg.from_user.id if msg.from_user else None):
        return
    if not command.args:
        return await msg.reply("Usage: /setglobalad <text>")
    conn = await db.connect(); svc = AdsService(conn); await svc.set_owner_fallback(command.args.strip()); await conn.close()
    await msg.answer("✅ Global ad text updated")


@router.message(Command("status"))
async def status(msg: Message, db: DB):
    if not _is_owner_id(msg.from_user.id if msg.from_user else None):
        return
    await _send_status(msg, db)
