"""Chat-scoped genealogy, opt-in weddings and judicial divorces."""
from __future__ import annotations

import json
import secrets
import time
import unicodedata
from collections import defaultdict


class FamilyError(ValueError):
    pass


EMPTY_ORIGIN = 0  # Telegram users always have positive IDs.


def normalized(value):
    return unicodedata.normalize("NFKC", value or "").casefold().replace("ё", "е").strip()


def family_map(state):
    """Split the archive into the root's component and other recorded families."""
    root = state["origin"]
    edges = defaultdict(list)
    branches = ((EMPTY_ORIGIN, user) for user in state.get("branches", ())) if root == EMPTY_ORIGIN else ()
    for a, b in [*state["parents"], *state["marriages"], *state.get("siblings", ()), *branches]:
        edges[a].append(b)
        edges[b].append(a)
    visited = set()

    def component(start):
        queue = [start]
        visited.add(start)
        for person in queue:
            for neighbor in edges[person]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return sorted(queue)

    main = set(component(root)) if root is not None else set()
    detached = [component(person) for person in sorted(edges) if person not in visited]
    return main, detached, visited


def parent_index(state):
    parents = defaultdict(set)
    for parent, child in state["parents"]:
        parents[child].add(parent)
    return parents


def upwards(parents, user):
    seen, queue = set(), [user]
    for person in queue:
        for parent in parents[person] - seen:
            seen.add(parent)
            queue.append(parent)
    return seen, parents[user]


def close_relatives(state, a, b, parents=None):
    parents = parent_index(state) if parents is None else parents
    av, ap = upwards(parents, a)
    bv, bp = upwards(parents, b)
    return a in bv or b in av or bool(ap & bp) or sorted((a, b)) in state.get("siblings", ())


def validate_generations(state):
    """Sibling groups share a generation. Parent links must descend between groups."""
    siblings = state["siblings"]
    if not siblings:
        return
    _, components, _ = family_map(dict(origin=None, parents=[], marriages=[], siblings=siblings))
    groups = {person: group[0] for group in components for person in group}
    edges, incoming = defaultdict(set), defaultdict(int)
    for parent, child in state["parents"]:
        a, b = groups.get(parent, parent), groups.get(child, child)
        incoming.setdefault(a, 0)
        if b not in edges[a]:
            edges[a].add(b)
            incoming[b] += 1
    ready = [person for person, count in incoming.items() if count == 0]
    for person in ready:
        for child in edges[person]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if len(ready) != len(incoming):
        raise FamilyError("Эта связь противоречит записанным поколениям.")


def spouse(state, user):
    return next((b if a == user else a for a, b in state["marriages"] if user in (a, b)), None)


