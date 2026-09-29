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


def rendered_phrase(
    phrase: str, user_id: int, name: str, reward: int,
    *, username: str | None = None,
) -> str:
    display_name = f"@{username}" if username else name
    return (
        html.escape(phrase)
        .replace("{user}", user_mention(user_id, display_name))
        .replace("{amount}", str(reward))
    )


def public_event_view(event) -> tuple[str, InlineKeyboardMarkup | None]:
    config = json.loads(event["snapshot_json"])
    kind = config["kind"]
    body = html.escape(config["prompt"])
    if kind == "choice":
        buttons = [
            [InlineKeyboardButton(text=label, callback_data=f"fe:{event['id']}:{index}")]
            for index, label in enumerate(config["options"])
        ]
        return body, keyboard(buttons)
    if kind == "text":
        return body, None
    return body, keyboard([
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
            f"Текст: {html.escape(config['prompt'])}"
        )
        custom_choice = config["kind"] == "choice" and config["choice_mode"] == "outcomes"
        custom_luck = config["kind"] == "luck" and config["luck_mode"] == "outcomes"
        if custom_choice:
            body += "\nРежим: исход для каждой кнопки; первое нажатие завершает событие."
        elif custom_luck:
            body += "\nРежим: несколько случайных исходов с разными весами и наградами."
        else:
            body += (
                f"\n💰 Успех: {config['success_reward']} ₣ · неудача: {config['failure_reward']} ₣"
            )
            if config["kind"] == "luck":
                body += f" · шанс успеха {config['success_chance']}%"
            body += "\nФразы: {0} успеха / {1} неудачи.".format(
                len(config["success_messages"]), len(config["failure_messages"])
            )
        body += "\nМетки: {user} — тег участника, {amount} — начисленные франки."
        if not custom_choice and config["kind"] != "luck" and config["failure_reward"]:
            body += "\n⚠️ Награду за ошибку может получить каждый участник по одному разу."
        rows = [
            [InlineKeyboardButton(text="✏️ Текст события", callback_data=f"evm:field:{template_id}:prompt")],
        ]
        if not (custom_choice or custom_luck):
            rows.append([
                InlineKeyboardButton(text="💰 Награда за успех", callback_data=f"evm:field:{template_id}:success_reward"),
                InlineKeyboardButton(text="💸 За неудачу", callback_data=f"evm:field:{template_id}:failure_reward"),
            ])
        if config["kind"] == "choice":
            rows.append([InlineKeyboardButton(
                text="🎛 Режим: исходы по кнопкам" if custom_choice else "🎛 Режим: викторина",
                callback_data=f"evm:mode:{template_id}",
            )])
            rows.append([InlineKeyboardButton(text=f"🔘 Кнопки ({len(config['options'])})", callback_data=f"evm:items:{template_id}:options")])
            if custom_choice:
                rows.append([InlineKeyboardButton(text="🎭 Исходы кнопок", callback_data=f"evm:outcomes:{template_id}:choice")])
        elif config["kind"] == "text":
            rows.append([InlineKeyboardButton(text=f"💬 Верные ответы ({len(config['answers'])})", callback_data=f"evm:items:{template_id}:answers")])
        else:
            rows.append([InlineKeyboardButton(
                text="🎛 Режим: несколько исходов" if custom_luck else "🎛 Режим: успех / неудача",
                callback_data=f"evm:mode:{template_id}",
            )])
            if custom_luck:
                rows.append([InlineKeyboardButton(text="🎲 Случайные исходы", callback_data=f"evm:outcomes:{template_id}:luck")])
            else:
                rows.append([InlineKeyboardButton(text="🎲 Шанс успеха", callback_data=f"evm:field:{template_id}:success_chance")])
            rows.append([InlineKeyboardButton(text=f"🔘 Кнопка: {config['luck_button'][:25]}", callback_data=f"evm:field:{template_id}:luck_button")])
        if not (custom_choice or custom_luck):
            rows.append([
                InlineKeyboardButton(text="✅ Фразы успеха", callback_data=f"evm:items:{template_id}:success"),
                InlineKeyboardButton(text="❌ Фразы неудачи", callback_data=f"evm:items:{template_id}:failure"),
            ])
        rows += [
            [InlineKeyboardButton(text="🚀 Запустить сейчас", callback_data=f"evm:launch_confirm:{template_id}")],
            [InlineKeyboardButton(text="⏯ Включить / выключить", callback_data=f"evm:toggle:{template_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"evm:delete:{template_id}"),
             InlineKeyboardButton(text="← Список", callback_data="evm:list")],
        ]
        return body, keyboard(rows)

    async def items_view(template_id: int, field: str, page: int = 0) -> tuple[str, InlineKeyboardMarkup] | None:
        row = await store.get_template(template_id)
        if row is None or field not in LIST_NAMES:
            return None
        config = event_config(row)
        items = config[field if field in {"options", "answers"} else f"{field}_messages"]
        page_count = max(1, (len(items) + 3) // 4)
        page = max(0, min(page, page_count - 1))
        rows = []
        lines = [f"<b>{LIST_NAMES[field]}</b> · событие №{template_id} · стр. {page + 1}/{page_count}"]
        for index in range(page * 4, min((page + 1) * 4, len(items))):
            item = items[index]
            quiz_option = field == "options" and config["choice_mode"] == "quiz"
            prefix = "✅ " if quiz_option and index == config["correct_index"] else ""
            lines.append(f"{prefix}{index + 1}. {html.escape(item)}")
            rows.append([
                InlineKeyboardButton(text=str(index + 1), callback_data=f"evm:edit:{template_id}:{field}:{index}"),
                InlineKeyboardButton(text="🗑", callback_data=f"evm:del:{template_id}:{field}:{index}"),
            ])
            if quiz_option and index != config["correct_index"]:
                rows.append([InlineKeyboardButton(text=f"☑️ Сделать кнопку {index + 1} правильной", callback_data=f"evm:correct:{template_id}:{index}")])
        navigation = []
        if page > 0:
            navigation.append(InlineKeyboardButton(text="←", callback_data=f"evm:items:{template_id}:{field}:{page - 1}"))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(text="→", callback_data=f"evm:items:{template_id}:{field}:{page + 1}"))
        if navigation:
            rows.append(navigation)
        rows += [
            [InlineKeyboardButton(text="➕ Добавить вариант", callback_data=f"evm:add:{template_id}:{field}")],
            [InlineKeyboardButton(text="← Событие", callback_data=f"evm:detail:{template_id}")],
        ]
        body = "\n".join(lines) + "\nНажми номер, чтобы изменить. Добавление — по одному сообщению."
        if field == "options" and config["choice_mode"] == "quiz":
            body += "\n✅ отмечена правильная кнопка."
        elif field == "options":
            body += "\nНастрой отдельный исход для каждой кнопки в карточке события."
        return body, keyboard(rows)

    async def outcomes_view(template_id: int, kind: str) -> tuple[str, InlineKeyboardMarkup] | None:
        row = await store.get_template(template_id)
        if row is None or kind not in {"choice", "luck"} or row["kind"] != kind:
            return None
        config = event_config(row)
        outcomes = config[f"{kind}_outcomes"]
        total_weight = sum(int(item["weight"]) for item in outcomes) if kind == "luck" else 0
        lines = [f"<b>🎭 Исходы события №{template_id}</b>"]
        rows = []
        for index, outcome in enumerate(outcomes):
            name = config["options"][index] if kind == "choice" else outcome["name"]
            extra = (
                f" · вес {outcome['weight']} (≈{100 * int(outcome['weight']) / total_weight:.1f}%)"
                if kind == "luck" and total_weight else ""
            )
            lines.append(
                f"{index + 1}. {html.escape(name)} — {outcome['reward']} ₣{extra}; "
                f"фраз: {len(outcome['messages'])}"
            )
            rows.append([InlineKeyboardButton(
                text=str(index + 1), callback_data=f"evm:outcome:{template_id}:{kind}:{index}"
            )])
        if kind == "luck":
            rows.append([InlineKeyboardButton(
                text="➕ Добавить исход", callback_data=f"evm:oaddnew:{template_id}:luck"
            )])
        rows.append([InlineKeyboardButton(text="← Событие", callback_data=f"evm:detail:{template_id}")])
        lines.append("Нажми номер, чтобы настроить награду, вес и фразы.")
        return "\n".join(lines), keyboard(rows)

    async def outcome_view(
        template_id: int, kind: str, index: int, page: int = 0,
    ) -> tuple[str, InlineKeyboardMarkup] | None:
        row = await store.get_template(template_id)
        if row is None or kind not in {"choice", "luck"} or row["kind"] != kind:
            return None
        config = event_config(row)
        outcomes = config[f"{kind}_outcomes"]
        if not 0 <= index < len(outcomes):
            return None
        outcome = outcomes[index]
        name = config["options"][index] if kind == "choice" else outcome["name"]
        messages = outcome["messages"]
        page_count = max(1, (len(messages) + 3) // 4)
        page = max(0, min(page, page_count - 1))
        lines = [
            f"<b>🎭 Исход {index + 1}: {html.escape(name)}</b>",
            f"Награда: {outcome['reward']} ₣"
            + (f" · вес: {outcome['weight']}" if kind == "luck" else ""),
            f"Фразы · стр. {page + 1}/{page_count}:",
        ]
        rows = []
        for message_index in range(page * 4, min((page + 1) * 4, len(messages))):
            lines.append(f"{message_index + 1}. {html.escape(messages[message_index])}")
            rows.append([
                InlineKeyboardButton(
                    text=str(message_index + 1),
                    callback_data=f"evm:oedit:{template_id}:{kind}:{index}:{message_index}",
                ),
                InlineKeyboardButton(
                    text="🗑", callback_data=f"evm:odel:{template_id}:{kind}:{index}:{message_index}"
                ),
            ])
        if not messages:
            lines.append("Пока нет фраз — добавь хотя бы одну.")
        navigation = []
        if page > 0:
            navigation.append(InlineKeyboardButton(
                text="←", callback_data=f"evm:outcome:{template_id}:{kind}:{index}:{page - 1}"
            ))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(
                text="→", callback_data=f"evm:outcome:{template_id}:{kind}:{index}:{page + 1}"
            ))
        if navigation:
            rows.append(navigation)
        fields = [InlineKeyboardButton(
            text="💰 Награда", callback_data=f"evm:ofield:{template_id}:{kind}:{index}:reward"
        )]
        if kind == "luck":
            fields.append(InlineKeyboardButton(
                text="🎲 Вес", callback_data=f"evm:ofield:{template_id}:{kind}:{index}:weight"
            ))
            rows.append([InlineKeyboardButton(
                text="✏️ Название", callback_data=f"evm:ofield:{template_id}:{kind}:{index}:name"
            )])
        rows.append(fields)
        rows.append([InlineKeyboardButton(
            text="➕ Добавить фразу", callback_data=f"evm:oadd:{template_id}:{kind}:{index}"
        )])
        if kind == "luck":
            rows.append([InlineKeyboardButton(
                text="🗑 Удалить исход", callback_data=f"evm:odelconfirm:{template_id}:{kind}:{index}"
            )])
        rows.append([InlineKeyboardButton(
            text="← Все исходы", callback_data=f"evm:outcomes:{template_id}:{kind}"
        )])
        return "\n".join(lines), keyboard(rows)

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
            if action not in {"field", "add", "edit", "ofield", "oadd", "oedit"}:
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
                view = await items_view(
                    int(parts[2]), parts[3], int(parts[4]) if len(parts) > 4 else 0
                )
            elif action == "mode":
                template_id = int(parts[2])
                if not await store.toggle_outcome_mode(template_id):
                    raise ValueError
                view = await detail_view(template_id)
                notice = "Режим изменён. Проверь исходы перед запуском."
            elif action == "outcomes":
                view = await outcomes_view(int(parts[2]), parts[3])
            elif action == "outcome":
                view = await outcome_view(
                    int(parts[2]), parts[3], int(parts[4]),
                    int(parts[5]) if len(parts) > 5 else 0,
                )
            elif action == "oaddnew":
                template_id, kind = int(parts[2]), parts[3]
                result = await store.change_outcome(template_id, kind, "add")
                notice = "Исход добавлен." if result == "updated" else "Достигнут лимит исходов."
                view = await outcomes_view(template_id, kind)
            elif action == "odelconfirm":
                template_id, kind, index = int(parts[2]), parts[3], int(parts[4])
                if await outcome_view(template_id, kind, index) is None or kind != "luck":
                    raise ValueError
                view = (
                    f"Удалить случайный исход №{index + 1}?",
                    keyboard([
                        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"evm:odeloutcome:{template_id}:{kind}:{index}")],
                        [InlineKeyboardButton(text="← Отмена", callback_data=f"evm:outcome:{template_id}:{kind}:{index}")],
                    ]),
                )
            elif action == "odeloutcome":
                template_id, kind, index = int(parts[2]), parts[3], int(parts[4])
                result = await store.change_outcome(template_id, kind, "delete", index=index)
                notice = "Исход удалён." if result == "updated" else "Исход уже недоступен."
                view = await outcomes_view(template_id, kind)
            elif action == "odel":
                template_id, kind, index, message_index = (
                    int(parts[2]), parts[3], int(parts[4]), int(parts[5])
                )
                result = await store.change_outcome(
                    template_id, kind, "message_delete", index=index,
                    message_index=message_index,
                )
                notice = "Фраза удалена." if result == "updated" else "Фраза уже недоступна."
                view = await outcome_view(template_id, kind, index, message_index // 4)
            elif action in {"ofield", "oadd", "oedit"}:
                template_id, kind, index = int(parts[2]), parts[3], int(parts[4])
                if await outcome_view(template_id, kind, index) is None:
                    raise ValueError
                operation = (
                    parts[5] if action == "ofield" else
                    "message_add" if action == "oadd" else "message_edit"
                )
                message_index = int(parts[5]) if action == "oedit" else None
                if operation not in {"reward", "weight", "name", "message_add", "message_edit"}:
                    raise ValueError
                if kind == "choice" and operation in {"weight", "name"}:
                    raise ValueError
                await state.clear()
                await state.set_state(EventInput.value)
                await state.update_data(
                    template_id=template_id, kind=kind, index=index,
                    message_index=message_index, operation=operation, action="outcome",
                )
                prompts = {
                    "reward": "Награда за этот исход: от 0 до 500 ₣.",
                    "weight": "Вес исхода: от 1 до 100. Шанс пропорционален сумме весов.",
                    "name": "Название исхода (до 50 символов; видно только в конструкторе).",
                }
                await callback.message.answer(
                    prompts.get(operation, "Пришли одну фразу исхода (до 500 символов).")
                    + "\nМетки: {user} и {amount}. /отмена — отменить ввод."
                )
                await callback.answer()
                return
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
                view = await items_view(template_id, field, index // 4)
            elif action == "correct":
                template_id, index = int(parts[2]), int(parts[3])
                if not await store.set_correct_option(template_id, index):
                    raise ValueError
                view = await items_view(template_id, "options", index // 4)
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
        field = str(data.get("field", ""))
        action = str(data["action"])
        try:
            if action == "outcome":
                kind = str(data["kind"])
                index = int(data["index"])
                operation = str(data["operation"])
                result = await store.change_outcome(
                    template_id, kind, operation, index=index, value=value,
                    message_index=data.get("message_index"),
                )
                if result != "updated":
                    await message.answer({
                        "invalid": "Некорректное значение или длина.",
                        "full": "Список фраз заполнен.",
                    }.get(result, "Исход уже недоступен."))
                    return
                view = await outcome_view(template_id, kind, index)
            elif action == "field":
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
                view = await items_view(
                    template_id, field,
                    int(data["index"]) // 4 if data.get("index") is not None else 0,
                )
        except ValueError:
            await message.answer("Некорректное значение. Проверь диапазон или длину.")
            return
        await state.clear()
        if view:
            await message.answer(view[0], reply_markup=view[1], parse_mode="HTML")

    async def finish_public_event(event, result: dict, user: Message | CallbackQuery, bot: Bot) -> None:
        actor = user.from_user
        name = actor.full_name if actor else "участник"
        text = rendered_phrase(
            str(result["phrase"]), actor.id, name, int(result["reward"]),
            username=actor.username,
        )
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
            await callback.answer()
            await finish_public_event(event, result, callback, bot)
        else:
            phrase = str(result["phrase"])
            if "{user}" in phrase:
                text = rendered_phrase(
                    phrase, callback.from_user.id, callback.from_user.full_name,
                    int(result["reward"]), username=callback.from_user.username,
                )
                try:
                    await bot.send_message(int(event["chat_id"]), text, parse_mode="HTML")
                except TelegramAPIError:
                    await callback.answer("Ответ принят, но сообщение в чат отправить не удалось.", show_alert=True)
                else:
                    await callback.answer()
            else:
                text = phrase.replace("{amount}", str(result["reward"]))
                if len(text) <= 200:
                    await callback.answer(text, show_alert=True)
                else:
                    try:
                        await bot.send_message(int(event["chat_id"]), html.escape(text), parse_mode="HTML")
                    except TelegramAPIError:
                        await callback.answer("Ответ принят, но сообщение в чат отправить не удалось.", show_alert=True)
                    else:
                        await callback.answer()

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
                username=message.from_user.username,
            )
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
