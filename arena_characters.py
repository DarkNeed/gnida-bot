"""Five character slots, one account economy and one RPG reservation.

personal_profiles(chat_id=0) is the authoritative active working profile.
Inactive slots keep complete snapshots. Swapping profile, learned records and
sprite is a single transaction under the same lock used by battle settlement.
Never restore an old snapshot of the active slot on startup.
"""
import json
import time

from arena_archclasses import ARCHCLASSES
from arena_progression import choice_avatar
from arena_engine import FIGHTER_CLASSES
from arena_raid_engine import finish_if_needed

CHARACTER_PACK = 'characters'
CHARACTER_PRICE = 200
CHARACTER_TERMS_VERSION = 'characters-2026-10-14-v1'
CHARACTER_TERMS = (
    'Четыре дополнительных персонажа — 200 Stars, одна покупка без подписки. '
    'Всего пять слотов во всех чатах. Новые персонажи начинают с первого уровня. '
    'Класс, опыт, навыки и внешний вид отдельные; инвентарь, питомцы, ресурсы и '
    'лимиты наград общие для аккаунта. Одновременно доступен один RPG-бой. '
    'Покупка не даёт предметов или характеристик. При возврате оплаты '
    'дополнительные слоты блокируются, их данные сохраняются. Активный бой '
    'дополнительного персонажа закрывается без награды с возвратом ставок, '
    'активным становится первый персонаж. Поддержка и возвраты: /paysupport.'
)