class FamilyTreeMixin:
    def _connect_family_tree(self):
        self.connection.create_function("family_normalize", 1, normalized, deterministic=True)
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS family_trees (
                chat_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS family_log (
                id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, actor INTEGER NOT NULL,
                description TEXT NOT NULL, at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS family_log_chat ON family_log(chat_id, id DESC);
            CREATE TABLE IF NOT EXISTS family_offers (
                token TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, sender INTEGER NOT NULL,
                recipient INTEGER NOT NULL, until INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS family_offers_people ON family_offers(chat_id,sender,recipient);
            CREATE INDEX IF NOT EXISTS family_offers_expiry ON family_offers(until);
            CREATE TABLE IF NOT EXISTS family_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                a INTEGER NOT NULL, b INTEGER NOT NULL, requester INTEGER NOT NULL,
                reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                decided_by INTEGER, created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS family_cases_chat ON family_cases(chat_id,id DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS family_cases_pending
                ON family_cases(chat_id,a,b) WHERE status='open';
            CREATE TABLE IF NOT EXISTS family_avatars (
                chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, photo_key TEXT NOT NULL,
                image BLOB NOT NULL, mime TEXT NOT NULL, PRIMARY KEY(chat_id,user_id)
            );
        """)

    def _family_state(self, chat):
        row = self.connection.execute("SELECT revision,state FROM family_trees WHERE chat_id=?", (chat,)).fetchone()
        if row is None:
            return 0, dict(origin=None, branches=[], parents=[], marriages=[], siblings=[], judges=[])
        state = json.loads(row["state"])
        state.setdefault("branches", [])
        state.setdefault("siblings", [])
        return row["revision"], state

    def _family_write(self, chat, revision, state, actor, description):
        self.connection.execute("""
            INSERT INTO family_trees(chat_id, revision, state) VALUES (?,?,?)
            ON CONFLICT(chat_id) DO UPDATE SET revision=excluded.revision,state=excluded.state
        """, (chat, revision + 1, json.dumps(state, separators=(",", ":"))))
        self.connection.execute("INSERT INTO family_log(chat_id,actor,description,at) VALUES (?,?,?,?)",
                                (chat, actor, description, int(time.time())))

    def _family_people(self, chat, ids):
        people = {}
        ids = sorted(set(ids) - {EMPTY_ORIGIN})
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            for row in self.connection.execute(
                f"SELECT user_id AS id,username,display_name AS name FROM users WHERE chat_id=? AND user_id IN ({placeholders})",
                (chat, *chunk),
            ):
                people[row["id"]] = dict(row)
        return [people.get(i, {"id": i, "name": f"Участник {i}", "username": None}) for i in ids]

    async def family_role(self, chat, actor, owner):
        async with self._lock:
            _, state = self._family_state(chat)
            return owner or actor in state["judges"]

    async def family_view(self, chat, actor, owner, case=None, offset=0, mine=False):
        async with self._lock:
            revision, state = self._family_state(chat)
            members, detached, map_ids = family_map(state)
            judge = owner or actor in state["judges"]
            where, params = ("", ()) if judge and not mine else (" AND (a=? OR b=?)", (actor, actor))
            if case is not None:
                where += " AND id=?"
                params += (case,)
            cases = [dict(r) for r in self.connection.execute(
                "SELECT * FROM family_cases WHERE chat_id=?" + where
                + " ORDER BY (status='open') DESC,id DESC LIMIT 21 OFFSET ?", (chat, *params, offset)
            )] if case is not None or not offset or judge else []
            more, cases = len(cases) > 20, cases[:20]
            log = [dict(r) for r in self.connection.execute(
                "SELECT actor,description,at FROM family_log WHERE chat_id=? ORDER BY id DESC LIMIT 20", (chat,)
            )] if owner else []
            judges = state["judges"] if owner else []
            title = self.connection.execute("SELECT title FROM chats WHERE chat_id=?", (chat,)).fetchone()
            view_ids = map_ids | set(judges) | {entry["actor"] for entry in log}
            edit_ids = ({i for edge in state["parents"] + state["marriages"] + state["siblings"] for i in edge}
                        | set(judges) | set(state["branches"])) if owner else set()
            view_ids |= edit_ids
            partner = spouse(state, actor)
            if partner is not None:
                view_ids.add(partner)
            for row in cases:
                view_ids.update(i for i in (row["a"],row["b"],row["decided_by"]) if i is not None)
                # Telegram chat scope is already supplied by the route.
                row.pop("chat_id")
            return dict(revision=revision, origin=state["origin"], members=sorted(members), detached=detached,
                        branches=state["branches"] if state["origin"] == EMPTY_ORIGIN else [],
                        parents=state["parents"], marriages=state["marriages"], siblings=state["siblings"],
                        editor=dict(parents=state["parents"], marriages=state["marriages"],
                                    siblings=state["siblings"]) if owner else None,
                        people=self._family_people(chat, view_ids), owner=owner, judge=judge, judges=judges,
                        cases=cases, more_cases=more, log=log, spouse=partner, actor=actor,
                        title=title["title"] if title else "Семейный архив")

    async def family_search(self, chat, query, directory):
        query = normalized(query).removeprefix("@")
        if len(query) < 2 or len(query) > 80:
            return []
        async with self._lock:
            _, state = self._family_state(chat)
            _, _, members = family_map(state)
            if directory:
                # Unicode case folding, and literal substring search (no wildcard expansion).
                found = self.connection.execute("""
                    SELECT user_id AS id, username, display_name AS name FROM users
                    WHERE chat_id=? AND
                    (instr(family_normalize(username),?)>0 OR instr(family_normalize(display_name),?)>0)
                    ORDER BY CASE
                        WHEN family_normalize(username)=? OR family_normalize(display_name)=? THEN 0
                        WHEN instr(family_normalize(username),?)=1 OR instr(family_normalize(display_name),?)=1 THEN 1
                        ELSE 2 END,
                        last_seen DESC,user_id LIMIT 8
                """, (chat, *([query] * 6))).fetchall()
                return [dict(row, in_tree=row["id"] in members) for row in found]
            def score(person):
                keys = (normalized(person["username"]), normalized(person["name"]))
                return 0 if query in keys else 1 if any(k.startswith(query) for k in keys) else 2 if any(query in k for k in keys) else 3
            hits = [(score(p), p) for p in self._family_people(chat, members)]
            return [p for score, p in sorted(hits, key=lambda pair: (pair[0], normalized(pair[1]["name"]))) if score < 3][:8]

    async def family_avatar_allowed(self, chat, target):
        async with self._lock:
            _, state = self._family_state(chat)
            return target != EMPTY_ORIGIN and (
                target == state["origin"] or any(target in pair for pair in state["parents"] + state["marriages"])
                or (state["origin"] == EMPTY_ORIGIN and target in state["branches"])
            )

    async def family_saved_avatar(self, chat, user):
        async with self._lock:
            row = self.connection.execute(
                "SELECT photo_key,image,mime FROM family_avatars WHERE chat_id=? AND user_id=?", (chat, user)
            ).fetchone()
            return tuple(row) if row else None

    async def family_save_avatar(self, chat, user, avatar):
        async with self._lock:
            with self.connection:
                if avatar is None:
                    self.connection.execute("DELETE FROM family_avatars WHERE chat_id=? AND user_id=?", (chat, user))
                else:
                    self.connection.execute("""INSERT INTO family_avatars(chat_id,user_id,photo_key,image,mime) VALUES(?,?,?,?,?)
                        ON CONFLICT(chat_id,user_id) DO UPDATE SET photo_key=excluded.photo_key,image=excluded.image,mime=excluded.mime""",
                        (chat, user, *avatar))

    def _family_edit(self, chat, state, operation, a, b, reason):
        if operation == "origin":
            if a == state["origin"]:
                raise FamilyError("Это уже Исток древа.")
            if a == EMPTY_ORIGIN:
                old = state["origin"]
                if old is not None and old not in state["branches"]:
                    state["branches"].append(old)
            elif any(child == a for _, child in state["parents"]):
                raise FamilyError("Истоком может стать только участник без записанных родителей.")
            state["origin"] = a
            description = "создан пустой Исток" if a == EMPTY_ORIGIN else "назначен Исток"
        elif operation in ("link", "unlink") and a == EMPTY_ORIGIN:
            if state["origin"] != EMPTY_ORIGIN:
                raise FamilyError("Сначала создай пустой Исток.")
            if operation == "link":
                if b in state["branches"]:
                    raise FamilyError("Участник уже прикреплён к Истоку.")
                state["branches"].append(b)
                description = "ветвь прикреплена к Истоку"
            else:
                if b not in state["branches"]:
                    raise FamilyError("Эта ветвь не прикреплена к Истоку.")
                state["branches"].remove(b)
                description = "ветвь отсоединена от Истока"
        elif operation == "link":
            if a == b or b == state["origin"] or b in upwards(parent_index(state), a)[0]:
                raise FamilyError("Эта связь замкнёт древо или сделает Исток чьим-то ребёнком.")
            if [a, b] in state["parents"]:
                raise FamilyError("Такая связь уже записана.")
            if sum(c == b for _, c in state["parents"]) >= 2:
                raise FamilyError("У участника уже два родителя.")
            state["parents"].append([a, b])
            validate_generations(state)
            index = parent_index(state)
            if any(close_relatives(state, x, y, index) for x, y in state["marriages"]):
                raise FamilyError("Эта связь сделает супругов близкими родственниками.")
            description = "добавлена родственная связь"
        elif operation == "unlink":
            if [a, b] not in state["parents"]:
                raise FamilyError("Такой связи больше нет.")
            state["parents"].remove([a, b])
            description = "удалена родственная связь"
        elif operation in ("sibling", "unsibling"):
            if not a or not b or a == b:
                raise FamilyError("Выбери двух разных участников.")
            pair = sorted((a, b))
            if operation == "sibling":
                if pair in state["siblings"]:
                    raise FamilyError("Эта связь братьев или сестёр уже записана.")
                if spouse(state, a) == b:
                    raise FamilyError("Супругов нельзя записать как брата или сестру.")
                state["siblings"].append(pair)
                validate_generations(state)
                description = "добавлена связь братьев или сестёр"
            else:
                if pair not in state["siblings"]:
                    raise FamilyError("Такая связь братьев или сестёр не записана.")
                state["siblings"].remove(pair)
                description = "удалена связь братьев или сестёр"
        elif operation == "marry":
            if not a or not b or a == b:
                raise FamilyError("Выбери двух разных участников.")
            if spouse(state, a) or spouse(state, b):
                raise FamilyError("Один из участников уже состоит в браке.")
            if close_relatives(state, a, b):
                raise FamilyError("Близкие родственники не могут заключить брак.")
            state["marriages"].append(sorted((a, b)))
            description = "брак внесён через редактор"
        elif operation in ("appoint", "revoke"):
            if operation == "appoint":
                if a in state["judges"]:
                    raise FamilyError("Этот участник уже судья.")
                state["judges"].append(a)
                description = "назначен судья"
            else:
                if a not in state["judges"]:
                    raise FamilyError("Этот участник не назначен судьёй.")
                state["judges"].remove(a)
                description = "снят судья"
        else:
            raise FamilyError("Неизвестная правка.")
        ids = [i for i in (a, b) if i not in (None, EMPTY_ORIGIN)]
        names = {p["id"]: p["name"] for p in self._family_people(chat, ids)}
        separator = " и " if operation in ("marry", "sibling", "unsibling") else " → "
        return description + (": " + separator.join(names[i] for i in ids) if ids else "") + (f". {reason}" if reason else "")

    async def family_edit(self, chat, actor, operation, a, b=None, reason="", *, expected=None):
        """Caller must check ownership. Preview is read-only; apply requires that revision."""
        async with self._lock:
            with self.connection:
                if expected is not None:
                    self.connection.execute("BEGIN IMMEDIATE")
                revision, state = self._family_state(chat)
                if expected is not None and revision != expected:
                    raise FamilyError("Древо уже изменилось. Проверь правку ещё раз.")
                before = family_map(state)[0]
                summary = self._family_edit(chat, state, operation, a, b, reason)
                after = family_map(state)[0]
                if expected is not None:
                    self._family_write(chat, revision, state, actor, summary)
                    if operation == "marry":
                        self.connection.execute(
                            "DELETE FROM family_offers WHERE chat_id=? AND (sender IN (?,?) OR recipient IN (?,?))",
                            (chat, a, b, a, b),
                        )
                result = dict(revision=revision, summary=summary,
                              added=self._family_people(chat, after - before),
                              removed=self._family_people(chat, before - after))
                if operation == "marry":
                    result["marriage_rooted"] = a in after and b in after
                return result

    async def family_offer(self, chat, sender, recipient):
        now = int(time.time())
        async with self._lock:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                _, state = self._family_state(chat)
                if sender == recipient or spouse(state, sender) or spouse(state, recipient):
                    raise FamilyError("Выбери другого участника, который не состоит в браке. Ты тоже должен быть свободен.")
                if close_relatives(state, sender, recipient):
                    raise FamilyError("Близкие родственники не могут заключить брак.")
                self.connection.execute("DELETE FROM family_offers WHERE until<=?", (now,))
                if self.connection.execute(
                    "SELECT 1 FROM family_offers WHERE chat_id=? AND (sender=? OR (sender=? AND recipient=?))",
                    (chat, sender, recipient, sender),
                ).fetchone():
                    raise FamilyError("Предложение уже отправлено. Дождись ответа или отзови его.")
                token = secrets.token_hex(12)
                self.connection.execute("INSERT INTO family_offers VALUES (?,?,?,?,?)",
                                        (token, chat, sender, recipient, now + 900))
                return token

    async def family_offer_people(self, chat, token):
        async with self._lock:
            row = self.connection.execute("SELECT sender,recipient FROM family_offers WHERE chat_id=? AND token=? AND until>?",
                                          (chat, token, int(time.time()))).fetchone()
            return tuple(row) if row else None

    async def family_offer_action(self, chat, token, actor, action):
        async with self._lock:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                row = self.connection.execute("SELECT * FROM family_offers WHERE chat_id=? AND token=? AND until>?",
                                              (chat, token, int(time.time()))).fetchone()
                if not row:
                    raise FamilyError("Предложение больше не действует.")
                a, b = row["sender"], row["recipient"]
                if action not in {"accept","decline","cancel"} or actor != (a if action == "cancel" else b):
                    raise FamilyError("Эта кнопка для другого участника.")
                if action == "accept":
                    revision, state = self._family_state(chat)
                    if spouse(state, a) or spouse(state, b) or close_relatives(state, a, b):
                        raise FamilyError("Этот брак теперь невозможен.")
                    state["marriages"].append(sorted((a,b)))
                    people = {p["id"]: p["name"] for p in self._family_people(chat, (a,b))}
                    self._family_write(chat, revision, state, actor, f"брак: {people[a]} и {people[b]}")
                self.connection.execute("DELETE FROM family_offers WHERE token=?", (token,))

    async def family_filing(self, chat, actor, reason):
        async with self._lock:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                _, state = self._family_state(chat)
                other = spouse(state, actor)
                if other is None:
                    raise FamilyError("У тебя нет зарегистрированного брака в этом чате.")
                a, b = sorted((actor, other))
                row = self.connection.execute(
                    "SELECT id FROM family_cases WHERE chat_id=? AND a=? AND b=? AND status='open'", (chat, a, b)
                ).fetchone()
                if row:
                    return row["id"], other, False
                cursor = self.connection.execute(
                    "INSERT INTO family_cases(chat_id,a,b,requester,reason,created_at) VALUES (?,?,?,?,?,?)",
                    (chat, a, b, actor, reason, int(time.time()))
                )
                return cursor.lastrowid, other, True

    async def family_decide(self, chat, actor, owner, case, approve):
        async with self._lock:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                revision, state = self._family_state(chat)
                if not owner and actor not in state["judges"]:
                    raise FamilyError("Нет полномочий судьи.")
                row = self.connection.execute("SELECT * FROM family_cases WHERE chat_id=? AND id=? AND status='open'",
                                              (chat, case)).fetchone()
                if not row:
                    raise FamilyError("Открытое дело не найдено.")
                pair = [row["a"], row["b"]]
                if actor in pair:
                    raise FamilyError("Свой развод должен рассмотреть другой судья.")
                if approve:
                    state["marriages"].remove(pair)
                status = "approved" if approve else "rejected"
                self.connection.execute("UPDATE family_cases SET status=?,decided_by=? WHERE id=?", (status, actor, case))
                self._family_write(chat, revision, state, actor,
                                   f"дело №{case}: " + ("брак расторгнут" if approve else "заявление отклонено"))
                return pair
