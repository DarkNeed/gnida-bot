import json
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node is needed for client tests")
class ArenaMarketClientTests(unittest.TestCase):
    def run_client(self, code, data):
        source = (
            (Path(__file__).resolve().parents[1] / "webapp" / "battle-client")
            .read_text(encoding="utf-8")
            .rsplit("boot();", 1)[0]
        )
        script = """
const vm=require('node:vm');
const payload=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const app={innerHTML:'',addEventListener(){}};
const c={window:{Telegram:undefined,matchMedia:()=>({matches:true})},
  document:{getElementById:()=>app,addEventListener(){}},
  location:{search:'',hostname:'example.test'},URLSearchParams,URL,
  setInterval(){},setTimeout(){},clearTimeout(){}, console,
  input:payload.data,out:''};
vm.runInNewContext(payload.source+'\\n'+payload.code,c);
process.stdout.write(c.out||app.innerHTML);
"""
        return subprocess.run(
            [shutil.which("node"), "-e", script],
            input=json.dumps({"data": data, "source": source, "code": code}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout

    def menu_data(self):
        return {
            "chat_id": 1,
            "slaves": [],
            "active": [],
            "balance": 100,
            "personal": {
                "user_id": 10,
                "personal": True,
                "name": "Игрок",
                "level": 20,
                "progress": [20, 0, 0],
                "class_name": "Оборванец",
                "class_id": "ragamuffin",
                "class_rarity": "common",
                "skills": [],
                "loadout": [],
                "passives": [
                    {
                        "skill_id": "stone_skin",
                        "name": "Каменная кожа",
                        "rarity": "uncommon",
                        "effects": [{"kind": "physical_defense_pct", "value": 0.15}],
                    }
                ],
                "passive_loadout": ["stone_skin"],
                "classes": [],
            },
            "inventory": [
                {
                    "id": 42,
                    "kind": "class",
                    "name": "Качок",
                    "rarity": "uncommon",
                    "quantity": 2,
                    "details": {},
                }
            ],
            "merchant": {
                "visit_id": 1,
                "ends": 2000000000,
                "offers": [
                    {
                        "id": 7,
                        "name": "Зелье",
                        "kind": "potion",
                        "price": 25,
                        "remaining": 3,
                        "rarity": "common",
                        "details": {"description": "Лечит"},
                    },
                    {
                        "id": 8,
                        "name": "Класс",
                        "kind": "class",
                        "price": 750,
                        "remaining": 1,
                        "rarity": "rare",
                        "details": {},
                    },
                ],
            },
            "owner": {"level": 25, "xp": 40000},
        }

    def render(self, page):
        return self.run_client(
            "page="
            + json.dumps(page)
            + ";profileId=10;classUsePending={item:42,name:'Игрок'};menuScreen(input);",
            self.menu_data(),
        )

    def test_inventory_transfer_number_and_target(self):
        body = self.render("inventory")
        self.assertIn("№42", body)
        self.assertIn("× 2", body)
        self.assertIn("/передать предмет 42 @участник", body)
        self.assertIn('value="p:10"', body)
        self.assertIn('data-do="useitem:42"', body)
        self.assertEqual(body.count("<select "), body.count("</select>"))

    def test_class_reset_requires_warning_and_confirmation(self):
        body = self.render("classConfirm")
        self.assertIn("Уровень станет 1", body)
        self.assertIn("пассивные навыки исчезнут", body)
        self.assertIn("Инвентарь и спрайт сохранятся", body)
        self.assertIn('data-do="confirmitem"', body)
        self.assertIn("Не менять", body)

    def test_merchant_affordable_and_expensive_disabled(self):
        body = self.render("merchant")
        self.assertIn('data-do="buy:7">', body)
        self.assertIn('data-do="buy:8" disabled', body)
        self.assertIn("Баланс: 100", body)
        self.assertIn("Редкий", body)

    def test_max_level_has_full_bar_not_nan(self):
        body = self.render("personal")
        self.assertIn("МАКСИМУМ · 20", body)
        self.assertIn("width:100%", body)
        self.assertNotIn("NaN", body)

    def test_profile_has_two_passive_slots_and_rarity(self):
        body = self.render("personalProfile")
        self.assertIn("Пассивные навыки · 1 / 2", body)
        self.assertIn("Каменная кожа", body)
        self.assertIn("Физ. защита: +15%", body)
        self.assertIn("Необычный", body)
        self.assertIn('data-do="savepassives"', body)

    def test_owner_has_no_craft_buttons(self):
        body = self.render("owner")
        self.assertIn("Крафт убран", body)
        self.assertNotIn('data-do="craft:', body)
        self.assertIn("Владелец · Lv.25", body)

    def test_battle_card_displays_effective_stats_and_escapes_names(self):
        data = {
            "name": "<img onerror=attack>",
            "class_name": "Качок",
            "class_rarity": "uncommon",
            "sprite": "jock",
            "level": 20,
            "hp": 30,
            "resource": 80,
            "resource_name": "Тестостерон",
            "stats": {"max_hp": 100, "resource_max": 100, "physical_defense": 20},
            "effective_stats": {"physical_defense": 23},
            "skill_details": [
                {
                    "skill_id": "hit",
                    "name": "Удар",
                    "rarity": "rare",
                    "cost": 20,
                    "power": 12,
                    "accuracy": 95,
                    "cooldown": 3,
                    "effects": [],
                }
            ],
            "cooldowns": {"hit": 2},
            "passive_details": [
                {
                    "name": "Каменная кожа",
                    "rarity": "uncommon",
                    "effects": [{"kind": "physical_defense_pct", "value": 0.15}],
                }
            ],
            "effects": [{"kind": "accuracy_flat", "value": -10, "duration": 2}],
        }
        body = self.run_client("out=fighterDetails(input,'a');", data)
        self.assertIn("&lt;img onerror=attack&gt;", body)
        self.assertIn("HP 30 / 100", body)
        self.assertIn("(база 20)", body)
        self.assertIn("Энергия 20", body)
        self.assertIn("Восстановится через 2 х.", body)
        self.assertIn("Пассивные навыки · 1 / 2", body)
        self.assertIn("Точность: -10", body)
        self.assertIn("/static/assets/jock.png", body)
