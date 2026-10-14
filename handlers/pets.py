"""Stars checkout is separate from gameplay: only confirmed payments grant tickets."""
import asyncio
import logging
import re
import sqlite3

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from arena_links import arena_link
from arena_pets import PET_TERMS_VERSION
from custom_commands import CUSTOM_COMMAND_OWNER_ID

PET_TERMS = (
    "Питомцы: условия покупки\n\n"
    "Покупаются билеты, а не конкретный питомец. 1 / 5 / 10 билетов стоят 25 / 110 / 200 Stars. "
    "Шансы редкостей: обычный 20%, редкий 50%, эпический 27%, легендарный 3%. "
    "Внутри редкости шансы одинаковые. После 9 открытий без эпического или легендарного следующий гарантирован; "
    "после 29 без легендарного следующий — легендарный. При эпической гарантии шансы 90% / 10%. "
    "Любое соответствующее выпадение сбрасывает свою гарантию. Купленные и бесплатные билеты равнозначны. "
    "Дубликаты дают 10 / 15 / 20 / 30 осколков. Питомцев можно получить бесплатно. "
    "Предметы не обмениваются на реальные деньги и не передаются между аккаунтами.\n\n"
    "Питомцы, ресурсы и экипированный спутник общие для аккаунта. "
    "Бонусы могут изменяться при балансировке. Результат сохраняется до показа анимации. "
    "При возврате оплаты билеты пакета вычитаются; если они потрачены, возникает долг билетов, "
    "и использование питомцев в новых боях приостанавливается до его погашения бесплатными или купленными билетами. "
    "Выпавшие питомцы сохраняются. Для вопросов и возврата: /paysupport, укажите номер заказа.\n\n"
    f"Версия: {PET_TERMS_VERSION}"
)


