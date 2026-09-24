"""Private event constructor and scheduled public franc events."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database, utc_timestamp
from franc_events import EVENT_LIFETIME_SECONDS, FrancEventStore, event_config


MSK = timezone(timedelta(hours=3), "MSK")
KIND_NAMES = {"choice": "Выбор кнопки", "text": "Ответ сообщением", "luck": "Кнопка удачи"}
LIST_NAMES = {
    "options": "Кнопки",
    "answers": "Правильные ответы",
    "success": "Фразы успеха",
    "failure": "Фразы неудачи",
}


class EventInput(StatesGroup):
    value = State()


def service_day(now: datetime) -> str:
    local = now.astimezone(MSK)
    if local.hour < 2:
        local -= timedelta(days=1)
    return local.date().isoformat()


def schedule_times(day: str, now: datetime) -> list[int]:
    start = datetime.fromisoformat(day).replace(hour=7, tzinfo=MSK)
    end = start + timedelta(hours=19)
    first = max(start, now.astimezone(MSK) + timedelta(minutes=1))
    last = end - timedelta(minutes=10)
    if first >= last:
        return []
    minutes = int((last - first).total_seconds() // 60)
    count = 2 if minutes >= 90 and random.choice((True, False)) else 1
    if count == 1:
        return [int((first + timedelta(minutes=random.randint(0, minutes))).timestamp())]
    first_minute = random.randint(0, minutes - 60)
    second_minute = random.randint(first_minute + 60, minutes)
    return [
        int((first + timedelta(minutes=first_minute)).timestamp()),
        int((first + timedelta(minutes=second_minute)).timestamp()),
    ]


def keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def rendered_phrase(phrase: str, user_id: int, name: str, reward: int) -> str:
    return (
        html.escape(phrase)
        .replace("{user}", user_mention(user_id, name))
        .replace("{amount}", str(reward))
    )


def public_event_view(event) -> tuple[str, InlineKeyboardMarkup | None]:
    config = json.loads(event["snapshot_json"])
    kind = config["kind"]
    body = (
        f"🎲 <b>Событие за франки</b>\n{html.escape(config['prompt'])}\n\n"
        f"💰 Успех: {config['success_reward']} ₣"
        + (f" · неудача: {config['failure_reward']} ₣" if config["failure_reward"] else "")
        + "\n⏱ Время: 10 минут · одна попытка на человека."
    )
    if kind == "choice":
        buttons = [
            [InlineKeyboardButton(text=label, callback_data=f"fe:{event['id']}:{index}")]
            for index, label in enumerate(config["options"])
        ]
        return body + "\nВыбери правильную кнопку.", keyboard(buttons)
    if kind == "text":
        return body + "\nОтветь на это сообщение правильным ответом.", None
    return body + "\nНажми кнопку — результат решит удача.", keyboard([
        [InlineKeyboardButton(text=config["luck_button"], callback_data=f"fe:{event['id']}:go")]
    ])


class EventReplyFilter(Filter):
    def __init__(self, store: FrancEventStore):
        self.store = store

    async def __call__(self, message: Message) -> dict | bool:
        if not message.text or not message.from_user or message.from_user.is_bot or not message.reply_to_message:
            return False
        if message.chat.type not in {"group", "supergroup"}:
            return False
        event = await self.store.event_for_reply(
            message.chat.id, message.reply_to_message.message_id
        )
        if event and json.loads(event["snapshot_json"])["kind"] == "text":
            return {"franc_event": event}
        return False


def create_franc_event_router(database: Database) -> Router:
    router = Router(name="franc_events")
    store = FrancEventStore(database)
    scheduler_task: asyncio.Task[None] | None = None

    async def template_list_view(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
        templates = await store.list_templates()
        page_count = max(1, (len(templates) + 7) // 8)
        page = max(0, min(page, page_count - 1))
        rows = [
            [InlineKeyboardButton(
                text=f"{'🟢' if row['enabled'] else '⚪'} {row['prompt'][:35]}",
                callback_data=f"evm:detail:{row['id']}",
            )]
            for row in templates[page * 8:(page + 1) * 8]
        ]
        navigation = []
        if page > 0:
            navigation.append(InlineKeyboardButton(text="←", callback_data=f"evm:list:{page - 1}"))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(text="→", callback_data=f"evm:list:{page + 1}"))
        if navigation:
            rows.append(navigation)
        rows.append([InlineKeyboardButton(text="➕ Создать событие", callback_data="evm:chats")])
        return (
            f"<b>🎲 Конструктор событий</b> · {len(templates)} шт. · стр. {page + 1}/{page_count}\n"
            "Активные события выходят 1–2 раза в сутки в каждом настроенном чате.\n"
            "Варианты ответов и фраз можно добавлять по одному.",
            keyboard(rows),
        )

    async def owner_in_chat(bot: Bot, chat_id: int) -> bool:
        if chat_id >= 0:
            return False
        try:
            member = await bot.get_chat_member(chat_id, CUSTOM_COMMAND_OWNER_ID)
        except TelegramAPIError:
            return False
        status = getattr(member.status, "value", member.status)
        return bool(
            getattr(member, "is_member", False) if status == "restricted"
            else status not in {"left", "kicked"}
        )

    async def chats_view(bot: Bot) -> tuple[str, InlineKeyboardMarkup]:
        chats = await database.list_custom_command_chats(CUSTOM_COMMAND_OWNER_ID)
        rows = []
        for chat in chats:
            if not await owner_in_chat(bot, int(chat["chat_id"])):
                continue
            rows.append([InlineKeyboardButton(
                text=str(chat["title"] or chat["chat_id"])[:55],
                callback_data=f"evm:kinds:{chat['chat_id']}",
            )])
        rows.append([InlineKeyboardButton(text="← События", callback_data="evm:list")])
        text = "Выбери чат для события." if len(rows) > 1 else "Сначала напиши что-нибудь в нужном чате."
        return f"<b>➕ Новое событие</b>\n{text}", keyboard(rows)

    def kinds_view(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
        rows = [
            [InlineKeyboardButton(text=name, callback_data=f"evm:new:{chat_id}:{kind}")]
            for kind, name in KIND_NAMES.items()
        ]
        rows.append([InlineKeyboardButton(text="← Чаты", callback_data="evm:chats")])
        return "<b>Тип события</b>\nВыбери способ участия.", keyboard(rows)

    async def detail_view(template_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
        row = await store.get_template(template_id)
        if row is None:
            return None
        config = event_config(row)
        body = (
            f"<b>🎲 Событие №{template_id}</b> · {'🟢 включено' if row['enabled'] else '⚪ выключено'}\n"
            f"Чат: {html.escape(str(row['chat_title'] or row['chat_id']))}\n"
            f"Тип: {KIND_NAMES[config['kind']]}\n"
            f"Текст: {html.escape(config['prompt'])}\n"
            f"💰 Успех: {config['success_reward']} ₣ · неудача: {config['failure_reward']} ₣"
        )
        if config["kind"] == "luck":
            body += f" · шанс успеха {config['success_chance']}%"
        body += "\nФразы: {0} успеха / {1} неудачи. Метки: {{user}}, {{amount}}.".format(
            len(config["success_messages"]), len(config["failure_messages"])
        )
        if config["kind"] != "luck" and config["failure_reward"]:
            body += "\n⚠️ Награду за ошибку может получить каждый участник по одному разу."
        rows = [
            [InlineKeyboardButton(text="✏️ Текст события", callback_data=f"evm:field:{template_id}:prompt")],
            [InlineKeyboardButton(text="💰 Награда за успех", callback_data=f"evm:field:{template_id}:success_reward"),
             InlineKeyboardButton(text="💸 За неудачу", callback_data=f"evm:field:{template_id}:failure_reward")],
        ]
        if config["kind"] == "choice":
            rows.append([InlineKeyboardButton(text=f"🔘 Кнопки ({len(config['options'])})", callback_data=f"evm:items:{template_id}:options")])
        elif config["kind"] == "text":
            rows.append([InlineKeyboardButton(text=f"💬 Верные ответы ({len(config['answers'])})", callback_data=f"evm:items:{template_id}:answers")])
        else:
            rows.append([InlineKeyboardButton(text="🎲 Шанс успеха", callback_data=f"evm:field:{template_id}:success_chance")])
            rows.append([InlineKeyboardButton(text=f"🔘 Кнопка: {config['luck_button'][:25]}", callback_data=f"evm:field:{template_id}:luck_button")])
        rows += [
            [InlineKeyboardButton(text="✅ Фразы успеха", callback_data=f"evm:items:{template_id}:success"),
             InlineKeyboardButton(text="❌ Фразы неудачи", callback_data=f"evm:items:{template_id}:failure")],
            [InlineKeyboardButton(text="🚀 Запустить сейчас", callback_data=f"evm:launch_confirm:{template_id}")],
            [InlineKeyboardButton(text="⏯ Включить / выключить", callback_data=f"evm:toggle:{template_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"evm:delete:{template_id}"),
             InlineKeyboardButton(text="← Список", callback_data="evm:list")],
        ]
        return body, keyboard(rows)

    async def items_view(template_id: int, field: str) -> tuple[str, InlineKeyboardMarkup] | None:
        row = await store.get_template(template_id)
        if row is None or field not in LIST_NAMES:
            return None
        config = event_config(row)
        items = config[field if field in {"options", "answers"} else f"{field}_messages"]
        rows = []
        for index, item in enumerate(items):
            prefix = "✅ " if field == "options" and index == config["correct_index"] else ""
            rows.append([
                InlineKeyboardButton(text=f"{prefix}{index + 1}. {item[:28]}", callback_data=f"evm:edit:{template_id}:{field}:{index}"),
                InlineKeyboardButton(text="🗑", callback_data=f"evm:del:{template_id}:{field}:{index}"),
            ])
            if field == "options" and index != config["correct_index"]:
                rows.append([InlineKeyboardButton(text=f"☑️ Сделать кнопку {index + 1} правильной", callback_data=f"evm:correct:{template_id}:{index}")])
        rows += [
            [InlineKeyboardButton(text="➕ Добавить вариант", callback_data=f"evm:add:{template_id}:{field}")],
            [InlineKeyboardButton(text="← Событие", callback_data=f"evm:detail:{template_id}")],
        ]
        body = f"<b>{LIST_NAMES[field]}</b> · событие №{template_id}\n"
        body += "Нажми на вариант, чтобы изменить. Добавление — по одному сообщению."
        if field == "options":
            body += "\n✅ отмечена правильная кнопка."
        return body, keyboard(rows)

    async def edit_or_send(callback: CallbackQuery, view: tuple[str, InlineKeyboardMarkup]) -> None:
        try:
            await callback.message.edit_text(view[0], reply_markup=view[1], parse_mode="HTML")
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).casefold():
                await callback.message.answer(view[0], reply_markup=view[1], parse_mode="HTML")

    async def send_event(bot: Bot, event) -> bool:
        body, markup = public_event_view(event)
        try:
            sent = await bot.send_message(
                int(event["chat_id"]), body, parse_mode="HTML", reply_markup=markup
            )
        except TelegramAPIError as error:
            await store.fail_event(int(event["id"]))
            logging.getLogger(__name__).warning("Could not send franc event %s: %s", event["id"], error)
            return False
        await store.activate_event(int(event["id"]), sent.message_id)
        return True

    async def launch_manual_event(bot: Bot, template_id: int) -> str:
        event, error = await store.begin_manual_event(template_id)
        if event is None:
            return error or "Не удалось запустить событие."
        if not await send_event(bot, event):
            return "Не удалось отправить событие в чат. Проверь, что бот там есть и может писать."
        return f"🚀 Событие №{template_id} запущено. На ответ есть 10 минут."

    @router.message(F.text.regexp(r"^/(?:event|событие)(?:@\w+)?(?:\s+\d+)?\s*$"))
    async def event_manual_command(message: Message, bot: Bot, state: FSMContext) -> None:
        if message.chat.type != "private" or not message.from_user or message.from_user.id != CUSTOM_COMMAND_OWNER_ID:
            return
        await state.clear()
        parts = (message.text or "").split()
        if len(parts) == 1:
            body, markup = await template_list_view()
            await message.answer(body + "\nДля ручного запуска: /event ID", reply_markup=markup, parse_mode="HTML")
            return
        await message.answer(await launch_manual_event(bot, int(parts[1])))

    @router.message(F.text.regexp(r"^/(?:события|events)(?:@\w+)?\s*$"))
    async def events_menu(message: Message) -> None:
        if message.chat.type != "private" or not message.from_user or message.from_user.id != CUSTOM_COMMAND_OWNER_ID:
            return
        body, markup = await template_list_view()
        await message.answer(body, reply_markup=markup, parse_mode="HTML")

    @router.callback_query(F.data.startswith("evm:"))
    async def event_admin_callback(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if (
            not callback.from_user or callback.from_user.id != CUSTOM_COMMAND_OWNER_ID
            or not callback.message or callback.message.chat.type != "private"
        ):
            await callback.answer("Меню доступно только владельцу бота.", show_alert=True)
            return
        parts = (callback.data or "").split(":")
        action = parts[1] if len(parts) > 1 else ""
        view = None
        notice = None
        try:
            if action not in {"field", "add", "edit"}:
                await state.clear()
            if action == "list":
                view = await template_list_view(int(parts[2]) if len(parts) > 2 else 0)
            elif action == "chats":
                view = await chats_view(bot)
            elif action == "kinds":
                chat_id = int(parts[2])
                allowed = await owner_in_chat(bot, chat_id) and any(int(chat["chat_id"]) == chat_id for chat in await database.list_custom_command_chats(CUSTOM_COMMAND_OWNER_ID))
                if not allowed:
                    raise ValueError
                view = kinds_view(chat_id)
            elif action == "new":
                chat_id, kind = int(parts[2]), parts[3]
                allowed = await owner_in_chat(bot, chat_id) and any(int(chat["chat_id"]) == chat_id for chat in await database.list_custom_command_chats(CUSTOM_COMMAND_OWNER_ID))
                if not allowed:
                    raise ValueError
                template_id = await store.create_template(chat_id, kind)
                view = await detail_view(template_id)
                notice = "Черновик создан. Настрой его и включи."
            elif action == "detail":
                view = await detail_view(int(parts[2]))
            elif action == "items":
                view = await items_view(int(parts[2]), parts[3])
            elif action in {"field", "add", "edit"}:
                template_id = int(parts[2])
                if not await store.get_template(template_id):
                    raise ValueError
                field = parts[3]
                index = int(parts[4]) if action == "edit" else None
                if action == "field" and field not in {"prompt", "luck_button", "success_chance", "success_reward", "failure_reward"}:
                    raise ValueError
                if action in {"add", "edit"} and field not in LIST_NAMES:
                    raise ValueError
                await state.clear()
                await state.set_state(EventInput.value)
                await state.update_data(template_id=template_id, field=field, action=action, index=index)
                prompts = {
                    "prompt": "Напиши текст события (до 500 символов).",
                    "luck_button": "Напиши текст кнопки (до 50 символов).",
                    "success_chance": "Напиши шанс успеха от 0 до 100.",
                    "success_reward": "Напиши награду за успех от 0 до 500 ₣.",
                    "failure_reward": "Напиши награду за неудачу от 0 до 20 ₣.",
                }
                prompt = prompts.get(field, "Пришли один вариант текстом (до 500 символов; кнопка — до 50).")
                await callback.message.answer(prompt + "\n/отмена — отменить ввод.")
                await callback.answer()
                return
            elif action == "del":
                template_id, field, index = int(parts[2]), parts[3], int(parts[4])
                notice = await store.change_list(template_id, field, "delete", index=index)
                view = await items_view(template_id, field)
            elif action == "correct":
                template_id, index = int(parts[2]), int(parts[3])
                if not await store.set_correct_option(template_id, index):
                    raise ValueError
                view = await items_view(template_id, "options")
            elif action == "toggle":
                template_id = int(parts[2])
                enabled, error = await store.toggle_template(template_id)
                notice = error or ("Событие включено." if enabled else "Событие выключено.")
                view = await detail_view(template_id)
            elif action == "launch_confirm":
                template_id = int(parts[2])
                row = await store.get_template(template_id)
                if row is None:
                    raise ValueError
                view = (
                    f"Запустить событие №{template_id} сейчас в чате "
                    f"{html.escape(str(row['chat_title'] or row['chat_id']))}?",
                    keyboard([
                        [InlineKeyboardButton(text="🚀 Да, запустить", callback_data=f"evm:launch:{template_id}")],
                        [InlineKeyboardButton(text="← Отмена", callback_data=f"evm:detail:{template_id}")],
                    ]),
                )
            elif action == "launch":
                template_id = int(parts[2])
                notice = await launch_manual_event(bot, template_id)
                view = await detail_view(template_id)
            elif action == "delete":
                template_id = int(parts[2])
                view = (
                    f"Удалить событие №{template_id}? Активное событие в чате продолжит работу.",
                    keyboard([
                        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"evm:confirm:{template_id}")],
                        [InlineKeyboardButton(text="← Отмена", callback_data=f"evm:detail:{template_id}")],
                    ]),
                )
            elif action == "confirm":
                deleted = await store.delete_template(int(parts[2]))
                notice = "Событие удалено." if deleted else "Оно уже удалено."
                view = await template_list_view()
            else:
                raise ValueError
        except (ValueError, IndexError):
            await callback.answer("Кнопка устарела или некорректна.", show_alert=True)
            return
        if view is None:
            view = await template_list_view()
            notice = notice or "Событие уже удалено."
        await edit_or_send(callback, view)
        await callback.answer(notice)

    @router.message(EventInput.value)
    async def event_input(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private" or not message.from_user or message.from_user.id != CUSTOM_COMMAND_OWNER_ID:
            return
        value = (message.text or "").strip()
        if value.casefold() in {"/отмена", "отмена"}:
            await state.clear()
            await message.answer("Ввод отменён.")
            return
        if not value:
            await message.answer("Пришли обычный текст.")
            return
        data = await state.get_data()
        template_id = int(data["template_id"])
        field = str(data["field"])
        action = str(data["action"])
        try:
            if action == "field":
                result = await store.update_scalar(template_id, field, value)
                if not result:
                    raise ValueError
                view = await detail_view(template_id)
            else:
                result = await store.change_list(
                    template_id, field, action, value=value, index=data.get("index")
                )
                if result != "updated":
                    await message.answer({
                        "invalid": "Пустой или слишком длинный вариант.",
                        "full": "Список заполнен.",
                        "duplicate": "Такой ответ уже есть.",
                    }.get(result, "Вариант уже недоступен."))
                    return
                view = await items_view(template_id, field)
        except ValueError:
            await message.answer("Некорректное значение. Проверь диапазон или длину.")
            return
        await state.clear()
        if view:
            await message.answer(view[0], reply_markup=view[1], parse_mode="HTML")

    async def finish_public_event(event, result: dict, user: Message | CallbackQuery, bot: Bot) -> None:
        actor = user.from_user
        name = actor.full_name if actor else "участник"
        mention = rendered_phrase(str(result["phrase"]), actor.id, name, int(result["reward"]))
        reward = f"\n💰 +{result['reward']} ₣" if result["reward"] else "\n💸 Без награды"
        heading = "✅ Успех" if result["status"] == "success" else "❌ Неудача"
        text = f"🎲 <b>Событие завершено</b> · {heading}\n{mention}\n{user_mention(actor.id, name)}{reward}"
        try:
            await bot.edit_message_text(
                text, chat_id=int(event["chat_id"]), message_id=int(event["message_id"]),
                parse_mode="HTML", reply_markup=None,
            )
        except TelegramAPIError as error:
            logging.getLogger(__name__).warning("Could not update event %s: %s", event["id"], error)
            try:
                await bot.send_message(int(event["chat_id"]), text, parse_mode="HTML")
            except TelegramAPIError:
                pass

    @router.callback_query(F.data.startswith("fe:"))
    async def event_button(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.from_user or callback.from_user.is_bot or not callback.data:
            return
        try:
            _, raw_id, action = callback.data.split(":", 2)
            event_id = int(raw_id)
        except ValueError:
            await callback.answer("Некорректная кнопка.")
            return
        event = await store.get_event(event_id)
        if event is None or not callback.message or callback.message.chat.id != int(event["chat_id"]):
            await callback.answer("Событие недоступно.", show_alert=True)
            return
        try:
            member = await bot.get_chat_member(int(event["chat_id"]), callback.from_user.id)
            status = getattr(member.status, "value", member.status)
            present = status not in {"left", "kicked"}
            if status == "restricted":
                present = bool(getattr(member, "is_member", False))
        except TelegramAPIError:
            present = False
        if not present:
            await callback.answer("Участвовать могут только участники чата.", show_alert=True)
            return
        result = await store.submit_attempt(event_id, callback.from_user.id, action)
        if result["status"] in {"closed", "already", "invalid"}:
            await callback.answer({
                "closed": "Событие уже завершено.",
                "already": "Ты уже участвовал в этом событии.",
                "invalid": "Эта кнопка недоступна.",
            }[result["status"]], show_alert=True)
            return
        if result["resolved"]:
            await callback.answer("Результат готов!")
            await finish_public_event(event, result, callback, bot)
        else:
            text = (
                str(result["phrase"])
                .replace("{user}", callback.from_user.full_name)
                .replace("{amount}", str(result["reward"]))
                + (f" +{result['reward']} ₣" if result["reward"] else "")
            )
            await callback.answer(text[:190], show_alert=True)

    @router.message(EventReplyFilter(store))
    async def event_text_answer(message: Message, franc_event, bot: Bot) -> None:
        result = await store.submit_attempt(int(franc_event["id"]), message.from_user.id, message.text)
        if result["status"] in {"closed", "already"}:
            await message.reply("Событие завершено или ты уже отвечал.")
            return
        if result["resolved"]:
            await finish_public_event(franc_event, result, message, bot)
        else:
            text = rendered_phrase(
                str(result["phrase"]), message.from_user.id,
                message.from_user.full_name, int(result["reward"]),
            ) + (f" +{result['reward']} ₣" if result["reward"] else "")
            await message.reply(text, parse_mode="HTML")

    async def event_scheduler(bot: Bot) -> None:
        while True:
            try:
                now = datetime.now(MSK)
                day = service_day(now)
                for chat_id in await store.enabled_chats():
                    times = schedule_times(day, now)
                    if times:
                        await store.ensure_schedule(chat_id, day, times)
                await store.skip_stale_schedules(utc_timestamp() - EVENT_LIFETIME_SECONDS)
                for scheduled in await store.due_schedules(utc_timestamp()):
                    event = await store.begin_scheduled_event(int(scheduled["id"]))
                    if event is None:
                        continue
                    await send_event(bot, event)
                for event in await store.active_events_to_expire(utc_timestamp()):
                    if await store.expire_event(int(event["id"])):
                        try:
                            await bot.edit_message_text(
                                "⌛ Событие завершено: время вышло. Франки никому не начислены.",
                                chat_id=int(event["chat_id"]), message_id=int(event["message_id"]),
                                reply_markup=None,
                            )
                        except TelegramAPIError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception("Franc event scheduler failed")
            await asyncio.sleep(20)

    @router.startup()
    async def start_event_scheduler(bot: Bot) -> None:
        nonlocal scheduler_task
        await store.recover_sending_events()
        scheduler_task = asyncio.create_task(event_scheduler(bot))

    @router.shutdown()
    async def stop_event_scheduler() -> None:
        if scheduler_task is not None:
            scheduler_task.cancel()

    return router
