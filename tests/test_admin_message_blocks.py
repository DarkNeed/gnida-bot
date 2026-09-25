import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User

from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database
from handlers.admin_message_blocks import (
    ADMIN_BLOCK_COMMAND,
    BlockedAdminMessage,
    create_admin_message_block_router,
)


CHAT_ID = -100123
BOT_ID = 9000
ADMIN_ID = 7000


class AdminMessageBlockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.folder.name) / "admin-blocks.sqlite3")
        await self.database.connect()
        await self.database.upsert_chat(CHAT_ID, "Каргассия")
        self.owner = User(id=CUSTOM_COMMAND_OWNER_ID, is_bot=False, first_name="Владелец")
        self.admin = User(id=ADMIN_ID, is_bot=False, first_name="Админ", username="active_admin")
        self.bot_member = SimpleNamespace(status="administrator", can_delete_messages=True)
        self.admin_member = SimpleNamespace(status="administrator", user=self.admin)
        self.bot = SimpleNamespace(id=BOT_ID, get_chat_member=AsyncMock(), delete_message=AsyncMock())

        async def get_chat_member(chat_id, user_id):
            self.assertEqual(chat_id, CHAT_ID)
            return self.bot_member if user_id == BOT_ID else self.admin_member

        self.bot.get_chat_member.side_effect = get_chat_member

    async def asyncTearDown(self):
        await self.database.close()
        self.folder.cleanup()

    def command_message(self, text, *, private=False, reply=None, sender=None):
        return SimpleNamespace(
            text=text,
            chat=SimpleNamespace(
                id=CUSTOM_COMMAND_OWNER_ID if private else CHAT_ID,
                type="private" if private else "supergroup",
            ),
            from_user=sender or self.owner,
            reply_to_message=reply,
            answer=AsyncMock(),
        )

    def command_handler(self, *, private_chat_id=CHAT_ID):
        router = create_admin_message_block_router(
            self.database, kargassia_chat_id=private_chat_id
        )
        return next(
            entry.callback for entry in router.message.handlers
            if entry.callback.__name__ == "change_admin_block"
        )

    async def test_group_reply_blocks_new_text_media_and_edits_until_unblocked(self):
        handler = self.command_handler()
        reply = SimpleNamespace(from_user=self.admin, sender_chat=None)
        command = self.command_message("/банадмин", reply=reply)
        self.assertIsNotNone(ADMIN_BLOCK_COMMAND.fullmatch(command.text))
        await handler(command, self.bot)
        self.assertTrue(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))

        blocked_filter = BlockedAdminMessage(self.database)
        media = SimpleNamespace(
            chat=SimpleNamespace(id=CHAT_ID, type="supergroup"),
            from_user=self.admin, sender_chat=None, message_id=101, photo=[object()],
        )
        self.assertTrue(await blocked_filter(media))
        router = create_admin_message_block_router(self.database)
        delete = next(
            entry.callback for entry in router.message.handlers
            if entry.callback.__name__ == "delete_blocked_admin_message"
        )
        self.assertTrue(any(
            entry.callback.__name__ == "delete_blocked_admin_message"
            for entry in router.edited_message.handlers
        ))
        await delete(media, self.bot)
        self.bot.delete_message.assert_awaited_once_with(CHAT_ID, 101)

        unban = self.command_message("/разбанадмин @active_admin")
        await handler(unban, self.bot)
        self.assertFalse(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))
        self.assertFalse(await blocked_filter(media))

    async def test_private_tag_targets_configured_chat_and_persists(self):
        await self.database.upsert_user(CHAT_ID, ADMIN_ID, self.admin.username, self.admin.full_name)
        handler = self.command_handler()
        command = self.command_message("/банадмин @active_admin", private=True)
        await handler(command, self.bot)
        self.assertTrue(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))
        self.assertFalse(await self.database.admin_messages_blocked(-200, ADMIN_ID))
        await self.database.close()
        await self.database.connect()
        self.assertTrue(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))
        unban = self.command_message("/разбанадмин @active_admin", private=True)
        await handler(unban, self.bot)
        self.assertFalse(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))

    async def test_only_owner_can_change_list_and_bot_needs_delete_rights(self):
        handler = self.command_handler()
        reply = SimpleNamespace(from_user=self.admin, sender_chat=None)
        stranger = User(id=42, is_bot=False, first_name="Чужой")
        command = self.command_message("/банадмин", reply=reply, sender=stranger)
        await handler(command, self.bot)
        self.assertFalse(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))
        self.bot_member.can_delete_messages = False
        command.from_user = self.owner
        await handler(command, self.bot)
        self.assertFalse(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))
        self.assertIn("нет права", command.answer.await_args.args[0])

    async def test_regular_member_cannot_be_added(self):
        self.admin_member.status = "member"
        command = self.command_message(
            "/банадмин", reply=SimpleNamespace(from_user=self.admin, sender_chat=None)
        )
        await self.command_handler()(command, self.bot)
        self.assertFalse(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))
        self.assertIn("не администратор", command.answer.await_args.args[0])

    async def test_stale_username_cannot_target_wrong_account(self):
        stale = User(id=100, is_bot=False, first_name="Бывший", username="new_name")
        await self.database.upsert_user(CHAT_ID, stale.id, "active_admin", stale.full_name)
        await self.database.upsert_user(CHAT_ID, ADMIN_ID, "active_admin", self.admin.full_name)

        async def get_chat_member(chat_id, user_id):
            if user_id == BOT_ID:
                return self.bot_member
            if user_id == stale.id:
                return SimpleNamespace(status="administrator", user=stale)
            return self.admin_member

        self.bot.get_chat_member.side_effect = get_chat_member
        await self.command_handler()(self.command_message("/банадмин @active_admin"), self.bot)
        self.assertTrue(await self.database.admin_messages_blocked(CHAT_ID, ADMIN_ID))
        self.assertFalse(await self.database.admin_messages_blocked(CHAT_ID, stale.id))

    async def test_anonymous_sender_cannot_be_attributed_to_blocked_admin(self):
        await self.database.block_admin_messages(CHAT_ID, ADMIN_ID, CUSTOM_COMMAND_OWNER_ID)
        anonymous = SimpleNamespace(
            chat=SimpleNamespace(id=CHAT_ID, type="supergroup"),
            from_user=self.admin, sender_chat=SimpleNamespace(id=CHAT_ID),
        )
        self.assertFalse(await BlockedAdminMessage(self.database)(anonymous))
