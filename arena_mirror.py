"""Saved Mirror Wasteland runs, including already-issued legacy routes."""

import json
import random
import secrets
import time

from arena_engine import create_battle_state, BUILTIN_SKILLS, BUILTIN_PASSIVES, FIGHTER_CLASSES
from arena_archprogress import skill_branch
from arena_wasteland import enemy_source, victory_xp
from message_activity import message_week
from arena_mirror_effects import GIFTS, NORMAL_GIFTS, apply_gifts
import arena_mirror_dungeon as dungeon

MIRROR_FLOORS = 5


def mirror_reward_items(start_level, rng=None, *, enabled_classes=None):
    """Permanent boss loot; branch unlocks and exclusive raid drops stay separate."""
    rng = rng or random.SystemRandom()
    active_pool = [
            skill
            for skill in BUILTIN_SKILLS.values()
            if skill.class_id != "ragamuffin"
            and (enabled_classes is None or skill.class_id in enabled_classes)
            and not skill_branch(skill)
            and "raid_loot" not in skill.tags
            and skill.rarity
            in ({"rare"} if start_level >= 10 else {"uncommon", "rare"})
        ]
    active = rng.choice(active_pool or [BUILTIN_SKILLS['dust_in_eyes']])
    # Keep this existing reward pool unchanged: adding forge epics must not
    # silently turn 40% of mirror rewards into epic passive scrolls.
    passive = rng.choice([p for p in BUILTIN_PASSIVES.values() if p.rarity in {"common", "uncommon", "rare"}])
    return [
        dict(
            kind="skill",
            content_id=active.skill_id,
            rarity=active.rarity,
            name=active.name,
            quantity=1,
        ),
        dict(
            kind="passive",
            content_id=passive.skill_id,
            rarity=passive.rarity,
            name=passive.name,
            quantity=1,
        ),
        dict(
            kind="potion",
            content_id="healing",
            rarity="common",
            name="Зелье лечения",
            quantity=3,
        ),
        dict(
            kind="candy",
            content_id="experience",
            rarity="common",
            name="Конфета опыта",
            quantity=2,
        ),
    ]


