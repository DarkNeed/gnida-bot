"""Guild gear supply. Legacy merchant records are retained, never resold."""
from copy import deepcopy
from datetime import datetime
import json
import random
import secrets
from arena_equipment import CATALOG,RANKS,RARITIES,AFFIXES,public_item,item_price,apply_stats


class GearMerchantMixin:
    def _connect_gear_market(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS gear_merchant_offers(id TEXT PRIMARY KEY,visit_id INTEGER NOT NULL,
                position INTEGER NOT NULL,data TEXT NOT NULL,UNIQUE(visit_id,position));
            CREATE TABLE IF NOT EXISTS gear_merchant_purchases(actor INTEGER NOT NULL,offer TEXT NOT NULL,
                visit_id INTEGER NOT NULL,day TEXT NOT NULL,rarity TEXT NOT NULL,PRIMARY KEY(actor,offer));
            CREATE TABLE IF NOT EXISTS gear_guild_offers(id TEXT PRIMARY KEY,day TEXT NOT NULL,
                rank TEXT NOT NULL,data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS gear_guild_stock ON gear_guild_offers(day,rank);
            CREATE TABLE IF NOT EXISTS gear_guild_purchases(actor INTEGER NOT NULL,nonce TEXT NOT NULL,
                offer TEXT NOT NULL,day TEXT NOT NULL,rarity TEXT NOT NULL,PRIMARY KEY(actor,nonce));
            CREATE INDEX IF NOT EXISTS gear_guild_daily_purchases ON gear_guild_purchases(actor,day,rarity);
        ''')

    def _gear_guild_stock_locked(self,rank,day):
        # Fixed public properties, not a hidden reroll at checkout. Permanent
        # stock survives restarts; the daily showcase is global across chats.
        specs=[('','guild-gear-v1-'+rank+'-'+rarity+'-'+key,key,rarity)
            for key,v in CATALOG.items() if v['biome']!='nazarick' for rarity in ('uncommon','rare')]
        if RANKS.index(rank)>=2:
            for slot in ('weapon','armor','accessory','relic'):
                ident='guild-gear-v1-'+day+'-'+rank+'-'+slot
                rng=random.Random(ident)
                key=rng.choice([k for k,v in CATALOG.items() if v['slot']==slot and v['biome']!='nazarick'])
                specs.append((day,ident,key,'epic'))
        existing={r[0] for r in self.connection.execute("SELECT id FROM gear_guild_offers WHERE rank=? AND day IN ('',?)",(rank,day))}
        for stamp,ident,key,rarity in specs:
            if ident in existing:continue
            rng=random.Random(ident)
            item=dict(id=ident,key=key,rank=rank,rarity=rarity,upgrade=0,
                affixes=rng.sample([k for k in AFFIXES if k!=CATALOG[key]['main']],min(2,RARITIES.index(rarity))),
                favorite=False,rerolled=False,created=0)
            self.connection.execute('INSERT OR IGNORE INTO gear_guild_offers VALUES(?,?,?,?)',
                (ident,stamp,rank,json.dumps(item,ensure_ascii=False)))
        return self.connection.execute("SELECT * FROM gear_guild_offers WHERE rank=? AND day IN ('',?) ORDER BY day, id",(rank,day)).fetchall()

    def _gear_guild_reason_locked(self,actor,item,day):
        if RANKS.index(item['rank'])>self._guild_hunter_locked(actor)['rank']:
            return 'Нужен ранг охотника '+item['rank']+'. Покупать на ранг выше нельзя.'
        if item['rarity']=='epic' and (self.connection.execute(
            "SELECT 1 FROM gear_guild_purchases WHERE actor=? AND day=? AND rarity='epic'",(actor,day)).fetchone() or
            self.connection.execute("SELECT 1 FROM gear_merchant_purchases WHERE actor=? AND day=? AND rarity='epic'",(actor,day)).fetchone()):
            return 'Эпическую экипировку можно купить раз в сутки на аккаунт.'
        return ''

    def _gear_guild_view_locked(self,chat,actor,rank=None):
        from arena_market import market_now,MSK
        now=market_now();day=datetime.fromtimestamp(now,MSK).date().isoformat()
        h=self._guild_hunter_locked(actor);rank=rank or RANKS[h['rank']]
        if not isinstance(rank,str) or rank not in RANKS:raise ValueError('Неизвестный ранг снаряжения.')
        gear=self._gear_view_locked(chat,actor);current=self._gear_snapshot_locked(actor,gear['level']);offers=[]
        for row in self._gear_guild_stock_locked(rank,day):
            item=public_item(json.loads(row['data']))
            other=[i for i in current if CATALOG[i['key']]['slot']!=item['slot']]
            item.update(price=item_price(item),daily=bool(row['day']),
                purchase_warning=self._gear_guild_reason_locked(actor,item,day),
                comparison=apply_stats(gear['base_stats'],other+[item]))
            offers.append(item)
        money=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone()
        return dict(offers=offers,stats=gear['stats'],stat_names=gear['stat_names'],rank=rank,
            character_slot=gear['character_slot'],level=gear['level'],hunter_rank=gear['hunter_rank'],
            balance=money['balance'] if money else 0,day=day,server_time=now,
            refresh_at=int(datetime.combine(datetime.fromtimestamp(now,MSK).date(),datetime.min.time(),tzinfo=MSK).timestamp())+86400)

    async def gear_guild_view(self,chat,actor,rank=None):
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'arena')
                return self._gear_guild_view_locked(chat,actor,rank)

    def _gear_market_locked(self,chat,actor,visit=None):
        # Selling remains available at the merchant even when he is absent.
        gear=self._gear_view_locked(chat,actor)
        return dict(offers=[],items=gear['items'],stats=gear['stats'],stat_names=gear['stat_names'],
            revision=gear['revision'],character_slot=gear['character_slot'],level=gear['level'],
            hunter_rank=gear['hunter_rank'],busy=gear['busy'],moved_to_guild=True)

    async def gear_merchant_buy(self,*args,**kwargs):
        raise ValueError('Покупка снаряжения перенесена в гильдию: Лавка → Снаряжение.')

    async def gear_guild_buy(self,chat,actor,offer,nonce,confirm=False,*,expected_price=None):
        from arena_market import market_now,MSK
        if confirm is not True or not isinstance(offer,str) or not isinstance(nonce,str) or not 8<=len(nonce)<=80:
            raise ValueError('Подтверди покупку экипировки.')
        if type(expected_price) is not int or not 0<expected_price<=20000:raise ValueError('Обнови цену перед покупкой.')
        mark=json.dumps(dict(action='guild_gear_buy',chat=chat,offer=offer,price=expected_price),sort_keys=True)
        async with self._lock:
            with self.connection:
                if not self.connection.in_transaction:self.connection.execute('BEGIN IMMEDIATE')
                self._require_feature_locked(chat,'arena')
                old=self.connection.execute('SELECT fingerprint FROM gear_requests WHERE actor=? AND nonce=?',(actor,nonce)).fetchone()
                if old:
                    if old[0]!=mark:raise ValueError('Запрос уже использован для другой операции.')
                    return 'Покупка уже выполнена. Вещь в общем инвентаре.'
                now=market_now();day=datetime.fromtimestamp(now,MSK).date().isoformat()
                row=self.connection.execute('SELECT * FROM gear_guild_offers WHERE id=?',(offer,)).fetchone()
                if not row or row['day'] not in ('',day):raise ValueError('Предложение устарело. Обнови лавку гильдии.')
                item=json.loads(row['data'])
                if item['rarity'] not in ('uncommon','rare','epic') or CATALOG[item['key']]['biome']=='nazarick':
                    raise ValueError('Эксклюзив не продаётся.')
                reason=self._gear_guild_reason_locked(actor,item,day)
                if reason:raise ValueError(reason)
                price=item_price(item)
                if price!=expected_price:raise ValueError('Цена изменилась. Обнови лавку и подтверди покупку заново.')
                if not self.connection.execute('UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?',
                        (price,now,chat,actor,price)).rowcount:raise ValueError('Не хватает франков.')
                owned=deepcopy(item);owned.update(id=secrets.token_hex(10),created=now)
                self._gear_save_locked(actor,owned);self._gear_touch_locked(actor)
                self.connection.execute('INSERT INTO gear_guild_purchases VALUES(?,?,?,?,?)',(actor,nonce,offer,day,item['rarity']))
                self.connection.execute('INSERT INTO gear_requests VALUES(?,?,?)',(actor,nonce,mark))
                return 'Куплено: «'+CATALOG[item['key']]['name']+'». Вещь добавлена в общее снаряжение.'
