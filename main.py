from __future__ import annotations

import asyncio
import logging
from os import getenv
from urllib.parse import urlsplit
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.types.error_event import ErrorEvent
from dotenv import load_dotenv

from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database
from runtime_diagnostics import ErrorNotifier, MemoryProbe, memory_log_interval
from handlers.admin_message_blocks import create_admin_message_block_router
from handlers.franc_events import create_franc_event_router
from handlers.routes import create_router
from handlers.message_activity import MessageActivityMiddleware, create_message_activity_router
from handlers.arena import ArenaPublisher, create_arena_router
from arena_web import ROOT as ARENA_WEB_ROOT, create_arena_app
from runtime_cache_pressure import FileCachePressure, supported as cache_pressure_supported
from arena_links import arena_link
from handlers.pets import create_pet_router
from handlers.admin_menu import create_admin_menu_router
from handlers.character_grants import create_character_grant_router
from handlers.pet_grants import create_pet_grant_router
from handlers.enterprises import create_enterprise_router, sweep_recovery_events
from handlers.rp import create_rp_router
from handlers.runtime_diagnostics import create_runtime_diagnostics_router
from handlers.guild import create_guild_router,GuildPublisher
from handlers.kingdom import create_kingdom_router
from handlers.slave_finance import sweep_finance, create_finance_router
from handlers.quick_duel import QuickDuelPublisher, create_quick_duel_router
from handlers.family import create_family_router


def pet_sales_enabled() -> bool:
    """Owner-approved live rollout; an explicit zero remains the kill switch."""
    return getenv("PETS_PAYMENTS_ENABLED", "1").strip() == "1"


def telegram_updates_limit() -> int:
    raw = getenv("TELEGRAM_UPDATES_LIMIT", "").strip() or "24"
    try:
        limit = int(raw)
    except ValueError:
        limit = 0
    if not 1 <= limit <= 64:
        raise RuntimeError("TELEGRAM_UPDATES_LIMIT must be an integer from 1 to 64")
    return limit


