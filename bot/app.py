from __future__ import annotations
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from bot.config import settings
from database.db import DB
from database.migrations import CREATE_TABLES
from utils.solana_rpc import SolanaRPC
from bot.wizard import router as wizard_router
from bot.handlers import router as handlers_router
from services.buy_watcher import BuyWatcher
from services.leaderboard import LeaderboardUpdater


async def _migrate(db: DB):
    conn = await db.connect()
    for stmt in CREATE_TABLES:
        try:
            await conn.execute(stmt)
        except Exception:
            pass
    upgrades = [
        "ALTER TABLE tracked_tokens ADD COLUMN token_name TEXT",
        "ALTER TABLE tracked_tokens ADD COLUMN telegram_link TEXT",
        "ALTER TABLE tracked_tokens ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE tracked_tokens ADD COLUMN force_trending INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tracked_tokens ADD COLUMN force_leaderboard INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tracked_tokens ADD COLUMN manual_rank INTEGER",
        "ALTER TABLE tracked_tokens ADD COLUMN manual_boost REAL NOT NULL DEFAULT 0",
        "ALTER TABLE group_settings ADD COLUMN token_name TEXT",
        "ALTER TABLE group_settings ADD COLUMN show_media INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE group_settings ADD COLUMN show_mcap INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE group_settings ADD COLUMN show_price INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE group_settings ADD COLUMN show_dex INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE price_snapshots ADD COLUMN mcap_usd REAL",
        "ALTER TABLE ads ADD COLUMN token_mint TEXT",
        "ALTER TABLE ads ADD COLUMN link TEXT",
        "ALTER TABLE ads ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'",
    ]
    for stmt in upgrades:
        try:
            await conn.execute(stmt)
        except Exception:
            pass
    await conn.commit(); await conn.close()


async def run():
    load_dotenv()
    db = DB(settings.DATABASE_URL)
    await _migrate(db)
    bot = Bot(token=settings.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())
    rpc = SolanaRPC(settings.SOLANA_RPC)
    dp.workflow_data.update({"db": db, "rpc": rpc})
    dp.include_router(handlers_router)
    dp.include_router(wizard_router)
    watcher = BuyWatcher(bot=bot, db=db, rpc=rpc)
    lb = LeaderboardUpdater(bot=bot, db=db)
    task = asyncio.create_task(watcher.run_forever())
    task_lb = asyncio.create_task(lb.run_forever())
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel(); task_lb.cancel()
        await lb.close(); await watcher.close(); await rpc.close(); await bot.session.close()