def create_pet_router(db, username, payments_enabled=False):
    router = Router(name="pet_payments")
    refund_lock = asyncio.Lock()

    @router.message(F.text.regexp(re.compile(r"^/(?:питомцы|pets)(?:@\w+)?\s*$", re.I)))
    async def pets(message):
        start = "pets" if message.chat.type == "private" else f"pets_{message.chat.id}"
        await message.answer("✦ Питомцы: коллекция, посылки, прокачка и магазин.", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть питомцев", url=arena_link(username, start))]]))

    @router.message(F.text.regexp(re.compile(r"^/terms(?:@\w+)?\s*$", re.I)))
    async def terms(message):
        await message.answer(PET_TERMS)

    @router.message(F.text.regexp(re.compile(r"^/paysupport(?:@\w+)?(?:\s.*)?$", re.I | re.S)))
    async def support(message):
        if message.chat.type != "private":
            await message.answer("По оплатам напишите /paysupport в личку боту.")
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2:
            try:
                await message.bot.send_message(CUSTOM_COMMAND_OWNER_ID,
                    f"Поддержка питомцев, покупатель {message.from_user.id}:\n{parts[1][:3000]}\n\n"
                    f"Ответ: /ответпокупателю {message.from_user.id} ТЕКСТ")
                await message.answer("Обращение передано владельцу. Ответ придёт сюда.")
            except TelegramAPIError:
                logging.exception("Could not deliver pet support request")
                await message.answer("Не удалось передать обращение. Используйте кнопку связи с владельцем ниже.")
        view = await db.pet_view(message.from_user.id)
        lines = [f"№{o['id']}: {o['tickets']} бил. / {o['stars']} Stars · {o['status']}" for o in view["orders"]]
        await message.answer("Поддержка оплат: /paysupport НОМЕР ЗАКАЗА И ОПИСАНИЕ ПРОБЛЕМЫ — передам обращение владельцу. Также можно написать по кнопке ниже.\n"
                             + ("Ваши последние заказы:\n" + "\n".join(lines) if lines else "Оплаченных заказов пока нет."),
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                                 text="Написать владельцу", url=f"tg://user?id={CUSTOM_COMMAND_OWNER_ID}")]]))

    @router.message(F.text.regexp(re.compile(r"^/ответпокупателю\s+\d+\s+.+$", re.I | re.S)))
    async def support_reply(message):
        if message.from_user.id != CUSTOM_COMMAND_OWNER_ID or message.chat.type != "private":
            return
        _, user, body = message.text.split(maxsplit=2)
        try:
            await message.bot.send_message(int(user), "Ответ поддержки питомцев:\n" + body[:3800])
            await message.answer("Ответ отправлен.")
        except TelegramAPIError:
            await message.answer("Не удалось доставить ответ. Возможно, пользователь заблокировал бота.")

    @router.pre_checkout_query(F.invoice_payload.startswith("pets_"))
    async def checkout(query):
        try:
            if not payments_enabled:
                raise ValueError("Продажи временно выключены.")
            await db.pet_check_order(query.from_user.id, query.invoice_payload, query.currency, query.total_amount)
        except ValueError as error:
            await query.answer(ok=False, error_message=str(error))
        else:
            await query.answer(ok=True)

    @router.message(F.successful_payment.invoice_payload.startswith("pets_"))
    async def payment(message):
        p = message.successful_payment
        try:
            # Process confirmed payments even if sales were switched off meanwhile.
            order = await db.pet_payment(message.from_user.id, p.invoice_payload, p.currency,
                                         p.total_amount, p.telegram_payment_charge_id)
        except (ValueError, sqlite3.IntegrityError):
            logging.exception("Pet payment needs reconciliation for user %s", message.from_user.id)
            issue = await db.pet_record_payment_issue(message.from_user.id, p.invoice_payload, p.currency,
                                                      p.total_amount, p.telegram_payment_charge_id)
            await message.answer(f"Оплата требует проверки. Сбой №{issue['id']}, данные сохранены; напишите /paysupport.")
            try:
                await message.bot.send_message(CUSTOM_COMMAND_OWNER_ID, f"Нужна проверка оплаты питомцев пользователя {message.from_user.id}, сбой №{issue['id']}. Возврат без начисленных билетов: /возвратсбояпитомцев {issue['id']}")
            except TelegramAPIError:
                logging.warning("Could not notify pet payment support")
            return
        if not order["replay"]:
            if order["status"] == "refunded":
                await message.answer(f"Заказ №{order['id']}: Telegram уже вернул оплату, билеты не начислены. Поддержка: /paysupport")
            else:
                await message.answer(f"✅ Заказ №{order['id']} оплачен. Начислено {order['tickets']} билетов. Питомцы: /питомцы\nПоддержка: /paysupport")

    @router.message(F.refunded_payment.invoice_payload.startswith("pets_"))
    async def refund_received(message):
        p = message.refunded_payment
        await db.pet_receive_refund(p.invoice_payload, p.currency, p.total_amount, p.telegram_payment_charge_id)

    @router.message(F.text.regexp(re.compile(r"^/(?:возвратпитомцев|подтвердитьвозвратпитомцев)\s+\d+\s*$", re.I)))
    async def refund(message):
        if message.from_user.id != CUSTOM_COMMAND_OWNER_ID or message.chat.type != "private":
            return
        order_id = int(message.text.split()[1])
        confirm = message.text.split()[0].lower() == "/подтвердитьвозвратпитомцев"
        async with refund_lock:
            try:
                if confirm:
                    await db.pet_finish_refund(order_id)
                    await message.answer("Возврат отмечен завершённым. Используйте подтверждение только после проверки возврата Stars в Telegram.")
                    return
                order = await db.pet_start_refund(order_id)
                if order["status"] == "refunded":
                    await message.answer("Этот заказ уже возвращён.")
                    return
                await message.bot.refund_star_payment(user_id=order["user_id"], telegram_payment_charge_id=order["charge_id"])
                await db.pet_finish_refund(order_id)
                await message.answer(f"Заказ №{order_id}: Stars возвращены, билеты вычтены.")
            except ValueError as error:
                await message.answer(str(error))
            except TelegramAPIError:
                logging.exception("Pet refund needs reconciliation: %s", order_id)
                await message.answer("Telegram не подтвердил возврат. Открытия для аккаунта приостановлены. Проверь статус платежа; повтори возврат или после проверки напиши /подтвердитьвозвратпитомцев НОМЕР.")

    @router.message(F.text.regexp(re.compile(r"^/возвратсбояпитомцев\s+\d+\s*$", re.I)))
    async def issue_refund(message):
        if message.from_user.id != CUSTOM_COMMAND_OWNER_ID or message.chat.type != "private":
            return
        async with refund_lock:
            try:
                issue = await db.pet_payment_issue(int(message.text.split()[1]))
                if issue["refunded_at"]:
                    await message.answer("Этот сбой уже возвращён.")
                    return
                await message.bot.refund_star_payment(user_id=issue["user_id"], telegram_payment_charge_id=issue["charge_id"])
                await db.pet_payment_issue_refunded(issue["id"])
                await message.answer("Оплата возвращена. Билеты не списаны: они не начислялись по этому платежу.")
            except ValueError as error:
                await message.answer(str(error))
            except TelegramAPIError:
                logging.exception("Pet payment issue refund needs reconciliation")
                await message.answer("Возврат не подтверждён. Проверь платёж в Telegram прежде чем повторять.")

    return router
