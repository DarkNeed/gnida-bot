"""Compact Telegram pages; every enterprise has its own stable detail ID."""

import html
from aiogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup

PERIODS = {"day": "Вчера", "week": "Неделя", "all": "Всё время"}


def link(user, name):
    return f'<a href="tg://user?id={user}">{html.escape(str(name)[:80])}</a>'


async def enterprise_top_view(db, chat, actor=None, *, kind="owners", period="week", page=0, mine=False):
    data = await db.enterprise_leaderboard(chat, kind=kind, period=period, page=page, actor=actor, mine=mine)
    heading = "Владельцы · после налога" if kind == "owners" else "Предприятия · до налога"
    body = [f"<b>🏆 Топ предприятий · {PERIODS[period]}</b>", heading,
        "Только завершённые дни (МСК). Не баланс кошелька.", ""]
    buttons = []
    for row in data["entries"]:
        name = row["name"]
        tail = f' · {row["sites"]} предпр. · {row["workers"]} работников' if kind == "owners" else f' · {html.escape(row["owner_name"][:40])}' + (" · закрыто" if row["closed"] else "")
        body.append(f'<b>{row["place"]}.</b> {html.escape(str(name)[:60])} — <b>{row["amount"]} ₣</b>{tail}')
        detail = "owner" if kind == "owners" else "site"
        buttons.append([Button(text=f'{row["place"]}. {name} · {row["amount"]} ₣'[:60],
            callback_data=f'es:{chat}:{detail}:{row["id"]}:{period}')])
    if not data["entries"]:
        body.append("Пока нет предприятий и учтённых доходов.")
    if data["own"]:
        own = data["own"]
        body.append(f'\nТвоё место: <b>{own["place"]}</b> · {own["amount"]} ₣' + (" (лучшее предприятие)" if kind == "sites" else ""))
    body.append(f'\nСтраница {data["page"] + 1}/{data["pages"]}. Нажми на строку для подробностей.')
    buttons += [[Button(text=("✓ " if kind == tab else "") + label, callback_data=f"es:{chat}:top:{tab}:{period}:0")
        for tab, label in (("owners", "Владельцы"), ("sites", "Предприятия"))]]
    buttons += [[Button(text=("✓ " if period == value else "") + label,
        callback_data=f"es:{chat}:top:{kind}:{value}:0") for value, label in PERIODS.items()]]
    navigation = []
    if data["page"]:
        navigation.append(Button(text="←", callback_data=f'es:{chat}:top:{kind}:{period}:{data["page"] - 1}'))
    navigation.append(Button(text="Моё место", callback_data=f"es:{chat}:top:{kind}:{period}:me"))
    if data["page"] + 1 < data["pages"]:
        navigation.append(Button(text="→", callback_data=f'es:{chat}:top:{kind}:{period}:{data["page"] + 1}'))
    buttons.append(navigation)
    return "\n".join(body), Markup(inline_keyboard=buttons)


async def enterprise_owner_view(db, chat, owner, period="week"):
    snapshot = await db.enterprise_leaderboard(chat, period=period)
    entry = next((r for r in snapshot["all_entries"] if r["id"] == owner), None)
    if entry is None:
        return None
    # Keep the established historical labels and tax ledger; this also works
    # for owners whose last enterprise has already closed.
    totals = await db.enterprise_owner_periods(chat, owner)
    yesterday, week = totals["day"]["net"], totals["week"]["net"]
    yesterday_tax, week_tax = totals["day"]["tax"], totals["week"]["tax"]
    sites = await db.enterprise_leaderboard(chat, kind="sites", period=period)
    owned = [r for r in sites["all_entries"] if r["owner_id"] == owner]
    body = (f'<b>🏭 Предприятия владельца</b>\n{link(owner, entry["name"])}\n'
        f'Место: {entry["place"]} · {PERIODS[period]}: <b>{entry["amount"]} ₣</b> после налога\n'
        f'Открытых предприятий: {entry["sites"]} · работников: {entry["workers"]}\n\n'
        f'💰 Доход после налога вчера: <b>{yesterday} ₣</b> (налог {yesterday_tax} ₣)\n'
        f'📈 Доход после налога за 7 завершённых дней: <b>{week} ₣</b> (налог {week_tax} ₣)\n\n'
        'Выбери конкретное предприятие. Доход закрытых остаётся в истории владельца.\n'
        'История считается с момента подключения соответствующего учёта.')
    buttons = [[Button(text=("Закрыто · " if s["closed"] else "") + s["name"][:45],
        callback_data=f'es:{chat}:site:{s["id"]}:{period}')] for s in owned[:10]]
    buttons.append([Button(text="← Топ владельцев", callback_data=f"es:{chat}:top:owners:{period}:0")])
    return body, Markup(inline_keyboard=buttons)


