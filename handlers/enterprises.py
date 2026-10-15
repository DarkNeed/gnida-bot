"""Private multi-enterprise menu and owner-only slave recovery mini-game."""

import asyncio
import html
import json
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from enterprises import CATALOG, CAPACITIES, MAX_ENTERPRISES, UPGRADE_PRICES, config, title, role_labels
from slave_recovery import DIRECTIONS, RECOVERY_LENGTH, RECOVERY_MAX_ERRORS


def button(text, data):return InlineKeyboardButton(text=text[:60],callback_data=data)
def keyboard(rows):return InlineKeyboardMarkup(inline_keyboard=rows)
def esc(value):return html.escape(str(value))


async def enterprise_menu(db, actor, chat):
    await db.settle_business(chat,actor)
    sites=[dict(s) for s in await db.list_owned_businesses(actor) if s['chat_id']==chat]
    pending=await db.recovery_pending(chat,actor)
    rows=[];lines=[f'<b>🏭 Мои предприятия · {len(sites)}/{MAX_ENTERPRISES}</b>']
    for site in sites:
        view=await db.enterprise_view(chat,site['id'],actor)
        lines.append(f"\n{CATALOG[site['business_type']]['emoji']} <b>{esc(title(site))}</b> · ур. {site['level']}\nЗанято: {len(view['workers'])}/{view['capacity']}")
        rows.append([button('Открыть · '+title(site),f"ent:v:{chat}:{site['id']}")])
    for event in pending:rows.append([button('🚨 Вернуть пропавшего раба',f"rec:{event['id']}:{event['revision']}:view")])
    if len(sites)<MAX_ENTERPRISES:rows.append([button('➕ Открыть предприятие',f'ent:new:{chat}')])
    rows.append([button('← Меню',f'sm:c:{chat}:home')])
    lines.append('\nДо трёх разных типов в чате. Одно своё предприятие, один управляющий на каждое. Вместимость: 10 → 15 → 20. Налог общий для всех предприятий владельца в этом чате.')
    lines.append('При более чем 20 рабах возможен побег или похищение. Проигрыш мини-игры освобождает пропавшего раба.')
    return '\n'.join(lines),keyboard(rows)


async def enterprise_detail(db, actor, chat, site_id):
    site=await db.enterprise_view(chat,site_id,actor)
    if not site:return await enterprise_menu(db,actor,chat)
    cfg=config(site);producer,leader=role_labels(site);workers=site['workers']
    producers=sum(w['role']==cfg['producer_role'] for w in workers)
    leaders=sum(w['role']==cfg['leader_role'] for w in workers)
    text=(f"<b>{CATALOG[site['business_type']]['emoji']} {esc(title(site))}</b>\n"
          f"{esc(CATALOG[site['business_type']]['name'])} · уровень {site['level']}\n"
          f"Занято: <b>{len(workers)}/{site['capacity']}</b>\n"
          f"{esc(producer)}: {producers} · {esc(leader)}: {leaders}\n"
          f"Доход активного работника: {cfg['owner_per_producer']} ₣/час до налога; неактивного: {cfg['inactive_owner_per_producer']} ₣/час. Управляющий: +20% активной выручки.\n"
          'Зарплата активного работника: 1 ₣/6 ч, управляющего: 1 ₣/12 ч.\n')
    if site['description']:text+='\n'+esc(site['description'])+'\n'
    if len(workers)>site['capacity'] or leaders>1:text+='\n⚠️ Лишние назначения сохранены, но доход и зарплату дают только места в пределах вместимости и один управляющий. Распредели работников.\n'
    if any(w['away'] for w in workers):text+='\n🚨 Пропавшие временно не работают. Вернуть их можно в меню предприятий.\n'
    rows=[]
    if site['can_edit']:
        rows.append([button('👥 Работники',f'ent:w:{chat}:{site_id}:0'),button('✏️ Оформление',f'ent:customize:{chat}:{site_id}')])
        if site['level']<3:rows.append([button(f"⬆️ Уровень {site['level']+1} · {UPGRADE_PRICES[site['level']]} ₣ · {CAPACITIES[site['level']+1]} мест",f"ent:up:{chat}:{site_id}:{site['level']}")])
        rows.append([button('📊 Статистика',f'ent:stats:{chat}:{site_id}')])
    rows.append([button('← Предприятия',f'ent:list:{chat}')])
    return text,keyboard(rows)


