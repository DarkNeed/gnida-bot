"""Guild commands and one persistent, shared chat invitation per party."""
import asyncio
import hashlib
import html
import logging
import re
import time
from aiogram import F,Router
from aiogram.exceptions import TelegramAPIError,TelegramRetryAfter
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
from arena_links import arena_link
from arena_guild_rules import CONTRACTS,RANKS,contract_by_code
from arena_web import require_member
from handlers.routes import text_or_caption_regexp

GUILD_RE=re.compile(r'^\s*/(?:гильдия|охота|guild|заказы)(?:@\w+)?\s*$',re.I)
HUNT_RE=re.compile(r'^\s*/охота(?:@\w+)?\s+(?P<code>\S+)\s*$',re.I)
INVITE_RE=re.compile(r'^\s*/позвать(?:@\w+)?\s*$',re.I)


class GuildPublisher:
    def __init__(self,db,bot,username):
        self.db,self.bot,self.username=db,bot,username
        self.lock=asyncio.Lock();self.last_edit=0.0

    def card(self,run):
        c=run['contract'];esc=html.escape
        code=c.get('code',CONTRACTS.get(c['id'],{}).get('code',''))
        text='🏹 <b>Заказ '+esc(code)+' — '+esc(c['name'])+'</b>\n\n'+esc(c['description'])
        text+='\n\nРекомендуется: '+('1–3' if c['recommended_party']==1 else str(c['recommended_party'])+'–3')+' охотника'
        text+='\nПолная награда: '+str(c['reward'])+' ₣ и припас'+(' + трактат' if c['kind']!='hunt' else '')
        text+='\nПосле 3 побед: 25% франков, 30% репутации, половина материалов; без припаса и трактата. Дроп экипировки прежний.'
        text+='\nДопуск: ранг '+RANKS[max(0,RANKS.index(c['rank'])-1)]+' и выше'
        text+='\n\n<b>Отряд: '+str(len(run['members']))+'/3</b>\n'
        for p in run['members']:
            reward=p.get('reward_preview',{})
            mode='полная награда, ещё '+str(reward.get('remaining',3)) if reward.get('full',True) else 'повторная награда: 25% ₣ / 30% реп.'
            text+=('👑 ' if p['actor_id']==run['leader'] else '⚔️ ')+esc(p['name'])+' · '+esc(p['class_name'])+', ур. '+str(p['level'])+' — '+mode+'\n'
        link=arena_link(self.username,'guildrun_'+run['id'])
        button=lambda text,action:InlineKeyboardButton(text=text,callback_data='gg:'+action+':'+run['id'])
        if run['status']=='lobby':
            text+='\nПоходы без лимита. Полная награда расходуется только при победе, по дню её завершения. Сброс в 00:00 МСК.\n\nСбор открыт. До старта можно выйти бесплатно. Сбор закрывается через 30 минут после создания.'
            buttons=[[button('➕ Вступить','join'),InlineKeyboardButton(text='Подробнее',url=link)],
                     [button('⚔️ Начать поход','start'),button('🚪 Выйти','leave')],
                     [button('Отменить сбор · лидер','cancel')]]
        elif run['status']=='active':
            text+='\n\n⚔️ Поход начался. Карта, действия и мини-игры — в мини-приложении.'
            entry=arena_link(self.username,'r_'+run['battle']) if run['battle'] and c['kind']!='dungeon' else link
            buttons=[[InlineKeyboardButton(text='⚔️ Открыть поход',url=entry)]]
            if run['battle']:buttons.append([InlineKeyboardButton(text='👁 Наблюдать бой',url=arena_link(self.username,'r_'+run['battle']))])
        else:
            text+='\n\n'+esc(run['reason'] or 'Сбор отменён или срок сбора истёк.')
            buttons=[[InlineKeyboardButton(text='Итоги / гильдия',url=link)]]
        return text,InlineKeyboardMarkup(inline_keyboard=buttons)

    async def invite(self,ident,actor):
        async with self.lock:
            ticket=await self.db.guild_claim_invite(ident,actor)
            run=ticket['run'];text,keyboard=self.card(run)
            try:
                sent=await self.bot.send_message(run['chat_id'],text,parse_mode='HTML',reply_markup=keyboard)
            except BaseException as error:
                await self.db.guild_finish_invite(ident,ticket['claim'])
                if isinstance(error,TelegramAPIError):
                    logging.warning('Guild invitation failed: %s',error)
                    raise ValueError('Не удалось отправить приглашение. Проверь право бота писать в этот чат и попробуй /позвать.') from error
                raise
            signature=hashlib.sha256((text+keyboard.model_dump_json()).encode()).hexdigest()
            await self.db.guild_finish_invite(ident,ticket['claim'],sent.message_id,run['revision'],signature)
            if ticket['previous']:
                try:
                    await self.bot.edit_message_text('🏹 Этот сбор опубликован повторно. Актуальный состав и вступление — в походе.',
                        chat_id=run['chat_id'],message_id=ticket['previous'],
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Открыть актуальный поход',url=arena_link(self.username,'guildrun_'+ident))]]))
                except TelegramAPIError:logging.info('Old guild invitation could not be retired: %s',ident)
            await self._changed(ident)
        return await self.db.guild_get(ident,actor)

    async def _changed(self,ident):
        run,publication=await self.db.guild_publication(ident)
        if not publication or not publication['message_id'] or publication['retry_at']>time.time():return
        text,keyboard=self.card(run)
        signature=hashlib.sha256((text+keyboard.model_dump_json()).encode()).hexdigest()
        if signature==publication['signature']:
            await self.db.guild_publication_done(ident,publication['message_id'],run['revision'],signature);return
        await asyncio.sleep(max(0,.4-(asyncio.get_running_loop().time()-self.last_edit)))
        # Re-read after pacing edits so a concurrent join/start cannot be overwritten.
        run,publication=await self.db.guild_publication(ident)
        text,keyboard=self.card(run);signature=hashlib.sha256((text+keyboard.model_dump_json()).encode()).hexdigest()
        try:
            await self.bot.edit_message_text(text,chat_id=run['chat_id'],message_id=publication['message_id'],parse_mode='HTML',reply_markup=keyboard)
        except TelegramRetryAfter as error:
            await self.db.guild_publication_done(ident,publication['message_id'],publication['published_revision'],publication['signature'],int(time.time())+error.retry_after+1)
        except TelegramAPIError as error:
            if 'message is not modified' in str(error).lower():
                await self.db.guild_publication_done(ident,publication['message_id'],run['revision'],signature)
            else:
                logging.warning('Guild invitation update failed: %s',error)
                await self.db.guild_publication_done(ident,publication['message_id'],publication['published_revision'],publication['signature'],int(time.time())+60)
        else:await self.db.guild_publication_done(ident,publication['message_id'],run['revision'],signature)
        self.last_edit=asyncio.get_running_loop().time()

    async def changed(self,ident):
        async with self.lock:await self._changed(ident)

    async def sweep(self):
        for ident in await self.db.guild_publications_due():await self.changed(ident)


async def guild_chat_action(db,ident,actor,action):
    # Telegram clicks have no trusted revision. Retry only stale-revision errors;
    # rank, capacity, ownership and energy checks remain authoritative.
    for attempt in range(3):
        run=await db.guild_get(ident,actor)
        try:return await db.guild_action(ident,actor,action,run['revision'])
        except ValueError as error:
            if 'Поход изменился.' not in str(error) or attempt==2:raise


def create_guild_router(db,bot,username,enabled,publisher=None):
    router=Router(name='hunter_guild')
    publisher=publisher or GuildPublisher(db,bot,username)

    async def remember(chat,user):
        member=await require_member(bot,chat.id,user.id)
        if getattr(getattr(member,'user',None),'is_bot',False):raise ValueError('Боты не участвуют в гильдии.')
        await db.arena_require_enabled(chat.id)
        await db.upsert_chat(chat.id,getattr(chat,'title',None) or str(chat.id))
        await db.upsert_user(chat.id,user.id,getattr(user,'username',None),getattr(user,'full_name',str(user.id)),touch=False)

    @router.message(text_or_caption_regexp(GUILD_RE))
    async def guild(message):
        if not message.from_user or message.from_user.is_bot:return
        if not enabled:await message.answer('Гильдия недоступна: нужно настроить WEBAPP_URL.');return
        if message.chat.type not in ('private','group','supergroup'):
            await message.answer('Используй /гильдия в группе или в личных сообщениях боту.');return
        board=bool(re.match(r'^\s*/заказы',message.text or message.caption or '',re.I))
        parameter='guildboard' if board else 'guild'
        if message.chat.type!='private':
            try:await remember(message.chat,message.from_user)
            except ValueError as error:await message.answer(str(error));return
            parameter+='_'+str(message.chat.id)
        await message.answer('🏹 Гильдия охотников: заказы F–S и подземелья. '
            'Выбери заказ в меню или создай сбор командой /охота F1. '
            'Позвать друзей в свой сбор: /позвать. Походы без лимита; первые 3 победы в день с полной наградой, затем сниженные награды без урезания дропа экипировки.'+
            (' Сначала выбери чат.' if message.chat.type=='private' else ''),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='📋 Доска заказов' if board else '🏹 Открыть гильдию',url=arena_link(username,parameter))]]))

    async def command(message):
        if not message.from_user or message.from_user.is_bot:return
        if not enabled:await message.answer('Гильдия недоступна: нужно настроить WEBAPP_URL.');return
        if message.chat.type not in ('group','supergroup'):
            await message.answer('Напиши /охота F1 или /позвать в группе, где собираешь отряд. Выбрать доступный чат можно через /гильдия в ЛС боту.');return
        try:
            await remember(message.chat,message.from_user)
            match=HUNT_RE.fullmatch(message.text or message.caption or '')
            if match:
                contract=contract_by_code(match['code'])
                nonce=hashlib.sha256(f'guild:{message.chat.id}:{message.message_id}'.encode()).hexdigest()
                run=await db.guild_create(message.chat.id,message.from_user.id,contract,nonce)
                # Re-delivery of an already published command never reposts it.
                if run['invite']['posted']:await publisher.changed(run['id']);return
            else:run=await db.guild_current(message.chat.id,message.from_user.id)
            await publisher.invite(run['id'],message.from_user.id)
        except ValueError as error:await message.answer(str(error))
    router.message.register(command,text_or_caption_regexp(HUNT_RE))
    router.message.register(command,text_or_caption_regexp(INVITE_RE))

    @router.callback_query(F.data.startswith('gg:'))
    async def callback(callback):
        if not enabled or not callback.message or callback.from_user.is_bot:await callback.answer();return
        try:
            _,action,ident=callback.data.split(':',2)
            if action not in ('join','leave','start','cancel'):raise ValueError('Неизвестная кнопка гильдии.')
            run,publication=await db.guild_publication(ident)
            if callback.message.chat.id!=run['chat_id']:raise ValueError('Этот сбор относится к другому чату.')
            if not publication or publication['message_id']!=callback.message.message_id:raise ValueError('Приглашение устарело. Открой актуальный поход или последний сбор.')
            await remember(callback.message.chat,callback.from_user)
            if action in ('start','cancel') and callback.from_user.id!=run['leader']:raise ValueError('Эта кнопка доступна только лидеру.')
            if action=='start':
                for p in run['members']:
                    member=await require_member(bot,run['chat_id'],p['actor_id'])
                    if getattr(getattr(member,'user',None),'is_bot',False):raise ValueError('Боты не участвуют в гильдии.')
            await guild_chat_action(db,ident,callback.from_user.id,'leave' if action=='cancel' else action)
            await callback.answer('Готово. Поход и действия — в мини-приложении.')
            await publisher.changed(ident)
        except (ValueError,TypeError) as error:await callback.answer(str(error)[:190],show_alert=True)
    return router
