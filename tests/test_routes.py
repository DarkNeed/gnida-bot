import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User

from handlers.routes import (
    BASEMENT_RE,
    FEMBOY_RE,
    HUILO_RE,
    IMMUNITY_TEXT,
    KARGASTAN_RE,
    LEGS_RE,
    JOKE_COOLDOWN_SECONDS,
    MAKE_SLAVE_RE,
    MAKE_SLAVE_REPLY_RE,
    METAL_RASCALS_RE,
    MODERATION_RE,
    CLEAR_RE,
    RESTORE_RE,
    SAFEBOORU_TAGS,
    STATS_RE,
    TRANSFER_RE,
    resolve_target,
    select_safebooru_post,
    user_is_immune,
)


class RoutePatternTests(unittest.TestCase):
    def test_joke_cooldown_is_two_minutes(self):
        self.assertEqual(JOKE_COOLDOWN_SECONDS, 120)

    def test_moderation_accepts_bang_prefix(self):
        self.assertTrue(MODERATION_RE.match("!мут @user 1 минута причина"))
        self.assertTrue(MODERATION_RE.match("!бан @user причина"))
        self.assertTrue(MODERATION_RE.match("!пред @user причина"))

    def test_stats_accepts_both_names_and_prefixes(self):
        self.assertTrue(STATS_RE.match("!стата @user"))
        self.assertTrue(STATS_RE.match("/стат @user"))

    def test_restore_and_reputation_commands(self):
        self.assertTrue(RESTORE_RE.match("/разбан @user"))
        self.assertTrue(RESTORE_RE.match("!размут @user"))
        self.assertTrue(CLEAR_RE.match("/снять преды @user"))
        self.assertTrue(CLEAR_RE.match("/снять обвинения @user"))
        self.assertTrue(CLEAR_RE.match("/очистить репутацию @user"))

    def test_new_joke_phrases_are_case_insensitive(self):
        self.assertTrue(HUILO_RE.match("ХУЙЛО"))
        self.assertTrue(FEMBOY_RE.match("Дима фембой"))
        self.assertTrue(BASEMENT_RE.match("Забрать в Подвалград"))
        self.assertTrue(BASEMENT_RE.match("В подвалград"))

    def test_special_command_phrases(self):
        command = (
            "Пусть звенят позолоченные кранчики самоваров 8 народов. "
            "Божественный ебатель самоваров @Kit_kitovich23.\n"
            "Выеби эту ньюху за Каргастан"
        )
        self.assertTrue(KARGASTAN_RE.match(command))
        self.assertTrue(LEGS_RE.match("Скинь ножки"))

    def test_slave_management_commands(self):
        self.assertTrue(TRANSFER_RE.match("/передать @slave @owner"))
        self.assertTrue(MAKE_SLAVE_RE.match("/сделать @user1 рабом @user2"))
        self.assertTrue(MAKE_SLAVE_REPLY_RE.match("/сделать рабом @owner"))

    def test_metal_rascals_command(self):
        self.assertTrue(METAL_RASCALS_RE.match("Металлические поганцы"))
        self.assertEqual(SAFEBOORU_TAGS, "murder_drones rating:safe")

    def test_safebooru_selector_keeps_only_safe_static_art(self):
        post = select_safebooru_post(
            {
                "post": [
                    {"id": 1, "rating": "e", "file_url": "https://x/unsafe.jpg"},
                    {"id": 2, "rating": "s", "file_url": "https://x/video.webm"},
                    {"id": 3, "rating": "safe", "sample_url": "//x/art.jpg"},
                ]
            }
        )
        self.assertEqual(post["id"], 3)
        self.assertEqual(post["selected_url"], "https://x/art.jpg")

    def test_kit_is_immune_case_insensitively(self):
        user = User(id=77, is_bot=False, first_name="Kit", username="KIT_Kitovich23")
        self.assertTrue(user_is_immune(user))
        self.assertIn("@Kit_kitovich23", IMMUNITY_TEXT)


class TargetResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_spaced_reply_duration_is_not_treated_as_user_id(self):
        replied_user = User(id=42, is_bot=False, first_name="Сон")
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            reply_to_message=SimpleNamespace(from_user=replied_user, sender_chat=None),
            answer=AsyncMock(),
        )
        database = SimpleNamespace(upsert_user=AsyncMock(), resolve_user=AsyncMock())

        target = await resolve_target(message, database, "1 минута")

        self.assertEqual(target, (42, "Сон", "1 минута"))
        database.resolve_user.assert_not_awaited()

    async def test_username_can_override_reply_target(self):
        replied_user = User(id=42, is_bot=False, first_name="Сон")
        row = {"user_id": 99, "display_name": "Другой"}
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            reply_to_message=SimpleNamespace(from_user=replied_user, sender_chat=None),
            answer=AsyncMock(),
        )
        database = SimpleNamespace(upsert_user=AsyncMock(), resolve_user=AsyncMock(return_value=row))

        target = await resolve_target(message, database, "@other причина")

        self.assertEqual(target, (99, "Другой", "причина"))


if __name__ == "__main__":
    unittest.main()