async def enterprise_jobs(db, actor, chat):
    sites=[s for s in await db.list_available_businesses(actor) if s['chat_id']==chat]
    rows=[[button(CATALOG[s['business_type']]['emoji']+' '+title(s)+' · '+str(s['display_name'] or s['owner_id']),f"ent:job:{chat}:{s['id']}")] for s in sites[:30]]
    rows.append([button('← Меню',f'sm:c:{chat}:home')])
    intro='Выбери предприятие.' if sites else 'Подходящих чужих предприятий пока нет.'
    return '<b>🧰 Подработка</b>\n'+intro+' Одна смена в час на все предприятия чата, выплата 20–100 ₣. Прежний лимит заработка рабов сохраняется.',keyboard(rows)


async def present(db, bot, chat, actor):
    if not await db.user_knows_chat(actor,chat):return False
    try:member=await bot.get_chat_member(chat,actor)
    except (TelegramAPIError,asyncio.TimeoutError):return False
    status=getattr(member.status,'value',member.status)
    return bool(getattr(member,'is_member',False)) if status=='restricted' else status not in ('left','kicked')


async def recovery_view(db, row):
    user=await db.get_user(row['chat_id'],row['slave_id'])
    name=(user['display_name'] or str(row['slave_id'])) if user else str(row['slave_id'])
    tag=f'<a href="tg://user?id={row["slave_id"]}">{esc(name)}</a>'
    status=row['status'];prefix=f'🚨 {tag} '+('сбежал!' if row['kind']=='escaped' else 'похитили!')
    if status in ('announcing','pending'):
        pattern=' '.join(DIRECTIONS[i] for i in json.loads(row['pattern_json']))
        return (prefix+'\n\nЗапомни путь и повтори его после старта:\n<b>'+pattern+'</b>\n\n'
                '⚠️ После нажатия «Начать»: 2 минуты и максимум одна ошибка. Вторая ошибка или истечение времени освобождает раба. До старта таймера нет. Играть может только владелец.',
                keyboard([[button('Начать · риск потерять раба',f"rec:{row['id']}:{row['revision']}:start")]]))
    if status=='playing':
        text=prefix+f"\nПовтори путь: направление {row['step']+1}/{RECOVERY_LENGTH}.\nОшибки: {row['errors']}/{RECOVERY_MAX_ERRORS}. После старта — 2 минуты."
        return text,keyboard([[button(arrow,f"rec:{row['id']}:{row['revision']}:{i}") for i,arrow in enumerate(DIRECTIONS)]])
    result={'returned':'✅ Раб возвращён. Назначение на предприятии сохранено.',
            'lost':'❌ Поиски провалены. Раб освобождён от этого владельца в этом чате и снят с работы.',
            'cancelled':'Событие отменено: владение изменилось, модуль выключен или сообщение игры недоступно.'}.get(status,'Событие завершено.')
    return tag+'\n'+result,keyboard([])


