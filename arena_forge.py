"""Chat-scoped scroll recycling. Inventory, francs and recipes change atomically."""

from dataclasses import asdict
import hashlib
import json
import random
import re
import time

from arena_engine import BUILTIN_PASSIVES, RARITY_LABELS
from arena_archprogress import skill_branch
from arena_raid_engine import BOSSES

FORGE_RULES = {
    rarity: dict(salvage_pages=2, craft_pages=6, craft_price=price, rewrite_price=price // 2)
    for rarity, price in (("common", 40), ("uncommon", 70), ("rare", 130), ("epic", 250))
}
FORGE_BOSS_SEALS = 3


class ForgeMixin:
    def _connect_forge(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_forge_wallets (
                chat_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                pages_json TEXT NOT NULL DEFAULT '{}', seals_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(chat_id,owner_id)
            );
            CREATE TABLE IF NOT EXISTS arena_forge_recipes (
                chat_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
                kind TEXT NOT NULL, content_id TEXT NOT NULL,
                PRIMARY KEY(chat_id,owner_id,kind,content_id)
            );
            CREATE TABLE IF NOT EXISTS arena_forge_actions (
                chat_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, nonce TEXT NOT NULL,
                request_json TEXT NOT NULL, notice TEXT NOT NULL, created_at INTEGER NOT NULL,
                PRIMARY KEY(chat_id,owner_id,nonce)
            );
        """)

    def _forge_receipt_locked(self, chat, actor, kind, content):
        if kind in {"skill", "passive"}:
            self.connection.execute(
                "INSERT OR IGNORE INTO arena_forge_recipes VALUES(?,?,?,?)",
                (chat, actor, kind, content),
            )

    def _forge_wallet_locked(self, chat, actor):
        self.connection.execute("INSERT OR IGNORE INTO arena_forge_wallets(chat_id,owner_id) VALUES(?,?)", (chat, actor))
        row = self.connection.execute("SELECT * FROM arena_forge_wallets WHERE chat_id=? AND owner_id=?", (chat, actor)).fetchone()
        return dict(revision=row["revision"], pages=json.loads(row["pages_json"]), seals=json.loads(row["seals_json"]))

    def _forge_save_wallet_locked(self, chat, actor, wallet):
        self.connection.execute(
            "UPDATE arena_forge_wallets SET revision=revision+1,pages_json=?,seals_json=? WHERE chat_id=? AND owner_id=?",
            (json.dumps(wallet["pages"]), json.dumps(wallet["seals"]), chat, actor),
        )

    def _forge_boss_seal_locked(self, chat, actor, boss):
        if not BOSSES.get(boss, {}).get("loot_skill"):
            return ""
        wallet = self._forge_wallet_locked(chat, actor)
        wallet["seals"][boss] = wallet["seals"].get(boss, 0) + 1
        self._forge_save_wallet_locked(chat, actor, wallet)
        return "Печать: " + BOSSES[boss]["name"]

    def _forge_catalog_locked(self):
        # Only public merchant content and specifically registered boss loot.
        # Hidden/exclusive grants, branch skills, class scrolls and free attacks
        # cannot leak into the random pool or become reproducible recipes.
        catalog = {
            key: dict(value, boss_id="", seals=0)
            for key, value in self._arena_shop_catalog_locked().items()
            if key[0] in {"skill", "passive"}
        }
        _, skills = self._fighter_catalog_locked()
        for key in list(catalog):
            if key[0] == "skill" and (skill_branch(skills[key[1]]) or "raid_loot" in skills[key[1]].tags):
                del catalog[key]
        for boss_id, boss in BOSSES.items():
            skill = skills.get(boss.get("loot_skill"))
            if skill:
                catalog[("skill", skill.skill_id)] = dict(
                    kind="skill", content_id=skill.skill_id, name=skill.name,
                    rarity=skill.rarity, details=asdict(skill), boss_id=boss_id, seals=FORGE_BOSS_SEALS,
                )
        return {k: v for k, v in catalog.items() if v["rarity"] in FORGE_RULES}

    def _forge_view_locked(self, chat, actor):
        wallet = self._forge_wallet_locked(chat, actor)
        catalog = self._forge_catalog_locked()
        known = {(r["kind"], r["content_id"]) for r in self.connection.execute(
            "SELECT kind,content_id FROM arena_forge_recipes WHERE chat_id=? AND owner_id=?", (chat, actor))}
        inventory = [
            dict(item, salvage_pages=FORGE_RULES[item["rarity"]]["salvage_pages"],
                 can_rewrite=(item["kind"], item["content_id"]) in catalog and not catalog[(item["kind"], item["content_id"])]["boss_id"])
            for item in self._arena_inventory_locked(chat, actor)
            if item["kind"] in {"skill", "passive"} and item["rarity"] in FORGE_RULES
        ]
        recipes = []
        for key, item in catalog.items():
            if key not in known:
                continue
            rule = FORGE_RULES[item["rarity"]]
            recipes.append(dict(item, pages=rule["craft_pages"], price=rule["craft_price"],
                boss_name=BOSSES[item["boss_id"]]["name"] if item["boss_id"] else "",
                can_craft=wallet["pages"].get(item["rarity"], 0) >= rule["craft_pages"]
                    and wallet["seals"].get(item["boss_id"], 0) >= item["seals"]))
        recipes.sort(key=lambda r: (list(FORGE_RULES).index(r["rarity"]), r["kind"], r["name"]))
        pools = []
        for kind in ("skill", "passive"):
            for rarity in FORGE_RULES:
                choices = [dict(v) for v in catalog.values() if v["kind"] == kind and v["rarity"] == rarity and not v["boss_id"]]
                choices.sort(key=lambda c: c["content_id"])
                if choices:
                    pools.append(dict(kind=kind, rarity=rarity, price=FORGE_RULES[rarity]["rewrite_price"], choices=choices))
        return dict(**wallet, catalog_revision=self._forge_catalog_revision(catalog), inventory=inventory, recipes=recipes, pools=pools,
            rarities=[dict(id=k, name=RARITY_LABELS[k], **v) for k,v in FORGE_RULES.items()],
            bosses=[dict(id=k, name=v["name"]) for k,v in BOSSES.items() if v.get("loot_skill")])

    @staticmethod
    def _forge_catalog_revision(catalog):
        snapshot = dict(rules=FORGE_RULES, catalog=[catalog[k] for k in sorted(catalog)])
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:16]

    async def arena_forge_view(self, chat, actor):
        async with self._lock:
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
        if not self.connection.execute(
            "UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?",
            (price, int(time.time()), chat, actor, price),
        ).rowcount:
            raise ValueError("Не хватает франков.")

    def _forge_consume_locked(self, row, quantity):
        if row["quantity"] < quantity:
            raise ValueError("Трактатов уже недостаточно. Обнови кузницу.")
        if row["quantity"] == quantity:
            self.connection.execute("DELETE FROM arena_inventory WHERE id=?", (row["id"],))
        else:
            self.connection.execute("UPDATE arena_inventory SET quantity=quantity-? WHERE id=?", (quantity, row["id"]))

    async def arena_forge_action(self, chat, actor, data):
        if not isinstance(data, dict) or data.get("confirm") is not True:
            raise ValueError("Подтверди операцию кузницы.")
        action, nonce, revision = data.get("operation"), data.get("nonce"), data.get("revision")
        if not isinstance(action, str) or action not in {"dismantle", "craft", "rewrite"} or not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise ValueError("Некорректная операция кузницы.")
        if type(revision) is not int or revision < 0:
            raise ValueError("Обнови кузницу перед операцией.")
        catalog_revision = data.get("catalog_revision")
        if not isinstance(catalog_revision, str) or not re.fullmatch(r"[0-9a-f]{16}", catalog_revision):
            raise ValueError("Обнови список рецептов и стоимость.")
        request = dict(operation=action, revision=revision, catalog_revision=catalog_revision)
        if action == "craft":
            kind, content = data.get("kind"), data.get("content")
            if not isinstance(kind, str) or kind not in {"skill", "passive"} or not isinstance(content, str) or len(content) > 128:
                raise ValueError("Некорректный рецепт.")
            request.update(kind=kind, content=content)
        else:
            inputs, total = self._forge_inputs(data, 99 if action == "dismantle" else 3)
            if action == "rewrite" and total != 3:
                raise ValueError("Для переписывания нужны ровно три трактата.")
            request["items"] = inputs
        serialized = json.dumps(request, sort_keys=True)
        async with self._lock:
            with self.connection:
                previous = self.connection.execute("SELECT * FROM arena_forge_actions WHERE chat_id=? AND owner_id=? AND nonce=?", (chat, actor, nonce)).fetchone()
                if previous:
                    if previous["request_json"] != serialized:
                        raise ValueError("Этот запрос уже использован для другой операции.")
                    return previous["notice"]
                wallet = self._forge_wallet_locked(chat, actor)
                if wallet["revision"] != revision:
                    raise ValueError("Кузница изменилась. Обнови меню и проверь стоимость заново.")
                catalog = self._forge_catalog_locked()
                if catalog_revision != self._forge_catalog_revision(catalog):
                    raise ValueError("Рецепты или стоимость изменились. Обнови кузницу.")
                if action == "craft":
                    recipe = catalog.get((kind, content))
                    known = self.connection.execute("SELECT 1 FROM arena_forge_recipes WHERE chat_id=? AND owner_id=? AND kind=? AND content_id=?", (chat, actor, kind, content)).fetchone()
                    if not recipe or not known:
                        raise ValueError("Рецепт недоступен. Сначала получи этот трактат.")
                    rule, rarity, boss = FORGE_RULES[recipe["rarity"]], recipe["rarity"], recipe["boss_id"]
                    if wallet["pages"].get(rarity, 0) < rule["craft_pages"]:
                        raise ValueError("Не хватает страниц нужной редкости.")
                    if wallet["seals"].get(boss, 0) < recipe["seals"]:
                        raise ValueError("Не хватает печатей соответствующего босса.")
                    self._forge_spend_francs_locked(chat, actor, rule["craft_price"])
                    wallet["pages"][rarity] -= rule["craft_pages"]
                    if boss:
                        wallet["seals"][boss] -= recipe["seals"]
                    self._arena_add_item_locked(chat, actor, kind, content, rarity)
                    notice = f"Создан трактат «{recipe['name']}». Он в инвентаре; для изучения действуют прежние ограничения."
                else:
                    rows = [(self._arena_item_locked(chat, actor, i["id"]), i["quantity"]) for i in inputs]
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
                        notice = "Трактаты разобраны. Страницы: " + ", ".join(f"{RARITY_LABELS[k]} +{v}" for k,v in gains.items()) + "."
                    else:
                        kind, rarity = rows[0][0]["kind"], rows[0][0]["rarity"]
                        for row, _ in rows:
                            item = catalog.get((row["kind"], row["content_id"]))
                            if row["kind"] != kind or row["rarity"] != rarity or not item or item["boss_id"] or item["rarity"] != rarity:
                                raise ValueError("Нужны три общедоступных трактата одного типа и редкости. Боссовые и эксклюзивные не подходят.")
                        pool = sorted((v for v in catalog.values() if v["kind"] == kind and v["rarity"] == rarity and not v["boss_id"]), key=lambda v: v["content_id"])
                        if len(pool) < 2:
                            raise ValueError("В этой группе только один результат. Используй разбор и восстановление по рецепту.")
                        self._forge_spend_francs_locked(chat, actor, FORGE_RULES[rarity]["rewrite_price"])
                        result = random.SystemRandom().choice(pool)
                        for row, quantity in rows:
                            self._forge_consume_locked(row, quantity)
                        self._arena_add_item_locked(chat, actor, kind, result["content_id"], rarity)
                        notice = f"Переписано: получен трактат «{result['name']}». Его рецепт открыт."
                self._forge_save_wallet_locked(chat, actor, wallet)
                self.connection.execute("INSERT INTO arena_forge_actions VALUES(?,?,?,?,?,?)", (chat, actor, nonce, serialized, notice, int(time.time())))
                return notice
