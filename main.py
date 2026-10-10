from __future__ import annotations

import asyncio
import logging
from os import getenv
from urllib.parse import urlsplit
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from dotenv import load_dotenv

from database import Database
from handlers.admin_message_blocks import create_admin_message_block_router
from handlers.franc_events import create_franc_event_router
from handlers.routes import create_router
from handlers.arena import ArenaPublisher, create_arena_router
from arena_web import create_arena_app
from arena_links import arena_link


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
        raise RuntimeError(
            "KARGASSIA_CHAT_ID must be a numeric Telegram chat ID"
        ) from error

    webapp_url = getenv("WEBAPP_URL", "").strip()
    if not webapp_url and getenv("DOMAIN", "").strip():
        webapp_url = "https://" + getenv("DOMAIN", "").strip().removeprefix(
            "https://"
        ).rstrip("/")
    if webapp_url and (
        urlsplit(webapp_url).scheme != "https" or not urlsplit(webapp_url).hostname
    ):
        raise RuntimeError(
            "WEBAPP_URL must be the public HTTPS address of this Python service"
        )
    database = Database(getenv("DATABASE_PATH", "data/gnida_bot.sqlite3"))
    await database.connect()
    bot = Bot(token=token)
    try:
        username = (await bot.get_me()).username
    except BaseException:
        await database.close()
        await bot.session.close()
        raise
    publisher = ArenaPublisher(database, bot, username)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        create_admin_message_block_router(database, kargassia_chat_id=kargassia_chat_id)
    )
    dispatcher.include_router(create_franc_event_router(database))
    dispatcher.include_router(
        create_arena_router(database, bot, username, bool(webapp_url), publisher)
    )
    dispatcher.include_router(
        create_router(
            database,
            kargassia_chat_id=kargassia_chat_id,
            yookassa_shop_id=getenv("YUKASSA_SHOP_ID", "").strip() or None,
            yookassa_secret_key=getenv("YUKASSA_SECRET_KEY", "").strip() or None,
            yookassa_return_url=getenv("YUKASSA_RETURN_URL", "").strip() or None,
            arena_username=username if webapp_url else None,
        )
    )
    runner = None
    arena_task = None

    async def arena_timeouts() -> None:
        last_merchant_sweep = float("-inf")
        while True:
            try:
                for battle in await database.arena_expire():
                    await publisher.changed(battle["token"])
                for raid in await database.arena_raid_expire():
                    await publisher.raid_changed(raid["token"])
                await publisher.raids.retry_pending()
                sweep_time = asyncio.get_running_loop().time()
                if webapp_url and sweep_time - last_merchant_sweep >= 30:
                    last_merchant_sweep = sweep_time
                    for visit in await database.arena_due_merchants():
                        try:
                            await bot.send_message(
                                visit["chat_id"],
                                "🧳 Пришёл странствующий торговец. Трактаты, зелья и конфеты — в арене. Он останется на два часа.",
                                reply_markup=InlineKeyboardMarkup(
                                    inline_keyboard=[
                                        [
                                            InlineKeyboardButton(
                                                text="Посмотреть товары",
                                                url=arena_link(
                                                    username, f"shop_{visit['chat_id']}"
                                                ),
                                            )
                                        ]
                                    ]
                                ),
                            )
                        except TelegramAPIError as error:
                            logging.warning(
                                "Could not announce arena merchant in %s: %s",
                                visit["chat_id"],
                                error,
                            )
            except Exception:
                logging.exception("Arena timeout sweep failed")
            await asyncio.sleep(5)

    logging.info("GnidaBot is starting")
    try:
        if webapp_url:
            port = int(getenv("PORT") or getenv("WEBAPP_PORT") or "8080")
            if not 1 <= port <= 65535:
                raise RuntimeError("PORT must be between 1 and 65535")
            runner = web.AppRunner(
                create_arena_app(database, bot, token, publisher.changed, publisher.raid_changed)
            )
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", port).start()
            logging.info("Arena HTTP server is listening on port %s", port)
        arena_task = asyncio.create_task(arena_timeouts())
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False,
        )
    finally:
        if arena_task:
            arena_task.cancel()
            await asyncio.gather(arena_task, return_exceptions=True)
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