async def main() -> None:
    load_dotenv()
    memory_interval = memory_log_interval(getenv("MEMORY_LOG_INTERVAL_SECONDS", "").strip())
    database_path = getenv("DATABASE_PATH", "data/gnida_bot.sqlite3")
    memory = MemoryProbe(database=database_path)
    if memory_interval:
        memory.log("before_database")
    else:
        memory.capture()
    token = getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing in .env")
    updates_limit = telegram_updates_limit()

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
    database = Database(database_path)
    await database.connect()
    cache_pressure = (FileCachePressure(memory, database.path, ARENA_WEB_ROOT / "assets")
                      if getenv("FILE_CACHE_PRESSURE_RELIEF", "1").strip() != "0"
                      and cache_pressure_supported(memory) else None)
    if memory_interval:
        memory.log("after_database")
    bot = Bot(token=token)
    try:
        username = (await bot.get_me()).username
    except BaseException:
        await database.close()
        await bot.session.close()
        raise
    publisher = ArenaPublisher(database, bot, username)
    errors = ErrorNotifier(bot, CUSTOM_COMMAND_OWNER_ID,
                           enabled=getenv("ERROR_DM_ENABLED", "1").strip() != "0")
    guild_publisher=GuildPublisher(database,bot,username)
    duel_publisher = QuickDuelPublisher(database, bot)
    dispatcher = Dispatcher()

    async def on_update_error(event: ErrorEvent):
        errors.report("Обработка обновления Telegram", event.exception)
        return True

    dispatcher.errors.register(on_update_error)
    # Root middleware counts messages even when another feature handles them.
    # Deliberately not registered on edited_message or channel_post.
    dispatcher.message.outer_middleware(MessageActivityMiddleware(database))
    dispatcher.include_router(create_runtime_diagnostics_router(memory))
    dispatcher.include_router(create_admin_menu_router(database))
    dispatcher.include_router(create_character_grant_router(database, username))
    dispatcher.include_router(create_pet_grant_router(database, username))
    pets_payments_enabled = pet_sales_enabled()
    logging.info("Pet Stars sales: %s", "ENABLED (live payments)" if pets_payments_enabled else "DISABLED")
    dispatcher.include_router(
        create_admin_message_block_router(database, kargassia_chat_id=kargassia_chat_id)
    )
    dispatcher.include_router(create_pet_router(database, username, pets_payments_enabled))
    dispatcher.include_router(create_message_activity_router(database))
    dispatcher.include_router(create_quick_duel_router(database, duel_publisher))
    dispatcher.include_router(create_family_router(database, bot, username, bool(webapp_url)))
    dispatcher.include_router(create_franc_event_router(database))
    dispatcher.include_router(create_finance_router(database))
    dispatcher.include_router(create_enterprise_router(database))
    dispatcher.include_router(create_rp_router(database, bot, username, bool(webapp_url)))
    dispatcher.include_router(create_guild_router(database, bot, username, bool(webapp_url),guild_publisher))
    dispatcher.include_router(create_kingdom_router(database, bot, username, bool(webapp_url)))
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
    duel_task = None
    memory_task = None
    cache_task = None
    error_task = None

    async def duel_timeouts():
        while True:
            try:
                await duel_publisher.sweep()
            except Exception as error:
                errors.report("Фоновая проверка дуэлей", error)
            await asyncio.sleep(5)

    async def enterprise_events():
        last_create=float('-inf')
        while True:
            try:
                current=asyncio.get_running_loop().time()
                create=current-last_create>=60
                if create:last_create=current
                await sweep_recovery_events(database,bot,create=create,username=username if webapp_url else None)
                await sweep_finance(database,bot)
                if webapp_url:
                    from enterprise_protection_notices import publish_protection
                    await publish_protection(database,bot,username,publisher.raids)
                for trip in await database.expedition_sweep():
                    try:
                        escapes=trip['escapes']
                        await bot.send_message(trip['owner_id'],
                            '🧭 Экспедиция завершена. '+('Сбежали во время похода: '+', '.join(escapes)+'. ' if escapes else '')+
                            'Итоги и добыча — в твоих владениях.',parse_mode=None,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                                text='Посмотреть итоги',url=arena_link(username,f"holdings_{trip['chat_id']}"))]]))
                    except TelegramAPIError:
                        # Results are already committed and remain in the app;
                        # a blocked PM must never cause re-awards or group spam.
                        logging.info('Expedition notification unavailable: %s',trip['id'])
                    await database.expedition_notified(trip['id'])
            except Exception as error:
                errors.report("Фоновая проверка предприятий и экспедиций", error)
            await asyncio.sleep(5)

    async def arena_timeouts() -> None:
        last_merchant_sweep = float("-inf")
        while True:
            try:
                for battle in await database.arena_expire(compact=True):
                    await publisher.changed(battle["token"])
                for raid in await database.arena_raid_expire(compact=True):
                    await publisher.raid_changed(raid["token"])
                await publisher.raids.retry_pending()
                await guild_publisher.sweep()
                if webapp_url:
                    from arena_kingdom_notices import publish_kingdom_notices
                    await publish_kingdom_notices(database,bot)
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
            except Exception as error:
                errors.report("Фоновая проверка арены, рейдов и гильдии", error)
            await asyncio.sleep(5)

    logging.info("GnidaBot is starting (max %d Telegram update handlers)", updates_limit)
    loop = asyncio.get_running_loop()
    previous_error_handler = loop.get_exception_handler()

    def on_task_error(current_loop, context):
        if isinstance(error := context.get("exception"), Exception):
            errors.report("Необработанная фоновая задача", error)
        elif previous_error_handler is None:
            current_loop.default_exception_handler(context)
        else:
            previous_error_handler(current_loop, context)

    loop.set_exception_handler(on_task_error)
    try:
        if errors.enabled:
            error_task = asyncio.create_task(errors.run())
        if webapp_url:
            port = int(getenv("PORT") or getenv("WEBAPP_PORT") or "8080")
            if not 1 <= port <= 65535:
                raise RuntimeError("PORT must be between 1 and 65535")
            runner = web.AppRunner(
                create_arena_app(database, bot, token, publisher.changed, publisher.raid_changed,
                                 pets_payments_enabled=pets_payments_enabled, rp_publisher=publisher.raids,
                                 guild_publisher=guild_publisher, report_error=errors.report,
                                 record_asset=cache_pressure.record_asset if cache_pressure else None)
            )
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", port).start()
            logging.info("Arena HTTP server is listening on port %s", port)
        arena_task = asyncio.create_task(arena_timeouts())
        enterprise_task = asyncio.create_task(enterprise_events())
        duel_task = asyncio.create_task(duel_timeouts())
        if memory_interval:
            memory.log("ready")
            memory_task = asyncio.create_task(memory.run(memory_interval))
        if cache_pressure:
            cache_task = asyncio.create_task(cache_pressure.run())
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=False,
            # Take the semaphore before creating a Task. Transiently slow
            # Telegram calls must not leave an unlimited backlog in Python.
            tasks_concurrency_limit=updates_limit,
        )
    except Exception as error:
        errors.report("Остановка бота из-за ошибки", error)
        if error_task:
            try:
                await asyncio.wait_for(errors.queue.join(), timeout=5)
            except TimeoutError:
                pass
        raise
    finally:
        loop.set_exception_handler(previous_error_handler)
        if memory_task:
            memory_task.cancel()
            await asyncio.gather(memory_task, return_exceptions=True)
        if cache_task:
            cache_task.cancel()
            await asyncio.gather(cache_task, return_exceptions=True)
        if duel_task:
            duel_task.cancel()
            await asyncio.gather(duel_task, return_exceptions=True)
        if enterprise_task:
            enterprise_task.cancel()
            await asyncio.gather(enterprise_task,return_exceptions=True)
        if arena_task:
            arena_task.cancel()
            await asyncio.gather(arena_task, return_exceptions=True)
        if runner:
            await runner.cleanup()
        if error_task:
            error_task.cancel()
            await asyncio.gather(error_task, return_exceptions=True)
        await database.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
