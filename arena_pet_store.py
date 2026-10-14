"""Global pet economy. Every grant/open/payment is durable and replay-safe."""
import json
import random
import secrets
import time
from datetime import datetime, timedelta, timezone

from arena_global import RPG_SCOPE
from arena_characters import CHARACTER_PACK, CHARACTER_PRICE, CHARACTER_TERMS_VERSION
from arena_pets import PETS, PET_ODDS, PET_PACKS, PET_TERMS_VERSION, PET_MILESTONES, pet_snapshot


def pet_day():
    return datetime.now(timezone(timedelta(hours=3))).date().isoformat()


def next_odds(wallet):
    if wallet["legend_misses"] >= 29:
        return dict(common=0, rare=0, epic=0, legendary=100)
    if wallet["epic_misses"] >= 9:
        return dict(common=0, rare=0, epic=90, legendary=10)
    return dict(PET_ODDS)


class PetMixin:
    def _connect_pets(self):
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS pet_wallets (
          user_id INTEGER PRIMARY KEY, tickets INTEGER NOT NULL DEFAULT 0,
          food INTEGER NOT NULL DEFAULT 0, essence INTEGER NOT NULL DEFAULT 0,
          shards INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
          epic_misses INTEGER NOT NULL DEFAULT 0, legend_misses INTEGER NOT NULL DEFAULT 0,
          terms_version TEXT, terms_at INTEGER);
        CREATE TABLE IF NOT EXISTS pet_owned (
          user_id INTEGER NOT NULL, pet_id TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 1,
          power INTEGER NOT NULL DEFAULT 0, tempo INTEGER NOT NULL DEFAULT 0,
          acquired_at INTEGER NOT NULL, PRIMARY KEY(user_id,pet_id));
        CREATE TABLE IF NOT EXISTS pet_equipment (
          chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, pet_id TEXT NOT NULL,
          PRIMARY KEY(chat_id,user_id));
        CREATE TABLE IF NOT EXISTS pet_openings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          nonce TEXT NOT NULL, result_json TEXT NOT NULL, created_at INTEGER NOT NULL,
          UNIQUE(user_id,nonce));
        CREATE TABLE IF NOT EXISTS pet_grants (
          user_id INTEGER NOT NULL, event_key TEXT NOT NULL, kind TEXT NOT NULL,
          day TEXT NOT NULL, reward_json TEXT NOT NULL,
          PRIMARY KEY(user_id,event_key));
        CREATE TABLE IF NOT EXISTS pet_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL UNIQUE,
          user_id INTEGER NOT NULL, pack TEXT NOT NULL, tickets INTEGER NOT NULL,
          stars INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          charge_id TEXT UNIQUE, created_at INTEGER NOT NULL, paid_at INTEGER,
          terms_version TEXT NOT NULL, refund_at INTEGER);
        CREATE TABLE IF NOT EXISTS pet_payment_issues (
          charge_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, payload TEXT NOT NULL,
          currency TEXT NOT NULL, total INTEGER NOT NULL, received_at INTEGER NOT NULL,
          refunded_at INTEGER);
        CREATE TABLE IF NOT EXISTS pet_refund_receipts (
          charge_id TEXT PRIMARY KEY, payload TEXT NOT NULL, currency TEXT NOT NULL,
          total INTEGER NOT NULL, received_at INTEGER NOT NULL);
        """)
        if "refunded_at" not in {r["name"] for r in self.connection.execute("PRAGMA table_info(pet_payment_issues)")}:
            self.connection.execute("ALTER TABLE pet_payment_issues ADD COLUMN refunded_at INTEGER")
        self.connection.commit()

    def _pet_wallet_locked(self, user):
        if type(user) is not int or user <= 0:
            raise ValueError("Некорректный пользователь.")
        self.connection.execute("INSERT OR IGNORE INTO pet_wallets(user_id) VALUES(?)", (user,))
        return dict(self.connection.execute("SELECT * FROM pet_wallets WHERE user_id=?", (user,)).fetchone())

    def _pet_view_locked(self, user, chat=0):
        wallet = self._pet_wallet_locked(user)
        owned = []
        for row in self.connection.execute("SELECT * FROM pet_owned WHERE user_id=? ORDER BY acquired_at,pet_id", (user,)):
            item = pet_snapshot(dict(row, id=row["pet_id"]))
            if item:
                new_level = item["level"] + 1
                item["upgrade"] = dict(food=10 * new_level, essence=2 if new_level in PET_MILESTONES else 0,
                                       choice=new_level in PET_MILESTONES) if new_level <= 10 else None
                owned.append(item)
        equipment = self.connection.execute("SELECT pet_id FROM pet_equipment WHERE chat_id=? AND user_id=?", (RPG_SCOPE, user)).fetchone()
        openings = [dict(id=r["id"], **json.loads(r["result_json"])) for r in self.connection.execute(
            "SELECT * FROM pet_openings WHERE user_id=? ORDER BY id DESC LIMIT 12", (user,))]
        history = [dict(r) for r in self.connection.execute(
            "SELECT id,pack,tickets,stars,status,created_at,paid_at FROM pet_orders WHERE user_id=? ORDER BY id DESC LIMIT 12", (user,))]
        refund_pending = bool(self.connection.execute("SELECT 1 FROM pet_orders WHERE user_id=? AND status='refunding' AND pack<>'characters'", (user,)).fetchone())
        chat_row = self.connection.execute("SELECT title FROM chats WHERE chat_id=?", (chat,)).fetchone() if chat else None
        return dict(wallet=dict(tickets=max(0,wallet["tickets"]), ticket_debt=max(0,-wallet["tickets"]),
                                food=wallet["food"], essence=wallet["essence"], shards=wallet["shards"], revision=wallet["revision"]),
                    owned=owned, equipped=equipment["pet_id"] if equipment else None, chat_id=chat,
                    chat_title=chat_row["title"] if chat_row else str(chat),
                    catalog=[dict(p, exchange_cost={"common":100,"rare":150,"epic":220,"legendary":350}[p["rarity"]]) for p in PETS.values()],
                    packs=[dict(id=k,tickets=v[0],stars=v[1]) for k,v in PET_PACKS.items()],
                    odds=next_odds(wallet), base_odds=PET_ODDS, pity=dict(epic=10-wallet["epic_misses"],legendary=30-wallet["legend_misses"]),
                    daily_available=not bool(self.connection.execute("SELECT 1 FROM pet_grants WHERE user_id=? AND event_key=?", (user,"daily:"+pet_day())).fetchone()),
                    openings=openings, orders=history, refund_pending=refund_pending,
                    terms_version=PET_TERMS_VERSION)

    async def pet_view(self, user, chat=0):
        async with self._lock:
            view = self._pet_view_locked(user, chat)
            self.connection.commit()
            return view

    def _pet_source_locked(self, chat, user):
        wallet = self.connection.execute("SELECT tickets FROM pet_wallets WHERE user_id=?", (user,)).fetchone()
        if wallet and wallet["tickets"] < 0:
            return None
        row = self.connection.execute("""SELECT o.* FROM pet_equipment e JOIN pet_owned o
          ON o.user_id=e.user_id AND o.pet_id=e.pet_id WHERE e.chat_id=? AND e.user_id=?""", (RPG_SCOPE,user)).fetchone()
        return pet_snapshot(dict(row,id=row["pet_id"])) if row else None

    def _pet_revision_locked(self, user, revision):
        wallet = self._pet_wallet_locked(user)
        if type(revision) is not int or wallet["revision"] != revision:
            raise ValueError("Меню устарело. Обновите страницу.")
        return wallet

    async def pet_open(self, user, revision, nonce, chat=0, rng=None):
        if not isinstance(nonce,str) or not 8 <= len(nonce) <= 64 or not all(c.isalnum() or c in "-_" for c in nonce):
            raise ValueError("Некорректный номер открытия.")
        async with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                old = self.connection.execute("SELECT result_json FROM pet_openings WHERE user_id=? AND nonce=?", (user,nonce)).fetchone()
                if old:
                    result = json.loads(old["result_json"])
                else:
                    wallet = self._pet_revision_locked(user,revision)
                    if wallet["tickets"] <= 0:
                        raise ValueError("Нет билетов на посылку.")
                    if self.connection.execute("SELECT 1 FROM pet_orders WHERE user_id=? AND status='refunding' AND pack<>'characters'", (user,)).fetchone():
                        raise ValueError("Сначала дождитесь завершения возврата.")
                    rng = rng or random.SystemRandom()
                    odds = next_odds(wallet)
                    roll = rng.random() * 100
                    rarity = "legendary"
                    for tier, weight in odds.items():
                        if roll < weight: rarity=tier; break
                        roll -= weight
                    pet_id = rng.choice([k for k,p in PETS.items() if p["rarity"]==rarity])
                    duplicate = bool(self.connection.execute("SELECT 1 FROM pet_owned WHERE user_id=? AND pet_id=?", (user,pet_id)).fetchone())
                    shards = {"common":10,"rare":15,"epic":20,"legendary":30}[rarity] if duplicate else 0
                    self.connection.execute("INSERT OR IGNORE INTO pet_owned(user_id,pet_id,acquired_at) VALUES(?,?,?)", (user,pet_id,int(time.time())))
                    self.connection.execute("""UPDATE pet_wallets SET tickets=tickets-1,shards=shards+?,revision=revision+1,
                      epic_misses=?,legend_misses=? WHERE user_id=?""",
                      (shards,0 if rarity in {"epic","legendary"} else wallet["epic_misses"]+1,
                       0 if rarity=="legendary" else wallet["legend_misses"]+1,user))
                    result = dict(pet=dict(PETS[pet_id]),duplicate=duplicate,shards=shards,nonce=nonce)
                    self.connection.execute("INSERT INTO pet_openings(user_id,nonce,result_json,created_at) VALUES(?,?,?,?)", (user,nonce,json.dumps(result,ensure_ascii=False),int(time.time())))
                view = self._pet_view_locked(user,chat)
                self.connection.commit()
                return dict(result=result,view=view)
            except Exception:
                self.connection.rollback(); raise

    async def pet_action(self,user,revision,action,pet_id="",choice="",chat=0):
        async with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                wallet = self._pet_revision_locked(user,revision)
                if action != "daily" and wallet["tickets"] < 0:
                    raise ValueError("После возврата нужно погасить долг билетов. Бесплатные билеты тоже подходят.")
                if action == "daily":
                    self._pet_reward_locked(user,"daily","daily:"+pet_day())
                elif action in {"equip","unequip"}:
                    if action == "unequip":
                        self.connection.execute("DELETE FROM pet_equipment WHERE chat_id=? AND user_id=?",(RPG_SCOPE,user))
                    else:
                        if pet_id not in PETS or not self.connection.execute("SELECT 1 FROM pet_owned WHERE user_id=? AND pet_id=?",(user,pet_id)).fetchone():
                            raise ValueError("Этот питомец вам не принадлежит.")
                        self.connection.execute("INSERT INTO pet_equipment VALUES(?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET pet_id=excluded.pet_id",(RPG_SCOPE,user,pet_id))
                    self.connection.execute("UPDATE pet_wallets SET revision=revision+1 WHERE user_id=?",(user,))
                elif action == "exchange":
                    if pet_id not in PETS: raise ValueError("Неизвестный питомец.")
                    if self.connection.execute("SELECT 1 FROM pet_owned WHERE user_id=? AND pet_id=?",(user,pet_id)).fetchone():
                        raise ValueError("Питомец уже есть в коллекции.")
                    cost = {"common":100,"rare":150,"epic":220,"legendary":350}[PETS[pet_id]["rarity"]]
                    if wallet["shards"] < cost: raise ValueError("Не хватает осколков.")
                    self.connection.execute("UPDATE pet_wallets SET shards=shards-?,revision=revision+1 WHERE user_id=?",(cost,user))
                    self.connection.execute("INSERT INTO pet_owned(user_id,pet_id,acquired_at) VALUES(?,?,?)",(user,pet_id,int(time.time())))
                elif action == "upgrade":
                    row = self.connection.execute("SELECT * FROM pet_owned WHERE user_id=? AND pet_id=?",(user,pet_id)).fetchone()
                    if not row or row["level"] >= 10: raise ValueError("Питомца нельзя улучшить.")
                    level = row["level"]+1
                    milestone = level in PET_MILESTONES
                    if milestone and choice not in {"power","tempo"}: raise ValueError("Выберите силу или частоту срабатывания.")
                    if not milestone and choice: raise ValueError("Выбор доступен только на уровнях 3, 6 и 10.")
                    food, essence = 10*level, 2 if milestone else 0
                    missing_food,missing_essence = max(0,food-wallet["food"]),max(0,essence-wallet["essence"])
                    substitute = 2*missing_food+10*missing_essence
                    if wallet["shards"] < substitute: raise ValueError("Не хватает корма/эссенции и заменяющих осколков.")
                    self.connection.execute("UPDATE pet_wallets SET food=food-?,essence=essence-?,shards=shards-?,revision=revision+1 WHERE user_id=?",
                                            (food-missing_food,essence-missing_essence,substitute,user))
                    self.connection.execute("UPDATE pet_owned SET level=?,power=power+?,tempo=tempo+? WHERE user_id=? AND pet_id=?",
                                            (level,int(milestone and choice=="power"),int(milestone and choice=="tempo"),user,pet_id))
                else: raise ValueError("Неизвестное действие.")
                result = self._pet_view_locked(user,chat)
                self.connection.commit(); return result
            except Exception:
                self.connection.rollback(); raise

    def _pet_reward_locked(self,user,kind,event_key):
        """Only called inside settlement transactions; global daily caps, no forfeits."""
        self._pet_wallet_locked(user)
        if self.connection.execute("SELECT 1 FROM pet_grants WHERE user_id=? AND event_key=?",(user,event_key)).fetchone(): return {}
        day=pet_day()
        count=self.connection.execute("SELECT count(*) AS n FROM pet_grants WHERE user_id=? AND day=? AND kind=?",(user,day,kind)).fetchone()["n"]
        if kind=="daily": reward=dict(tickets=1,food=4,essence=0)
        elif kind=="wasteland": reward=dict(tickets=int(count==2),food=2 if count<10 else 0,essence=0)
        elif kind=="raid": reward=dict(tickets=int(count==0),food=5 if count<3 else 0,essence=2 if count==0 else 0)
        elif kind=="mirror": reward=dict(tickets=int(count==0),food=8 if count<2 else 0,essence=4 if count==0 else 0)
        else: raise ValueError("Неизвестный источник награды.")
        self.connection.execute("INSERT INTO pet_grants VALUES(?,?,?,?,?)",(user,event_key,kind,day,json.dumps(reward)))
        self.connection.execute("UPDATE pet_wallets SET tickets=tickets+?,food=food+?,essence=essence+?,revision=revision+1 WHERE user_id=?",(reward["tickets"],reward["food"],reward["essence"],user))
        return reward

    async def pet_create_order(self,user,pack,terms_version):
        packs={**PET_PACKS,CHARACTER_PACK:(0,CHARACTER_PRICE)}
        expected_terms=CHARACTER_TERMS_VERSION if pack==CHARACTER_PACK else PET_TERMS_VERSION
        if pack not in packs or terms_version!=expected_terms: raise ValueError("Примите актуальные условия покупки.")
        async with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                self._pet_wallet_locked(user)
                tickets,stars=packs[pack]
                now=int(time.time())
                if pack==CHARACTER_PACK:
                    if self._character_unlocked_locked(user):raise ValueError('Все дополнительные слоты уже открыты.')
                    pending=self.connection.execute("SELECT * FROM pet_orders WHERE user_id=? AND pack=? AND status='pending' AND created_at>? ORDER BY id DESC LIMIT 1",(user,pack,now-3600)).fetchone()
                    if pending:
                        self.connection.commit();return dict(pending)
                recent = self.connection.execute("SELECT count(*) AS n FROM pet_orders WHERE user_id=? AND created_at>?", (user, now-300)).fetchone()["n"]
                if recent >= 5:
                    raise ValueError("Слишком много счетов. Подождите пять минут.")
                self.connection.execute("UPDATE pet_wallets SET terms_version=?,terms_at=? WHERE user_id=?",(terms_version,now,user))
                payload="pets_"+secrets.token_urlsafe(24)
                self.connection.execute("INSERT INTO pet_orders(payload,user_id,pack,tickets,stars,created_at,terms_version) VALUES(?,?,?,?,?,?,?)",(payload,user,pack,tickets,stars,now,terms_version))
                order=dict(self.connection.execute("SELECT * FROM pet_orders WHERE payload=?",(payload,)).fetchone())
                self.connection.commit(); return order
            except Exception: self.connection.rollback(); raise

    async def pet_check_order(self,user,payload,currency,total):
        async with self._lock:
            row=self.connection.execute("SELECT * FROM pet_orders WHERE payload=?",(payload,)).fetchone()
            if not row or row["user_id"]!=user or currency!="XTR" or type(total) is not int or total!=row["stars"] or row["status"]!="pending" or int(time.time())-row["created_at"]>3600:
                raise ValueError("Счёт недействителен. Создайте новый в магазине питомцев.")
            if row['pack']==CHARACTER_PACK and self._character_unlocked_locked(user):
                raise ValueError('Все дополнительные слоты уже открыты.')
            return dict(row)

    async def pet_payment(self,user,payload,currency,total,charge):
        if not isinstance(charge,str) or not charge or len(charge)>1024: raise ValueError("Нет номера платежа.")
        async with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                row=self.connection.execute("SELECT * FROM pet_orders WHERE payload=?",(payload,)).fetchone()
                if not row or row["user_id"]!=user or currency!="XTR" or type(total) is not int or row["stars"]!=total:
                    raise ValueError("Параметры оплаты не совпали с заказом.")
                if row["charge_id"]==charge:
                    self.connection.commit(); return dict(row, replay=True)
                if row["status"]!="pending": raise ValueError("Этот заказ уже оплачен.")
                if row['pack']==CHARACTER_PACK and self._character_unlocked_locked(user):
                    raise ValueError('Слоты уже открыты другим платежом. Требуется возврат второго платежа.')
                self._pet_wallet_locked(user)
                self.connection.execute("UPDATE pet_orders SET status='paid',charge_id=?,paid_at=? WHERE id=?",(charge,int(time.time()),row["id"]))
                receipt = self.connection.execute("SELECT * FROM pet_refund_receipts WHERE charge_id=?", (charge,)).fetchone()
                if receipt:
                    if receipt["payload"] != payload or receipt["currency"] != currency or receipt["total"] != total:
                        raise ValueError("Возврат не совпал с параметрами оплаты.")
                    # Refund updates can overtake the successful_payment handler.
                    # Never grant goods for an already refunded charge.
                    self.connection.execute("UPDATE pet_orders SET status='refunded',refund_at=? WHERE id=?", (receipt["received_at"], row["id"]))
                    self.connection.commit()
                    return dict(row, status="refunded", charge_id=charge, replay=False)
                self.connection.execute("UPDATE pet_wallets SET tickets=tickets+?,revision=revision+1 WHERE user_id=?",(row["tickets"],user))
                if row['pack']==CHARACTER_PACK:self._character_license_changed_locked(user)
                result=dict(row,status="paid",charge_id=charge,replay=False)
                self.connection.commit(); return result
            except Exception: self.connection.rollback(); raise

    async def pet_start_refund(self,order_id):
        async with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                row=self.connection.execute("SELECT * FROM pet_orders WHERE id=?",(order_id,)).fetchone()
                if not row or row["status"] not in {"paid","refunding","refunded"}: raise ValueError("Нет оплаченного заказа.")
                if row["status"]=="paid":
                    self.connection.execute("UPDATE pet_orders SET status='refunding' WHERE id=?",(order_id,))
                    if row['pack']==CHARACTER_PACK:self._character_license_changed_locked(row['user_id'])
                self.connection.commit(); return dict(row)
            except Exception: self.connection.rollback(); raise

    async def pet_record_payment_issue(self, user, payload, currency, total, charge):
        async with self._lock:
            self.connection.execute("INSERT OR IGNORE INTO pet_payment_issues(charge_id,user_id,payload,currency,total,received_at) VALUES(?,?,?,?,?,?)",
                                    (charge, user, payload, currency, total, int(time.time())))
            receipt = self.connection.execute("SELECT * FROM pet_refund_receipts WHERE charge_id=?", (charge,)).fetchone()
            if receipt and receipt["payload"] == payload and receipt["currency"] == currency and receipt["total"] == total:
                self.connection.execute("UPDATE pet_payment_issues SET refunded_at=? WHERE charge_id=?", (receipt["received_at"], charge))
            issue = dict(self.connection.execute("SELECT rowid AS id,* FROM pet_payment_issues WHERE charge_id=?", (charge,)).fetchone())
            self.connection.commit()
            return issue

    async def pet_receive_refund(self, payload, currency, total, charge):
        if currency != "XTR" or type(total) is not int or total <= 0 or not charge:
            raise ValueError("Некорректный возврат Stars.")
        async with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                self.connection.execute("INSERT OR IGNORE INTO pet_refund_receipts VALUES(?,?,?,?,?)",
                                        (charge,payload,currency,total,int(time.time())))
                receipt = self.connection.execute("SELECT * FROM pet_refund_receipts WHERE charge_id=?", (charge,)).fetchone()
                if (receipt["payload"], receipt["currency"], receipt["total"]) != (payload,currency,total):
                    raise ValueError("Повтор возврата содержит другие параметры.")
                row = self.connection.execute("SELECT * FROM pet_orders WHERE payload=? AND charge_id=?", (payload,charge)).fetchone()
                if row:
                    if row["stars"] != total:
                        raise ValueError("Сумма возврата не совпала с заказом.")
                    if row["status"] != "refunded":
                        self.connection.execute("UPDATE pet_wallets SET tickets=tickets-?,revision=revision+1 WHERE user_id=?", (row["tickets"],row["user_id"]))
                        self.connection.execute("UPDATE pet_orders SET status='refunded',refund_at=? WHERE id=?", (receipt["received_at"],row["id"]))
                        if row['pack']==CHARACTER_PACK:self._character_license_changed_locked(row['user_id'])
                self.connection.execute("UPDATE pet_payment_issues SET refunded_at=? WHERE payload=? AND charge_id=? AND currency=? AND total=?", (receipt["received_at"],payload,charge,currency,total))
                self.connection.commit()
            except Exception:
                self.connection.rollback(); raise

    async def pet_payment_issue(self, issue_id):
        async with self._lock:
            row = self.connection.execute("SELECT rowid AS id,* FROM pet_payment_issues WHERE rowid=?", (issue_id,)).fetchone()
            if not row or row["currency"] != "XTR":
                raise ValueError("Не найден сбой оплаты Stars.")
            # Never refund a replayed charge that actually funded a valid order.
            if self.connection.execute("SELECT 1 FROM pet_orders WHERE charge_id=?", (row["charge_id"],)).fetchone():
                raise ValueError("Этот платёж относится к обычному заказу. Используй возврат по номеру заказа.")
            return dict(row)

    async def pet_payment_issue_refunded(self, issue_id):
        async with self._lock:
            self.connection.execute("UPDATE pet_payment_issues SET refunded_at=COALESCE(refunded_at,?) WHERE rowid=?", (int(time.time()), issue_id))
            self.connection.commit()

    async def pet_refund_order(self, payload, currency, total, charge):
        async with self._lock:
            row = self.connection.execute("SELECT * FROM pet_orders WHERE payload=? AND charge_id=?", (payload, charge)).fetchone()
            if not row:
                issue = self.connection.execute("SELECT rowid AS id,* FROM pet_payment_issues WHERE payload=? AND charge_id=?", (payload, charge)).fetchone()
                if issue and currency == "XTR" and total == issue["total"]:
                    return dict(issue, issue=True)
            if not row or currency != "XTR" or total != row["stars"]:
                raise ValueError("Возврат не совпал с заказом.")
            return dict(row)

    async def pet_finish_refund(self,order_id):
        async with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                row=self.connection.execute("SELECT * FROM pet_orders WHERE id=?",(order_id,)).fetchone()
                if not row or row["status"] not in {"refunding","refunded"}: raise ValueError("Возврат не начат.")
                if row["status"]!="refunded":
                    # Spent tickets create explicit debt, never a second free paid pack.
                    self.connection.execute("UPDATE pet_wallets SET tickets=tickets-?,revision=revision+1 WHERE user_id=?",(row["tickets"],row["user_id"]))
                    self.connection.execute("UPDATE pet_orders SET status='refunded',refund_at=? WHERE id=?",(int(time.time()),order_id))
                    if row['pack']==CHARACTER_PACK:self._character_license_changed_locked(row['user_id'])
                self.connection.commit(); return dict(row,status="refunded")
            except Exception: self.connection.rollback(); raise
