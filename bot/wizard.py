from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
import time
import re

from bot.keyboards import configure_kb, wizard_nav_kb, confirm_kb
from services.token_meta import fetch_token_meta
from database.db import DB

router = Router()

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")  # base58-ish

class Cfg(StatesGroup):
    token = State()
    min_buy = State()
    emoji = State()
    tg = State()
    media = State()
    confirm = State()

@router.my_chat_member()
async def on_added(evt: ChatMemberUpdated):
    # When bot is added to a group, show configure button
    if evt.chat.type not in ("group", "supergroup"):
        return
    new = evt.new_chat_member
    if new and new.status in ("member", "administrator"):
        await evt.bot.send_message(evt.chat.id, "🎩 Welcome to PumpTools BuyBot\n\nTap Configure to set it up.", reply_markup=configure_kb())

@router.callback_query(F.data == "cfg:start")
async def cfg_start(cq: CallbackQuery, state: FSMContext):
    if cq.message:
        await cq.message.answer("Send the token CA (mint) you want to track.", reply_markup=wizard_nav_kb(cancel=True))
    await state.set_state(Cfg.token)
    await cq.answer()

@router.callback_query(F.data == "cfg:cancel")
async def cfg_cancel(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.answer("Setup cancelled.")
    await cq.answer()

@router.message(Cfg.token)
async def cfg_token(msg: Message, state: FSMContext):
    mint = (msg.text or "").strip()
    if not MINT_RE.match(mint):
        return await msg.reply("Invalid mint address. Please send a valid Solana token mint (CA).")
    await state.update_data(token_mint=mint)
    meta = await fetch_token_meta(mint)
    await state.update_data(token_name=meta.get("symbol") or meta.get("name") or mint[:6])
    await msg.answer(
        f"Token set to: **{meta.get('symbol') or meta.get('name') or mint[:6]}**\n\nNow send the minimum buy in SOL (example: `0.5`).",
        parse_mode="Markdown",
        reply_markup=wizard_nav_kb(back="cfg:start"),
    )
    await state.set_state(Cfg.min_buy)

@router.message(Cfg.min_buy)
async def cfg_min_buy(msg: Message, state: FSMContext):
    t = (msg.text or "").strip().replace(",", "")
    try:
        v = float(t)
        if v < 0:
            raise ValueError()
    except Exception:
        return await msg.reply("Send a number in SOL, e.g. `0.5`", parse_mode="Markdown")
    await state.update_data(min_buy_sol=v)
    await msg.answer("Send the emoji you want for buys (example: 🟢).", reply_markup=wizard_nav_kb(back="cfg:start"))
    await state.set_state(Cfg.emoji)

@router.message(Cfg.emoji)
async def cfg_emoji(msg: Message, state: FSMContext):
    e = (msg.text or "").strip()
    if len(e) == 0:
        return await msg.reply("Send an emoji like 🟢 or 🔥.")
    await state.update_data(emoji=e)
    await msg.answer("Send the project Telegram link (or type `skip`).", parse_mode="Markdown", reply_markup=wizard_nav_kb(back="cfg:start"))
    await state.set_state(Cfg.tg)

@router.message(Cfg.tg)
async def cfg_tg(msg: Message, state: FSMContext):
    t = (msg.text or "").strip()
    if t.lower() == "skip":
        t = ""
    await state.update_data(telegram_link=t)
    await msg.answer("Optional: send a photo (logo/banner) to attach to buy posts, or type `skip`.", parse_mode="Markdown", reply_markup=wizard_nav_kb(back="cfg:start"))
    await state.set_state(Cfg.media)

@router.message(Cfg.media)
async def cfg_media(msg: Message, state: FSMContext):
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    else:
        if (msg.text or "").strip().lower() != "skip":
            return await msg.reply("Send a photo or type `skip`.")
    await state.update_data(media_file_id=file_id)
    data = await state.get_data()
    preview = (
        f"✅ **Review**\n\n"
        f"Token: `{data['token_mint']}`\n"
        f"Min buy: `{data['min_buy_sol']}` SOL\n"
        f"Emoji: {data['emoji']}\n"
        f"Telegram: {data.get('telegram_link') or '—'}\n"
        f"Media: {'Yes' if file_id else 'No'}\n\n"
        f"Activate?"
    )
    await msg.answer(preview, parse_mode="Markdown", reply_markup=confirm_kb())
    await state.set_state(Cfg.confirm)

@router.callback_query(F.data == "cfg:activate")
async def cfg_activate(cq: CallbackQuery, state: FSMContext, db: DB):
    data = await state.get_data()
    if not cq.message:
        return await cq.answer()
    conn = await db.connect()
    now = int(time.time())
    await conn.execute(
        """INSERT INTO group_settings(group_id, token_mint, min_buy_sol, emoji, telegram_link, media_file_id, is_active, created_at)
           VALUES(?,?,?,?,?,?,1,?)
           ON CONFLICT(group_id) DO UPDATE SET
             token_mint=excluded.token_mint,
             min_buy_sol=excluded.min_buy_sol,
             emoji=excluded.emoji,
             telegram_link=excluded.telegram_link,
             media_file_id=excluded.media_file_id,
             is_active=1
        """,
        (cq.message.chat.id, data["token_mint"], float(data["min_buy_sol"]), data["emoji"], data.get("telegram_link"), data.get("media_file_id"), now),
    )
    await conn.commit()
    await conn.close()
    await state.clear()
    await cq.message.answer("✅ BuyBot activated for this group.")
    await cq.answer()
