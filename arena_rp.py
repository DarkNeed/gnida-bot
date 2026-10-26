"""Private RP templates. Never grants content, modifies profiles or pays rewards."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import secrets
import time

from arena_engine import BUILTIN_PASSIVES, create_battle_state, stats_for
from arena_archclasses import ARCHCLASSES
from arena_progression import choice_avatar

STAT_NAMES = ('max_hp', 'resource_max', 'physical_attack', 'magic_attack',
              'physical_defense', 'magic_defense', 'speed', 'evasion')
SCRIPTED = {
    'chaplain_rewind': 'Откат раунда требует сценария Капеллана и недоступен как отдельный навык.',
    'kit_field': 'Поле Кита требует сценария босса и недоступно как отдельный навык.',
}
BOSS_NOTES = {
    'doof_deport': 'Прямой урон инатора работает; высылка игрока требует сценария Фуфелшмерца.',
    'whaler_miasma': 'Здесь выполняется прямой урон атаки. Для наложения чумы выбери трактат «Миазмы».',
    'whaler_punishment': 'Физическая часть Кары. Магическая часть выбирается отдельным навыком.',
    'whaler_rot': 'Физическая часть Гнили. Ритуал, массовые цели и магическая часть — отдельные действия.',
    'kit_reflection': 'Физическая часть Отражения. Пепельная сторона выбирается отдельным навыком.',
    'kit_coins': 'Физическая сторона монеты. Обратная магическая сторона выбирается отдельно.',
}


def rp_skills(skills):
    from arena_raid_engine import BOSS_SKILLS
    return {**skills, **BOSS_SKILLS}


def rp_passives(classes):
    result = {key: dict(asdict(p), description=' · '.join(e.get('description', e['kind']) for e in p.effects))
              for key, p in BUILTIN_PASSIVES.items()}
    for cid, cls in classes.items():
        for index, passive in enumerate(cls.passives):
            key = f'inherent:{cid}:{index}'
            result[key] = dict(skill_id=key, name=passive.get('name', key), class_id=cid,
                               rarity=cls.rarity, description=passive.get('description', ''), effects=[passive])
    return result


def warnings(skill, class_id='', branch=''):
    notes = []
    if skill.skill_id in SCRIPTED:
        notes.append(SCRIPTED[skill.skill_id])
    if skill.skill_id in BOSS_NOTES:
        notes.append(BOSS_NOTES[skill.skill_id])
    if skill.class_id not in (class_id, 'universal', 'ragamuffin'):
        notes.append('Чужой класс: его механика накоплений не выдаётся автоматически.')
    required = next((t.split(':', 1)[1] for t in skill.tags if t.startswith('archclass:')), '')
    if required and required != branch:
        notes.append('Приём чужой ветки: боевые условия и нужные накопления сохраняются.')
    if skill.skill_id.startswith(('kit_', 'whaler_', 'doof_', 'chaplain_')):
        notes.append('Отдельная атака: фазы, реакции и сценарий исходного босса не переносятся.')
    if any(t in skill.tags for t in ('once_per_battle', 'once_on_hit', 'twice_per_battle')):
        notes.append('Лимит применений за бой сохраняется.')
    return notes


def rp_restriction(side, skill):
    if side.get('rp_sandbox') and skill.skill_id in SCRIPTED:
        return SCRIPTED[skill.skill_id]
    return ''


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label}: целое число от {low} до {high}.')
    return value


def text(value, limit, label, *, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f'{label}: от {0 if empty else 1} до {limit} символов.')
    return value.strip()


def normalize_template(value, kind, classes, skills, passives):
    if not isinstance(value, dict) or kind not in ('character', 'mob'):
        raise ValueError('Некорректный RP-шаблон.')
    cid = value.get('class_id', 'ragamuffin')
    if not isinstance(cid, str) or cid not in classes:
        raise ValueError('Неизвестный класс.')
    level = integer(value.get('level', 1), 1, 20, 'Уровень')
    branch = value.get('archclass_id', '')
    if not isinstance(branch, str) or branch and (branch not in ARCHCLASSES or ARCHCLASSES[branch]['class_id'] != cid or level < 10):
        raise ValueError('Ветка должна соответствовать классу; доступна с 10 уровня.')
    stage = value.get('archclass_stage', 20)
    if type(stage) is not int or stage not in (10, 20):
        raise ValueError('Ступень ветки: 10 или 20.')
    stage = 10 if level < 20 else stage
    result = dict(name=text(value.get('name', ''), 80, 'Имя', empty=False),
                  description=text(value.get('description', ''), 2000, 'Описание'),
                  class_id=cid, level=level, archclass_id=branch, archclass_stage=stage,
                  defense_mode=value.get('defense_mode', 'dodge'))
    from arena_encounters import MOBS
    preset=value.get('preset_id','')
    if not isinstance(preset,str) or preset and preset not in MOBS:
        raise ValueError('Неизвестный внешний вид готового моба.')
    result['preset_id']=preset if kind=='mob' else ''
    if result['defense_mode'] not in ('dodge', 'block'):
        raise ValueError('Защита: блок или уклонение.')
    for field, catalog in (('skills', skills), ('passives', passives)):
        ids = value.get(field, ['bum_punch'] if field == 'skills' else [])
        if not isinstance(ids, list) or len(ids) > len(catalog) or any(not isinstance(i, str) or i not in catalog for i in ids):
            raise ValueError('Выбери навыки из RP-каталога.')
        if len(set(ids)) != len(ids):
            raise ValueError('Один навык нельзя добавить дважды.')
        result[field] = ids
    for field in ('avatar_key', 'sprite_key'):
        key = value.get(field, '')
        if not isinstance(key, str) or key and (len(key) != 64 or any(c not in '0123456789abcdef' for c in key)):
            raise ValueError('Некорректное изображение.')
        result[field] = key
    if type(value.get('flip', False)) is not bool:
        raise ValueError('Некорректное отражение.')
    result['flip'] = value.get('flip', False)
    scale = value.get('scale', 1)
    if type(scale) not in (int, float) or not math.isfinite(scale) or not .5 <= scale <= 2:
        raise ValueError('Размер спрайта: от 0,5 до 2.')
    result['scale'] = scale if kind == 'mob' else 1
    result['stats'] = {}
    if kind == 'mob':
        overrides = value.get('stats', {})
        if not isinstance(overrides, dict) or set(overrides) - set(STAT_NAMES):
            raise ValueError('Некорректные характеристики.')
        for key, number in overrides.items():
            ceiling = 100 if key == 'evasion' else 100000 if key == 'max_hp' else 10000
            result['stats'][key] = integer(number, 1 if key in ('max_hp', 'resource_max') else 0, ceiling, key)
    ai = value.get('ai', 'random')
    if not isinstance(ai, str) or ai not in ('random', 'sequence', 'priority'):
        raise ValueError('Поведение: случайное, последовательность или приоритеты.')
    result['ai'] = ai
    return result


def template_source(template, actor):
    v = template['definition']
    return dict(slave_id=actor, owner_id=actor, class_id=v['class_id'], level=v['level'],
                archclass_id=v['archclass_id'], archclass_stage=v['archclass_stage'],
                progression_level=20 if v['level'] >= 20 else 10 if v['level'] >= 10 else 5,
                loadout=v['skills'], passive_details=[], defense_mode=v['defense_mode'])


def template_fighter(template, actor, classes, skills):
    source = template_source(template, actor)
    v = template['definition']
    fighter = create_battle_state(source, source, classes=classes, skills=skills)['sides']['a']
    passives = rp_passives(classes)
    details = [deepcopy(passives[p]) for p in v['passives']]
    # Do not route this free loadout through the ordinary character normalizer.
    fighter.update(rp_sandbox=True, rp_template_id=template['id'], rp_template_revision=template['revision'],
                   name=v['name'], rp_description=v['description'], loadout=list(v['skills']),
                   passive_details=details, effects=[], rp_ai=v['ai'], rp_ai_index=0,
                   rp_avatar_key=v['avatar_key'], rp_sprite_key=v['sprite_key'],
                   rp_builtin_sprite=v.get('preset_id',''),
                   rp_flip=v['flip'], rp_scale=v['scale'])
    starting = {'accuracy_flat', 'damage_pct', 'speed_pct', 'physical_defense_pct',
                'magic_defense_pct', 'evasion_flat', 'physical_attack_pct', 'magic_attack_pct'}
    for p in details:
        for effect in p['effects']:
            if effect['kind'] in starting:
                fighter['effects'].append(dict(effect, duration=1000000))
    fighter['stats'].update(v['stats'])
    fighter['hp'] = fighter['stats']['max_hp']
    fighter['resource'] = fighter['stats']['resource_max']
    return fighter


def appearance(fighter):
    from arena_encounters import MOBS
    avatar = fighter.get('rp_avatar_key')
    sprite = fighter.get('rp_sprite_key')
    default=MOBS.get(fighter.get('rp_builtin_sprite'),{}).get('sprite')
    return dict(class_avatar_url='/rp/images/' + avatar + '.png' if avatar else default or choice_avatar(
                    fighter['class_id'], fighter.get('archclass_id', ''), fighter.get('archclass_stage', 20)),
                sprite_url='/rp/images/' + sprite + '.png' if sprite else '',
                rp_flip=fighter.get('rp_flip', False), rp_scale=fighter.get('rp_scale', 1), pixel_art=False)


class RPMixin:
    def _connect_rp(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS arena_rp_templates (
                id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, kind TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1, definition_json TEXT NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_rp_templates_owner ON arena_rp_templates(owner_id,kind);
            CREATE TABLE IF NOT EXISTS arena_rp_images (
                key TEXT NOT NULL, owner_id INTEGER NOT NULL, png BLOB NOT NULL,
                PRIMARY KEY(key,owner_id));
            CREATE TABLE IF NOT EXISTS arena_rp_selections (
                token TEXT NOT NULL, actor_id INTEGER NOT NULL, template_id TEXT NOT NULL,
                PRIMARY KEY(token,actor_id));
            CREATE TABLE IF NOT EXISTS arena_rp_requests (
                owner_id INTEGER NOT NULL, nonce TEXT NOT NULL, fingerprint TEXT NOT NULL,
                token TEXT NOT NULL, PRIMARY KEY(owner_id,nonce));
            CREATE INDEX IF NOT EXISTS idx_rp_requests_token ON arena_rp_requests(token);
        ''')

    def _rp_template_locked(self, actor, ident, kind=None):
        if not isinstance(ident, str):
            raise ValueError('Некорректный шаблон.')
        row = self.connection.execute('SELECT * FROM arena_rp_templates WHERE id=? AND owner_id=?', (ident, actor)).fetchone()
        if not row or kind and row['kind'] != kind:
            raise ValueError('RP-шаблон не найден или принадлежит другому пользователю.')
        return dict(id=row['id'], kind=row['kind'], revision=row['revision'], definition=json.loads(row['definition_json']))

    async def arena_rp_templates(self, actor):
        async with self._lock:
            return [self._rp_template_locked(actor, r['id']) for r in self.connection.execute(
                'SELECT id FROM arena_rp_templates WHERE owner_id=? ORDER BY updated_at DESC,id', (actor,)).fetchall()]

    async def arena_rp_save(self, actor, kind, value, *, ident=None, revision=None):
        async with self._lock:
            with self.connection:
                classes, skills = self._fighter_catalog_locked()
                v = normalize_template(value, kind, classes, rp_skills(skills), rp_passives(classes))
                for key in (v['avatar_key'], v['sprite_key']):
                    if key and not self.connection.execute('SELECT 1 FROM arena_rp_images WHERE key=? AND owner_id=?', (key, actor)).fetchone():
                        raise ValueError('Сначала загрузи своё изображение.')
                now = int(time.time())
                if ident is not None:
                    old = self._rp_template_locked(actor, ident, kind)
                    if type(revision) is not int or old['revision'] != revision:
                        raise ValueError('Шаблон изменился. Обнови его перед сохранением.')
                    self.connection.execute('UPDATE arena_rp_templates SET definition_json=?,revision=revision+1,updated_at=? WHERE id=?',
                                            (json.dumps(v, ensure_ascii=False), now, ident))
                else:
                    ident = secrets.token_hex(12)
                    self.connection.execute('INSERT INTO arena_rp_templates VALUES(?,?,?,1,?,?,?)',
                                            (ident, actor, kind, json.dumps(v, ensure_ascii=False), now, now))
                return self._rp_template_locked(actor, ident)

    async def arena_rp_delete(self, actor, ident, revision):
        async with self._lock:
            with self.connection:
                old = self._rp_template_locked(actor, ident)
                if type(revision) is not int or revision != old['revision']:
                    raise ValueError('Шаблон изменился. Обнови список.')
                self.connection.execute('DELETE FROM arena_rp_templates WHERE id=? AND owner_id=?', (ident, actor))

    async def arena_rp_image(self, actor, png):
        key = hashlib.sha256(png).hexdigest()
        async with self._lock:
            with self.connection:
                known = self.connection.execute('SELECT 1 FROM arena_rp_images WHERE key=? AND owner_id=?', (key, actor)).fetchone()
                size = self.connection.execute('SELECT COALESCE(SUM(LENGTH(png)),0) FROM arena_rp_images WHERE owner_id=?', (actor,)).fetchone()[0]
                if not known and size + len(png) > 32 * 1024 * 1024:
                    raise ValueError('Лимит RP-изображений аккаунта — 32 МБ. Уменьши размер PNG.')
                self.connection.execute('INSERT OR IGNORE INTO arena_rp_images VALUES(?,?,?)', (key, actor, png))
        return key

    async def arena_rp_image_png(self, key):
        async with self._lock:
            row = self.connection.execute('SELECT png FROM arena_rp_images WHERE key=? LIMIT 1', (key,)).fetchone()
            return bytes(row['png']) if row else None

    async def arena_rp_catalog(self):
        from arena_encounters import MOBS
        async with self._lock:
            classes, skills = self._fighter_catalog_locked()
            catalog = rp_skills(skills)
            presets = []
            for key, mob in MOBS.items():
                values = {k: round(v) for k,v in stats_for('ragamuffin', 1, classes=classes).items() if k in STAT_NAMES}
                values.update(max_hp=mob['hp'] + mob['growth'], physical_attack=6, magic_attack=6 if key == 'shaman' else 0,
                              physical_defense=6 if key == 'brute' else 2, magic_defense=2, evasion=10 if key == 'goblin' else 3)
                presets.append(dict(id=key, name=mob['name'], role=mob['role'], sprite=mob['sprite'], skill=mob['skill'],
                                    definition=dict(name=mob['name'], description=mob['role'], class_id='ragamuffin', level=1,preset_id=key,
                                                    skills=[mob['skill']], passives=[], stats=values, ai='priority')))
            return dict(classes=[dict(id=k, name=c.name, avatar=choice_avatar(k), resource_name=c.resource_name,
                                      branches=[dict(id=b, **info, avatar=choice_avatar(k,b,10), final_avatar=choice_avatar(k,b,20)) for b, info in ARCHCLASSES.items() if info['class_id'] == k])
                                 for k, c in classes.items()],
                        skills=[dict(asdict(s), warnings=warnings(s), scripted=s.skill_id in SCRIPTED)
                                for s in catalog.values()],
                        passives=list(rp_passives(classes).values()),
                        mobs=presets)

    async def arena_rp_preview(self, actor, kind, value):
        from arena_engine import effective_skill, skill_restriction
        from arena_raid_engine import pair_state
        from arena_rpg_descriptions import skill_description
        async with self._lock:
            classes, ordinary = self._fighter_catalog_locked()
            skills = rp_skills(ordinary)
            v = normalize_template(value, kind, classes, skills, rp_passives(classes))
            f = template_fighter(dict(id='preview', revision=0, definition=v), actor, classes, skills)
            pair = pair_state(f, deepcopy(f))
            details = []
            for sid in f['loadout']:
                skill = effective_skill(pair, 'a', sid, skills)
                details.append(dict(asdict(skill), description=skill_description(skill,f), warnings=warnings(skill, v['class_id'], v['archclass_id']),
                                    unavailable_reason=skill_restriction(f, skill)))
            return dict(stats=f['stats'], skills=details)

    async def arena_rp_encounter_create(self, chat, actor, roster, nonce):
        from arena_encounters import MOBS
        from arena_raid import RAID_LOBBY_SECONDS
        if not isinstance(roster, list) or not 1 <= len(roster) <= 3:
            raise ValueError('Выбери от одного до трёх противников.')
        if not isinstance(nonce, str) or not 16 <= len(nonce) <= 80:
            raise ValueError('Некорректный номер запроса.')
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat, 'arena')
                chosen = []
                for item in roster:
                    if not isinstance(item, dict) or item.get('kind') not in ('builtin', 'mob') or not isinstance(item.get('id'), str):
                        raise ValueError('Некорректный противник.')
                    if item['kind'] == 'builtin':
                        if item['id'] not in MOBS:
                            raise ValueError('Неизвестный моб.')
                        name = MOBS[item['id']]['name']
                    else:
                        name = self._rp_template_locked(actor, item['id'], 'mob')['definition']['name']
                    chosen.append(dict(kind=item['kind'], id=item['id'], name=name))
                fingerprint = hashlib.sha256(json.dumps([chat, [dict(kind=i['kind'], id=i['id']) for i in chosen]], sort_keys=True).encode()).hexdigest()
                old = self.connection.execute('SELECT * FROM arena_rp_requests WHERE owner_id=? AND nonce=?', (actor, nonce)).fetchone()
                if old:
                    if old['fingerprint'] != fingerprint:
                        raise ValueError('Номер запроса уже использован для другой встречи.')
                    return self._raid_row_locked(old['token'])
                self._raid_expire_locked()
                if self.connection.execute("SELECT 1 FROM arena_raids WHERE chat_id=? AND creator_id=? AND boss_id='encounter' AND status IN ('lobby','active')", (chat, actor)).fetchone():
                    raise ValueError('Сначала заверши или отмени свою текущую встречу в этом чате.')
                now, token = int(time.time()), secrets.token_urlsafe(12)
                self.connection.execute('''INSERT INTO arena_raids
                    (token,chat_id,creator_id,created_at,deadline,boss_id,encounter_json,silent)
                    VALUES(?,?,?,?,?,'encounter',?,1)''',
                    (token, chat, actor, now, now + RAID_LOBBY_SECONDS, json.dumps(dict(rp=True, roster=chosen), ensure_ascii=False)))
                self.connection.execute('INSERT INTO arena_rp_requests VALUES(?,?,?,?)', (actor, nonce, fingerprint, token))
                return self._raid_row_locked(token)

    def _rp_source_locked(self, actor, ident):
        template = self._rp_template_locked(actor, ident, 'character')
        return dict(template_source(template, actor), _rp_template=template)

    def _rp_roster_locked(self, row):
        config = json.loads(row['encounter_json'])
        if not config.get('rp'):
            return config['roster']
        result = []
        for item in config['roster']:
            result.append(item['id'] if item['kind'] == 'builtin' else
                          self._rp_template_locked(row['creator_id'], item['id'], 'mob'))
        return result
