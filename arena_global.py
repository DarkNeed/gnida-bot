"""Recoverable account migration. chat_id=0 is internal RPG storage only.

Membership and franc payments always use the real invoking chat ID.
Old per-chat rows are retained as historical data, never read as live profiles.
"""
import json
import logging
import sqlite3
import time
import uuid
from collections import defaultdict
from contextlib import closing
from arena_engine import BUILTIN_PASSIVES, fighter_xp_limit, level_from_total_xp

RPG_SCOPE = 0


class GlobalArenaMixin:
    async def arena_leave_mirror(self, chat, actor, token):
        async with self._lock:
            self._require_feature_locked(chat,'arena')
            with self.connection:
                row=self._mirror_row_locked(token)
                if row['actor_id']!=actor or row['status']!='active':
                    raise ValueError('Это не твой активный забег.')
                self._mirror_close_locked(row,'Забег оставлен. Награды за босса нет.')
            return 'Зеркальный забег оставлен без награды за босса.'

    async def arena_leave_raid(self, chat, actor, token):
        await self.arena_require_enabled(chat)
        row=await self.arena_raid_get(token)
        if not any(p['actor_id']==actor for p in row['participants']):
            raise ValueError('Ты не участвуешь в этом рейде.')
        if row['status']=='lobby':
            await self.arena_raid_setup(token,actor,'cancel' if row['creator_id']==actor else 'leave')
        elif row['status']=='active':
            await self.arena_raid_action(token,actor,json.loads(row['data_json'])['round'],'surrender')
        else:
            raise ValueError('Этот рейд уже закрыт.')
        return 'Ты вышел из рейда. Награда не выдаётся.'

    async def arena_leave_battle(self, chat, actor, token):
        """Exit one's reservation through another joined chat, even after leaving
        the original group. Pending stakes refund; active PvP is a surrender.
        """
        async with self._lock:
            self._require_feature_locked(chat,'arena')
            with self.connection:
                row=self._arena_row_locked(token)
                if actor not in {row['a_owner'],row['b_owner']}:
                    raise ValueError('Это не твой бой.')
                if row['status']=='pending':
                    self._arena_refund_locked(row,'cancelled')
                elif row['status']=='active':
                    state=json.loads(row['state_json'])
                    side='a' if row['a_owner']==actor else 'b'
                    state.update(finished=True,winner='b' if side=='a' else 'a',finish_reason='surrender')
                    self._arena_finish_locked(row,state)
                    self.connection.execute('UPDATE arena_battles SET state_json=?,revision=revision+1 WHERE id=?',
                        (json.dumps(state,ensure_ascii=False),row['id']))
                else:
                    raise ValueError('Этот бой уже закрыт.')
            return 'Бой закрыт: приглашение отменено либо засчитана сдача.'

    def _global_cancel_arena_locked(self, chat=None):
        where,params=(' AND chat_id=?',(chat,)) if chat is not None else ('',())
        now=int(time.time())
        for row in self.connection.execute("SELECT * FROM arena_battles WHERE status IN ('pending','active')"+where,params).fetchall():
            for side in ('a','b'):
                if row['escrow_'+side]:
                    self._add_francs_locked(row['chat_id'],row[side+'_owner'],row['escrow_'+side])
            state=json.loads(row['state_json']) if row['state_json'] else None
            if state:
                state.update(finished=True,winner=None,finish_reason='cancelled',rewards={},payout=0)
            self.connection.execute("UPDATE arena_battles SET status='cancelled',escrow_a=0,escrow_b=0,state_json=?,finished_at=?,revision=revision+1 WHERE id=?",
                (json.dumps(state,ensure_ascii=False) if state else None,now,row['id']))
        for row in self.connection.execute("SELECT * FROM arena_raids WHERE status IN ('lobby','active')"+where,params).fetchall():
            data=json.loads(row['data_json']) if row['data_json'] else None
            if data:
                data.update(finished=True,won=False,rewards={},result='Рейд закрыт при обновлении или отключении арены. Награды не выданы.')
            self.connection.execute("UPDATE arena_raids SET status='cancelled',data_json=?,finished_at=?,revision=revision+1 WHERE token=?",
                (json.dumps(data,ensure_ascii=False) if data else None,now,row['token']))
        for row in self.connection.execute("SELECT * FROM arena_mirror_runs WHERE status='active'"+where,params).fetchall():
            data=json.loads(row['data_json'])
            data.update(phase='ended',result='Забег закрыт при обновлении или отключении арены. Уже полученный опыт сохранён.')
            self.connection.execute("UPDATE arena_mirror_runs SET status='finished',data_json=?,updated_at=? WHERE token=?",
                (json.dumps(data,ensure_ascii=False),now,row['token']))

    def _connect_global_arena(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_global_migrations(name TEXT PRIMARY KEY,created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS arena_global_item_aliases(old_id INTEGER PRIMARY KEY,new_id INTEGER NOT NULL,owner_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS arena_global_legacy_profiles (
                user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,personal INTEGER NOT NULL,
                profile_json TEXT NOT NULL,PRIMARY KEY(user_id,chat_id,personal));
            CREATE INDEX IF NOT EXISTS idx_account_battle_a_owner ON arena_battles(a_owner,status);
            CREATE INDEX IF NOT EXISTS idx_account_battle_b_owner ON arena_battles(b_owner,status);
            CREATE INDEX IF NOT EXISTS idx_account_battle_a_fighter ON arena_battles(a_fighter,status);
            CREATE INDEX IF NOT EXISTS idx_account_battle_b_fighter ON arena_battles(b_fighter,status);
            CREATE INDEX IF NOT EXISTS idx_account_raid_actor ON arena_raid_players(actor_id);
            CREATE INDEX IF NOT EXISTS idx_account_raid_fighter ON arena_raid_players(fighter_id);
            CREATE INDEX IF NOT EXISTS idx_account_mirror_actor ON arena_mirror_runs(actor_id,status);
            CREATE INDEX IF NOT EXISTS idx_account_mirror_fighter ON arena_mirror_runs(fighter_id,status);
        """)
        if self.connection.execute("SELECT 1 FROM arena_global_migrations WHERE name='account_rpg_v1'").fetchone():
            return
        has_legacy=any(self.connection.execute(f'SELECT 1 FROM {table} WHERE chat_id<>0 LIMIT 1').fetchone()
            for table in ('personal_profiles','slave_profiles','arena_inventory','arena_forge_wallets'))
        if has_legacy:
            # A separate read-only connection includes WAL without hanging on
            # an open writer transaction. Preserve a restorable snapshot first.
            backup_dir=self.path.parent/'backups'
            backup_dir.mkdir(parents=True,exist_ok=True)
            backup_path=backup_dir/('before-account-rpg-'+str(int(time.time()))+'-'+uuid.uuid4().hex[:8]+'.sqlite3')
            with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)) as source:
                with closing(sqlite3.connect(backup_path)) as snapshot:
                    source.backup(snapshot)
                    if snapshot.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                        raise RuntimeError('Не удалось проверить резервную копию перед переносом RPG.')
            logging.info('Account RPG migration backup: %s',backup_path)
        with self.connection:
            self._global_cancel_arena_locked()
            profiles=defaultdict(list)
            current_classes,current_skills=self._fighter_catalog_locked()
            for table,personal in (('personal_profiles',1),('slave_profiles',0)):
                for row in self.connection.execute(f'SELECT * FROM {table} WHERE chat_id<>0').fetchall():
                    source=dict(row);profiles[row['user_id']].append((personal,source))
                    self.connection.execute('INSERT OR IGNORE INTO arena_account_chats VALUES(?,?)',(row['user_id'],row['chat_id']))
                    self.connection.execute('INSERT OR IGNORE INTO arena_global_legacy_profiles VALUES(?,?,?,?)',
                        (row['user_id'],row['chat_id'],personal,json.dumps(source)))
            columns=[r['name'] for r in self.connection.execute('PRAGMA table_info(personal_profiles)')]
            for user,candidates in profiles.items():
                existing=self.connection.execute('SELECT * FROM personal_profiles WHERE chat_id=0 AND user_id=?',(user,)).fetchone()
                if existing:candidates.append((1,dict(existing)))
                personal,chosen=max(candidates,key=lambda p:(p[1]['xp'],p[0],p[1]['updated_at'],p[1]['chat_id']))
                chosen=dict(chosen);source_chat=chosen['chat_id']
                chosen.update(chat_id=0,xp=min(chosen['xp'],fighter_xp_limit()))
                chosen['level']=level_from_total_xp(chosen['xp'])
                if chosen['class_id'] not in current_classes:
                    chosen.update(class_id='ragamuffin',archclass_id='',progression_level=0,loadout='["bum_punch"]',passive_loadout='[]')
                chosen['catchup_target_xp']=max(p[1].get('catchup_target_xp',0) for p in candidates)
                if chosen['catchup_target_xp']<=chosen['xp']:chosen['catchup_target_xp']=0
                chosen['skills_reset']=1
                for kind,catalog in (('skill',current_skills),('passive',BUILTIN_PASSIVES)):
                    memory=json.loads(chosen.get(kind+'_memory') or '[]')
                    memory=[k for k in memory if k in catalog or (kind=='passive' and k.startswith('inherent:'+chosen['class_id']+':'))]
                    chosen[kind+'_memory']=json.dumps(memory) if memory else None
                    for old_personal,source in candidates:
                        learned=self.connection.execute('SELECT kind,content_id FROM arena_learned WHERE chat_id=? AND user_id=? AND personal=? AND kind=?',
                            (source['chat_id'],user,old_personal,kind)).fetchall()
                        for entry in learned:
                            if entry['content_id'] in catalog:
                                self.connection.execute('INSERT OR IGNORE INTO arena_learned VALUES(0,?,1,?,?)',(user,kind,entry['content_id']))
                chosen['loadout']=json.dumps([k for k in json.loads(chosen['loadout']) if k in current_skills] or ['bum_punch'])
                update=','.join(k+'=excluded.'+k for k in columns if k not in {'chat_id','user_id'})
                self.connection.execute('INSERT INTO personal_profiles ('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+') ON CONFLICT(chat_id,user_id) DO UPDATE SET '+update,tuple(chosen[k] for k in columns))
                sprite=self.connection.execute('SELECT * FROM arena_sprites WHERE user_id=? ORDER BY (chat_id=?) DESC,rowid DESC LIMIT 1',(user,source_chat)).fetchone()
                if sprite:self.connection.execute('INSERT OR IGNORE INTO arena_sprites VALUES(0,?,?,?,?)',(user,sprite['sprite_key'],sprite['png'],sprite['pixel_art']))
            for row in self.connection.execute('SELECT * FROM pet_equipment WHERE chat_id<>0 ORDER BY rowid DESC').fetchall():
                self.connection.execute('INSERT OR IGNORE INTO pet_equipment VALUES(0,?,?)',(row['user_id'],row['pet_id']))
            for row in self.connection.execute('SELECT * FROM arena_inventory WHERE chat_id<>0').fetchall():
                if not self._arena_content_enabled_locked(0,row['kind'],row['content_id']):continue
                self.connection.execute("""INSERT INTO arena_inventory(chat_id,owner_id,kind,content_id,rarity,quantity) VALUES(0,?,?,?,?,?)
                    ON CONFLICT(chat_id,owner_id,kind,content_id) DO UPDATE SET quantity=quantity+excluded.quantity""",
                    (row['owner_id'],row['kind'],row['content_id'],row['rarity'],row['quantity']))
                item=self.connection.execute('SELECT id FROM arena_inventory WHERE chat_id=0 AND owner_id=? AND kind=? AND content_id=?',
                    (row['owner_id'],row['kind'],row['content_id'])).fetchone()
                self.connection.execute('INSERT INTO arena_global_item_aliases VALUES(?,?,?)',(row['id'],item['id'],row['owner_id']))
            wallets=defaultdict(dict)
            for row in self.connection.execute('SELECT * FROM arena_forge_wallets WHERE chat_id<>0').fetchall():
                for rarity,amount in json.loads(row['pages_json']).items():
                    wallets[row['owner_id']][rarity]=wallets[row['owner_id']].get(rarity,0)+amount
            for user,pages in wallets.items():
                existing=self.connection.execute('SELECT pages_json FROM arena_forge_wallets WHERE chat_id=0 AND owner_id=?',(user,)).fetchone()
                if existing:
                    for rarity,amount in json.loads(existing['pages_json']).items():pages[rarity]=pages.get(rarity,0)+amount
                self.connection.execute('INSERT INTO arena_forge_wallets(chat_id,owner_id,pages_json) VALUES(0,?,?) ON CONFLICT(chat_id,owner_id) DO UPDATE SET pages_json=excluded.pages_json',(user,json.dumps(pages)))
            for row in self.connection.execute('SELECT * FROM arena_forge_actions WHERE chat_id<>0').fetchall():
                request=json.loads(row['request_json']);request['payment_chat']=row['chat_id']
                self.connection.execute('INSERT OR IGNORE INTO arena_forge_actions VALUES(0,?,?,?,?,?)',
                    (row['owner_id'],row['nonce'],json.dumps(request,sort_keys=True),row['notice'],row['created_at']))
            self.connection.execute("""INSERT INTO arena_pair_rewards SELECT 0,first_id,second_id,day,SUM(count)
                FROM arena_pair_rewards WHERE chat_id<>0 GROUP BY first_id,second_id,day
                ON CONFLICT(chat_id,first_id,second_id,day) DO UPDATE SET count=count+excluded.count""")
            self.connection.execute("INSERT INTO arena_global_migrations VALUES('account_rpg_v1',?)",(int(time.time()),))
