"""A siege cannot start before its warning was accepted by Telegram."""
import asyncio
from html import escape
import logging


async def publish_kingdom_notices(db,bot):
    await db.kingdom_siege_sweep()
    for notice in await db.kingdom_siege_notices():
        try:
            await asyncio.wait_for(bot.send_message(notice['chat'],
                '⚔️ Объявлена осада!\n\n'
                f"{escape(notice['attacker'])} атакует пограничную землю {notice['q']}:{notice['r']} владения «{escape(notice['defender'])}».\n"
                f"<a href=\"tg://user?id={notice['owner']}\">Правитель-защитник</a>, до боя сутки с доставки этого предупреждения. "
                'Открой /карта → Войны: подготовь строй и оборонительную тактику.\n\n'
                'Столица не захватывается. Сам бой займёт ещё 6 часов; после него действует защита от повторных нападений.',
                parse_mode='HTML'),timeout=8)
        except Exception:
            # No warning delivery -> no battle clock. At most three attempts,
            # five minutes apart; the pending order expires with a refund.
            logging.warning('Kingdom siege warning unavailable: %s',notice['id'])
            continue
        await db.kingdom_siege_announced(notice['id'])
