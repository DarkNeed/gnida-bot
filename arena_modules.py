"""Local feature switches, not class gates. RPG progression is account-wide."""
import json
import time

FEATURE_MODULES = {
    'arena': dict(name='Арена', classes=()),
    'slavery': dict(name='Рабовладение', classes=()),
}
CLASS_MODULES = FEATURE_MODULES


def class_module(class_id):
    return ''


class ClassModulesMixin:
    def _connect_class_modules(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS chat_feature_modules (
                chat_id INTEGER PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0,
                disabled_json TEXT NOT NULL DEFAULT '[]',updated_by INTEGER,updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS arena_class_archives (
                chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,personal INTEGER NOT NULL,
                module_id TEXT NOT NULL,profile_json TEXT NOT NULL,learned_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,PRIMARY KEY(chat_id,user_id,personal,module_id));
        """)

    def _arena_modules_locked(self, chat):
        row=self.connection.execute('SELECT * FROM chat_feature_modules WHERE chat_id=?',(chat,)).fetchone()
        disabled=set(json.loads(row['disabled_json'])) if row else set()
        return dict(revision=row['revision'] if row else 0,modules=[dict(id=k,**v,enabled=k not in disabled) for k,v in FEATURE_MODULES.items()])

    def _feature_enabled_locked(self, chat, feature):
        return any(m['id']==feature and m['enabled'] for m in self._arena_modules_locked(chat)['modules'])

    def _require_feature_locked(self, chat, feature):
        if not self._feature_enabled_locked(chat,feature):
            raise ValueError(f"Модуль «{FEATURE_MODULES[feature]['name']}» выключен в этом чате.")

    async def feature_enabled(self, chat, feature):
        async with self._lock:
            return self._feature_enabled_locked(chat,feature)

    async def arena_require_enabled(self, chat):
        async with self._lock:
            self._require_feature_locked(chat,'arena')

    def _arena_class_enabled_locked(self, chat, cls):
        return cls in self._fighter_catalog_locked()[0]

    def _arena_content_enabled_locked(self, chat, kind, content, catalog=None):
        classes,skills=self._fighter_catalog_locked()
        return content in classes if kind=='class' else content in skills if kind=='skill' else True

    async def arena_modules(self, chat):
        async with self._lock:
            return self._arena_modules_locked(chat)

    async def arena_module_profile(self, chat, user, personal, class_id):
        return dict(module_blocked=False,module_pending_at=None,module_archives=[])

    async def arena_set_module(self, chat, actor, module, enabled, revision):
        if module not in FEATURE_MODULES or type(enabled) is not bool or type(revision) is not int:
            raise ValueError('Некорректный модуль.')
        async with self._lock:
            with self.connection:
                current=self._arena_modules_locked(chat)
                if current['revision']!=revision:
                    raise ValueError('Настройки изменились. Обнови меню.')
                previous=self._feature_enabled_locked(chat,module)
                disabled={m['id'] for m in current['modules'] if not m['enabled']}
                disabled.discard(module) if enabled else disabled.add(module)
                if previous!=enabled:
                    if module=='arena' and not enabled:
                        self._global_cancel_arena_locked(chat=chat)
                    if module=='slavery':
                        if previous:
                            for b in self.connection.execute('SELECT owner_id FROM businesses WHERE chat_id=?',(chat,)).fetchall():
                                self._settle_business_locked(chat,b['owner_id'],int(time.time()))
                        self.connection.execute('UPDATE businesses SET last_accrued=? WHERE chat_id=?',(int(time.time()),chat))
                        if not enabled:
                            self.connection.execute("UPDATE challenges SET friendly=1,forced=0,opponent_newcomer=0 WHERE chat_id=? AND status IN ('pending','betting','active')",(chat,))
                            from slave_recovery import timestamp
                            self.connection.execute("""UPDATE slave_recovery_events SET status='cancelled',
                                ended_at=?,deadline=NULL,revision=revision+1 WHERE chat_id=?
                                AND status IN ('announcing','pending','playing')""",(timestamp(),chat))
                self.connection.execute("""INSERT INTO chat_feature_modules VALUES(?,?,?,?,?)
                    ON CONFLICT(chat_id) DO UPDATE SET revision=excluded.revision,disabled_json=excluded.disabled_json,
                    updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                    (chat,revision+1,json.dumps(sorted(disabled)),actor,int(time.time())))
        return 'Модуль включён.' if enabled else 'Модуль выключен. Прогресс сохранён; ставки закрытых боёв возвращены.'

    def _arena_module_switch_locked(self, *args, **kwargs):
        raise ValueError('Модули классов удалены. Используй обычный сброс или трактат смены класса.')
