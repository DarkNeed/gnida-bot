"""Atomic account-wide scroll forging; francs are paid in the invoking chat."""

import hashlib
import json
import math
import random
import re
import time
from arena_engine import RARITY_LABELS
from arena_modules import ClassModulesMixin
from arena_global import RPG_SCOPE

FORGE_RULES = {
    r: dict(salvage_pages=2, craft_pages=6, craft_price=p, rewrite_price=p // 2)
    for r, p in (("common", 40), ("uncommon", 70), ("rare", 130), ("epic", 250))
}
FORGE_FUSION_ODDS = {r: dict(zip(FORGE_RULES, row)) for r, row in zip(FORGE_RULES,
    ((85, 14, 1, 0), (15, 70, 14, 1), (3, 17, 75, 5), (2, 8, 20, 70)))}
FORGE_PAGE_ODDS = {r: dict(zip(FORGE_RULES, row)) for r, row in zip(FORGE_RULES,
    ((85, 14, 1, 0), (25, 60, 14, 1), (5, 25, 65, 5), (5, 15, 40, 40)))}


def forge_distribution(catalog, kind, ingredients, *, pages=False):
    """Average ingredients' weights; quote normalized odds if a tier is empty."""
    table = FORGE_PAGE_ODDS if pages else FORGE_FUSION_ODDS
    available = {c["rarity"] for c in catalog.values() if c["kind"] == kind}
    weights = {r: sum(table[source][r] * qty for source, qty in ingredients) if r in available else 0 for r in FORGE_RULES}
    total = sum(weights.values())
    if not total:
        raise ValueError("Нет доступных результатов для этих материалов.")
    return {r: w * 100 / total for r, w in weights.items()}


class ForgeMixin(ClassModulesMixin):
    def _connect_forge(self):
        self._connect_class_modules()
        # Historical recipe tables and seals are preserved, not spent or erased.
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_forge_wallets (
                chat_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                pages_json TEXT NOT NULL DEFAULT '{}', seals_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(chat_id,owner_id));
            CREATE TABLE IF NOT EXISTS arena_forge_actions (
                chat_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, nonce TEXT NOT NULL,
                request_json TEXT NOT NULL, notice TEXT NOT NULL, created_at INTEGER NOT NULL,
                PRIMARY KEY(chat_id,owner_id,nonce));
        """)

    def _forge_wallet_locked(self, chat, actor):
        chat = RPG_SCOPE
        self.connection.execute("INSERT OR IGNORE INTO arena_forge_wallets(chat_id,owner_id) VALUES(?,?)", (chat, actor))
        row = self.connection.execute("SELECT * FROM arena_forge_wallets WHERE chat_id=? AND owner_id=?", (chat, actor)).fetchone()
        return dict(revision=row["revision"], pages=json.loads(row["pages_json"]), seals=json.loads(row["seals_json"]))

    def _forge_save_wallet_locked(self, chat, actor, wallet):
        chat = RPG_SCOPE
        self.connection.execute("UPDATE arena_forge_wallets SET revision=revision+1,pages_json=?,seals_json=? WHERE chat_id=? AND owner_id=?",
            (json.dumps(wallet["pages"]), json.dumps(wallet["seals"]), chat, actor))

    def _forge_catalog_locked(self, chat=None):
        # Merchant catalog excludes boss, branch, free and hidden skills.
        return {k: dict(v) for k, v in self._arena_shop_catalog_locked().items()
                if k[0] in {"skill", "passive"} and v["rarity"] in FORGE_RULES
                and (chat is None or self._arena_content_enabled_locked(chat, k[0], k[1]))}

    def _forge_view_locked(self, chat, actor):
        wallet, catalog = self._forge_wallet_locked(chat, actor), self._forge_catalog_locked(chat)
        inventory = [dict(i, salvage_pages=FORGE_RULES[i["rarity"]]["salvage_pages"],
                          can_rewrite=(i["kind"], i["content_id"]) in catalog
                          and catalog[(i["kind"], i["content_id"])]["rarity"] == i["rarity"])
                     for i in self._arena_inventory_locked(chat, actor)
                     if i["kind"] in {"skill", "passive"} and i["rarity"] in FORGE_RULES]
        pools, crafts, fusion = [], [], {}
        for kind in ("skill", "passive"):
            fusion[kind] = {}
            for rarity, rule in FORGE_RULES.items():
                choices = sorted((v for v in catalog.values() if v["kind"] == kind and v["rarity"] == rarity), key=lambda c: c["content_id"])
                if choices:
                    pools.append(dict(kind=kind, rarity=rarity, choices=choices))
                fusion[kind][rarity] = forge_distribution(catalog, kind, [(rarity, 1)])
                crafts.append(dict(kind=kind, rarity=rarity, pages=rule["craft_pages"], price=rule["craft_price"],
                    odds=forge_distribution(catalog, kind, [(rarity, 1)], pages=True)))
        return dict(**wallet, catalog_revision=self._forge_catalog_revision(catalog), inventory=inventory,
                    crafts=crafts, pools=pools, fusion_odds=fusion,
                    rarities=[dict(id=k, name=RARITY_LABELS[k], **v) for k, v in FORGE_RULES.items()])

    @staticmethod
    def _forge_catalog_revision(catalog):
        snapshot = dict(rules=FORGE_RULES, fusion=FORGE_FUSION_ODDS, pages=FORGE_PAGE_ODDS, catalog=[catalog[k] for k in sorted(catalog)])
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:16]

    async def arena_forge_view(self, chat, actor):
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            with self.connection:
                return self._forge_view_locked(chat, actor)

    @staticmethod
    def _forge_inputs(data, max_total):
        raw = data.get("items")
        if not isinstance(raw, list) or not 1 <= len(raw) <= max_total:
            raise ValueError("Выбери трактаты.")
        inputs, seen, total = [], set(), 0
        for item in raw:
            if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] <= 0:
                raise ValueError("Некорректный предмет.")
            count = item.get("quantity")
            if type(count) is not int or not 1 <= count <= max_total or item["id"] in seen:
                raise ValueError("Некорректное количество или повтор предмета.")
            seen.add(item["id"])
            total += count
            inputs.append(dict(id=item["id"], quantity=count))
        if total > max_total:
            raise ValueError("Слишком много трактатов.")
        return sorted(inputs, key=lambda i: i["id"]), total

    def _forge_spend_francs_locked(self, chat, actor, price):
        if not self.connection.execute("UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?",
            (price, int(time.time()), chat, actor, price)).rowcount:
            raise ValueError("Не хватает франков.")

    def _forge_consume_locked(self, row, quantity):
        if row["quantity"] < quantity:
            raise ValueError("Трактатов уже недостаточно. Обнови кузницу.")
        if row["quantity"] == quantity:
            self.connection.execute("DELETE FROM arena_inventory WHERE id=?", (row["id"],))
        else:
            self.connection.execute("UPDATE arena_inventory SET quantity=quantity-? WHERE id=?", (quantity, row["id"]))

    @staticmethod
    def _forge_roll(catalog, kind, odds):
        rng = random.SystemRandom()
        roll, cumulative, rarity = rng.random() * 100, 0, None
        for grade, chance in odds.items():
            if chance <= 0:
                continue
            cumulative += chance
            rarity = grade
            if roll < cumulative:
                break
        pool = sorted((c for c in catalog.values() if c["kind"] == kind and c["rarity"] == rarity), key=lambda c: c["content_id"])
        return rng.choice(pool)

    async def arena_forge_action(self, chat, actor, data):
        if not isinstance(data, dict) or data.get("confirm") is not True:
            raise ValueError("Подтверди операцию кузницы.")
        action, nonce, revision = data.get("operation"), data.get("nonce"), data.get("revision")
        if not isinstance(action, str) or action not in {"dismantle", "craft", "rewrite"} or not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise ValueError("Некорректная операция кузницы.")
        if type(revision) is not int or revision < 0:
            raise ValueError("Обнови кузницу перед операцией.")
        quote = data.get("catalog_revision")
        if not isinstance(quote, str) or not re.fullmatch(r"[0-9a-f]{16}", quote):
            raise ValueError("Обнови шансы и стоимость.")
        request = dict(operation=action, revision=revision, catalog_revision=quote, payment_chat=chat)
        if action == "craft":
            kind, rarity = data.get("kind"), data.get("rarity")
            if not isinstance(kind, str) or kind not in {"skill", "passive"} or not isinstance(rarity, str) or rarity not in FORGE_RULES or "content" in data:
                raise ValueError("Выбери тип трактата и редкость страниц. Рецептов больше нет.")
            request.update(kind=kind, rarity=rarity)
        else:
            inputs, total = self._forge_inputs(data, 99 if action == "dismantle" else 3)
            if action == "rewrite" and total != 3:
                raise ValueError("Для слияния нужны ровно три трактата.")
            request["items"] = inputs
        serialized = json.dumps(request, sort_keys=True)
        async with self._lock:
            with self.connection:
                previous = self.connection.execute("SELECT * FROM arena_forge_actions WHERE chat_id=? AND owner_id=? AND nonce=?", (RPG_SCOPE, actor, nonce)).fetchone()
                if previous:
                    if previous["request_json"] != serialized:
                        raise ValueError("Этот запрос уже использован для другой операции.")
                    return previous["notice"]
                wallet = self._forge_wallet_locked(chat, actor)
                if wallet["revision"] != revision:
                    raise ValueError("Кузница изменилась. Обнови меню и проверь стоимость заново.")
                catalog = self._forge_catalog_locked(chat)
                if quote != self._forge_catalog_revision(catalog):
                    raise ValueError("Шансы, трактаты или стоимость изменились. Обнови кузницу.")
                if action == "craft":
                    rule = FORGE_RULES[rarity]
                    if wallet["pages"].get(rarity, 0) < rule["craft_pages"]:
                        raise ValueError("Не хватает страниц нужной редкости.")
                    odds = forge_distribution(catalog, kind, [(rarity, 1)], pages=True)
                    self._forge_spend_francs_locked(chat, actor, rule["craft_price"])
                    wallet["pages"][rarity] -= rule["craft_pages"]
                    result = self._forge_roll(catalog, kind, odds)
                    self._arena_add_item_locked(chat, actor, kind, result["content_id"], result["rarity"])
                    notice = f"Выкован трактат «{result['name']}» · {RARITY_LABELS[result['rarity']]}. Он в инвентаре."
                else:
                    rows = [(self._arena_item_locked(chat, actor, i["id"]), i["quantity"]) for i in inputs]
                    if len({row['id'] for row,_ in rows}) != len(rows):
                        raise ValueError('Один предмет указан повторно через старые номера.')
                    for row, quantity in rows:
                        if row["kind"] not in {"skill", "passive"} or row["rarity"] not in FORGE_RULES or row["quantity"] < quantity:
                            raise ValueError("Выбери имеющиеся активные или пассивные трактаты.")
                    if action == "dismantle":
                        gains = {}
                        for row, quantity in rows:
                            rarity = row["rarity"]
                            gains[rarity] = gains.get(rarity, 0) + FORGE_RULES[rarity]["salvage_pages"] * quantity
                            self._forge_consume_locked(row, quantity)
                        for rarity, gain in gains.items():
                            wallet["pages"][rarity] = wallet["pages"].get(rarity, 0) + gain
                        notice = "Трактаты разобраны. Страницы: " + ", ".join(f"{RARITY_LABELS[k]} +{v}" for k, v in gains.items()) + "."
                    else:
                        kind = rows[0][0]["kind"]
                        for row, _ in rows:
                            item = catalog.get((row["kind"], row["content_id"]))
                            if row["kind"] != kind or not item or item["rarity"] != row["rarity"]:
                                raise ValueError("Нужны три общедоступных трактата одного типа. Редкости можно смешивать; боссовые, веточные и эксклюзивные не подходят.")
                        ingredients = [(r["rarity"], q) for r, q in rows]
                        odds = forge_distribution(catalog, kind, ingredients)
                        price = math.ceil(sum(FORGE_RULES[r]["rewrite_price"] * q for r, q in ingredients) / 3)
                        self._forge_spend_francs_locked(chat, actor, price)
                        result = self._forge_roll(catalog, kind, odds)
                        for row, quantity in rows:
                            self._forge_consume_locked(row, quantity)
                        self._arena_add_item_locked(chat, actor, kind, result["content_id"], result["rarity"])
                        notice = f"Слияние: получен трактат «{result['name']}» · {RARITY_LABELS[result['rarity']]}. Он в инвентаре."
                self._forge_save_wallet_locked(chat, actor, wallet)
                self.connection.execute("INSERT INTO arena_forge_actions VALUES(?,?,?,?,?,?)", (RPG_SCOPE, actor, nonce, serialized, notice, int(time.time())))
                return notice
