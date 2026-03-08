from __future__ import annotations
import re, time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from bot.keyboards import configure_kb, wizard_nav_kb, confirm_kb
from services.token_meta import fetch_token_meta
from database.db import DB

router = Router()
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class Cfg(StatesGroup):
    token = State()
    min_buy = State()
    emoji = State()
    tg = State()
    media = State()
    confirm = State()


@router.my_chat_member()
async def on_added(evt: ChatMemberUpdated):
    if evt.chat.type not in ("group", "supergroup"):
        return
    new = evt.new_chat_member
    if new and new.status in ("member", "administrator"):
        await evt.bot.send_message(evt.chat.id, "Pumptools is ready. Tap Add Token to configure this group.", reply_markup=configure_kb())


@router.callback_query(F.data == "cfg:start")
async def cfg_start(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.answer("Paste the token contract address", reply_markup=wizard_nav_kb(cancel=True))
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
        return await msg.reply("Send a valid Solana token contract address.")
    meta = await fetch_token_meta(mint)
    await state.update_data(token_mint=mint, token_name=meta.get("name") or meta.get("symbol") or mint[:6])
    await msg.answer(
        f"Token Details\nName: <b>{meta.get('name') or mint[:6]}</b>\nSymbol: <b>{meta.get('symbol') or '-'}</b>\n\nIs this correct?",
        reply_markup=confirm_kb(),
    )
    await state.set_state(Cfg.min_buy)


@router.callback_query(F.data == "cfg:activate")
async def cfg_after_confirm(cq: CallbackQuery, state: FSMContext):
    await cq.message.answer("Set min buy in SOL. Example: 0.5")
    await state.set_state(Cfg.min_buy)
    await cq.answer()


@router.message(Cfg.min_buy)
async def cfg_min_buy(msg: Message, state: FSMContext):
    try:
        val = float((msg.text or "0").strip())
    except Exception:
        return await msg.reply("Send a number like 0.5")
    await state.update_data(min_buy_sol=max(0.0, val))
    await msg.answer("Send emoji for buy bar. Example: 🟢")
    await state.set_state(Cfg.emoji)


@router.message(Cfg.emoji)
async def cfg_emoji(msg: Message, state: FSMContext):
    emoji = (msg.text or "🟢").strip()[:4] or "🟢"
    await state.update_data(emoji=emoji)
    await msg.answer("Send Telegram group/channel link for this token or type skip")
    await state.set_state(Cfg.tg)


@router.message(Cfg.tg)
async def cfg_tg(msg: Message, state: FSMContext):
    text = (msg.text or "").strip()
    tg = None if text.lower() == "skip" else text
    await state.update_data(telegram_link=tg)
    await msg.answer("Send image for buy posts, or type skip")
    await state.set_state(Cfg.media)


@router.message(Cfg.media)
async def cfg_media(msg: Message, state: FSMContext, db: DB):
    data = await state.get_data()
    media = None
    if msg.photo:
        media = msg.photo[-1].file_id
    elif (msg.text or "").strip().lower() != "skip":
        return await msg.reply("Send a photo or type skip")
    data["media_file_id"] = media

    if msg.chat.type not in ("group", "supergroup"):
        await state.clear()
        return await msg.answer("This setup must be completed inside the target group.")

    conn = await db.connect()
    await conn.execute(
        """
        INSERT INTO group_settings(group_id, token_mint, token_name, min_buy_sol, emoji, telegram_link, media_file_id, is_active, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(group_id) DO UPDATE SET
          token_mint=excluded.token_mint,
          token_name=excluded.token_name,
          min_buy_sol=excluded.min_buy_sol,
          emoji=excluded.emoji,
          telegram_link=excluded.telegram_link,
          media_file_id=excluded.media_file_id,
          is_active=1
        """,
        (
            msg.chat.id,
            data["token_mint"],
            data.get("token_name"),
            float(data["min_buy_sol"]),
            data["emoji"],
            data.get("telegram_link"),
            media,
            1,
            int(time.time()),
        ),
    )
    await conn.execute(
        """
        INSERT INTO tracked_tokens(mint, token_name, telegram_link, post_mode, created_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(mint) DO UPDATE SET token_name=COALESCE(excluded.token_name, tracked_tokens.token_name), telegram_link=COALESCE(excluded.telegram_link, tracked_tokens.telegram_link), is_active=1
        """,
        (data["token_mint"], data.get("token_name"), data.get("telegram_link"), "channel", int(time.time())),
    )
    await conn.commit()
    await conn.close()
    await state.clear()
    await msg.answer("✅ Token saved. Buys will post here and in the trending channel.")
