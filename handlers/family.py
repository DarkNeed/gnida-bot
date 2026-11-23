"""Chat entry points for the family archive and consensual weddings."""
from html import escape
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from arena_links import arena_link
from arena_web import require_member
from family_tree import EMPTY_ORIGIN, FamilyError
from family_web import family_access, family_target, MAX_ID
from handlers.routes import message_content, text_or_caption_regexp

FAMILY_RE = re.compile(r"^\s*[/!]древо(?:@\w+)?(?=\s|$)", re.I)
OFFER_RE = re.compile(r"family:([0-9a-f]{24}):(accept|decline|cancel)")
EDITS = {("исток",):"origin", ("связь",):"link", ("убрать","связь"):"unlink",
         ("родные",):"sibling", ("убрать","родных"):"unsibling",
         ("судья","+"):"appoint", ("судья","-"):"revoke"}


def create_family_router(db, bot, username, enabled):
    router = Router(name="family_tree")

    def archive_link(chat, view="", *ids, label="🌌 Открыть древо"):
        parameter = "_".join(map(str, ("family",chat,view,*ids))).rstrip("_")
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=arena_link(username, parameter))]])

    async def pick(message, token=None, *, historical=False):
        chat = message.chat.id
        if token is not None:
            if not re.fullmatch(r"@[\w]{1,32}", token, re.ASCII):
                raise FamilyError("Введи @ник или ответь на сообщение участника.")
            rows = await db.users_by_username(chat, token[1:])
            if historical and len(rows) == 1:
                return rows[0]["user_id"], rows[0]["display_name"]
            for row in rows[:10]:
                try:
                    user = (await require_member(bot, chat, row["user_id"])).user
                except ValueError:
                    continue
                if (user.username or "").casefold() == token[1:].casefold() and not user.is_bot:
                    await db.upsert_user(chat,user.id,user.username,user.full_name,touch=False)
                    return user.id, user.full_name
            raise FamilyError("Не нашёл этот @ник. Если участник ещё не знаком боту, ответь на его сообщение.")
        reply = message.reply_to_message
        user = reply.from_user if reply and not reply.sender_chat else None
        if not user or user.is_bot:
            raise FamilyError("Укажи @ник или ответь на сообщение участника.")
        target = (await family_target(db, bot, require_member, chat, user.id)).user
        return target.id, target.full_name

    @router.message(text_or_caption_regexp(FAMILY_RE))
    async def family_command(message):
        user = message.from_user
        if not user or user.is_bot or message.sender_chat:
            return
        if message.chat.type not in ("group","supergroup"):
            await message.answer("Используй !древо в нужном общем чате.")
            return
        if not enabled:
            await message.answer("Семейный архив недоступен: не настроен WEBAPP_URL.")
            return
        chat = message.chat.id
        raw = message_content(message)
        parts = raw[FAMILY_RE.match(raw).end():].split()
        words = [word.casefold().replace("−", "-") for word in parts]
        try:
            owner = await family_access(bot, require_member, chat, user.id)
            await db.upsert_chat(chat, message.chat.title or "Семейный архив")
            await db.upsert_user(chat, user.id, user.username, user.full_name, touch=False)
            if not words:
                await message.answer("🌌 Семейный архив этого чата.", reply_markup=archive_link(chat))
                return
            cmd = words[0]
            if cmd == "найти" and len(parts) <= 2:
                target, _ = await pick(message, parts[1] if len(parts) == 2 else None)
                if not await db.family_avatar_allowed(chat, target):
                    raise FamilyError("Этого участника пока нет в общем древе.")
                await message.answer("🌌 Карточка в семейном древе.", reply_markup=archive_link(chat,"find",target))
                return
            if cmd == "брак" and len(parts) <= 2:
                target, name = await pick(message, parts[1] if len(parts) == 2 else None)
                token = await db.family_offer(chat,user.id,target)
                def button(text, action):
                    return InlineKeyboardButton(text=text, callback_data=f"family:{token}:{action}")
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [button("💍 Принять","accept"), button("Отклонить","decline")],
                    [button("Отозвать","cancel")],
                ])
                try:
                    await message.answer(f'💍 <b>{escape(user.full_name)}</b> предлагает брак '
                                         f'<a href="tg://user?id={target}">{escape(name)}</a>. '
                                         "Предложение действует 15 минут.", parse_mode="HTML", reply_markup=keyboard)
                except TelegramAPIError:
                    await db.family_offer_action(chat,token,user.id,"cancel")
                    raise
                return
            if cmd == "развод" and len(words) == 1:
                await message.answer("⚖️ Заявление и его статус — в семейном архиве. Причина не публикуется в чате.",
                                     reply_markup=archive_link(chat,"file",label="Открыть заявление"))
                return
            if cmd == "суд" and len(words) <= 2:
                if not await db.family_role(chat,user.id,owner):
                    raise FamilyError("Список дел доступен судьям.")
                case = words[1] if len(words) > 1 else None
                if case is not None and (not re.fullmatch(r"[1-9][0-9]{0,15}",case) or int(case) > MAX_ID):
                    raise FamilyError("Укажи номер дела, например !древо суд 12.")
                await message.answer("⚖️ Семейный суд.", reply_markup=archive_link(chat,"court",*([case] if case else []),label="Открыть суд"))
                return
            for prefix, edit in EDITS.items():
                if tuple(words[:len(prefix)]) != prefix:
                    continue
                if not owner:
                    raise FamilyError("Редактировать древо может владелец чата или создатель бота.")
                arguments = parts[len(prefix):]
                if edit in ("sibling", "unsibling"):
                    if len(arguments) == 2:
                        targets = arguments
                    elif len(arguments) == 1 and message.reply_to_message:
                        targets = [arguments[0], None]
                    else:
                        raise FamilyError("Укажи двух участников: !древо родные @ник1 @ник2.")
                    ids = [(await pick(message, arg, historical=edit=="unsibling"))[0] for arg in targets]
                elif edit in ("link","unlink"):
                    if arguments and arguments[0].casefold() == "исток" and len(arguments) <= 2:
                        target, _ = await pick(message, arguments[1] if len(arguments) == 2 else None, historical=edit=="unlink")
                        ids = [EMPTY_ORIGIN, target]
                    elif len(arguments) == 2:
                        ids = [(await pick(message, arg, historical=edit=="unlink"))[0] for arg in arguments]
                    else:
                        raise FamilyError("Укажи @родитель @ребёнок или исток @участник.")
                elif edit == "origin" and ((len(arguments) == 1 and arguments[0].casefold() == "пустой")
                                          or (not arguments and not message.reply_to_message)):
                    ids = [EMPTY_ORIGIN]
                else:
                    if len(arguments) > 1:
                        raise FamilyError("Укажи одного участника.")
                    ids = [(await pick(message, arguments[0] if arguments else None, historical=edit=="revoke"))[0]]
                await message.answer("✏️ Проверь правку в редакторе. В чате она ещё не применена.",
                                     reply_markup=archive_link(chat,edit,*ids,label="Проверить правку"))
                return
            commands = ("!древо · !древо найти @ник · !древо брак @ник · !древо развод")
            if await db.family_role(chat,user.id,owner):
                commands += "\n!древо суд [номер]"
            if owner:
                commands += ("\n!древо исток пустой · !древо исток @ник · !древо судья +/− @ник\n"
                             "!древо связь @родитель @ребёнок · !древо связь исток @ник\n"
                             "!древо убрать связь @родитель @ребёнок · !древо убрать связь исток @ник\n"
                             "!древо родные @ник1 @ник2 · !древо убрать родных @ник1 @ник2")
            await message.answer(commands)
        except ValueError as error:
            await message.answer(str(error))

    @router.callback_query(F.data.startswith("family:"))
    async def offer_callback(callback):
        match = OFFER_RE.fullmatch(callback.data or "")
        message = callback.message
        if not match or not isinstance(message, Message) or message.chat.type not in ("group", "supergroup"):
            await callback.answer("Кнопка недоступна.", show_alert=True)
            return
        token, action = match.groups()
        chat, actor = message.chat.id, callback.from_user.id
        try:
            if action == "accept":
                pair = await db.family_offer_people(chat,token)
                if not pair or actor != pair[1]:
                    raise FamilyError("Предложение истекло или адресовано другому участнику.")
                for person in pair:
                    await family_target(db, bot, require_member, chat, person)
            await db.family_offer_action(chat,token,actor,action)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return
        await callback.answer()
        result = {"accept":"💍 Брак зарегистрирован.", "decline":"Предложение отклонено.", "cancel":"Предложение отозвано."}
        try:
            await message.edit_text(result[action], reply_markup=archive_link(chat) if enabled else None)
        except TelegramAPIError:
            pass

    return router