class CharacterMixin:
    def _connect_characters(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS arena_character_accounts (
                user_id INTEGER PRIMARY KEY, active_slot INTEGER NOT NULL DEFAULT 1
                CHECK(active_slot BETWEEN 1 AND 5), revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS arena_character_slots (
                user_id INTEGER NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 5),
                profile_json TEXT NOT NULL, learned_json TEXT NOT NULL,
                sprite_key TEXT, png BLOB, pixel_art INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id,slot));
            CREATE INDEX IF NOT EXISTS idx_character_sprite_key ON arena_character_slots(sprite_key);
        ''')
        for column in ('a_character_slot','b_character_slot'):
            self._ensure_column('arena_battles',column,'INTEGER NOT NULL DEFAULT 1')
        self.connection.commit()

    def _character_account_locked(self,user):
        if type(user) is not int or user<=0:raise ValueError('Некорректный пользователь.')
        self.connection.execute('INSERT OR IGNORE INTO arena_character_accounts(user_id) VALUES(?)',(user,))
        return dict(self.connection.execute('SELECT * FROM arena_character_accounts WHERE user_id=?',(user,)).fetchone())

    def _character_active_locked(self,user):
        row=self.connection.execute('SELECT active_slot FROM arena_character_accounts WHERE user_id=?',(user,)).fetchone()
        return row['active_slot'] if row else 1

    def _character_unlocked_locked(self,user):
        return bool(self.connection.execute("SELECT 1 FROM pet_orders WHERE user_id=? AND pack=? AND status='paid'",(user,CHARACTER_PACK)).fetchone())

    def _character_require_locked(self,user,expected_slot=None):
        slot=self._character_active_locked(user)
        if expected_slot is not None and (type(expected_slot) is not int or expected_slot!=slot):
            raise ValueError('Активный персонаж изменился. Обнови меню.')
        if slot>1 and not self._character_unlocked_locked(user):
            raise ValueError('Дополнительный персонаж недоступен. Обнови меню.')
        return slot

    def _character_save_locked(self,user):
        slot=self._character_active_locked(user)
        profile=dict(self._arena_profile_locked(0,user,True))
        learned=[dict(r) for r in self.connection.execute('SELECT kind,content_id FROM arena_learned WHERE chat_id=0 AND user_id=? AND personal=1',(user,))]
        sprite=self.connection.execute('SELECT * FROM arena_sprites WHERE chat_id=0 AND user_id=?',(user,)).fetchone()
        profile_json,learned_json=json.dumps(profile),json.dumps(learned)
        sprite_key,pixel_art=(sprite['sprite_key'],sprite['pixel_art']) if sprite else (None,0)
        existing=self.connection.execute('SELECT profile_json,learned_json,sprite_key,pixel_art FROM arena_character_slots WHERE user_id=? AND slot=?',(user,slot)).fetchone()
        if existing and tuple(existing)==(profile_json,learned_json,sprite_key,pixel_art):return
        self.connection.execute('''INSERT INTO arena_character_slots VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(user_id,slot) DO UPDATE SET profile_json=excluded.profile_json,
            learned_json=excluded.learned_json,sprite_key=excluded.sprite_key,png=excluded.png,pixel_art=excluded.pixel_art''',
            (user,slot,profile_json,learned_json,sprite_key,
             sprite['png'] if sprite else None,sprite['pixel_art'] if sprite else 0))

    def _character_switch_locked(self,user,slot):
        self._character_save_locked(user)
        saved=self.connection.execute('SELECT * FROM arena_character_slots WHERE user_id=? AND slot=?',(user,slot)).fetchone()
        self.connection.execute('DELETE FROM personal_profiles WHERE chat_id=0 AND user_id=?',(user,))
        self.connection.execute('DELETE FROM arena_learned WHERE chat_id=0 AND user_id=? AND personal=1',(user,))
        self.connection.execute('DELETE FROM arena_sprites WHERE chat_id=0 AND user_id=?',(user,))
        self.connection.execute('UPDATE arena_character_accounts SET active_slot=?,revision=revision+1 WHERE user_id=?',(slot,user))
        if saved:
            profile=json.loads(saved['profile_json'])
            existing={r['name'] for r in self.connection.execute('PRAGMA table_info(personal_profiles)')}
            profile={k:v for k,v in profile.items() if k in existing}
            profile.update(chat_id=0,user_id=user)
            self.connection.execute('INSERT INTO personal_profiles('+','.join(profile)+') VALUES('+','.join('?' for _ in profile)+')',tuple(profile.values()))
            for entry in json.loads(saved['learned_json']):
                self.connection.execute('INSERT INTO arena_learned VALUES(0,?,1,?,?)',(user,entry['kind'],entry['content_id']))
            if saved['sprite_key']:
                self.connection.execute('INSERT INTO arena_sprites VALUES(0,?,?,?,?)',(user,saved['sprite_key'],saved['png'],saved['pixel_art']))
        else:
            self._arena_profile_locked(0,user,True)
        self._character_save_locked(user)

    def _character_cancel_locked(self,user):
        # No XP or daily claim for cancelled activity; other raid members stay.
        for raw in self.connection.execute("SELECT * FROM arena_battles WHERE status IN ('pending','active') AND (a_owner=? OR b_owner=?)",(user,user)).fetchall():
            self._arena_refund_locked(dict(raw),'cancelled')
        for raw in self.connection.execute("SELECT * FROM arena_mirror_runs WHERE status='active' AND actor_id=?",(user,)).fetchall():
            self._mirror_close_locked(dict(raw),'Дополнительный слот закрыт при возврате оплаты.')
        raids=self.connection.execute("SELECT DISTINCT r.token FROM arena_raids r JOIN arena_raid_players p ON p.token=r.token WHERE r.status IN ('lobby','active') AND p.actor_id=?",(user,)).fetchall()
        for raw in raids:
            row=self._raid_row_locked(raw['token'])
            if row['status']=='lobby':
                if row['creator_id']==user:
                    self.connection.execute("UPDATE arena_raids SET status='cancelled',finished_at=?,revision=revision+1 WHERE token=?",(int(time.time()),row['token']))
                else:
                    self.connection.execute('DELETE FROM arena_raid_players WHERE token=? AND actor_id=?',(row['token'],user))
                    self.connection.execute('UPDATE arena_raids SET revision=revision+1 WHERE token=?',(row['token'],))
            else:
                data=json.loads(row['data_json']);player=data['players'].get(str(user))
                if player and not player['withdrawn']:
                    player.update(withdrawn=True,reward_blocked=True,selected=None)
                    if finish_if_needed(data):self._raid_finish_locked(row,data)
                    else:
                        self._raid_save_locked(row,data)
                        self.connection.execute('UPDATE arena_raids SET deadline=? WHERE token=?',(row['deadline'],row['token']))

    def _character_license_changed_locked(self,user):
        account=self._character_account_locked(user)
        if account['active_slot']>1 and not self._character_unlocked_locked(user):
            self._character_cancel_locked(user)
            self._character_switch_locked(user,1)
        else:
            self.connection.execute('UPDATE arena_character_accounts SET revision=revision+1 WHERE user_id=?',(user,))

    def _character_view_locked(self,user):
        account=self._character_account_locked(user)
        active=account['active_slot'];unlocked=self._character_unlocked_locked(user)
        self._character_save_locked(user)
        classes,_=self._fighter_catalog_locked()
        saved={r['slot']:r for r in self.connection.execute('SELECT slot,profile_json,sprite_key,pixel_art FROM arena_character_slots WHERE user_id=?',(user,))}
        slots=[]
        for slot in range(1,6):
            row=saved.get(slot);profile=json.loads(row['profile_json']) if row else {}
            cls=profile.get('class_id','ragamuffin');arch=profile.get('archclass_id','')
            name=ARCHCLASSES.get(arch,{}).get('name') or classes.get(cls,FIGHTER_CLASSES['ragamuffin']).name
            slots.append(dict(slot=slot,active=slot==active,locked=slot>1 and not unlocked,
                created=row is not None,level=profile.get('level',1),class_name=name,
                avatar_url='/sprites/'+row['sprite_key']+'.png' if row and row['sprite_key'] else choice_avatar(cls,arch),
                pixel_art=bool(row and row['pixel_art'])))
        return dict(active_slot=active,revision=account['revision'],unlocked=unlocked,
            capacity=5 if unlocked else 1,price=CHARACTER_PRICE,terms_version=CHARACTER_TERMS_VERSION,
            terms=CHARACTER_TERMS,slots=slots,busy=self._arena_busy_locked(0,user))

    async def arena_characters(self,user):
        async with self._lock:
            with self.connection:return self._character_view_locked(user)

    async def arena_select_character(self,chat,user,slot,revision):
        if type(slot) is not int or not 1<=slot<=5 or type(revision) is not int:
            raise ValueError('Некорректный слот персонажа.')
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'arena')
                account=self._character_account_locked(user)
                if account['revision']!=revision:raise ValueError('Персонажи изменились. Обнови меню.')
                if slot>1 and not self._character_unlocked_locked(user):raise ValueError('Этот слот закрыт.')
                if slot==account['active_slot']:return 'Этот персонаж уже выбран.'
                if self._arena_busy_locked(chat,user):raise ValueError('Сначала заверши бой, рейд или зеркальный забег.')
                self._character_switch_locked(user,slot)
            return 'Выбран персонаж №'+str(slot)+'.'

    async def arena_character_sprite_info(self,user,slot=1):
        if not user:return dict(sprite_url=None,pixel_art=False)
        async with self._lock:
            if slot==self._character_active_locked(user):
                row=self.connection.execute('SELECT sprite_key,pixel_art FROM arena_sprites WHERE chat_id=0 AND user_id=?',(user,)).fetchone()
            else:
                row=self.connection.execute('SELECT sprite_key,pixel_art FROM arena_character_slots WHERE user_id=? AND slot=?',(user,slot)).fetchone()
            return dict(sprite_url='/sprites/'+row['sprite_key']+'.png' if row and row['sprite_key'] else None,pixel_art=bool(row and row['pixel_art']))
