"""Notifications/invitations; retries never create another economic event."""
import html
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError
from arena_links import arena_link
from enterprise_protection import EVENTS


async def publish_protection(db,bot,username,publisher):
    if not username:return
    for e in await db.protection_notifications():
        try:
            if e['raid']:
                row=await db.arena_raid_get(e['raid'])
                if row['message_id'] or row['status']!='lobby':
                    await db.protection_notified(e['id']);continue
                sent=await bot.send_message(e['chat'],await publisher.body(row),parse_mode='HTML',reply_markup=publisher.keyboard(row))
                await db.arena_raid_set_message(e['raid'],sent.message_id)
            else:
                info=EVENTS[e['kind']]
                await bot.send_message(e['owner'],'🏴 <b>'+html.escape(info['name'])+'</b>\n'+html.escape(info['text'])+'\n\nНа решение — 24 часа. Подробности и последствия — в управлении предприятиями.',parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Предприятия · защита',url=arena_link(username,'holdings_'+str(e['chat'])))]]))
            await db.protection_notified(e['id'])
        except TelegramAPIError:
            # A lease delays retry. The persistent deadline never resets.
            continue
