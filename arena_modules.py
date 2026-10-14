"""Per-chat class modules; combat catalogs for already started fights stay intact."""

import json
import time

CLASS_MODULES = {
    "classic": dict(name="Классика рпг", classes=("warrior", "mage", "priest", "hunter")),
    "moon": dict(name="Луна", classes=("thumb", "index", "middle", "ring", "pinky")),
    "humor": dict(name="Юмор", classes=("cutie", "jock", "nerd")),
}


def class_module(class_id):
    return next((key for key, module in CLASS_MODULES.items() if class_id in module["classes"]), "")


class ClassModulesMixin:
    def _connect_class_modules(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_module_settings (
                chat_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0,
                disabled_json TEXT NOT NULL DEFAULT '[]', updated_by INTEGER, updated_at INTEGER);
            CREATE TABLE IF NOT EXISTS arena_class_archives (
                chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, personal INTEGER NOT NULL,
                module_id TEXT NOT NULL, profile_json TEXT NOT NULL, learned_json TEXT NOT NULL,
                created_at INTEGER NOT NULL, PRIMARY KEY(chat_id,user_id,personal,module_id));
        """)

    def _arena_modules_locked(self, chat):
        row = self.connection.execute("SELECT * FROM arena_module_settings WHERE chat_id=?", (chat,)).fetchone()
        # Existing communities keep their current content. New RPG content is
        # opt-in, and its final art has not yet been approved by the bot owner.
        disabled = set(json.loads(row["disabled_json"])) if row else {'classic'}
        return dict(revision=row["revision"] if row else 0,
                    modules=[dict(id=k, **v, enabled=k not in disabled) for k,v in CLASS_MODULES.items()])

    def _arena_class_enabled_locked(self, chat, cls):
        module = class_module(cls)
        return not module or next(m["enabled"] for m in self._arena_modules_locked(chat)["modules"] if m["id"]==module)

    def _arena_content_enabled_locked(self, chat, kind, content, catalog=None):
        if kind == "class":
            return self._arena_class_enabled_locked(chat, content)
        if kind == "skill":
            skill = (catalog or self._fighter_catalog_locked()[1]).get(content)
            return bool(skill and self._arena_class_enabled_locked(chat, skill.class_id))
        return True

    async def arena_modules(self, chat):
        async with self._lock:
            return self._arena_modules_locked(chat)

    async def arena_module_profile(self, chat, user, personal, class_id):
        async with self._lock:
            disabled = not self._arena_class_enabled_locked(chat,class_id)
            settings = self.connection.execute('SELECT updated_at FROM arena_module_settings WHERE chat_id=?',(chat,)).fetchone()
            archives=[]
            for row in self.connection.execute('SELECT module_id,profile_json FROM arena_class_archives WHERE chat_id=? AND user_id=? AND personal=?',(chat,user,int(personal))):
                profile=json.loads(row['profile_json'])
                archives.append(dict(class_id=profile['class_id'],archclass_id=profile['archclass_id'],level=profile['level'],enabled=self._arena_class_enabled_locked(chat,profile['class_id'])))
            return dict(module_blocked=disabled,module_pending_at=settings['updated_at'] if disabled and settings else None,module_archives=archives)

    async def arena_set_module(self, chat, actor, module, enabled, revision):
        # Telegram ownership must be checked by the caller immediately before
        # entering this transaction; this method is never exposed as a player API.
        if module not in CLASS_MODULES or type(enabled) is not bool or type(revision) is not int:
            raise ValueError("Некорректный модуль.")
        async with self._lock:
            with self.connection:
                current = self._arena_modules_locked(chat)
                if current["revision"] != revision:
                    raise ValueError("Настройки изменились. Обнови меню.")
                disabled = {m["id"] for m in current["modules"] if not m["enabled"]}
                disabled.discard(module) if enabled else disabled.add(module)
                self.connection.execute("""INSERT INTO arena_module_settings VALUES(?,?,?,?,?)
                    ON CONFLICT(chat_id) DO UPDATE SET revision=excluded.revision,
                    disabled_json=excluded.disabled_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                    (chat, revision+1, json.dumps(sorted(disabled)), actor, int(time.time())))
        return "Модуль включён." if enabled else "Модуль выключен. Прогресс и текущие бои сохранены."

    def _arena_module_switch_locked(self, chat, user, personal, chosen, *, restore=False):
        from arena_engine import VISIBLE_CLASS_ALIASES
        table = "personal_profiles" if personal else "slave_profiles"
        profile = dict(self._arena_profile_locked(chat, user, personal))
        classes, _ = self._fighter_catalog_locked()
        if chosen not in classes or not self._arena_class_enabled_locked(chat, chosen):
            raise ValueError("Класс выключен или недоступен.")
        if self._arena_busy_locked(chat, user):
            raise ValueError("Сначала заверши текущий бой, рейд или зеркальную пустошь.")
        saved = None
        if restore:
            module = class_module(chosen)
            saved = self.connection.execute("SELECT * FROM arena_class_archives WHERE chat_id=? AND user_id=? AND personal=? AND module_id=?", (chat,user,int(personal),module)).fetchone()
            if not saved or json.loads(saved["profile_json"])["class_id"] != chosen:
                raise ValueError("Этот архив недоступен.")
        elif self._arena_class_enabled_locked(chat, profile["class_id"]):
            raise ValueError("Бесплатная смена доступна только для отключённого класса.")
        if not restore and chosen != "ragamuffin" and (chosen not in VISIBLE_CLASS_ALIASES.values() or profile['level'] < classes[chosen].base_level):
            raise ValueError("Класс недоступен этому уровню.")
        module = class_module(profile["class_id"])
        if module:
            learned = [dict(r) for r in self.connection.execute("SELECT * FROM arena_learned WHERE chat_id=? AND user_id=? AND personal=?",(chat,user,int(personal)))]
            self.connection.execute("INSERT OR REPLACE INTO arena_class_archives VALUES(?,?,?,?,?,?,?)", (chat,user,int(personal),module,json.dumps(profile),json.dumps(learned),int(time.time())))
        if saved:
            snapshot, learned = json.loads(saved["profile_json"]), json.loads(saved["learned_json"])
            if snapshot["xp"] < profile["xp"]:
                snapshot.update(xp=profile["xp"],level=profile["level"])
            fields = {k:v for k,v in snapshot.items() if k not in {"chat_id","user_id"}}
            # Catch-up XP belongs to current progression, not an archived build.
            fields['catchup_target_xp'] = profile['catchup_target_xp']
            fields['updated_at'] = int(time.time())
            self.connection.execute(f"UPDATE {table} SET " + ','.join(k+'=?' for k in fields) + " WHERE chat_id=? AND user_id=?", (*fields.values(),chat,user))
            self.connection.execute("DELETE FROM arena_learned WHERE chat_id=? AND user_id=? AND personal=?",(chat,user,int(personal)))
            for row in learned:
                self.connection.execute("INSERT OR IGNORE INTO arena_learned VALUES(?,?,?,?,?)",(chat,user,int(personal),row['kind'],row['content_id']))
        else:
            _, skill_catalog = self._fighter_catalog_locked()
            shared = [dict(r) for r in self.connection.execute('SELECT * FROM arena_learned WHERE chat_id=? AND user_id=? AND personal=?',(chat,user,int(personal)))
                      if r['kind']=='passive' or (r['kind']=='skill' and r['content_id'] in skill_catalog and not class_module(skill_catalog[r['content_id']].class_id))]
            self._arena_reset_profile_locked(chat,user,personal,chosen,preserve_archives=True)
            self.connection.execute(f"UPDATE {table} SET xp=?,level=?,progression_level=?,updated_at=? WHERE chat_id=? AND user_id=?", (profile['xp'],profile['level'],5 if chosen!='ragamuffin' else profile['level'],int(time.time()),chat,user))
            self._arena_equip_class_passives_locked(chat,user,personal,chosen)
            for row in shared:
                self.connection.execute('INSERT OR IGNORE INTO arena_learned VALUES(?,?,?,?,?)',(chat,user,int(personal),row['kind'],row['content_id']))
        return "Архивный билд восстановлен; накопленный опыт сохранён." if restore else "Класс изменён бесплатно. Уровень и опыт сохранены, прежний билд в архиве."