def create_enterprise_router(db):
    router=Router(name='enterprises')

    @router.callback_query(F.data.startswith('ent:'))
    async def enterprise_callback(callback: CallbackQuery, state: FSMContext, bot):
        try:
            parts=callback.data.split(':');action=parts[1];chat=int(parts[2]);actor=callback.from_user.id
            if not await present(db,bot,chat,actor):raise ValueError('Этот чат тебе недоступен.')
            if callback.message.chat.type!='private' and callback.message.chat.id!=chat:raise ValueError('Кнопка относится к другому чату.')
            if not await db.feature_enabled(chat,'slavery'):raise ValueError('Рабовладение выключено в этом чате.')
            notice=None;site_id=int(parts[3]) if len(parts)>3 and action not in ('create',) else None
            if action=='list':view=await enterprise_menu(db,actor,chat)
            elif action=='new':
                existing={s['business_type'] for s in await db.list_owned_businesses(actor) if s['chat_id']==chat}
                rows=[[button(f"{m['emoji']} {m['name']} · {m['price']} ₣",f'ent:create:{chat}:{kind}')] for kind,m in CATALOG.items() if kind not in existing]
                rows.append([button('← Предприятия',f'ent:list:{chat}')])
                view=('Выбери тип. До трёх разных предприятий в чате; своё — только одно.\nСтоимость списывается при нажатии.',keyboard(rows))
            elif action=='create':
                result=await db.enterprise_create(chat,actor,parts[3])
                notice={'created':'Предприятие открыто.','exists':'Такой тип уже открыт.','limit':'Максимум три предприятия в чате.','no_slaves':'Нужен хотя бы один раб.','insufficient':'Недостаточно франков.'}[result]
                view=await enterprise_menu(db,actor,chat)
            elif action=='job':
                site=await db.enterprise_view(chat,site_id,actor)
                if not site:raise ValueError('Предприятие недоступно.')
                result,pay,_,until=await db.work_at_business(chat,site['owner_id'],actor,site_id)
                notice=f'Смена завершена: +{pay} ₣.' if result in ('worked','inactive_slave') else {'cooldown':'Одна смена в час на все предприятия.','away':'Сначала нужно завершить событие возвращения.','own_business':'Нельзя подрабатывать у себя.'}.get(result,'Предприятие недоступно.')
                view=await enterprise_jobs(db,actor,chat)
            elif action=='v':view=await enterprise_detail(db,actor,chat,site_id)
            else:
                site=await db.enterprise_view(chat,site_id,actor)
                if not site or not site['can_edit']:raise ValueError('Управлять предприятием может только владелец.')
                if action=='up':
                    result=await db.enterprise_upgrade(chat,actor,site_id,int(parts[4]))
                    notice={'upgraded':'Предприятие расширено.','insufficient':'Недостаточно франков.','stale':'Уровень уже изменился.','max':'Уже максимальный уровень.','missing':'Предприятие недоступно.'}[result]
                    view=await enterprise_detail(db,actor,chat,site_id)
                elif action=='customize':
                    fields=[('name','Название'),('description','Описание')]
                    if site['business_type']=='custom':fields += [('producer_title','Название должности работника'),('leader_title','Название должности управляющего')]
                    view=('Выбери поле для изменения.',keyboard([[button(label,f'ent:edit:{chat}:{site_id}:{field}')] for field,label in fields]+[[button('← Предприятие',f'ent:v:{chat}:{site_id}')]]))
                elif action=='edit':
                    if callback.message.chat.type!='private':raise ValueError('Изменять текст можно через меню в личке бота.')
                    field=parts[4]
                    if field not in ('name','description','producer_title','leader_title'):raise ValueError('Неизвестное поле.')
                    await state.set_state('EnterpriseEdit:value');await state.set_data(dict(chat=chat,site=site_id,field=field))
                    view=(f'Предприятие: <b>{esc(title(site))}</b>\nПришли новый текст одним сообщением. Название — до 60, описание — до 500, должность — до 30 символов.\n/отмена — отменить. Для пустого описания отправь «-».',keyboard([[button('Отмена',f'ent:v:{chat}:{site_id}')]]))
                elif action in ('w','a'):
                    if action=='a':
                        worker=int(parts[4]);role={'p':config(site)['producer_role'],'l':config(site)['leader_role'],'x':None}[parts[5]]
                        result=await db.enterprise_assign(chat,actor,worker,role,site_id)
                        notice={'updated':'Назначение сохранено.','removed':'Снят с работы.','full':'Нет свободных мест.','leader_full':'Управляющий уже назначен.','away':'Раб временно отсутствует.','not_owned':'Это не твой раб.','other_business':'Раб работает на другом предприятии.'}.get(result,'Назначение недоступно.')
                        view=await enterprise_detail(db,actor,chat,site_id)
                    else:
                        page=max(0,int(parts[4]));slaves=list(await db.list_business_slaves(chat,actor));rows=[];staff=[]
                        workers={w['worker_id']:w for w in site['workers']};producer,leader=role_labels(site)
                        for slave in slaves[page*6:(page+1)*6]:
                            worker=slave['user_id'];w=workers.get(worker)
                            label=slave['display_name'] or slave['username'] or str(worker)
                            job=(leader if w['role']==config(site)['leader_role'] else producer) if w else ('На другом предприятии' if slave['business_id'] else 'Без работы')
                            if w and w['away']:job+=' · пропал'
                            staff.append(f'• {esc(label)} — {esc(job)}')
                            rows.append([button(label,f'ent:worker:{chat}:{site_id}:{worker}')])
                        nav=[]
                        if page:nav.append(button('←',f'ent:w:{chat}:{site_id}:{page-1}'))
                        if (page+1)*6<len(slaves):nav.append(button('→',f'ent:w:{chat}:{site_id}:{page+1}'))
                        if nav:rows.append(nav)
                        rows.append([button('← Предприятие',f'ent:v:{chat}:{site_id}')])
                        view=(f'<b>👥 Работники · {len(site["workers"])}/{site["capacity"]}</b>\n'+ '\n'.join(staff)+'\n\nВыбери раба. Перевод автоматически снимает его с прежнего предприятия.',keyboard(rows))
                elif action=='worker':
                    worker=int(parts[4]);slaves=await db.list_business_slaves(chat,actor)
                    slave=next((s for s in slaves if s['user_id']==worker),None)
                    if not slave:raise ValueError('Это не твой раб.')
                    producer,leader=role_labels(site)
                    view=(f'<b>{esc(slave["display_name"] or str(worker))}</b>\nВыбери должность. Максимум один управляющий.',keyboard([
                        [button(producer,f'ent:a:{chat}:{site_id}:{worker}:p')],
                        [button(leader,f'ent:a:{chat}:{site_id}:{worker}:l')],
                        [button('Снять с этого предприятия',f'ent:a:{chat}:{site_id}:{worker}:x')],
                        [button('← Работники',f'ent:w:{chat}:{site_id}:0')]]))
                elif action=='stats':
                    stats=await db.enterprise_statistics(chat,actor,site_id)
                    lines=[f'<b>📊 {esc(title(site))}</b>','Последние 7 дней с начислениями:']
                    lines += [f"{r['income_day']}: {r['gross_income']} ₣ до налога → {r['net_income']} ₣ после" for r in stats]
                    lines.append('Налог считается с общего дохода всех твоих предприятий в чате. Для старых начислений сохранена общая статистика владельца.')
                    view=('\n'.join(lines),keyboard([[button('← Предприятие',f'ent:v:{chat}:{site_id}')]]))
                else:raise ValueError('Устаревшая кнопка.')
            if action!='edit':await state.clear()
            await callback.message.edit_text(view[0],reply_markup=view[1],parse_mode='HTML')
            await callback.answer(notice)
        except (ValueError,IndexError,KeyError):
            await callback.answer('Действие недоступно или кнопка устарела. Открой меню заново.',show_alert=True)
        except TelegramBadRequest as error:
            if 'message is not modified' not in str(error).lower():raise
            await callback.answer()

    @router.message(StateFilter('EnterpriseEdit:value'), F.chat.type=='private', F.text)
    async def enterprise_text(message: Message, state: FSMContext, bot):
        data=await state.get_data()
        if message.text.casefold() in ('/отмена','/cancel'):
            await state.clear();await message.answer('Изменение отменено.');return
        try:
            if not await present(db,bot,data['chat'],message.from_user.id):raise ValueError('Чат недоступен.')
            value='' if data['field']=='description' and message.text=='-' else message.text
            await db.enterprise_edit(data['chat'],message.from_user.id,data['site'],data['field'],value)
            await state.clear();view=await enterprise_detail(db,message.from_user.id,data['chat'],data['site'])
            await message.answer('✅ Сохранено.\n\n'+view[0],reply_markup=view[1],parse_mode='HTML')
        except ValueError as error:await message.answer(str(error))

    @router.callback_query(F.data.startswith('rec:'))
    async def recovery_callback(callback: CallbackQuery, bot):
        try:
            _,event_id,revision,action=callback.data.split(':');event_id=int(event_id)
            row=await db.recovery_get(event_id)
            if not row or row['owner_id']!=callback.from_user.id:raise ValueError('Играть может только владелец.')
            if not await present(db,bot,row['chat_id'],callback.from_user.id):raise ValueError('Чат недоступен.')
            if callback.message.chat.type!='private' and callback.message.chat.id!=row['chat_id']:raise ValueError('Кнопка относится к другому чату.')
            if action!='view':row=await db.recovery_action(event_id,callback.from_user.id,int(revision),action)
            view=await recovery_view(db,row)
            try:
                await callback.message.edit_text(view[0],reply_markup=view[1],parse_mode='HTML')
            except (TelegramAPIError,asyncio.TimeoutError) as error:
                if not isinstance(error,TelegramBadRequest) or 'message is not modified' not in str(error).lower():
                    await db.recovery_cancel_delivery(event_id,callback.from_user.id,row['revision'])
                    notice=('Не удалось показать игру. Активный поиск отменён без потери раба.'
                            if row['status']=='playing' else 'Не удалось обновить сообщение. Результат уже сохранён.')
                    try:await callback.answer(notice,show_alert=True)
                    except TelegramAPIError:pass
                    return
            await callback.answer()
            if row['message_id'] and (callback.message.chat.id!=row['message_chat'] or callback.message.message_id!=row['message_id']):
                try:await bot.edit_message_text(view[0],chat_id=row['message_chat'],message_id=row['message_id'],reply_markup=view[1],parse_mode='HTML')
                except TelegramAPIError:pass
            elif row['status'] in ('lost','returned','cancelled'):
                await db.recovery_notified(row['id'])
        except (ValueError,IndexError) as error:await callback.answer(str(error),show_alert=True)
        except TelegramBadRequest as error:
            if 'message is not modified' not in str(error).lower():raise
            await callback.answer()

    return router


async def sweep_recovery_events(db,bot,*,create=True):
    for row in await db.recovery_expire():
        if row['message_id']:
            try:
                view=await recovery_view(db,row)
                await bot.edit_message_text(view[0],chat_id=row['message_chat'],message_id=row['message_id'],reply_markup=view[1],parse_mode='HTML')
                await db.recovery_notified(row['id'])
            except TelegramBadRequest:
                # Removed/unchanged messages do not keep a permanent retry loop.
                await db.recovery_notified(row['id'])
            except TelegramAPIError:logging.warning('Could not update recovery event %s',row['id'])
    if not create:return
    for row in await db.enterprise_due_recoveries():
        try:
            view=await recovery_view(db,row)
            text=f'<a href="tg://user?id={row["owner_id"]}">Владелец</a>, '+view[0]
            msg=await bot.send_message(row['chat_id'],text,reply_markup=view[1],parse_mode='HTML')
        except (TelegramAPIError,asyncio.TimeoutError):
            await db.recovery_cancel_publication(row['id']);continue
        await db.recovery_published(row['id'],row['chat_id'],msg.message_id)
