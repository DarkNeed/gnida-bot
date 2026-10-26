"""Chat raid lobbies and compact round announcements, without a DM prerequisite."""

import asyncio
import html
import hashlib
import json
import logging
import re

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from arena_links import arena_link
from arena_web import require_member
from arena_raid_engine import BOSSES
from handlers.routes import text_or_caption_regexp

RAID_RE = re.compile(
    r"^\s*/(?:рейд|raid)(?:@\w+)?(?:\s+(?P<boss>лей\s*хенг|lei[ _]?heng|фуфелшмерц|фуфел|doofenshmirtz|doof|китобой|whaler|кит|kit|маэль|капеллан|каппеллан|chaplain))?\s*$",
    re.I,
)
ENCOUNTER_RE = re.compile(r'^\s*/(?:встреча|encounter)(?:@\w+)?(?:\s+(?P<roster>[^\n]+))?\s*$', re.I)


def raid_boss_id(match):
    name = match.group("boss").casefold() if match and match.group("boss") else ""
    if name in ('капеллан', 'каппеллан', 'chaplain'):
        return 'chaplain'
    if name in ('китобой','whaler'):
        return 'whaler'
    if name in ('кит', 'kit', 'маэль'):
        return 'kit'
    return (
        "doofenshmirtz"
        if name.startswith(("фуфел", "doof"))
        else "lei_heng"
    )


