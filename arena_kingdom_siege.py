"""Chat-local, warned territorial PvP. Capitals and connected empires are safe."""
from copy import deepcopy
import json
import math
import secrets

from arena_kingdom_rules import HOUR,DAY,SITES,NEUTRAL_LANDS,coordinates,neighbours,land_cap
import arena_kingdom_council as council
import arena_kingdom_war as army

ACTIVE=('notice','warning','battle')
SIEGE_FEE=15000


def connected(capital, tiles):
    if capital not in tiles:return False
    seen={capital};pending=[capital]
    while pending:
        for p in neighbours(*pending.pop()):
            if p in tiles and p not in seen:seen.add(p);pending.append(p)
    return seen==tiles


def initialize(d):
    pvp=d.setdefault('pvp',dict(shield_until=0,next_attack_at=0,last_declare=0))
    pvp.setdefault('opponents',{})
    return pvp


def settle(m, fighters):
    lookup={u['source_id']:u for u in fighters};kept=[];lost=set()
    for unit in m['units']:
        result=lookup.get(unit['id'])
        if result:
            if result['hp']<=0:lost.add(unit['id']);continue
            unit['condition']=max(1,math.ceil(100*result['hp']/result['max_hp']))
        kept.append(unit)
    m['units']=kept;m['formation']=[None if uid in lost else uid for uid in m['formation']]
    return len(lost)


def mirrored(report):
    result=deepcopy(report)
    def flip(uid):return ('e:' if uid.startswith('p:') else 'p:')+uid[2:]
    for phase in ('initial','final'):
        result[phase]['own'],result[phase]['enemies']=result[phase]['enemies'],result[phase]['own']
        for u in result[phase]['own']+result[phase]['enemies']:u['id']=flip(u['id'])
    for e in result['events']:e['actor']=flip(e['actor']);e['target']=flip(e['target'])
    result['won']=not report['won']
    return result


