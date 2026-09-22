import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.types import User

from database import Database
from handlers.routes import TOP_DONORS_RE, create_router


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self.payload


class FakeYooKassaSession:
    def __init__(self, payment_status="succeeded", *, valid=True):
        self.payment_status = payment_status
        self.valid = valid
        self.posts = []
        self.gets = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({
            "id": "test-payment-1",
            "confirmation": {"confirmation_url": "https://yookassa.ru/pay/test"},
        })

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return FakeResponse({
            "id": "test-payment-1",
            "status": self.payment_status,
            "amount": {"value": "50.00" if self.valid else "500.00", "currency": "RUB"},
            "metadata": {"kind": "donation", "telegram_user_id": "10"},
        })


class DonationTests(unittest.IsolatedAsyncioTestCase):
    def test_command_accepts_requested_spelling_and_latin_alias(self):
        self.assertIsNotNone(TOP_DONORS_RE.fullmatch("/топ донатеров"))
        self.assertIsNotNone(TOP_DONORS_RE.fullmatch("/top_donors"))

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "donations.sqlite3")
        await self.database.connect()

    async def asyncTearDown(self):
        await self.database.close()
        self.temp_dir.cleanup()

    async def test_pending_payment_is_not_ranked_and_confirmed_payment_is_counted_once(self):
        await self.database.record_donation_payment(
            "payment-1", 10, 5000, "donor", "Донор",
        )
        await self.database.close()
        await self.database.connect()
        self.assertEqual(await self.database.top_donors(), [])
        self.assertTrue(await self.database.set_donation_status("payment-1", "succeeded"))
        self.assertFalse(await self.database.set_donation_status("payment-1", "succeeded"))
        await self.database.record_donation_payment(
            "payment-1", 10, 5000, "donor", "Донор",
        )
        await self.database.record_donation_payment(
            "payment-2", 10, 10000, "donor", "Донор",
        )
        await self.database.set_donation_status("payment-2", "canceled")
        await self.database.record_donation_payment(
            "payment-3", 20, 15000, "big_donor", "Щедрый",
        )
        await self.database.set_donation_status("payment-3", "succeeded")
        donors = await self.database.top_donors()
        self.assertEqual([row["user_id"] for row in donors], [20, 10])
        self.assertEqual(donors[1]["total_kopecks"], 5000)
        self.assertEqual(donors[1]["payment_count"], 1)

    async def test_payment_link_is_saved_then_verified_for_top_command(self):
        router = create_router(
            self.database, yookassa_shop_id="shop", yookassa_secret_key="secret",
        )
        menu_handler = next(
            item.callback for item in router.callback_query.handlers
            if item.callback.__name__ == "slave_menu_callback"
        )
        top_handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "top_donors"
        )
        user = User(id=10, is_bot=False, first_name="Донор", username="donor")
        menu_message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            edit_text=AsyncMock(), answer=AsyncMock(),
        )
        callback = SimpleNamespace(
            from_user=user, message=menu_message,
            data="sm:donate:50", answer=AsyncMock(),
        )
        session = FakeYooKassaSession()
        with patch("handlers.routes.aiohttp.ClientSession", return_value=session):
            await menu_handler(callback, SimpleNamespace())
            pending = await self.database.pending_donations()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["amount_kopecks"], 5000)
            self.assertEqual(await self.database.top_donors(), [])

            top_message = SimpleNamespace(
                from_user=user, chat=SimpleNamespace(type="private"),
                answer=AsyncMock(),
            )
            await top_handler(top_message)
            self.assertIn("donor — 50 ₽", top_message.answer.await_args.args[0])
            self.assertEqual(len(session.posts), 1)
            self.assertEqual(len(session.gets), 1)
            self.assertEqual(await self.database.pending_donations(), [])
            await top_handler(top_message)
            self.assertEqual(len(session.gets), 1)

    async def test_mismatched_provider_amount_does_not_count(self):
        await self.database.record_donation_payment(
            "test-payment-1", 10, 5000, "donor", "Донор",
        )
        router = create_router(
            self.database, yookassa_shop_id="shop", yookassa_secret_key="secret",
        )
        top_handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "top_donors"
        )
        message = SimpleNamespace(
            from_user=User(id=10, is_bot=False, first_name="Донор"),
            chat=SimpleNamespace(type="private"), answer=AsyncMock(),
        )
        with patch(
            "handlers.routes.aiohttp.ClientSession",
            return_value=FakeYooKassaSession(valid=False),
        ):
            await top_handler(message)
        self.assertIn("Донатов пока нет", message.answer.await_args.args[0])
        self.assertEqual(len(await self.database.pending_donations()), 1)

    async def test_canceled_provider_payment_is_removed_from_pending_without_ranking(self):
        await self.database.record_donation_payment(
            "test-payment-1", 10, 5000, "donor", "Донор",
        )
        router = create_router(
            self.database, yookassa_shop_id="shop", yookassa_secret_key="secret",
        )
        top_handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "top_donors"
        )
        message = SimpleNamespace(
            from_user=User(id=10, is_bot=False, first_name="Донор"),
            chat=SimpleNamespace(type="supergroup"), answer=AsyncMock(),
        )
        with patch(
            "handlers.routes.aiohttp.ClientSession",
            return_value=FakeYooKassaSession(payment_status="canceled"),
        ):
            await top_handler(message)
        self.assertIn("Донатов пока нет", message.answer.await_args.args[0])
        self.assertEqual(await self.database.pending_donations(), [])
