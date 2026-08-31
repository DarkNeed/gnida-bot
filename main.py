from __future__ import annotations

import asyncio
import logging
from os import getenv

from aiogram import Bot, Dispatcher
from aiohttp import web
from dotenv import load_dotenv

from database import Database
from handlers.routes import create_router
from webapp_server import create_webapp


def optional_int_env(name: str) -> int | None:
    raw_value = getenv(name, "").strip()
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a numeric value") from error


async def main() -> None:
    load_dotenv()
    token = getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing in .env")

    kargassia_chat_id = optional_int_env("KARGASSIA_CHAT_ID")
    superadmin_id = optional_int_env("SUPERADMIN_ID")
    webapp_url = getenv("WEBAPP_URL", "").strip() or None
    if not webapp_url:
        hosted_domain = getenv("DOMAIN", "").strip()
        if hosted_domain:
            webapp_url = (
                hosted_domain
                if hosted_domain.startswith(("https://", "http://"))
                else f"https://{hosted_domain}"
            )
    webapp_host = getenv("WEBAPP_HOST", "0.0.0.0").strip()
    webapp_port = optional_int_env("WEBAPP_PORT") or optional_int_env("PORT") or 8080

    database = Database(getenv("DATABASE_PATH", "data/gnida_bot.sqlite3"))
    await database.connect()
    bot = Bot(token=token)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        create_router(
            database,
            kargassia_chat_id=kargassia_chat_id,
            webapp_url=webapp_url,
            superadmin_id=superadmin_id,
        )
    )
    runner: web.AppRunner | None = None
    if webapp_url:
        runner = web.AppRunner(
            create_webapp(database, bot, token, superadmin_id=superadmin_id)
        )
        await runner.setup()
        await web.TCPSite(runner, webapp_host, webapp_port).start()
        logging.info("Slave arena is listening on %s:%s", webapp_host, webapp_port)

    logging.info("GnidaBot is starting")
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False,
        )
    finally:
        if runner:
            await runner.cleanup()
        await database.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