class RaidPublisher:
    def __init__(self, db, bot, username):
        self.db, self.bot, self.username = db, bot, username
        self.lock = asyncio.Lock()
        self.signatures = {}
        self.retry_at = {}
        self.last_edit = 0.0

    @staticmethod
    def signature(row):
        data = json.loads(row["data_json"]) if row["data_json"] else {}
        return (
            row["status"],
            row["round"],
            tuple(
                (p["actor_id"], p["fighter_id"], p["personal"])
                for p in row["participants"]
            ),
            tuple((key, p["withdrawn"]) for key, p in data.get("players", {}).items()),
        )

    def keyboard(self, row):
        buttons = [
            [
                InlineKeyboardButton(
                    text='⚔️ Открыть встречу' if row.get('boss_id') == 'encounter' else '👹 Открыть рейд',
                    url=arena_link(self.username, "r_" + row["token"]),
                )
            ]
        ]
        if row["status"] == "lobby":
            buttons += [
                [
                    InlineKeyboardButton(
                        text="➕ Присоединиться",
                        callback_data="rr:join:" + row["token"],
                    ),
                    InlineKeyboardButton(
                        text="🚪 Выйти", callback_data="rr:leave:" + row["token"]
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="⚔️ Начать", callback_data="rr:start:" + row["token"]
                    ),
                    InlineKeyboardButton(
                        text="↩️ Отменить", callback_data="rr:cancel:" + row["token"]
                    ),
                ],
            ]
        if row.get('boss_id') == 'encounter' and row['status'] == 'active':
            buttons.append([InlineKeyboardButton(text='Завершить · только мастер', callback_data='rr:finish:' + row['token'])])
        if row.get('boss_id') == 'encounter':
            buttons.append([InlineKeyboardButton(text='🎭 RP-меню · свои персонажи и мобы', url=arena_link(self.username, 'rp_' + str(row['chat_id'])))])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def body(self, row):
        names = {}
        for p in row["participants"]:
            user = await self.db.get_user(row["chat_id"], p["actor_id"])
            names[str(p["actor_id"])] = html.escape(
                user["display_name"] if user else str(p["actor_id"])
            )
        boss = BOSSES.get(row.get("boss_id", "iron"), BOSSES["iron"])
        if row.get('boss_id') == 'encounter':
            from arena_encounters import roster_text
            master = await self.db.get_user(row['chat_id'], row['creator_id'])
            master_name = html.escape(master['display_name'] if master else str(row['creator_id']))
            config = json.loads(row['encounter_json'])
            text = '⚔️ <b>РП-встреча</b> · ' + html.escape(roster_text(config['roster']))
            role = 'участвует в отряде' if any(p['actor_id'] == row['creator_id'] for p in row['participants']) else 'не занимает место, пока сам не вступит'
            text += f'\nМастер: {master_name} · {role}.\nНаграды отключены: без XP, франков, предметов и кулдаунов наград.\n'
            if row['status'] == 'lobby':
                return text + f'\nОтряд: {len(names)}/3\n' + '\n'.join('• ' + n for n in names.values()) + '\n\nМастер начинает бой с 1–3 участниками. До 3 врагов. Свои мобы сохраняют настройки мастера; готовые подстраиваются под отряд. На сбор — 10 минут.'
            if row['status'] == 'cancelled':
                return text + '\nСбор отменён или время истекло.'
            data = json.loads(row['data_json'])
            text += f'\nРаунд {data["round"]}\n' if row['status'] == 'active' else '\n' + html.escape(data['result']) + '\n'
            for key, enemy in data['enemies'].items():
                intent = data.get('enemy_intents', {}).get(key, {})
                text += f'\n👹 {html.escape(enemy["name"])}: {enemy["hp"]}/{enemy["stats"]["max_hp"]} HP'
                if row['status'] == 'active' and enemy['hp'] > 0:
                    text += ' · ' + html.escape(intent.get('text', ''))
                    targets = ', '.join(names.get(k, k) for k in intent.get('targets', []))
                    if targets:
                        text += ' → ' + targets
            for key, player in data['players'].items():
                text += f'\n{"🚪" if player["withdrawn"] else "⚔️"} {names.get(key, key)}: {player["fighter"]["hp"]} HP'
            return text + '\n\nДействия и выбор цели — в мини-приложении. На выбор — 2 минуты. Мастер может завершить встречу.'
        text = f"👹 <b>{html.escape(boss['name'])}</b> · командный рейд\n"
        if row["status"] == "lobby":
            text += f"Участники: {len(names)}/3\n" + "\n".join(
                "• " + n for n in names.values()
            )
            return (
                text
                + (
                    f"\n📜 {('Последняя поправка · легендарный трактат' if row.get('boss_id') == 'chaplain' else 'Солнечное затмение · легендарный трактат' if row.get('boss_id') == 'kit' else 'Депортатор-инатор · 80 энергии, один раз за бой' if row.get('boss_id') == 'doofenshmirtz' else 'Трактат поступи тигробоя')}: шанс 70%, гарантия на пятой подходящей победе после четырёх неудач."
                    if boss.get("loot_skill")
                    else ""
                )
                + ('\nЧетыре фазы, фиксированный уровень 25. Вход без ограничения уровня, рекомендуется 20+. HP зависит от размера отряда.' if row.get('boss_id') == 'chaplain' else '\nКошмар: фиксированный уровень 25, без подстройки под уровни, состав и размер отряда. Рассчитан на трёх подготовленных бойцов 20 уровня.' if boss.get('fixed_level') else '\nУровень босса подстраивается под отряд, выше самого сильного бойца.')
                + " Часовой кулдаун наград запускается только при выпадении трактата. Не выпал — следующая победа снова даёт полную награду и попытку дропа. Во время кулдауна: 20% франков и XP, без предметов. Таймер отдельный для каждого босса, общий для всех чатов и персонажей аккаунта; повторы его не продлевают.\n\nВыберите личного персонажа в «Открыть рейд».\nСоздатель может начать бой с 1–3 участниками, в том числе в одиночку. На сбор — 10 минут."
            )
        if row["status"] == "cancelled":
            return text + "Сбор рейда отменён или время сбора истекло."
        data = json.loads(row["data_json"])
        if row["status"] == "active":
            text += f"Раунд {data['round']} · фаза {data['phase']}/{data.get('phase_count',2)} · босс Lv.{data['boss']['level']}\nHP босса: {data['boss']['hp']}/{data['boss']['stats']['max_hp']}\n"
            text += html.escape(data["intent"]["text"]) + "\n"
            if len(data["intent"]["targets"]) == 1:
                text += "Цель: " + names[data["intent"]["targets"][0]] + "\n"
        else:
            text += html.escape(data["result"]) + "\n"
        for key, player in data["players"].items():
            mark = (
                "🚪"
                if player["withdrawn"]
                else "💀" if player["fighter"]["hp"] <= 0 else "⚔️"
            )
            text += f"\n{mark} {names[key]} · {player['fighter']['hp']} HP"
            reward = data["rewards"].get(key)
            if reward:
                text += f" · +{reward['francs']} ₣ · +{reward['xp']} XP"
                if reward.get("full_reward") is False:
                    text += " · повторная награда 20%"
                if reward["loot"]:
                    text += " · 📜 " + html.escape(reward["loot"])
                if reward.get("forge_seal"):
                    text += " · ⚒️ печать босса +1"
        if row["status"] == "active":
            text += "\n\nВсе выбирают одновременно. На выбор — 2 минуты. Зрители тоже могут открыть рейд."
        return text

    async def changed(self, token):
        async with self.lock:
            loop = asyncio.get_running_loop()
            if self.retry_at.get(token, 0) > loop.time():
                return
            row = await self.db.arena_raid_get(token)
            if not row["message_id"]:
                return
            signature = self.signature(row)
            if self.signatures.get(token) == signature:
                self.retry_at.pop(token, None)
                return
            await asyncio.sleep(max(0, 0.5 - (loop.time() - self.last_edit)))
            # Readiness can change while rate-limiting chat edits. Publish the
            # latest snapshot rather than an older lobby/round.
            row = await self.db.arena_raid_get(token)
            signature = self.signature(row)
            try:
                await self.bot.edit_message_text(
                    await self.body(row),
                    chat_id=row["chat_id"],
                    message_id=row["message_id"],
                    parse_mode="HTML",
                    reply_markup=self.keyboard(row),
                )
                self.signatures[token] = signature
                self.retry_at.pop(token, None)
                if len(self.signatures) > 1000:
                    self.signatures.pop(next(iter(self.signatures)))
            except TelegramRetryAfter as error:
                self.retry_at[token] = loop.time() + error.retry_after + 1
                logging.warning("Raid edit throttled; retry in %s s", error.retry_after)
            except TelegramAPIError as error:
                self.retry_at.pop(token, None)
                if "message is not modified" in str(error):
                    self.signatures[token] = signature
                else:
                    logging.warning("Could not update raid message: %s", error)
            self.last_edit = loop.time()

    async def retry_pending(self):
        now = asyncio.get_running_loop().time()
        for token, due in list(self.retry_at.items()):
            if due <= now:
                await self.changed(token)


