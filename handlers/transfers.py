"""One shared entry point for slave/item lists and multiline transfers."""

import html

from arena_web import require_member
from transfer_batch import parse_transfer_message


async def handle_transfers(message, database, bot):
    # Lazy imports avoid a cycle: both legacy routers delegate here.
    from handlers.routes import (
        message_content, stored_sleepy_attack_is_blocked, target_is_immune,
        SLEEPY_PROTECTION_TEXT, IMMUNITY_TEXT,
    )

    if not message.from_user or message.chat.type not in {"private", "group", "supergroup"}:
        return
    actor = message.from_user.id
    chat = message.chat.id
    reply = message.reply_to_message
    try:
        requests = parse_transfer_message(
            message_content(message), reply=bool(reply) and message.chat.type != "private")
        if message.chat.type == "private":
            if any(request.kind == "slave" for request in requests):
                raise ValueError("Рабов передают командой в группе. В личке можно передавать предметы выбранного чата.")
            selected = await database.selected_menu_chat(actor)
            if not selected:
                raise ValueError("Сначала выбери чат в /menu.")
            chat = int(selected if isinstance(selected, int) else selected["chat_id"])
            # A reply to the bot in private is not a group recipient.
            if any(request.recipient is None for request in requests):
                raise ValueError("В личке укажи получателя: /передать предмет 42x3 @участник.")
        if reply and getattr(reply, "sender_chat", None):
            raise ValueError("Нельзя определить автора сообщения от имени канала.")
        await require_member(bot, chat, actor)
        targets, names = {}, {}
        registered_recipients = set()

        async def resolve(token, *, recipient=False):
            if token is None:
                user = getattr(reply, "from_user", None)
                if not user:
                    raise ValueError("Ответь на сообщение получателя или укажи его @username/ID.")
                if user.is_bot:
                    raise ValueError("Ботам нельзя передавать рабов и предметы.")
                name = user.full_name or str(user.id)
                await database.upsert_user(chat, user.id, user.username, name, touch=False)
                user_id = user.id
            elif token.casefold() in {"мне", "себе"}:
                user_id, name = actor, str(actor)
            else:
                row = await database.resolve_user(chat, token)
                if row:
                    user_id, name = int(row["user_id"]), row["display_name"]
                elif token.isascii() and token.isdigit():
                    user_id, name = int(token), token
                else:
                    raise ValueError(f"Не найден {token} в выбранном чате. Используй Telegram ID или актуальный тег.")
            if not 0 < user_id < 2**63:
                raise ValueError("Нужен положительный Telegram ID участника.")
            # Verify live recipients and prevent stale @tags addressing old users.
            if recipient or (token and token.startswith("@")):
                if user_id not in targets:
                    targets[user_id] = await require_member(bot, chat, user_id)
                member = targets[user_id]
                if member.user.is_bot:
                    raise ValueError("Ботам нельзя передавать рабов и предметы.")
                if token and token.startswith("@") and (member.user.username or "").casefold() != token[1:].casefold():
                    raise ValueError("Тег участника изменился. Используй его ID или обновлённый тег.")
                if recipient:
                    name = member.user.full_name
                    if user_id not in registered_recipients:
                        await database.upsert_user(chat, user_id, member.user.username, name, touch=False)
                        registered_recipients.add(user_id)
            names[user_id] = name
            return user_id

        operations = []
        for request in requests:
            target = await resolve(request.recipient, recipient=True)
            for token, quantity in request.entries:
                if request.kind == "slave":
                    entry = await resolve(token)
                    if await stored_sleepy_attack_is_blocked(database, chat, message.from_user, entry):
                        raise ValueError(SLEEPY_PROTECTION_TEXT)
                    if await target_is_immune(database, chat, entry):
                        raise ValueError(IMMUNITY_TEXT)
                else:
                    entry = int(token)
                operations.append(dict(kind=request.kind, id=entry, quantity=quantity, target=target))
        receipt = await database.transfer_batch(
            chat, actor, operations, source_chat=message.chat.id,
            message_id=getattr(message, "message_id", None),
        )
    except ValueError as error:
        await message.answer(f"{error}\nНичего не передано.")
        return

    lines = ["🤝 Передача выполнена:"]
    for row in receipt:
        label = names.get(row["id"], str(row["id"])) if row["kind"] == "slave" else row["name"]
        amount = f' ×{row["quantity"]}' if row["kind"] == "item" else ""
        target = row["target"]
        name = html.escape(str(names.get(target, target))[:80])
        lines.append(f'• {html.escape(str(label)[:100])}{amount} → <a href="tg://user?id={target}">{name}</a>')
    # Split only at line boundaries: never cut an HTML entity or mention.
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 3500:
            await message.answer(chunk, parse_mode="HTML")
            chunk = ""
        chunk += ("\n" if chunk else "") + line
    if chunk:
        await message.answer(chunk, parse_mode="HTML")
