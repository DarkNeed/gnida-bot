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

    def test_global_activity_cards_use_correct_open_and_exit_actions(self):
        data=self.menu_data()
        data['active']=[dict(token='battle-key',mode='personal',status='pending')]
        data['mirror_runs']=[dict(token='mirror-key',status='active',floor=2,xp=40)]
        data['raids']=[dict(token='raid-key',status='active',round=2)]
        body=self.run_client("page='personal';menuScreen(input);",data)
        for action in ('battle:battle-key','leavebattle:battle-key','leavemirror:mirror-key','leaveraid:raid-key'):
            self.assertIn('data-do="'+action+'"',body)
        self.assertNotIn('data-do="open:battle-key"',body)
        self.assertEqual(body.count('Твои бои во всех чатах'),1)

    def test_leave_confirmation_warns_about_stakes_and_no_reward(self):
        body=self.run_client("leavePending={kind:'battle',token:'key'};page='leaveConfirm';menuScreen(input);",self.menu_data())
        self.assertIn('проигрыш ставки',body)
        self.assertIn('без награды',body)
        self.assertIn('data-do="confirmleave"',body)
        self.assertIn('data-do="cancelleave"',body)

    def test_class_reset_requires_warning_and_confirmation(self):
        body = self.render("classConfirm")
        self.assertIn("Уровень станет 5", body)
        self.assertIn("пассивные навыки исчезнут", body)
        self.assertIn("Инвентарь, питомцы и спрайт сохранятся", body)
        self.assertIn('data-do="confirmitem"', body)
        self.assertIn("Не менять", body)

    def test_merchant_affordable_and_expensive_disabled(self):
        body = self.render("merchant")
        self.assertIn('ассортимент едины для всех чатов', body)
        self.assertIn('Лимиты покупок общие для аккаунта', body)
        self.assertIn('Оплата франками выбранного чата', body)
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
        self.assertIn("Пассивные навыки · 1 / 3", body)
        self.assertIn("Каменная кожа", body)
        self.assertIn("Физ. защита: +15%", body)
        self.assertIn("Необычный", body)
        self.assertIn('data-do="savepassives"', body)
        self.assertIn("активных 0 / 6", body)
        self.assertIn("пассивных 1 / 4", body)
        self.assertIn('data-do="resetprofile"', body)

    def test_passive_limits_follow_level_and_allow_four_learned(self):
        self.assertEqual(
            self.run_client("out=String(learnedLimit('passive'));", {}), "4"
        )
        self.assertEqual(self.run_client("out=String(learnedLimit('skill'));", {}), "6")
        for level, limit in ((9, 2), (10, 3), (20, 3)):
            data = self.menu_data()
            data["personal"]["level"] = level
            body = self.run_client(
                "page='personalProfile';profileId=input.personal.user_id;menuScreen(input);",
                data,
            )
            self.assertIn(f"Пассивные навыки · 1 / {limit}", body)
            self.assertIn("пассивных 1 / 4", body)

    def test_free_class_reset_warning_and_correct_target(self):
        body = self.run_client(
            "page='resetConfirm';resetPending={user:10,personal:true,name:'Игрок'};menuScreen(input);",
            self.menu_data(),
        )
        self.assertIn("Оборванцем 5 уровня", body)
        self.assertIn("Боевой опыт ×2", body)
        self.assertIn("Это нельзя отменить", body)
        self.assertIn("Сброс бесплатный", body)
        self.assertIn('data-do="confirmreset"', body)
        self.assertIn('data-do="cancelreset"', body)

    def test_hourly_raid_status_and_global_limits_visible(self):
        data=self.menu_data()
        data['raid_bosses']=[dict(id='lei_heng',name='Лей Хенг',full_reward=False,cooldown_remaining=1801),
                            dict(id='doofenshmirtz',name='Фуфелшмерц',full_reward=True)]
        body=self.run_client("page='raids';menuScreen(input);",data)
        self.assertIn('Повторная награда 20% · полная через 31 мин.',body)
        self.assertIn('Полная награда доступна',body)
        self.assertIn('раз в час',body)
        self.assertNotIn('00:00 МСК',body)
        self.assertIn('общая для всех чатов и бойцов',body)
        self.assertNotIn('Железный сборщик',body)

    def test_catchup_level_display_and_low_level_reset_disabled(self):
        data=self.menu_data()
        data['personal'].update(level=5,progress=[5,0,40],catchup_level=18)
        body=self.run_client("menu=input;out=profileCard(input.personal,'Личный персонаж');",data)
        self.assertIn('Боевой опыт ×2 до 18 уровня',body)
        data['personal'].update(level=1,catchup_level=0)
        body=self.run_client("page='personalProfile';profileId=10;menuScreen(input);",data)
        self.assertIn('data-do="resetprofile" disabled',body)

    def test_finger_sprites_and_custom_override(self):
        for cls in ("thumb", "index", "middle", "ring", "pinky"):
            output = self.run_client("out=sprite(input);", dict(sprite=cls))
            self.assertEqual(output, "/static/assets/" + cls + ".png")
        custom = "/sprites/" + "a" * 64 + ".png"
        self.assertEqual(
            self.run_client(
                "out=sprite(input);", dict(sprite="thumb", sprite_url=custom)
            ),
            custom,
        )

    def test_scroll_replacement_lists_skills_and_cancel_without_free_attack(self):
        data = self.menu_data()
        data["inventory"].append(
            {
                "id": 43,
                "kind": "skill",
                "name": "Новый навык",
                "content_id": "new",
                "rarity": "rare",
                "quantity": 1,
                "details": {},
            }
        )
        data["personal"]["skills"] = [
            {"skill_id": "bum_punch", "name": "Удар бомжа", "rarity": "common"},
            {"skill_id": "humiliate", "name": "Унизить", "rarity": "uncommon"},
        ]
        body = self.run_client(
            "page='skillReplace';skillUsePending={item:43,user:10,personal:true};menuScreen(input);",
            data,
        )
        self.assertIn("Какой навык заменить?", body)
        self.assertIn("Новый навык", body)
        self.assertIn('data-do="replaceitem:humiliate"', body)
        self.assertNotIn('data-do="replaceitem:bum_punch"', body)
        self.assertIn("Отмена — ничего не менять", body)
        self.assertIn("До выбора трактат не тратится", body)

    def test_owner_has_no_craft_buttons(self):
        body = self.render("owner")
        self.assertIn("Персонаж", body)
        self.assertNotIn('data-do="craft:', body)
        self.assertNotIn("Владелец · Lv.25", body)

    def test_native_details_dialog_preserves_scroll_and_restores_focus(self):
        code = """
let modal=null,shown=0,closed=0,focus=0,returned=0,kind='';
const handlers={};
app.querySelector=()=>({focus(){returned++}});
document.documentElement={classList:{add(){},remove(){}}};
document.getElementById=id=>id==='fighter-stats'?modal:app;
document.body={append(el){modal=el}};
document.createElement=tag=>{kind=tag;return {
  innerHTML:'',scrollTop:0,setAttribute(){},addEventListener(name,fn){handlers[name]=fn},
  querySelector:()=>({focus(){focus++}}),showModal(){shown++},close(){closed++},remove(){modal=null}
}};
current={state:{sides:{a:{name:'Игрок',class_name:'Оборванец',class_rarity:'common',level:1,hp:20,resource:100,resource_name:'Энергия',stats:{max_hp:20,resource_max:100},skill_details:[],effects:[],cooldowns:{}}}}};
showStats('a');modal.scrollTop=90;showStats('a');
const scroll=modal.scrollTop;
handlers.cancel({preventDefault(){}});
out=JSON.stringify({kind,shown,closed,focus,returned,scroll,removed:modal===null});
"""
        result = json.loads(self.run_client(code, {}))
        self.assertEqual(
            result,
            {
                "kind": "dialog",
                "shown": 1,
                "closed": 1,
                "focus": 1,
                "returned": 1,
                "scroll": 90,
                "removed": True,
            },
        )

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
        self.assertIn("Пассивные навыки · 1 / 3", body)
        self.assertIn("Точность: -10", body)
        self.assertIn("/static/assets/jock.png", body)
