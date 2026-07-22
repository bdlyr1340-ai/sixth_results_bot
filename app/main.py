from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot import admin, handlers
from app.config import Settings
from app.database import Database
from app.importer.jobs import ImportManager
from app.web.server import create_web_app


async def run() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    db = Database(settings.database_path)
    await db.init()
    manager = ImportManager(db, settings)
    await manager.resume_pending()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["settings"] = settings
    dispatcher["db"] = db
    dispatcher.include_router(admin.router)
    dispatcher.include_router(handlers.router)

    web_app = create_web_app(settings, db, manager)
    uvicorn_config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    server = uvicorn.Server(uvicorn_config)

    async def serve_bot() -> None:
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(
            bot,
            settings=settings,
            db=db,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )

    try:
        await asyncio.gather(server.serve(), serve_bot())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