async def enterprise_site_view(db, chat, site_id, period="week"):
    snapshot = await db.enterprise_leaderboard(chat, kind="sites", period=period)
    row = next((r for r in snapshot["all_entries"] if r["id"] == site_id), None)
    if row is None:
        return None
    from enterprises import CATALOG
    body = (f'<b>{html.escape(row["name"])}</b>\n'
        f'Владелец: {link(row["owner_id"], row["owner_name"])}\n'
        f'{html.escape(CATALOG[row["business_type"]]["name"])} · уровень {row["level"]}'
        + (" · закрыто" if row["closed"] else f' · работников {row["workers"]}/{row["capacity"]}')
        + f'\n\n{PERIODS[period]} · место {row["place"]}\n'
        f'Доход до налога: <b>{row["amount"]} ₣</b>\n'
        f'После налога: {row["net"]} ₣ · налог: {row["tax"]} ₣\n\n'
        + html.escape(row.get("description", ""))
        + '\nВ топе заведений сравнивается доход до налога: налог зависит от всего хозяйства владельца.')
    return body, Markup(inline_keyboard=[
        [Button(text="Предприятия владельца", callback_data=f'es:{chat}:owner:{row["owner_id"]}:{period}')],
        [Button(text="← Топ предприятий", callback_data=f"es:{chat}:top:sites:{period}:0")]])


def arena_top_view(data, chat):
    body = [f'<b>⚔️ Топ арены · {data["season"]}</b>',
        "Все чаты · один рейтинг на аккаунт" + (" · сезон завершён" if data["archived"] else ""), ""]
    for row in data["entries"]:
        body.append(f'{row["place"]}. {link(row["actor_id"], row["name"])} — <b>{row["rating"]}</b> '
                    f'· {row["wins"]}П / {row["losses"]}Пор / {row["draws"]}Н'
                    + (" · " + row["title"] if row["title"] else ""))
    if not data["entries"]:
        body.append("Пока никто не завершил пять учтённых боёв калибровки.")
    own = data["own"]
    body.append(f'\nТы: {own["rating"]} · ' + (f'место {own["place"]}' if own["place"] else f'калибровка {min(own["games"], 5)}/5'))
    body.append(f'Страница {data["page"] + 1}/{data["pages"]}.\n\n'
        'Вызов: /рейт @участник или ответом /рейт. Без ставок.\n'
        'Обычные бои рейтинг не меняют. Одна учтённая встреча пары за 24 часа, до 10 в сутки (МСК).\n'
        'Сдача — поражение. За соперника без действий нет очков победителю. '
        'В рейтинге три пропуска подряд означают поражение. Каждый месяц — новый сезон; старые результаты сохраняются.')
    nav = []
    if data["page"]:
        nav.append(Button(text="←", callback_data=f'alt:{chat}:{data["season"]}:{data["page"] - 1}'))
    nav.append(Button(text="Моё место", callback_data=f'alt:{chat}:{data["season"]}:me'))
    if data["page"] + 1 < data["pages"]:
        nav.append(Button(text="→", callback_data=f'alt:{chat}:{data["season"]}:{data["page"] + 1}'))
    buttons = [nav]
    index = data["seasons"].index(data["season"])
    seasons = []
    if index + 1 < len(data["seasons"]):
        seasons.append(Button(text="← Прошлый сезон", callback_data=f'alt:{chat}:{data["seasons"][index + 1]}:0'))
    if data["archived"]:
        seasons.append(Button(text="Текущий сезон", callback_data=f'alt:{chat}:{data["current_season"]}:0'))
    if seasons:
        buttons.append(seasons)
    return "\n".join(body), Markup(inline_keyboard=buttons)
