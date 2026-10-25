"""Persistent PvE expeditions: snapshots, atomic rewards, no combat reservations."""

import hashlib
import json
import random
import re
import uuid

from arena_archclasses import class_title
from arena_engine import FIGHTER_CLASSES, stats_for, passive_skill_limit
from arena_progression import choice_avatar

EXPEDITIONS = {
    'outskirts': dict(name='Окраины', duration=1800, recommended='5–10', power=43,
                      base_loss=7, francs=50, pages=1, page_rarity='common'),
    'quarter': dict(name='Заброшенный квартал', duration=7200, recommended='12–16', power=78,
                    base_loss=14, francs=150, pages=2, page_rarity='uncommon'),
    'ruins': dict(name='Проклятые руины', duration=21600, recommended='18–20', power=108,
                  base_loss=23, francs=340, pages=3, page_rarity='rare'),
}
PARTICIPANT_COOLDOWN = 6 * 3600


def now():
    from database import utc_timestamp
    return utc_timestamp()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def participant_ids(values):
    if (not isinstance(values, list) or not 1 <= len(values) <= 5
            or any(type(v) is not int or v <= 0 for v in values) or len(set(values)) != len(values)):
        raise ValueError('Выбери от одного до пяти разных участников.')
    return sorted(values)


class ExpeditionMixin:
    def _init_expeditions(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS slave_expeditions(
                id TEXT PRIMARY KEY,chat_id INTEGER NOT NULL,owner_id INTEGER NOT NULL,
                mission TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',
                started_at INTEGER NOT NULL,ends_at INTEGER NOT NULL,finished_at INTEGER,
                nonce TEXT NOT NULL,quote_json TEXT NOT NULL,result_json TEXT NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0,UNIQUE(owner_id,nonce));
            CREATE UNIQUE INDEX IF NOT EXISTS idx_expedition_owner_active
                ON slave_expeditions(owner_id) WHERE status='active';
            CREATE INDEX IF NOT EXISTS idx_expedition_due ON slave_expeditions(status,ends_at);
            CREATE TABLE IF NOT EXISTS slave_expedition_members(
                expedition_id TEXT NOT NULL,user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,acquired_at INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1,
                started_at INTEGER NOT NULL,ended_at INTEGER,snapshot_json TEXT NOT NULL,
                PRIMARY KEY(expedition_id,user_id));
            CREATE UNIQUE INDEX IF NOT EXISTS idx_expedition_member_active
                ON slave_expedition_members(user_id) WHERE active=1;
            CREATE INDEX IF NOT EXISTS idx_expedition_member_history
                ON slave_expedition_members(user_id,started_at);
            CREATE TRIGGER IF NOT EXISTS expedition_release AFTER DELETE ON ownership
            BEGIN UPDATE slave_expedition_members SET active=0,ended_at=CAST(strftime('%s','now') AS INTEGER)
                WHERE chat_id=OLD.chat_id AND owner_id=OLD.owner_id AND user_id=OLD.slave_id AND active=1; END;
            CREATE TRIGGER IF NOT EXISTS expedition_transfer AFTER UPDATE OF owner_id,acquired_at ON ownership
            WHEN OLD.owner_id<>NEW.owner_id OR OLD.acquired_at<>NEW.acquired_at
            BEGIN UPDATE slave_expedition_members SET active=0,ended_at=CAST(strftime('%s','now') AS INTEGER)
                WHERE chat_id=OLD.chat_id AND owner_id=OLD.owner_id AND user_id=OLD.slave_id AND active=1; END;
        ''')

    def _expedition_away_locked(self, chat, owner, worker, begin, end):
        return bool(self.connection.execute('''SELECT 1 FROM slave_expedition_members
            WHERE chat_id=? AND owner_id=? AND user_id=? AND started_at<?
            AND (ended_at IS NULL OR ended_at>?) LIMIT 1''', (chat, owner, worker, end, begin)).fetchone())

    def _expedition_source_locked(self, chat, user, catalog=None):
        # Reading another participant must not auto-create a character, resolve
        # their choices, modify loadouts or save/switch their active slot.
        raw = self.connection.execute('SELECT * FROM personal_profiles WHERE chat_id=0 AND user_id=?', (user,)).fetchone()
        p = dict(raw) if raw else dict(class_id='ragamuffin', level=1, loadout='["bum_punch"]', passive_loadout='[]')
        classes, skills = catalog or self._fighter_catalog_locked()
        cls = classes.get(p['class_id'], FIGHTER_CLASSES['ragamuffin'])
        level = max(1, min(20, p['level']))
        stats = stats_for(cls.class_id, level, classes=classes)
        loadout = [s for s in json.loads(p['loadout']) if s in skills][:4]
        passives = json.loads(p.get('passive_loadout') or '[]')[:passive_skill_limit(level)]
        skill_power = sum(min(30, max(0, skills[s].power)) / (1+max(0, skills[s].cooldown)*.15)
                          + min(3,len(skills[s].effects))*2 for s in loadout) / max(1,len(loadout))
        power = round(level * 3 + stats['max_hp'] * .12
                      + max(stats['physical_attack'], stats['magic_attack']) * .5
                      + (stats['physical_defense'] + stats['magic_defense']) * .2
                      + stats['speed'] * .15 + len(loadout) * 2 + len(passives) * 2
                      + skill_power*.18 + (4 if p.get('archclass_id') else 0), 1)
        from slave_identity import TRAITS
        identity=self._slave_identity_locked(user)
        base_power=power
        power=round(power*(100+identity['expedition_bonus']+TRAITS[identity['trait_id']].get('power',0))/100,1)
        account = self.connection.execute('SELECT active_slot FROM arena_character_accounts WHERE user_id=?', (user,)).fetchone()
        slot = account['active_slot'] if account else 1
        sprite = self.connection.execute('SELECT sprite_key FROM arena_sprites WHERE chat_id=0 AND user_id=?', (user,)).fetchone()
        return dict(user_id=user, character_slot=slot, class_id=cls.class_id, level=level,
                    class_name=class_title(p, cls.name), archclass_id=p.get('archclass_id', ''),
                    avatar_url='/sprites/'+sprite['sprite_key']+'.png' if sprite and sprite['sprite_key'] else
                        choice_avatar(cls.class_id, p.get('archclass_id', ''), p.get('archclass_stage', 10)),
                    loadout=loadout, passives=passives, power=power,base_power=base_power,identity=identity)

    def _expedition_quote_locked(self, chat, owner, mission, users):
        self._require_feature_locked(chat, 'slavery')
        self._require_feature_locked(chat, 'arena')
        if mission not in EXPEDITIONS:
            raise ValueError('Неизвестная экспедиция.')
        users = participant_ids(users)
        if self.connection.execute("SELECT 1 FROM slave_expeditions WHERE owner_id=? AND status='active'", (owner,)).fetchone():
            raise ValueError('У тебя уже есть экспедиция. Лимит общий для всех чатов.')
        members = [];catalog=self._fighter_catalog_locked()
        for user in users:
            owned = self.connection.execute('SELECT acquired_at FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?', (chat, owner, user)).fetchone()
            if not owned:
                raise ValueError('Один из участников больше не принадлежит тебе.')
            if self._trader_listed_locked(chat,user):
                raise ValueError('Участник выставлен на продажу. Сначала сними предложение у работорговца.')
            if self.connection.execute("SELECT 1 FROM slave_recovery_events WHERE chat_id=? AND slave_id=? AND status IN ('announcing','pending','playing')", (chat, user)).fetchone():
                raise ValueError('Участник сейчас пропал. Сначала закончи его возвращение.')
            recent = self.connection.execute('''SELECT MAX(started_at) AS latest,MAX(active) AS active
                FROM slave_expedition_members WHERE user_id=?''', (user,)).fetchone()
            if recent['active'] or (recent['latest'] is not None and recent['latest'] + PARTICIPANT_COOLDOWN > now()):
                raise ValueError(f'Участник {user}: поход уже идёт или не прошло 6 часов с предыдущей отправки.')
            p = self._expedition_source_locked(chat, user,catalog)
            from slave_identity import TRAITS
            trait=TRAITS[p['identity']['trait_id']]
            mission_bonus=trait.get('mission_power',{}).get(mission,0)
            if mission_bonus:p['power']=round(p['power']+p['base_power']*mission_bonus/100,1)
            name = self.connection.execute('SELECT display_name FROM users WHERE chat_id=? AND user_id=?', (chat, user)).fetchone()
            p.update(name=name['display_name'] if name else str(user), acquired_at=owned['acquired_at'])
            members.append(p)
        cfg = EXPEDITIONS[mission]
        families = {m['class_id'] for m in members}
        healers = bool(families & {'priest', 'cutie'})
        guards = bool(families & {'warrior', 'jock', 'middle'})
        scouts = bool(families & {'hunter', 'pinky', 'index'})
        arcane = bool(families & {'mage', 'nerd', 'ring'})
        avg = sum(m['power'] for m in members) / len(members)
        chance = max(10, min(95, round(avg/cfg['power']*62 + len(members)*3 + len(families)*2 + 3*scouts + 2*arcane)))
        for m in members:
            trait=TRAITS[m['identity']['trait_id']]
            m['loss_win'] = max(2, min(60, round(cfg['base_loss'] + (cfg['power']-m['power'])*.55 - 3*healers - 2*guards+trait.get('loss',0))))
            m['loss_fail'] = max(2,min(65, m['loss_win'] + 8+trait.get('failure_loss',0)))
        reward = cfg['francs'] * len(members)
        value = dict(mission=mission, name=cfg['name'], duration=cfg['duration'], members=members,
                     chance=chance, owner_francs=reward, participant_francs=max(5, cfg['francs']//5),
                     pages=cfg['pages'], page_rarity=cfg['page_rarity'],
                     bonuses=[s for active,s in ((healers,'Поддержка: риск −3 п.п.'),(guards,'Прикрытие: риск −2 п.п.'),
                                                  (scouts,'Разведка: успех +3 п.п.'),(arcane,'Аномалии: успех +2 п.п.')) if active])
        value['revision'] = digest(value)
        return value

    async def expedition_quote(self, chat, owner, mission, users):
        async with self._lock:
            with self.connection:
                self._expedition_finish_due_locked()
                return self._expedition_quote_locked(chat, owner, mission, users)

    async def expedition_start(self, chat, owner, mission, users, revision, nonce, rng=None):
        if not isinstance(nonce, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', nonce):
            raise ValueError('Обнови подтверждение отправки.')
        rng = rng or random.SystemRandom()
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat, 'slavery')
                self._require_feature_locked(chat, 'arena')
                replay = self.connection.execute('SELECT * FROM slave_expeditions WHERE owner_id=? AND nonce=?', (owner, nonce)).fetchone()
                if replay:
                    if replay['chat_id'] != chat or replay['mission'] != mission or sorted(m['user_id'] for m in json.loads(replay['quote_json'])['members']) != participant_ids(users):
                        raise ValueError('Это подтверждение относится к другой экспедиции.')
                    return replay['id']
                self._expedition_finish_due_locked()
                quote = self._expedition_quote_locked(chat, owner, mission, users)
                if revision != quote['revision']:
                    raise ValueError('Состав или персонажи изменились. Заново проверь отряд.')
                stamp = now()
                self._enterprise_settle_owner_locked(chat, owner, stamp)
                won = rng.random()*100 < quote['chance']
                # Rolls persist at departure, but are never serialized while active.
                result = dict(won=won, lost=[m['user_id'] for m in quote['members']
                    if rng.random()*100 < m['loss_win' if won else 'loss_fail']])
                token = uuid.uuid4().hex
                self.connection.execute('''INSERT INTO slave_expeditions
                    (id,chat_id,owner_id,mission,started_at,ends_at,nonce,quote_json,result_json)
                    VALUES(?,?,?,?,?,?,?,?,?)''', (token, chat, owner, mission, stamp,
                    stamp+quote['duration'], nonce, json.dumps(quote, ensure_ascii=False), json.dumps(result)))
                for m in quote['members']:
                    self.connection.execute('''INSERT INTO slave_expedition_members
                        (expedition_id,user_id,chat_id,owner_id,acquired_at,started_at,snapshot_json)
                        VALUES(?,?,?,?,?,?,?)''', (token,m['user_id'],chat,owner,m['acquired_at'],stamp,json.dumps(m)))
                return token

    def _expedition_finish_due_locked(self):
        stamp = now()
        rows = self.connection.execute("SELECT * FROM slave_expeditions WHERE status='active'").fetchall()
        for row in rows:
            disabled = not self._feature_enabled_locked(row['chat_id'], 'slavery') or not self._feature_enabled_locked(row['chat_id'], 'arena')
            if not disabled and row['ends_at'] > stamp:
                continue
            self._expedition_finish_locked(row, cancel=disabled)

    def _expedition_finish_locked(self, row, cancel=False):
        if row['status'] != 'active':
            return
        stamp = now(); end = min(stamp, row['ends_at'])
        quote = json.loads(row['quote_json']); rolls = json.loads(row['result_json'])
        # Returnees resume work at the scheduled time, even after downtime.
        # Lost members never earn retroactive wages between deadline and sweep.
        for member in self.connection.execute('SELECT * FROM slave_expedition_members WHERE expedition_id=? AND active=1',(row['id'],)).fetchall():
            absence_end=stamp if not cancel and member['user_id'] in rolls['lost'] else end
            self.connection.execute('UPDATE slave_expedition_members SET ended_at=? WHERE expedition_id=? AND user_id=?',(absence_end,row['id'],member['user_id']))
        self._enterprise_settle_owner_locked(row['chat_id'], row['owner_id'], stamp)
        results=[]; survivors=0
        for member in self.connection.execute('SELECT * FROM slave_expedition_members WHERE expedition_id=?', (row['id'],)).fetchall():
            owned = self.connection.execute('''SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=?
                AND slave_id=? AND acquired_at=?''', (row['chat_id'],row['owner_id'],member['user_id'],member['acquired_at'])).fetchone()
            valid = bool(member['active'] and owned)
            outcome = 'cancelled' if cancel else 'removed' if not valid else 'freed' if member['user_id'] in rolls['lost'] else 'returned'
            # Mark absence ended before deleting ownership (release triggers).
            self.connection.execute('UPDATE slave_expedition_members SET active=0,ended_at=COALESCE(ended_at,?) WHERE expedition_id=? AND user_id=?', (end,row['id'],member['user_id']))
            if valid and outcome == 'freed':
                self.connection.execute('DELETE FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=? AND acquired_at=?', (row['chat_id'],row['owner_id'],member['user_id'],member['acquired_at']))
                self.connection.execute('DELETE FROM business_workers WHERE chat_id=? AND owner_id=? AND worker_id=?', (row['chat_id'],row['owner_id'],member['user_id']))
            elif valid and outcome == 'returned':
                survivors += 1
                if rolls['won']:
                    self._credit_labor_income_locked(row['chat_id'],member['user_id'],quote['participant_francs'],stamp)
            results.append(dict(user_id=member['user_id'],outcome=outcome))
        francs = quote['owner_francs']*survivors//len(quote['members']) if not cancel and rolls['won'] else 0
        pages = quote['pages'] if francs and survivors else 0
        if francs:
            # Expedition money shares enterprise progressive taxes. No untaxed
            # parallel farm; the ledger remains available after site closure.
            from database import BUSINESS_STATS_TZ
            from datetime import datetime
            francs,tax=self._credit_business_income_locked(row['chat_id'],row['owner_id'],datetime.fromtimestamp(stamp,BUSINESS_STATS_TZ).date().isoformat(),francs)
        else:
            tax=0
        if pages:
            wallet=self._forge_wallet_locked(0,row['owner_id'])
            rarity=quote['page_rarity'];wallet['pages'][rarity]=wallet['pages'].get(rarity,0)+pages
            self._forge_save_wallet_locked(0,row['owner_id'],wallet)
        public=dict(won=bool(not cancel and rolls['won']),members=results,francs=francs,tax=tax,pages=pages,page_rarity=quote['page_rarity'])
        self.connection.execute('UPDATE slave_expeditions SET status=?,finished_at=?,result_json=? WHERE id=?', ('cancelled' if cancel else 'finished',stamp,json.dumps(public),row['id']))

    async def expedition_sweep(self):
        async with self._lock:
            with self.connection:
                self._expedition_finish_due_locked()
                return [dict(r) for r in self.connection.execute("SELECT id,chat_id,owner_id FROM slave_expeditions WHERE status<>'active' AND notified=0 ORDER BY started_at LIMIT 20")]

    async def expedition_notified(self, token):
        async with self._lock:
            self.connection.execute('UPDATE slave_expeditions SET notified=1 WHERE id=? AND status<>\'active\'', (token,))
            self.connection.commit()

    def _expedition_public_locked(self, chat, owner):
        rows=self.connection.execute('SELECT * FROM slave_expeditions WHERE chat_id=? AND owner_id=? ORDER BY started_at DESC,rowid DESC LIMIT 10', (chat,owner)).fetchall()
        return [dict(id=r['id'],mission=r['mission'],status=r['status'],started_at=r['started_at'],ends_at=r['ends_at'],
                     quote=json.loads(r['quote_json']),result=json.loads(r['result_json']) if r['status']!='active' else None) for r in rows]
