from __future__ import annotations

import asyncio
import logging
from os import getenv

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from database import Database
from handlers.routes import create_router


async def main() -> None:
    load_dotenv()
    token = getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing in .env")

    raw_kargassia_chat_id = getenv("KARGASSIA_CHAT_ID", "").strip()
    try:
        kargassia_chat_id = (
            int(raw_kargassia_chat_id) if raw_kargassia_chat_id else None
        )
    except ValueError as error:
        raise RuntimeError("KARGASSIA_CHAT_ID must be a numeric Telegram chat ID") from error

    database = Database(getenv("DATABASE_PATH", "data/gnida_bot.sqlite3"))
    await database.connect()
    dispatcher = Dispatcher()
    dispatcher.include_router(
        create_router(database, kargassia_chat_id=kargassia_chat_id)
    )
    bot = Bot(token=token)

    logging.info("GnidaBot is starting")
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False,
        )
    finally:
        await database.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
