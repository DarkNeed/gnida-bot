import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import Chat, Message, PhotoSize, User

from handlers.routes import (
    BASEMENT_RE,
    BASEMENT_LIST_RE,
    BASEMENT_RELEASE_RE,
    DUCK_RE,
    DUCK_SLAPS_RE,
    DERMODEMOON_COOLDOWN_SECONDS,
    FEMBOY_RE,
    GNIDA_RE,
    HUILO_RE,
    HEAVENLY_PUNISHMENT_RE,
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
    SILENCE_RE,
    SLAP_RE,
    SLEEP_RE,
    STATS_RE,
    TRANSFER_RE,
    TrackingMiddleware,
    ART_THEFT_RE,
    basement_kick_allowed,
    dermodemoon_announcement_available,
    message_content,
    message_has_image,
    silence_duration_seconds,
    resolve_target,
    select_safebooru_post,
    text_or_caption_regexp,
    is_chat_participant,
    user_is_immune,
)


class RoutePatternTests(unittest.TestCase):
    def test_leg_request_accepts_any_image_message(self):
        empty = {
            "photo": None,
            "document": None,
            "sticker": None,
            "animation": None,
        }
        self.assertTrue(
            message_has_image(SimpleNamespace(**(empty | {"photo": [object()]})))
        )
        self.assertTrue(
            message_has_image(
                SimpleNamespace(
                    **(
                        empty
                        | {
                            "document": SimpleNamespace(mime_type="image/png"),
                        }
                    )
                )
            )
        )
        self.assertTrue(
            message_has_image(SimpleNamespace(**(empty | {"sticker": object()})))
        )
        self.assertTrue(
            message_has_image(SimpleNamespace(**(empty | {"animation": object()})))
        )
        self.assertFalse(
            message_has_image(
                SimpleNamespace(
                    **(
                        empty
                        | {
                            "document": SimpleNamespace(mime_type="video/mp4"),
                        }
                    )
                )
            )
        )

    def test_basement_admins_can_be_slapped_but_never_kicked(self):
        self.assertFalse(basement_kick_allowed("administrator"))
        self.assertFalse(basement_kick_allowed("creator"))
        self.assertTrue(basement_kick_allowed("member"))

    def test_message_content_uses_text_or_media_caption(self):
        self.assertEqual(
            message_content(SimpleNamespace(text="обычное сообщение", caption=None)),
            "обычное сообщение",
        )
        self.assertEqual(
            message_content(SimpleNamespace(text=None, caption="подпись к видео")),
            "подпись к видео",
        )

    def test_command_filter_matches_text_and_media_caption(self):
        command_filter = text_or_caption_regexp(MODERATION_RE)
        self.assertTrue(
            command_filter.resolve(
                SimpleNamespace(text="!мут @user 1 минута", caption=None)
            )
        )
        self.assertTrue(
            command_filter.resolve(
                SimpleNamespace(text=None, caption="!мут @user 1 минута")
            )
        )
        self.assertFalse(
            command_filter.resolve(SimpleNamespace(text=None, caption="просто видео"))
        )

    def test_joke_cooldown_is_two_minutes(self):
        self.assertEqual(JOKE_COOLDOWN_SECONDS, 120)

    def test_dermodemoon_cooldown_is_one_day(self):
        self.assertEqual(DERMODEMOON_COOLDOWN_SECONDS, 24 * 60 * 60)
        cooldowns = {}
        self.assertTrue(
            dermodemoon_announcement_available(cooldowns, chat_id=-1001, now=100)
        )
        self.assertFalse(
            dermodemoon_announcement_available(
                cooldowns,
                chat_id=-1001,
                now=100 + DERMODEMOON_COOLDOWN_SECONDS - 1,
            )
        )
        self.assertTrue(
            dermodemoon_announcement_available(
                cooldowns,
                chat_id=-1001,
                now=100 + DERMODEMOON_COOLDOWN_SECONDS,
            )
        )

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

    def test_joke_keywords_work_inside_messages(self):
        self.assertTrue(GNIDA_RE.search("Интересно, кто гнида сегодня?"))
        self.assertTrue(HUILO_RE.search("А он точно хуйло какое-то"))
        self.assertTrue(FEMBOY_RE.search("Все знают, что Дима фембой сегодня"))
        self.assertTrue(DUCK_RE.search("Говорят, Утин член огромный"))

    def test_basement_management_phrases(self):
        self.assertTrue(BASEMENT_LIST_RE.match("/подвалград"))
        self.assertTrue(BASEMENT_RELEASE_RE.match("/отпустить из подвалграда @user"))
        self.assertTrue(SLAP_RE.match("Леща @user"))

    def test_personal_trigger_phrases(self):
        self.assertTrue(ART_THEFT_RE.search("Я спизжу этот арт"))
        self.assertTrue(ART_THEFT_RE.search("Уже спиздил"))
        self.assertTrue(HEAVENLY_PUNISHMENT_RE.match("Это кара небесная, сосунок!"))
        self.assertTrue(DUCK_SLAPS_RE.match("Давать леща 10 лет"))
        self.assertTrue(SLEEP_RE.match("Усыпить"))

    def test_dimon_silence_requires_caps_and_allows_stretched_phrase(self):
        self.assertTrue(SILENCE_RE.search("МОЛЧАТЬ"))
        self.assertTrue(SILENCE_RE.search("МОЛЧАТЬ!!!!!!"))
        self.assertTrue(SILENCE_RE.search("ну всё, МОЛЧААААААААТЬ!!!!"))
        self.assertTrue(SILENCE_RE.search("МОЛЧАААААААААТЬ ТВАРЬ!!!!"))
        self.assertTrue(SILENCE_RE.search("ЗАТКНИСЬ"))
        self.assertTrue(SILENCE_RE.search("да всё, ЗАТКНИИИИИИСЬ!!!!!!"))
        self.assertTrue(SILENCE_RE.search("ЗАААТТККНИИИССЬЬЬ!!!!"))
        self.assertFalse(SILENCE_RE.search("Молчать"))
        self.assertFalse(SILENCE_RE.search("молчааааать тварь"))
        self.assertFalse(SILENCE_RE.search("Заткнись"))
        self.assertFalse(SILENCE_RE.search("заткниииись"))

    def test_each_silence_word_adds_three_minutes(self):
        self.assertEqual(silence_duration_seconds("МОЛЧАТЬ"), 180)
        self.assertEqual(silence_duration_seconds("МОЛЧААААТЬ!!!!!!"), 180)
        self.assertEqual(silence_duration_seconds("МОЛЧАТЬ ЗАТКНИСЬ"), 360)
        self.assertEqual(
            silence_duration_seconds("ЗАТКНИИИИСЬ, МОЛЧАТЬ! ЗАТКНИСЬ!"),
            540,
        )
        self.assertEqual(silence_duration_seconds("молчать Заткнись"), 0)

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
    async def test_tracking_middleware_completes_request_for_plain_photo(self):
        database = SimpleNamespace(
            upsert_chat=AsyncMock(),
            upsert_user=AsyncMock(),
            complete_leg_requests=AsyncMock(return_value=1),
        )
        handler = AsyncMock(return_value="handled")
        photo = Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=-1001, type="supergroup", title="Тест"),
            from_user=User(id=42, is_bot=False, first_name="Участник"),
            photo=[
                PhotoSize(
                    file_id="photo-id",
                    file_unique_id="unique-photo-id",
                    width=100,
                    height=100,
                )
            ],
        )

        result = await TrackingMiddleware(database)(handler, photo, {})

        self.assertEqual(result, "handled")
        database.complete_leg_requests.assert_awaited_once_with(-1001, 42)

    async def test_own_bot_can_be_selected_when_explicitly_allowed(self):
        replied_bot = User(id=777, is_bot=True, first_name="Гнида-бот")
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            reply_to_message=SimpleNamespace(from_user=replied_bot, sender_chat=None),
            answer=AsyncMock(),
        )
        database = SimpleNamespace(upsert_user=AsyncMock(), resolve_user=AsyncMock())

        target = await resolve_target(
            message, database, "", allowed_bot_id=replied_bot.id
        )

        self.assertEqual(target, (777, "Гнида-бот", ""))
        database.upsert_user.assert_awaited_once()

    async def test_users_who_left_are_not_chat_participants(self):
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="left"))
        )
        self.assertFalse(await is_chat_participant(bot, -1001, 42))

    async def test_restricted_non_member_is_not_chat_participant(self):
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(
                return_value=SimpleNamespace(status="restricted", is_member=False)
            )
        )
        self.assertFalse(await is_chat_participant(bot, -1001, 42))

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