class KingdomSiegeMixin:
    def _connect_kingdom_sieges(self):
        self.connection.executescript('''
          CREATE TABLE IF NOT EXISTS kingdom_sieges(
            id TEXT PRIMARY KEY,chat INTEGER NOT NULL,attacker TEXT NOT NULL REFERENCES kingdom_towns(id),
            defender TEXT NOT NULL REFERENCES kingdom_towns(id),q INTEGER NOT NULL,r INTEGER NOT NULL,
            status TEXT NOT NULL,created INTEGER NOT NULL,announced INTEGER NOT NULL DEFAULT 0,
            battle_at INTEGER NOT NULL DEFAULT 0,finish INTEGER NOT NULL DEFAULT 0,
            retry_at INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,data TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS kingdom_sieges_chat ON kingdom_sieges(chat,status);
        ''')

    def _siege_clock(self):
        from arena_kingdom import kingdom_now
        return kingdom_now()

    def _siege_row(self,ident):
        if not isinstance(ident,str):raise ValueError('Выбери осаду.')
        row=self.connection.execute('SELECT * FROM kingdom_sieges WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Осада не найдена.')
        row=dict(row);row['data']=json.loads(row['data']);return row

    def _siege_save(self,s):
        self.connection.execute('UPDATE kingdom_sieges SET status=?,announced=?,battle_at=?,finish=?,data=? WHERE id=?',
            (s['status'],s['announced'],s['battle_at'],s['finish'],json.dumps(s['data'],ensure_ascii=False),s['id']))

    def _siege_land(self,town):
        return {(r['q'],r['r']) for r in self.connection.execute('SELECT q,r FROM kingdom_tiles WHERE town=?',(town['id'],))}

    def _siege_reasons(self,a,b,point,now):
        reasons=[];ad=a['data'];bd=b['data'];ap=initialize(ad);bp=initialize(bd)
        at=self._siege_land(a);bt=self._siege_land(b)
        if a['chat']!=b['chat'] or a['owner']==b['owner']:reasons.append('Цель должна принадлежать другому игроку этого чата.')
        if ad['stage']<2 or bd['stage']<2:reasons.append('Оба поселения должны быть городами или столицами.')
        if min(now-ad['founded_at'],now-bd['founded_at'])<14*DAY:reasons.append('Защита новичка: первые 14 суток.')
        if point==(b['q'],b['r']):reasons.append('Столицу владения нельзя захватить.')
        if point not in bt or point in SITES or point in NEUTRAL_LANDS:reasons.append('Это не захватываемая земля защитника.')
        if not any(point in neighbours(*p) for p in at):reasons.append('Нужна общая граница с выбранной клеткой.')
        if len(at)>=land_cap(ad):reasons.append('Нет свободного слота земли. Предел 3/5/7 не обходится победой.')
        if not connected((b['q'],b['r']),bt-{point}):reasons.append('Захват разорвёт связность владений защитника.')
        if bp['shield_until']>now:reasons.append('У защитника действует послевоенная защита.')
        if ap['next_attack_at']>now or ap['last_declare']>now-HOUR:reasons.append('Твои военные приказы пока на перезарядке.')
        for town in (a,b):
            m=army.initialize(town['data'])
            if m.get('siege_lock') or m['campaign']:reasons.append('Одна из армий уже участвует в походе или осаде.');break
            if council.initialize(town['data'])['pending']:reasons.append('Дождитесь завершения текущих реформ.');break
        recent=self.connection.execute('SELECT 1 FROM kingdom_sieges WHERE attacker=? AND defender=? AND announced>? LIMIT 1',
                                       (a['id'],b['id'],now-7*DAY)).fetchone()
        if recent or ap['opponents'].get(b['id'],0)>now-7*DAY:
            reasons.append('Повторное объявление войны этому соседу — не чаще раза в неделю.')
        if not army.formation_units(ad,now) or any(u['ready_at']>now for u in army.formation_units(ad,now)):
            reasons.append('Нужен готовый боевой строй нападающего.')
        return list(dict.fromkeys(reasons))

    def _siege_cancel(self,s,reason,*,refund=False):
        a=self._kingdom_row_locked(s['attacker']);b=self._kingdom_row_locked(s['defender'])
        if refund:
            self._add_francs_locked(s['chat'],a['owner'],s['data']['fee'])
            a['data']['resources']['food']=min(600+a['data']['buildings']['warehouse']*500,
                                               a['data']['resources']['food']+s['data']['food'])
        for town in (a,b):
            lock=army.initialize(town['data']).get('siege_lock')
            if lock and lock['id']==s['id']:town['data']['military']['siege_lock']=None
            self._kingdom_log(town,reason,self._siege_clock());self._kingdom_save_locked(town)
        s['status']='cancelled';s['data']=dict(reason=reason,refunded=refund);self._siege_save(s)

    def _siege_declare(self,a,payload,now):
        ident=payload.get('defender')
        if not isinstance(ident,str):raise ValueError('Выбери соседнее владение.')
        b=self._kingdom_row_locked(ident)
        if b['chat']!=a['chat']:raise ValueError('Войны между чатами недоступны.')
        self._kingdom_advance_locked(b,self._kingdom_world_locked(b['chat']))
        point=coordinates(payload.get('q'),payload.get('r'));reasons=self._siege_reasons(a,b,point,now)
        if reasons:raise ValueError(' '.join(reasons))
        tactic=payload.get('tactic')
        if not isinstance(tactic,str) or tactic not in army.TACTICS:raise ValueError('Выбери тактику армии.')
        selected=army.formation_units(a['data'],now,ready=True);food=council.supplies(a['data'],len(selected))
        if a['data']['resources']['food']<food:raise ValueError('Не хватает походного снабжения.')
        self._forge_spend_francs_locked(a['chat'],a['owner'],SIEGE_FEE);a['data']['resources']['food']-=food
        ident=secrets.token_hex(12);unit_ids=[u['id'] for u in selected]
        data=dict(fee=SIEGE_FEE,food=food,seed=secrets.token_hex(16),tactic=tactic,
                  attacker_units=deepcopy(selected),attacker_fighters=council.buff(a['data'],army._fighters(selected,'p:')))
        self.connection.execute('INSERT INTO kingdom_sieges(id,chat,attacker,defender,q,r,status,created,data) VALUES(?,?,?,?,?,?,\'notice\',?,?)',
            (ident,a['chat'],a['id'],b['id'],*point,now,json.dumps(data,ensure_ascii=False)))
        for town,role in ((a,'attacker'),(b,'defender')):
            m=army.initialize(town['data']);m['siege_lock']=dict(id=ident,role=role,phase='notice',unit_ids=unit_ids if role=='attacker' else [])
            initialize(town['data'])
        a['data']['pvp']['last_declare']=now
        self._kingdom_save_locked(b)
        return ident

    def _siege_start_battle(self,s,now):
        a=self._kingdom_row_locked(s['attacker']);b=self._kingdom_row_locked(s['defender'])
        for town in (a,b):self._kingdom_advance_locked(town,self._kingdom_world_locked(town['chat']))
        target=(s['q'],s['r']);bt=self._siege_land(b);at=self._siege_land(a)
        if target not in bt or target==(b['q'],b['r']) or len(at)>=land_cap(a['data']) or not connected((b['q'],b['r']),bt-{target}) or not connected((a['q'],a['r']),at|{target}):
            self._siege_cancel(s,'Осада отменена: условия владения землёй изменились.',refund=True);return
        selected=[u for u in army.formation_units(b['data'],s['battle_at']) if u['ready_at']<=s['battle_at']]
        fighters=council.buff(b['data'],army._fighters(selected,'e:'))
        if len(fighters)<5:
            used={u['slot'] for u in selected};slot=next(i for i in range(5) if i not in used)
            guard=council.buff(b['data'],army._fighters([dict(id='guard:'+b['id'],kind='militia',slot=slot,condition=100)],'e:'),guard=True)[0]
            guard['name']='Городская стража';fighters.append(guard)
        tactic=b['data']['pvp'].get('defense_tactic','guard')
        s['data']['snapshot']=dict(target='siege',tactic=s['data']['tactic'],
            outpost=dict(name=b['name'],tactic=tactic),fighters=dict(own=s['data']['attacker_fighters'],enemies=fighters))
        s['status']='battle'
        for town in (a,b):
            lock=town['data']['military']['siege_lock'];lock['phase']='battle'
            if town['id']==b['id']:lock['unit_ids']=[u['id'] for u in selected]
            self._kingdom_save_locked(town)
        self._siege_save(s)

    def _siege_finish(self,s,now):
        a=self._kingdom_row_locked(s['attacker']);b=self._kingdom_row_locked(s['defender'])
        target=(s['q'],s['r']);at=self._siege_land(a);bt=self._siege_land(b)
        if target not in bt or target==(b['q'],b['r']) or len(at)>=land_cap(a['data']) or not connected((b['q'],b['r']),bt-{target}) or not connected((a['q'],a['r']),at|{target}):
            self._siege_cancel(s,'Осада отменена: безопасная передача земли больше невозможна.',refund=True);return
        report=army.resolve_battle(s['data']['snapshot'],s['data']['seed'])
        report.update(id=s['id'],kind='siege',name=f"Осада: {a['name']} → {b['name']}",target='siege',at=s['finish'],loot={})
        inverse=mirrored(report)
        for town,r,side in ((a,report,'own'),(b,inverse,'enemies')):
            m=army.initialize(town['data']);r['lost']=settle(m,report['final'][side]);m['siege_lock']=None
            m['reports']=(m['reports']+[r])[-3:]
            if r['won']:m['glory']+=1
        if report['won']:
            changed=self.connection.execute('UPDATE kingdom_tiles SET town=? WHERE chat=? AND q=? AND r=? AND town=?',
                (a['id'],s['chat'],*target,b['id'])).rowcount
            if changed!=1:raise RuntimeError('Siege land ownership changed in transaction')
        initialize(b['data'])['shield_until']=now+72*HOUR
        initialize(a['data'])['next_attack_at']=now+48*HOUR
        message=('Земля '+str(s['q'])+':'+str(s['r'])+' перешла к '+a['name']+'.' if report['won'] else b['name']+' удерживает землю.')
        for town in (a,b):self._kingdom_log(town,message,now);self._kingdom_save_locked(town)
        s['status']='finished';s['data']=dict(won=report['won'],reason=message);self._siege_save(s)

    def _kingdom_siege_advance_locked(self,chat):
        now=self._siege_clock()
        rows=self.connection.execute("SELECT id FROM kingdom_sieges WHERE chat=? AND status IN ('notice','warning','battle') ORDER BY created,id",(chat,)).fetchall()
        for row in rows:
            s=self._siege_row(row['id'])
            if s['status']=='notice' and s['created']+HOUR<=now:
                self._siege_cancel(s,'Уведомление об осаде не доставлено. Приказ отменён, затраты возвращены.',refund=True);continue
            if s['status']=='warning' and s['battle_at']<=now:self._siege_start_battle(s,now)
            if s['status']=='battle' and s['finish']<=now:self._siege_finish(s,now)
        # Only short public summaries survive. Detailed reports are bounded in
        # the two owners' military journals; active records are never pruned.
        self.connection.execute("DELETE FROM kingdom_sieges WHERE chat=? AND status IN ('finished','cancelled') AND id NOT IN (SELECT id FROM kingdom_sieges WHERE chat=? ORDER BY created DESC LIMIT 100)",(chat,chat))

    def _kingdom_siege_action_locked(self,a,action,payload,now):
        if action=='siege':
            ident=self._siege_declare(a,payload,now)
            return dict(siege=ident,notice='Осада подготовлена. Сутки предупреждения начнутся только после доставки сообщения в чат.')
        if action=='defense':
            tactic=payload.get('tactic');m=army.initialize(a['data']);lock=m.get('siege_lock')
            if not isinstance(tactic,str) or tactic not in army.TACTICS:raise ValueError('Выбери доступную оборонительную тактику.')
            if lock and (lock['role']=='attacker' or lock['phase']=='battle'):raise ValueError('Тактика текущего боя уже зафиксирована.')
            initialize(a['data'])['defense_tactic']=tactic;return dict(notice='Оборонительная тактика сохранена.')
        s=self._siege_row(payload.get('siege'))
        if s['chat']!=a['chat'] or s['attacker']!=a['id']:raise ValueError('Отозвать приказ может только нападающий этого чата.')
        if s['status'] not in ('notice','warning'):raise ValueError('Бой начался или осада уже закрыта.')
        self._siege_cancel(s,'Нападающий отозвал осаду.',refund=s['status']=='notice')
        # The cancellation saved both rows; reload the caller to prevent a
        # subsequent generic save from restoring its old military lock.
        updated=self._kingdom_row_locked(a['id']);a.update(updated)
        return dict(notice='Осада отозвана. После доставки предупреждения затраты не возвращаются.')

    def _kingdom_siege_view_locked(self,chat,actor,rows):
        now=self._siege_clock();own=next((r for r in rows if r['owner']==actor),None);wars=[];targets=[]
        for raw in self.connection.execute('SELECT id FROM kingdom_sieges WHERE chat=? ORDER BY created DESC LIMIT 20',(chat,)):
            s=self._siege_row(raw['id']);wars.append(dict(id=s['id'],attacker=s['attacker'],defender=s['defender'],q=s['q'],r=s['r'],
                status=s['status'],created=s['created'],battle_at=s['battle_at'],finish=s['finish'],
                reason=s['data'].get('reason',''),won=s['data'].get('won'),announced=s['announced']))
        if own:
            initialize(own['data']);owned=self._siege_land(own)
            for other in rows:
                if other['owner']==actor:continue
                for point in sorted(self._siege_land(other)-{(other['q'],other['r'])}):
                    if not any(point in neighbours(*p) for p in owned):continue
                    reasons=self._siege_reasons(own,other,point,now)
                    targets.append(dict(defender=other['id'],name=other['name'],q=point[0],r=point[1],reasons=reasons))
        return dict(wars=wars,targets=targets,fee=SIEGE_FEE,warning_hours=24,battle_hours=6,shield_hours=72)

    async def kingdom_siege_sweep(self):
        async with self._lock:
            with self.connection:
                for row in self.connection.execute("SELECT DISTINCT chat FROM kingdom_sieges WHERE status IN ('notice','warning','battle')").fetchall():
                    self._kingdom_siege_advance_locked(row['chat'])

    async def kingdom_siege_notices(self):
        async with self._lock:
            with self.connection:
                now=self._siege_clock();result=[]
                for raw in self.connection.execute("SELECT id FROM kingdom_sieges WHERE status='notice' AND retry_at<=? AND attempts<3 ORDER BY created LIMIT 10",(now,)).fetchall():
                    s=self._siege_row(raw['id']);a=self._kingdom_row_locked(s['attacker']);b=self._kingdom_row_locked(s['defender'])
                    self.connection.execute('UPDATE kingdom_sieges SET retry_at=?,attempts=attempts+1 WHERE id=?',(now+300,s['id']))
                    result.append(dict(id=s['id'],chat=s['chat'],attacker=a['name'],defender=b['name'],owner=b['owner'],q=s['q'],r=s['r']))
                return result

    async def kingdom_siege_announced(self,ident):
        async with self._lock:
            with self.connection:
                s=self._siege_row(ident)
                if s['status']!='notice':return False
                now=self._siege_clock()
                if s['created']+HOUR<=now:
                    self._siege_cancel(s,'Доставка предупреждения просрочена. Осада отменена, затраты возвращены.',refund=True);return False
                s.update(status='warning',announced=now,battle_at=now+24*HOUR,finish=now+30*HOUR)
                for key in ('attacker','defender'):
                    town=self._kingdom_row_locked(s[key]);town['data']['military']['siege_lock']['phase']='warning'
                    if key=='attacker':
                        opponents=initialize(town['data'])['opponents']
                        opponents={other:at for other,at in opponents.items() if at>now-7*DAY}
                        opponents[s['defender']]=now;town['data']['pvp']['opponents']=opponents
                    self._kingdom_log(town,'Объявлена осада. До боя сутки, до результата 30 часов. Открой /карта → Войны.',now)
                    self._kingdom_save_locked(town)
                self._siege_save(s);return True