class MirrorMixin:
    def _connect_mirror(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_mirror_runs (
                token TEXT PRIMARY KEY, chat_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL, fighter_id INTEGER NOT NULL,
                personal INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                revision INTEGER NOT NULL DEFAULT 0, data_json TEXT NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mirror_one_run
            ON arena_mirror_runs(chat_id,actor_id) WHERE status='active';
            CREATE INDEX IF NOT EXISTS idx_mirror_fighter
            ON arena_mirror_runs(chat_id,fighter_id,status);
            CREATE TABLE IF NOT EXISTS arena_mirror_reward_weeks (
                actor_id INTEGER NOT NULL, week_start INTEGER NOT NULL, token TEXT NOT NULL UNIQUE,
                PRIMARY KEY(actor_id,week_start)
            );
        """)
        self.connection.commit()

    def _mirror_row_locked(self, token):
        raw = self.connection.execute(
            "SELECT * FROM arena_mirror_runs WHERE token=?", (token,)
        ).fetchone()
        if not raw:
            raise ValueError("Забег не найден.")
        return dict(raw)

    def _mirror_save_locked(self, row, data, status=None):
        self.connection.execute(
            "UPDATE arena_mirror_runs SET data_json=?,status=?,revision=revision+1,updated_at=? WHERE token=?",
            (
                json.dumps(data, ensure_ascii=False),
                status or row["status"],
                int(time.time()),
                row["token"],
            ),
        )

    def _mirror_owner_valid_locked(self, row):
        if row["personal"]:
            return True
        data = json.loads(row["data_json"])
        return (
            self._arena_owns_locked(
                row["chat_id"], data["slave_owner"], row["fighter_id"]
            )
            and self._arena_combat_slot_locked(
                row["chat_id"], data["slave_owner"], row["fighter_id"]
            )
            is not None
        )

    def _mirror_close_locked(self, row, reason):
        data = json.loads(row["data_json"])
        data.update(phase="ended", result=reason)
        # No refunds/rewards on abandonment, and no dangling busy battle.
        self.connection.execute(
            "UPDATE arena_battles SET status='cancelled',finished_at=?,revision=revision+1 WHERE token=? AND status='active'",
            (int(time.time()), data["battle_token"]),
        )
        self._mirror_save_locked(row, data, "cancelled")

    def _mirror_cleanup_locked(self, chat):
        for raw in self.connection.execute(
            "SELECT * FROM arena_mirror_runs WHERE chat_id=? AND status='active'",
            (chat,),
        ).fetchall():
            row = dict(raw)
            if not self._mirror_owner_valid_locked(row):
                self._mirror_close_locked(
                    row, "Владелец бойца сменился или боевой слот снят. Забег закрыт."
                )

    def _mirror_public_locked(self, row, *, detail=True):
        data = json.loads(row["data_json"])
        if row["status"] == "active" and data["phase"] == "combat":
            battle = self._arena_row_locked(data["battle_token"])
            side = json.loads(battle["state_json"])["sides"]["a"]
            data.update(hp=side["hp"], resource=side["resource"])
        gifts = [
            dict(id=k, name=GIFTS[k][0], description=GIFTS[k][1]) for k in data["gifts"]
        ]
        choices = [
            dict(id=k, name=GIFTS[k][0], description=GIFTS[k][1])
            for k in data.get("choices", [])
        ]
        layout=data.get('layout',1)
        return dict(
            token=row["token"],
            chat_id=row["chat_id"],
            actor_id=row["actor_id"],
            fighter_id=row["fighter_id"],
            personal=bool(row["personal"]),
            status=row["status"],
            revision=row["revision"],
            **{
                k: data[k]
                for k in (
                    "phase",
                    "floor",
                    "battle_token",
                    "hp",
                    "resource",
                    "max_hp",
                    "resource_max",
                    "shards",
                    "result",
                    "xp",
                    "francs",
                    "loot",
                    "event",
                )
            },
            gifts=gifts,
            choices=choices,
            item_rewards=data.get("item_rewards", []),
            pet_rewards=data.get("pet_rewards", {}),
            gear_shards=data.get('gear_shards', {}),
            mirror_title=data.get('mirror_title', ''),
            layout=layout,
            total_floors=dungeon.DEPTH if layout==2 else MIRROR_FLOORS,
            **(dungeon.public_route(data) if layout==2 and detail else {}),
        )

    def _mirror_battle_locked(self, row, data, first=False, *, enemy=None, kind=None):
        source = data["source"]
        enemy = enemy or enemy_source(
            source["level"] + data["floor"] - 1, data.get("previous_class"),
            enabled_classes={k for k in FIGHTER_CLASSES if self._arena_class_enabled_locked(row['chat_id'],k)}
        )
        classes, skills = self._fighter_catalog_locked()
        state = create_battle_state(source, enemy, classes=classes, skills=skills, action_queue_version=True)
        state['qte_modes']={str(s['controller_id']):self._qte_enabled_locked(s['controller_id']) for s in state['sides'].values()}
        a, b = state["sides"].values()
        if not first:
            a["hp"] = min(a["stats"]["max_hp"], data["hp"])
            a["resource"] = min(a["stats"]["resource_max"], data["resource"])
        apply_gifts(a, data["gifts"])
        if kind is not None:
            dungeon.scale_enemy(b,data['floor'],kind,chapter=data.get('route_version')==2,
                                mirror_level=enemy.get('mirror_level'))
            state.update(mirror_layout=2,mirror_boss=kind=='boss',mirror_elite=kind=='elite')
            if data.get('route_version')==2:
                length=len(data['route'])+1
                state.update(mirror_step=length if kind=='boss' else data['step'],mirror_floor_length=length)
        elif data["floor"] == MIRROR_FLOORS:
            b["is_boss"] = True
            for stat in (
                "physical_attack",
                "magic_attack",
                "physical_defense",
                "magic_defense",
            ):
                b["stats"][stat] = round(b["stats"][stat] * 1.15, 2)
            b["stats"]["max_hp"] = max(1, round(b["stats"]["max_hp"] * 1.4))
            b["hp"] = b["stats"]["max_hp"]
        state.update(mirror_token=row["token"], turn_timer_seconds=0)
        from arena_unified_queue import initialize
        initialize(state, skills)
        token = secrets.token_urlsafe(16)
        self.connection.execute(
            """INSERT INTO arena_battles(token,chat_id,mode,a_owner,b_owner,a_fighter,b_fighter,a_control,b_accepted,status,state_json,floor,created_at,deadline,personal_solo)
            VALUES(?,?,'wasteland',?,0,?,0,?,1,'active',?,?,?,0,?)""",
            (
                token,
                row["chat_id"],
                row["actor_id"],
                row["fighter_id"],
                int(source["controlled"]),
                json.dumps(state, ensure_ascii=False),
                data["floor"],
                int(time.time()),
                row["personal"],
            ),
        )
        self.connection.execute('UPDATE arena_battles SET a_character_slot=? WHERE token=?',(self._character_active_locked(row['actor_id']),token))
        data.update(
            phase="combat",
            battle_token=token,
            hp=a["hp"],
            resource=a["resource"],
            max_hp=a["stats"]["max_hp"],
            resource_max=a["stats"]["resource_max"],
            previous_class=enemy["class_id"],
        )

    async def arena_mirror_start(self, chat, actor, fighter=None, personal=True, *, expected_slot=None, _layout=2, _route_version=2):
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            self._character_require_locked(actor,expected_slot)
            if not personal or (fighter and fighter != actor):
                raise ValueError('Забеги доступны только личным персонажам.')
            self._mirror_cleanup_locked(chat)
            self.connection.commit()
            fighter = fighter or actor
            if self._arena_busy_locked(chat, actor) or self._arena_busy_locked(
                chat, fighter
            ):
                raise ValueError("Сначала завершите текущий бой или забег.")
            if _layout==2 and self.connection.execute("""SELECT 1 FROM arena_mirror_runs
                WHERE actor_id=? AND status='finished' AND json_extract(data_json,'$.phase')='reward' LIMIT 1""",(actor,)).fetchone():
                raise ValueError('Сначала выбери трофей за предыдущий забег.')
            slave_owner = actor
            if personal and fighter != actor:
                raise ValueError("Личный персонаж может быть только своим.")
            if not personal:
                if fighter == actor:
                    owner = self.connection.execute(
                        "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                        (chat, fighter),
                    ).fetchone()
                    if not owner:
                        raise ValueError("Вы не состоите в рабстве.")
                    slave_owner = int(owner["owner_id"])
                self._arena_require_combat_locked(chat, slave_owner, fighter)
            self._arena_require_choice_locked(chat, fighter, personal)
            source = self._arena_source_locked(
                chat, fighter, actor, not personal and fighter != actor, personal
            )
            source["granted_skills"] = sorted(source["granted_skills"])
            data = dict(
                source=source,
                slave_owner=slave_owner,
                phase="combat",
                floor=1,
                gifts=[],
                choices=[],
                shards=20,
                xp=0,
                francs=0,
                loot="",
                item_rewards=[],
                result="",
                event="",
                battle_token="",
                hp=0,
                resource=0,
                max_hp=0,
                resource_max=0,
            )
            if _layout==2:
                enabled={k for k in FIGHTER_CLASSES if self._arena_class_enabled_locked(chat,k)}
                if _route_version==2:
                    data.update(route_version=2,route_seed=secrets.token_hex(16),route_classes=sorted(enabled))
                    self._mirror_prepare_floor(data)
                    final=data['final_enemy']
                else:
                    route,final=dungeon.make_route(source['level'],enabled,random.SystemRandom())
                    data.update(route=route,final_enemy=final,lane=None,path=[])
                classes,skills=self._fighter_catalog_locked()
                a=create_battle_state(source,final,classes=classes,skills=skills)['sides']['a']
                data.update(layout=2,phase='map',cleared=0,
                    pages={},max_hp=a['stats']['max_hp'],resource_max=a['stats']['resource_max'],
                    hp=a['hp'],resource=a['resource'],shards=0,dust=0)
            token = secrets.token_urlsafe(16)
            now = int(time.time())
            try:
                self.connection.execute(
                    "INSERT INTO arena_mirror_runs(token,chat_id,actor_id,fighter_id,personal,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        token,
                        chat,
                        actor,
                        fighter,
                        int(personal),
                        json.dumps(data),
                        now,
                        now,
                    ),
                )
                row = self._mirror_row_locked(token)
                if _layout!=2:
                    self._mirror_battle_locked(row, data, first=True)
                    self._mirror_save_locked(row, data)
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            return self._mirror_public_locked(self._mirror_row_locked(token))

    def _mirror_finish_battle_locked(self, battle, state):
        row = self._mirror_row_locked(state["mirror_token"])
        data = json.loads(row["data_json"])
        if (
            row["status"] != "active"
            or data["phase"] != "combat"
            or data["battle_token"] != battle["token"]
        ):
            raise ValueError("Этот этап уже закрыт.")
        won = state["winner"] == "a" and state.get("finish_reason") not in {
            "surrender",
            "timeout",
            "turn_limit",
        }
        reward = 0
        status = "active"
        if won:
            table = "personal_profiles" if row["personal"] else "slave_profiles"
            before = self._arena_profile_locked(
                row["chat_id"], row["fighter_id"], bool(row["personal"])
            )["xp"]
            self._grant_profile_xp_locked(
                table,
                row["chat_id"],
                row["fighter_id"],
                victory_xp(state["sides"]["b"]["level"]),
                battle=True,
            )
            reward = (
                self._arena_profile_locked(
                    row["chat_id"], row["fighter_id"], bool(row["personal"])
                )["xp"]
                - before
            )
            data["xp"] += reward
            if not row["personal"]:
                self._settle_materials_locked(row["chat_id"], data["slave_owner"])
                self._grant_profile_xp_locked(
                    "owner_profiles", row["chat_id"], data["slave_owner"], 6
                )
            data.update(
                hp=state["sides"]["a"]["hp"],
                resource=min(
                    data["resource_max"], state["sides"]["a"]["resource"] + 30
                ),
            )
            if data.get('layout')==2:
                if data.get('boss_active'):
                    if data.get('route_version')==2:
                        self._mirror_complete_floor_locked(row,data)
                    if data['floor']==dungeon.DEPTH:
                        status='finished'
                        self._mirror_dungeon_victory_locked(row,data)
                else:
                    dust=dungeon.ELITE_DUST if state.get('mirror_elite') else dungeon.NORMAL_DUST
                    data['dust']+=dust
                    notice=f'Отражение рассеялось. Получено {dust} ед. Пыли.'
                    if data.get('route_version')==2 and state.get('mirror_elite'):
                        if rank:=dungeon.elite_shard_rank(data['floor'],random.SystemRandom()):
                            self._mirror_add_gear_shards_locked(row,data,rank,1)
                            notice+=f' В инвентарь: +1 осколок {rank}.'
                    self._mirror_room_complete_locked(row,data,notice)
            elif data["floor"] == MIRROR_FLOORS:
                data['shards']+=15
                status = "finished"
                data.update(
                    phase="ended",
                    result="Зеркало пройдено! Дары остались по ту сторону.",
                )
                data["francs"] = 50 + 5 * data["source"]["level"]
                data["pet_rewards"] = self._pet_reward_locked(
                    row["actor_id"], "mirror", "mirror:" + row["token"])
                self._add_francs_locked(row["chat_id"], row["actor_id"], data["francs"])
                data["item_rewards"] = mirror_reward_items(data["source"]["level"],
                    enabled_classes={k for k in FIGHTER_CLASSES if self._arena_class_enabled_locked(row['chat_id'],k)})
                for item in data["item_rewards"]:
                    self._arena_add_item_locked(
                        row["chat_id"],
                        row["actor_id"],
                        item["kind"],
                        item["content_id"],
                        item["rarity"],
                        item["quantity"],
                    )
                # Keep the old field readable for saved clients and older previews.
                data["loot"] = ", ".join(
                    item["name"] for item in data["item_rewards"][:2]
                )
            else:
                data['shards']+=15
                pool = [k for k in NORMAL_GIFTS if k not in data["gifts"]]
                data.update(
                    phase="gift" if pool else "route",
                    choices=random.SystemRandom().sample(pool, min(3, len(pool))),
                )
        else:
            status = "lost"
            data.update(
                phase="ended",
                hp=state["sides"]["a"]["hp"],
                resource=state["sides"]["a"]["resource"],
                result=("Забег завершён. Опыт, франки и страницы с пройденных рубежей сохранены."
                    if data.get('layout')==2 else "Забег завершён. Опыт за уже пройденные этажи сохранён; награды за босса нет."),
            )
        self._mirror_save_locked(row, data, status)
        state.update(
            rewards={"a": max(0, reward)},
            payout=(data.get('final_francs',0) if data.get('layout')==2 else data['francs']) if status=='finished' else 0,
        )
        self.connection.execute(
            "UPDATE arena_battles SET status='finished',finished_at=? WHERE id=?",
            (int(time.time()), battle["id"]),
        )

    def _mirror_add_pages_locked(self,row,data,pages):
        if not pages:
            return
        chat,actor=row['chat_id'],row['actor_id']
        wallet=self._forge_wallet_locked(chat,actor)
        for key,amount in pages.items():
            wallet['pages'][key]=wallet['pages'].get(key,0)+amount
            data['pages'][key]=data['pages'].get(key,0)+amount
        self._forge_save_wallet_locked(chat,actor,wallet)

    def _mirror_open_shop_locked(self,row,data,notice):
        floor=data['floor']
        if data.get('route_version')==2:
            if data['step']!=len(data['route']) or len(data['path'])!=data['step'] or data['cleared']!=floor-1:
                raise ValueError('Лавка ещё недоступна.')
            data.update(phase='merchant',shop=dungeon.shop_stock(data),supplies=[],result=notice)
            return
        if data['cleared']!=floor-1 or len(data['path'])!=floor:
            raise ValueError('Этот этаж уже закрыт.')
        data.update(phase='merchant',cleared=floor,shop=dungeon.shop_stock(data),supplies=[],result=notice)
        self._mirror_checkpoint_locked(row,data)

    def _mirror_room_complete_locked(self,row,data,notice):
        if data.get('route_version')!=2:
            self._mirror_open_shop_locked(row,data,notice)
            return
        if data['step']>=len(data['route']) or len(data['path'])!=data['step']:
            raise ValueError('Эта комната уже закрыта.')
        data.update(phase='map',step=data['step']+1,result=notice,battle_token='')

    def _mirror_prepare_floor(self,data):
        rng=random.Random(f"{data['route_seed']}:{data['floor']}")
        route,boss=dungeon.make_floor(data['floor'],set(data['route_classes']),rng)
        data.update(route=route,final_enemy=boss,path=[],lane=None,step=1,phase='map',boss_active=False,
                    shop=[],supplies=[],discount=False,result='',battle_token='')

    def _mirror_complete_floor_locked(self,row,data):
        floor=data['floor']
        if data['cleared']!=floor-1 or len(data['path'])!=len(data['route']):
            raise ValueError('Этот этаж уже закрыт.')
        # Dust from a floor boss is usable on later floors, never paid out.
        if floor<dungeon.DEPTH:data['dust']+=dungeon.ELITE_DUST
        data.update(phase='landing',cleared=floor,hp=data['max_hp'],resource=data['resource_max'],
                    result='HP и энергия полностью восстановлены.',battle_token='')
        self._mirror_checkpoint_locked(row,data)

    def _mirror_checkpoint_locked(self,row,data):
        francs,pages=dungeon.checkpoint(data)
        if francs:
            self._add_francs_locked(row['chat_id'],row['actor_id'],francs)
            data['francs']+=francs
            data['result']+=f' Рубеж: +{francs} ₣ и {sum(pages.values())} стр. в кузницу.'
        self._mirror_add_pages_locked(row,data,pages)
        if data['floor']==9:
            self._mirror_add_gear_shards_locked(row,data,'S',3)
            data['result']+=' В инвентарь: +3 осколка S.'

    def _mirror_add_gear_shards_locked(self,row,data,rank,amount):
        self._gear_material_locked(row['actor_id'],rank,amount)
        self._gear_touch_locked(row['actor_id'])
        shards=data.setdefault('gear_shards',{})
        shards[rank]=shards.get(rank,0)+amount

    def _mirror_scroll_choices_locked(self,chat,actor,rng):
        profile=self._arena_profile_locked(chat,actor,True)
        from arena_global import RPG_SCOPE
        owned={(r['kind'],r['content_id']) for r in self.connection.execute(
            "SELECT kind,content_id FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind IN ('skill','passive')",
            (RPG_SCOPE,actor))}
        # Class skills generally unlock for free; only universal scrolls and portable passives.
        known={kind:self._arena_learned_locked(chat,actor,True,kind) for kind in ('skill','passive')}
        pool=[('skill',s) for s in BUILTIN_SKILLS.values() if s.class_id=='universal'
              and s.unlock_level<=profile['level'] and not skill_branch(s)
              and not any(t=='raid_loot' or t.startswith(('mastery:','derived:')) for t in s.tags)]
        pool += [('passive',p) for p in BUILTIN_PASSIVES.values()]
        rng.shuffle(pool)
        pool.sort(key=lambda pair: {'rare':0,'uncommon':1,'common':2}.get(pair[1].rarity,3))
        result=[]
        for kind,item in pool:
            ident=item.skill_id
            if (item.rarity not in ('common','uncommon','rare') or (kind,ident) in owned
                or ident in known[kind] or not self._arena_content_enabled_locked(chat,kind,ident)):
                continue
            result.append(dict(id=f'treatise-{len(result)+1}',kind=kind,content_id=ident,
                               rarity=item.rarity,name=item.name,quantity=1))
            if len(result)==3:break
        return result

    async def arena_mirror_title(self,actor):
        async with self._lock:
            unlocked=self.connection.execute('SELECT 1 FROM arena_mirror_reward_weeks WHERE actor_id=? LIMIT 1',
                                             (actor,)).fetchone()
            return dungeon.MIRROR_TITLE if unlocked else ''

    def _mirror_dungeon_victory_locked(self,row,data):
        chat,actor=row['chat_id'],row['actor_id']
        level=data['source']['level']
        final_francs=100+5*level
        self._add_francs_locked(chat,actor,final_francs)
        data['francs']+=final_francs
        data['final_francs']=final_francs
        data['pet_rewards']=self._pet_reward_locked(actor,'mirror','mirror:'+row['token'])
        if data.get('route_version')==2:
            weekly=self.connection.execute('INSERT OR IGNORE INTO arena_mirror_reward_weeks VALUES(?,?,?)',
                                            (actor,message_week(int(time.time())),row['token'])).rowcount
            from arena_engine import stats_for
            rng=random.SystemRandom()
            stats=stats_for(data['source']['class_id'],level)
            opts=dungeon.gear_rewards(stats,'epic' if weekly else 'rare',rng)
            opts+=self._mirror_scroll_choices_locked(chat,actor,rng)
            opts.append(dict(id='pages',kind='pages',name='Связка страниц',pages={'rare':6}))
            data.update(mirror_title=dungeon.MIRROR_TITLE,weekly_bonus=bool(weekly))
        else:
            enabled={k for k in FIGHTER_CLASSES if self._arena_class_enabled_locked(chat,k)}
            active,passive,*_=mirror_reward_items(level,enabled_classes=enabled)
            opts=[dict(id=i,**item) for i,item in [('active',active),('passive',passive)]
                  if self._arena_content_enabled_locked(chat,item['kind'],item['content_id'])]
            opts.append(dict(id='pages',kind='pages',name='Связка страниц',pages=dungeon.final_pages(level)))
        data.update(phase='reward',rewards_available=opts,result='Последнее отражение разбито. Выбери трофей.')

    def _mirror_dungeon_action_locked(self,row,data,action,value):
        phase=data['phase']
        if action=='visit' and phase=='map' and value in dungeon.available(data):
            node=next(n for n in data['route'][data.get('step',data['floor'])-1]['nodes'] if n['id']==value)
            data['lane']=node['lane']
            data['path'].append(value)
            if 'enemy' in node:
                self._mirror_battle_locked(row,data,enemy=node['enemy'],kind=node['kind'])
            elif node['kind']=='shop':
                self._mirror_open_shop_locked(row,data,'Лавка перед боссом этажа.' if data.get('route_version')==2 else 'Последняя лавка. Дальше — босс.')
            elif node['kind']=='rest':
                data['hp']=min(data['max_hp'],data['hp']+max(1,round(.34*data['max_hp'])))
                data['resource']=min(data['resource_max'],data['resource']+25)
                self._mirror_room_complete_locked(row,data,'Передышка: восстановлено до 34% HP и 25 энергии.')
            else:
                data['discount']=True
                self._mirror_room_complete_locked(row,data,'Тайник: скидка 5 ед. Пыли в лавке этого этажа.')
        elif action=='buy' and phase=='merchant':
            stock=dict(data['shop'])
            if value in stock and value not in data['gifts']:
                price=stock[value]
                if data['dust']<price:raise ValueError('Не хватает Пыли.')
                data['gifts'].append(value)
                notice=f'Артефакт «{GIFTS[value][0]}» действует до конца забега.'
            elif value in dungeon.SHOP_SUPPLIES and value not in data['supplies']:
                field,limit,amount=('hp','max_hp',max(1,round(data['max_hp']*.35))) if value=='heal' else ('resource','resource_max',45)
                if data[field]>=data[limit]:raise ValueError('Эта покупка сейчас ничего не восстановит.')
                price=dungeon.shop_price(data,dungeon.SHOP_SUPPLIES[value][2])
                if data['dust']<price:raise ValueError('Не хватает Пыли.')
                restored=min(amount,data[limit]-data[field]);data[field]+=restored
                data['supplies'].append(value)
                notice=f'Восстановлено: {restored} {"HP" if value=="heal" else "энергии"}.'
            else:
                raise ValueError('Предложение уже куплено или недоступно.')
            data['dust']-=price;data['result']=notice
        elif action=='next' and phase=='merchant':
            data.update(shop=[],supplies=[],discount=False,result='',battle_token='')
            if data['floor']==dungeon.DEPTH or data.get('route_version')==2:
                data['boss_active']=True
                self._mirror_battle_locked(row,data,enemy=data['final_enemy'],kind='boss')
            else:
                data.update(floor=data['floor']+1,phase='map')
        elif action=='next' and phase=='landing' and data.get('route_version')==2 and data['floor']<dungeon.DEPTH:
            data['floor']+=1
            self._mirror_prepare_floor(data)
        elif action=='claim' and phase=='reward':
            item=next((i for i in data['rewards_available'] if i['id']==value),None)
            if not item:raise ValueError('Такого трофея нет.')
            if item['kind']=='pages':
                self._mirror_add_pages_locked(row,data,item['pages'])
            elif item['kind']=='gear':
                from arena_equipment import public_item
                gear=self._gear_grant_locked(row['actor_id'],item['key'],'S',item['rarity'],affixes=item['affixes'])
                data['item_rewards'].append(dict(public_item(gear),kind='gear'))
            else:
                self._arena_add_item_locked(row['chat_id'],row['actor_id'],item['kind'],item['content_id'],item['rarity'],item['quantity'])
                data['item_rewards'].append(item)
            data.update(phase='ended',result=f'Пустошь пройдена. Трофей: {item["name"]}.',rewards_available=[])
        else:
            raise ValueError('Этот переход или действие сейчас недоступны.')
        self._mirror_save_locked(row,data)

    async def arena_mirror_get(self, token, actor):
        async with self._lock:
            row = self._mirror_row_locked(token)
            if row["actor_id"] != actor:
                raise ValueError("Это не ваш забег.")
            self._mirror_cleanup_locked(row["chat_id"])
            self.connection.commit()
            return self._mirror_public_locked(self._mirror_row_locked(token))

    async def arena_mirror_list(self, chat, actor):
        async with self._lock:
            self._mirror_cleanup_locked(chat)
            rows = self.connection.execute(
                "SELECT * FROM arena_mirror_runs WHERE actor_id=? ORDER BY created_at DESC,rowid DESC LIMIT 5",
                (actor,),
            ).fetchall()
            self.connection.commit()
            return [self._mirror_public_locked(dict(r),detail=False) for r in rows]

    async def arena_mirror_action(self, token, actor, revision, action, value=""):
        async with self._lock:
            row = self._mirror_row_locked(token)
            if row["actor_id"] != actor:
                raise ValueError("Это не ваш забег.")
            self._mirror_cleanup_locked(row["chat_id"])
            self.connection.commit()
            row = self._mirror_row_locked(token)
            data = json.loads(row["data_json"])
            claim=row['status']=='finished' and data.get('layout')==2 and data['phase']=='reward' and action=='claim'
            if (row['status']!='active' and not claim) or row['revision'] != revision:
                raise ValueError("Забег изменился. Обновите окно.")
            try:
                if action == "abandon":
                    self._mirror_close_locked(
                        row, "Забег оставлен. Награды за пройденные рубежи сохранены." if data.get('layout')==2
                        else "Забег оставлен. Награды за босса нет."
                    )
                elif data.get('layout')==2:
                    self._mirror_dungeon_action_locked(row,data,action,value)
                elif (
                    action == "gift"
                    and data["phase"] == "gift"
                    and value in data["choices"]
                ):
                    data["gifts"].append(value)
                    data.update(phase="route", choices=[])
                    self._mirror_save_locked(row, data)
                elif (
                    action == "route"
                    and data["phase"] == "route"
                    and value in {"rest", "event", "merchant"}
                ):
                    data["phase"] = value
                    if value == "rest":
                        data["hp"] = min(
                            data["max_hp"],
                            data["hp"] + max(1, round(data["max_hp"] * 0.35)),
                        )
                        data["resource"] = min(
                            data["resource_max"], data["resource"] + 35
                        )
                        data.update(
                            phase="ready",
                            result="Отдых: восстановлены 35% HP и 35 энергии.",
                        )
                    elif value == "event":
                        data["event"] = random.SystemRandom().choice(["altar", "chest"])
                    self._mirror_save_locked(row, data)
                elif (
                    action == "event"
                    and data["phase"] == "event"
                    and value in {"risk", "safe"}
                ):
                    if value == "risk":
                        if data["event"] == "altar":
                            cost = max(1, round(data["max_hp"] * 0.20))
                            if data["hp"] <= cost or "risk" in data["gifts"]:
                                raise ValueError(
                                    "Для жертвы не хватает HP или дар уже получен."
                                )
                            data["hp"] -= cost
                            data["gifts"].append("risk")
                            data["result"] = (
                                "Алтарь принял жертву. Урон +20%, обе защиты −15% до конца забега."
                            )
                        else:
                            success = random.SystemRandom().random() < 0.6
                            if success:
                                data["shards"] += 30
                            else:
                                data["hp"] = max(
                                    1, data["hp"] - max(1, round(data["max_hp"] * 0.15))
                                )
                            data["result"] = (
                                "В сундуке 30 осколков!"
                                if success
                                else "Ловушка: потеряно 15% максимального HP."
                            )
                    else:
                        data["result"] = "Ты прошёл мимо, ничего не потеряв."
                    data["phase"] = "ready"
                    self._mirror_save_locked(row, data)
                elif (
                    action == "shop"
                    and data["phase"] == "merchant"
                    and value in {"heal", "energy", "gift", "leave"}
                ):
                    if value != "leave":
                        if data.get("shop_bought") == data["floor"]:
                            raise ValueError("Одна покупка за эту встречу.")
                        price = 30 if value == "gift" else 20
                        if data["shards"] < price:
                            raise ValueError("Не хватает осколков.")
                        if value == "gift":
                            pool = [k for k in NORMAL_GIFTS if k not in data["gifts"]]
                            if not pool:
                                raise ValueError("Все дары уже получены.")
                            data["gifts"].append(random.SystemRandom().choice(pool))
                        elif value == "heal":
                            data["hp"] = min(
                                data["max_hp"],
                                data["hp"] + max(1, round(data["max_hp"] * 0.50)),
                            )
                        else:
                            data["resource"] = min(
                                data["resource_max"], data["resource"] + 60
                            )
                        data["shards"] -= price
                        data["shop_bought"] = data["floor"]
                    data.update(phase="ready", result="Торговец остался позади.")
                    self._mirror_save_locked(row, data)
                elif action == "next" and data["phase"] == "ready":
                    data["floor"] += 1
                    self._mirror_battle_locked(row, data)
                    self._mirror_save_locked(row, data)
                else:
                    raise ValueError("Действие недоступно на этом этапе.")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            return self._mirror_public_locked(self._mirror_row_locked(token))