def create_raid_router(db, bot, enabled, publisher):
    router = Router(name="raids")
    encounter_lock = asyncio.Lock()

    async def encounter_command(message):
        if not message.from_user or message.from_user.is_bot:
            return
        if not enabled:
            await message.answer('Арена отключена: нужно настроить WEBAPP_URL.')
            return
        if message.chat.type not in {'group', 'supergroup'}:
            await message.answer('Создай РП-встречу в группе: /встреча гоблин 2, шаман или /встреча название своего моба. Свои мобы — в /рп → Мои мобы. Мастер не вступает автоматически; награды отключены.')
            return
        try:
            from arena_encounters import parse_named_roster
            match = ENCOUNTER_RE.fullmatch(message.text or message.caption or '')
            await require_member(bot, message.chat.id, message.from_user.id)
            templates = await db.arena_rp_templates(message.from_user.id)
            roster = parse_named_roster(match.group('roster') or '', templates)
            async with encounter_lock:
                if any(item['kind'] == 'mob' for item in roster):
                    nonce = hashlib.sha256(f'encounter:{message.chat.id}:{message.message_id}'.encode()).hexdigest()
                    row = await db.arena_rp_encounter_create(message.chat.id, message.from_user.id, roster, nonce)
                    if row['status'] != 'lobby' or row['message_id'] is not None:
                        return  # A redelivered Telegram message must not publish a second lobby.
                else:
                    row = await db.arena_encounter_create(message.chat.id, message.from_user.id, [item['id'] for item in roster])
                try:
                    sent = await message.answer(await publisher.body(row), parse_mode='HTML', reply_markup=publisher.keyboard(row))
                    await db.arena_raid_set_message(row['token'], sent.message_id)
                except Exception:
                    await db.arena_raid_setup(row['token'], message.from_user.id, 'cancel')
                    raise
        except ValueError as error:
            await message.answer(str(error))

    @router.message(text_or_caption_regexp(RAID_RE))
    async def raid_command(message):
        if not message.from_user or message.from_user.is_bot:
            return
        if not enabled:
            await message.answer("Арена отключена: нужно настроить WEBAPP_URL.")
            return
        if message.chat.type not in {"group", "supergroup"}:
            await message.answer(
                "Для рейда без сообщений в группу: отправь /menu@GnidoBot в ЛС боту → Арена → Рейды → Создать тихий рейд. "
                "Для публичного сбора отряда используй /рейд в чате."
            )
            return
        try:
            await require_member(bot, message.chat.id, message.from_user.id)
            match = RAID_RE.fullmatch(
                getattr(message, "text", None)
                or getattr(message, "caption", None)
                or ""
            )
            row = await db.arena_raid_create(
                message.chat.id,
                message.from_user.id,
                raid_boss_id(match),
            )
            try:
                sent = await message.answer(
                    await publisher.body(row),
                    parse_mode="HTML",
                    reply_markup=publisher.keyboard(row),
                )
                await db.arena_raid_set_message(row["token"], sent.message_id)
            except Exception:
                await db.arena_raid_setup(row["token"], message.from_user.id, "cancel")
                raise
        except ValueError as error:
            await message.answer(str(error))

    router.message.register(encounter_command, text_or_caption_regexp(ENCOUNTER_RE))

    @router.callback_query(F.data.startswith("rr:"))
    async def raid_callback(callback):
        if not enabled or not callback.message:
            await callback.answer()
            return
        try:
            _, action, token = callback.data.split(":", 2)
            row = await db.arena_raid_get(token)
            if callback.message.chat.id != row["chat_id"]:
                raise ValueError("Рейд относится к другому чату.")
            member = await require_member(bot, row["chat_id"], callback.from_user.id)
            if member.user.is_bot:
                raise ValueError("Боты не участвуют в рейдах.")
            if action == "start":
                for p in row["participants"]:
                    for user in {p["actor_id"], p["fighter_id"]}:
                        member = await require_member(bot, row["chat_id"], user)
                        if member.user.is_bot:
                            raise ValueError("Боты не участвуют в рейдах.")
            # Joining from the chat must not reset an already chosen slave.
            if action != "join" or not any(
                p["actor_id"] == callback.from_user.id for p in row["participants"]
            ):
                await db.arena_raid_setup(
                    token,
                    callback.from_user.id,
                    action,
                    expected_revision=row["revision"] if action == "start" else None,
                )
            await callback.answer(
                "Готово. Выбрать бойца и играть можно в «Открыть рейд»."
            )
            await publisher.changed(token)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)

    return router
