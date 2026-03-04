from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import time

from bot.config import settings
from bot.keyboards import ads_duration_kb, ads_paid_kb
from services.payment_verifier import verify_sol_transfer
from services.ads_service import AdsService

router = Router()

class AdsFlow(StatesGroup):
    choose = State()
    text = State()
    tx = State()

def _price_for(key: str) -> tuple[float,int]:
    if key == "6h":
        return settings.ADS_6H_PRICE_SOL, 6*3600
    if key == "12h":
        return settings.ADS_12H_PRICE_SOL, 12*3600
    return settings.ADS_24H_PRICE_SOL, 24*3600

@router.message(Command("start"))
async def start(msg: Message):
    if msg.chat.type == "private":
        await msg.answer("PumpTools BuyBot is running. Add me to a group and tap Configure.")
    else:
        await msg.reply("Hi! Tap Configure to set me up (I must be admin).")

@router.message(Command("ads"))
async def ads(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "BuyBot Ads\n\nChoose duration:",
        reply_markup=ads_duration_kb(),
    )
    await state.set_state(AdsFlow.choose)

@router.callback_query(F.data.startswith("ads:"))
async def ads_cb(cq: CallbackQuery, state: FSMContext):
    action = cq.data.split(":")[1]
    if action in ("6h","12h","24h"):
        price, seconds = _price_for(action)
        await state.update_data(duration=action, price=price, seconds=seconds)
        await cq.message.answer(
            f"Send your **ad text** (one message).\n\nPrice: **{price} SOL**\nPay to: `{settings.PAYMENT_WALLET}`",
            parse_mode="Markdown",
        )
        await state.set_state(AdsFlow.text)
        return await cq.answer()
    if action == "paid":
        await cq.answer()
        return
    if action == "cancel":
        await state.clear()
        await cq.message.answer("Ads cancelled.")
        return await cq.answer()

@router.message(AdsFlow.text)
async def ads_text(msg: Message, state: FSMContext):
    txt = (msg.text or "").strip()
    if len(txt) < 3:
        return await msg.reply("Send a valid ad text.")
    await state.update_data(ad_text=txt)
    data = await state.get_data()
    await msg.answer(
        f"Now send the **transaction signature** after paying **{data['price']} SOL** to `{settings.PAYMENT_WALLET}`.\n\nExample: `5hD...xyz`",
        parse_mode="Markdown",
        reply_markup=ads_paid_kb(),
    )
    await state.set_state(AdsFlow.tx)

@router.message(AdsFlow.tx)
async def ads_tx(msg: Message, state: FSMContext):
    sig = (msg.text or "").strip()
    if len(sig) < 20:
        return await msg.reply("Send a valid Solana tx signature.")
    data = await state.get_data()
    rpc = msg.bot.get("rpc")
    res = await verify_sol_transfer(rpc, sig, settings.PAYMENT_WALLET, float(data["price"]))
    if not res.ok:
        return await msg.reply(f"❌ {res.reason}")
    now = int(time.time())
    start_ts = now
    end_ts = now + int(data["seconds"])
    db = msg.bot.get("db")
    conn = await db.connect()
    ads_svc = AdsService(conn)
    try:
        await ads_svc.create_ad(msg.from_user.id, data["ad_text"], start_ts, end_ts, sig, res.amount_sol)
    except Exception as e:
        await conn.close()
        return await msg.reply("❌ Could not activate ad (maybe tx already used).")
    await conn.close()
    await state.clear()
    await msg.answer(f"✅ Ad activated for {data['duration'].upper()}.")

# Owner commands
def _is_owner(msg: Message) -> bool:
    return msg.from_user and msg.from_user.id == settings.OWNER_ID

@router.message(Command("addtoken"))
async def addtoken(msg: Message, command: CommandObject):
    if not _is_owner(msg):
        return
    if not command.args:
        return await msg.reply("Usage: /addtoken <MINT>")
    mint = command.args.strip()
    db = msg.bot.get("db")
    conn = await db.connect()
    await conn.execute(
        "INSERT INTO tracked_tokens(mint, post_mode, created_at) VALUES(?, 'channel', ?) ON CONFLICT(mint) DO UPDATE SET post_mode='channel'",
        (mint, int(time.time())),
    )
    await conn.commit()
    await conn.close()
    await msg.reply(f"✅ Tracking enabled for {mint} (posting to channel).")

@router.message(Command("removetoken"))
async def removetoken(msg: Message, command: CommandObject):
    if not _is_owner(msg):
        return
    if not command.args:
        return await msg.reply("Usage: /removetoken <MINT>")
    mint = command.args.strip()
    db = msg.bot.get("db")
    conn = await db.connect()
    await conn.execute("DELETE FROM tracked_tokens WHERE mint=?", (mint,))
    await conn.commit()
    await conn.close()
    await msg.reply(f"✅ Removed {mint}.")

@router.message(Command("setad"))
async def setad(msg: Message, command: CommandObject):
    if not _is_owner(msg):
        return
    if not command.args:
        return await msg.reply("Usage: /setad <text>")
    db = msg.bot.get("db")
    conn = await db.connect()
    ads_svc = AdsService(conn)
    await ads_svc.set_owner_fallback(command.args.strip())
    await conn.close()
    await msg.reply("✅ Owner fallback ad set.")

@router.message(Command("status"))
async def status(msg: Message):
    if not _is_owner(msg):
        return
    db = msg.bot.get("db")
    conn = await db.connect()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM group_settings WHERE is_active=1")
    groups = (await cur.fetchone())["c"]
    cur = await conn.execute("SELECT COUNT(*) AS c FROM tracked_tokens")
    tokens = (await cur.fetchone())["c"]
    await conn.close()
    await msg.reply(f"Active groups: {groups}\nTracked tokens: {tokens}")
