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

    # best-effort schema upgrades
    try:
        await conn.execute("ALTER TABLE tracked_tokens ADD COLUMN telegram_link TEXT")
    except Exception:
        pass

    await conn.commit()
    await conn.close()

async def run():
    load_dotenv()

    db = DB(settings.DATABASE_URL)
    await _migrate(db)

    bot = Bot(token=settings.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    rpc = SolanaRPC(settings.SOLANA_RPC)

    # Attach shared objects to dispatcher workflow_data for Aiogram v3 DI.
    # Handlers can receive these as function parameters: (db: DB, rpc: SolanaRPC)
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
        task.cancel()
        task_lb.cancel()
        await lb.close()
        await watcher.close()
        await rpc.close()
        await bot.session.close()
