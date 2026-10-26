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
from handlers.pets import create_pet_router
from handlers.admin_menu import create_admin_menu_router
from handlers.character_grants import create_character_grant_router
from handlers.pet_grants import create_pet_grant_router
from handlers.enterprises import create_enterprise_router, sweep_recovery_events
from handlers.rp import create_rp_router


def pet_sales_enabled() -> bool:
    """Owner-approved live rollout; an explicit zero remains the kill switch."""
    return getenv("PETS_PAYMENTS_ENABLED", "1").strip() == "1"


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
    dispatcher.include_router(create_admin_menu_router(database))
    dispatcher.include_router(create_character_grant_router(database, username))
    dispatcher.include_router(create_pet_grant_router(database, username))
    pets_payments_enabled = pet_sales_enabled()
    logging.info("Pet Stars sales: %s", "ENABLED (live payments)" if pets_payments_enabled else "DISABLED")
    dispatcher.include_router(
        create_admin_message_block_router(database, kargassia_chat_id=kargassia_chat_id)
    )
    dispatcher.include_router(create_pet_router(database, username, pets_payments_enabled))
    dispatcher.include_router(create_franc_event_router(database))
    dispatcher.include_router(create_enterprise_router(database))
    dispatcher.include_router(create_rp_router(database, bot, username, bool(webapp_url)))
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
    enterprise_task = None

    async def enterprise_events():
        last_create=float('-inf')
        while True:
            try:
                current=asyncio.get_running_loop().time()
                create=current-last_create>=60
                if create:last_create=current
                await sweep_recovery_events(database,bot,create=create)
                for trip in await database.expedition_sweep():
                    try:
                        await bot.send_message(trip['owner_id'],
                            '🧭 Экспедиция завершена. Итоги и добыча — в твоих владениях.',
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                                text='Посмотреть итоги',url=arena_link(username,f"holdings_{trip['chat_id']}"))]]))
                    except TelegramAPIError:
                        # Results are already committed and remain in the app;
                        # a blocked PM must never cause re-awards or group spam.
                        logging.info('Expedition notification unavailable: %s',trip['id'])
                    await database.expedition_notified(trip['id'])
            except Exception:
                logging.exception('Enterprise event sweep failed')
            await asyncio.sleep(5)

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
                            # Settings may change after the sweep claimed a batch.
                            if not (await database.arena_merchant_notifications(visit['chat_id']))['enabled']:
                                continue
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
                create_arena_app(database, bot, token, publisher.changed, publisher.raid_changed,
                                 pets_payments_enabled=pets_payments_enabled, rp_publisher=publisher.raids)
            )
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", port).start()
            logging.info("Arena HTTP server is listening on port %s", port)
        arena_task = asyncio.create_task(arena_timeouts())
        enterprise_task = asyncio.create_task(enterprise_events())
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False,
        )
    finally:
        if enterprise_task:
            enterprise_task.cancel()
            await asyncio.gather(enterprise_task,return_exceptions=True)
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
