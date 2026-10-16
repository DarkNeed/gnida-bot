"""Account-wide seasonal PvP and chat-local enterprise income rankings."""

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))
RATING_START = 1000
RATING_K = 24
RATING_PLACEMENT_GAMES = 5
RATING_DAILY_LIMIT = 10
RATING_PAIR_SECONDS = 86400
TOP_PAGE_SIZE = 10


def rating_season(timestamp):
    return datetime.fromtimestamp(timestamp, MSK).strftime("%Y-%m")


def income_period(timestamp, period):
    if period not in {"day", "week", "all"}:
        raise ValueError("Неизвестный период.")
    today = datetime.fromtimestamp(timestamp, MSK).date()
    start = today - timedelta(days=1 if period == "day" else 7)
    return ("0001-01-01" if period == "all" else start.isoformat()), today.isoformat()


def elo_delta(rating, opponent, score):
    expected = 1 / (1 + 10 ** ((opponent - rating) / 400))
    change = round(RATING_K * (score - expected))
    return max(1, change) if score == 1 else min(-1, change) if score == 0 else change


class LeaderboardsMixin:
    def _connect_leaderboards(self):
        self._ensure_column("arena_battles", "ranked", "INTEGER NOT NULL DEFAULT 0")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_ratings (
                season TEXT NOT NULL,actor_id INTEGER NOT NULL,rating INTEGER NOT NULL DEFAULT 1000,
                games INTEGER NOT NULL DEFAULT 0,wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,draws INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(season,actor_id));
            CREATE TABLE IF NOT EXISTS arena_rating_results (
                token TEXT PRIMARY KEY,season TEXT NOT NULL,a_actor INTEGER NOT NULL,b_actor INTEGER NOT NULL,
                a_delta INTEGER NOT NULL,b_delta INTEGER NOT NULL,counted INTEGER NOT NULL,
                reason TEXT NOT NULL,finished_at INTEGER NOT NULL,result_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_rating_pair ON arena_rating_results(a_actor,b_actor,finished_at);
            CREATE INDEX IF NOT EXISTS idx_rating_other ON arena_rating_results(b_actor,finished_at);
            CREATE INDEX IF NOT EXISTS idx_ranking_names ON users(user_id,last_seen DESC);
            CREATE INDEX IF NOT EXISTS idx_ranking_expedition_income ON slave_expeditions(chat_id,finished_at);
            CREATE TABLE IF NOT EXISTS enterprise_site_archive (
                business_id INTEGER PRIMARY KEY,chat_id INTEGER NOT NULL,owner_id INTEGER NOT NULL,
                data_json TEXT NOT NULL,closed_at INTEGER NOT NULL);
        """)

    def _rating_profile_locked(self, season, actor):
        row = self.connection.execute("SELECT * FROM arena_ratings WHERE season=? AND actor_id=?", (season, actor)).fetchone()
        return dict(row) if row else dict(season=season, actor_id=actor, rating=RATING_START, games=0, wins=0, losses=0, draws=0)

    def _rating_block_locked(self, actor, target, timestamp):
        pair = self.connection.execute("""SELECT 1 FROM arena_rating_results WHERE counted=1 AND finished_at>?
            AND ((a_actor=? AND b_actor=?) OR (a_actor=? AND b_actor=?)) LIMIT 1""",
            (timestamp - RATING_PAIR_SECONDS, actor, target, target, actor)).fetchone()
        if pair:
            return "Рейтинг этой пары уже учтён за последние 24 часа. Можно сыграть обычный /бой."
        midnight = int(datetime.fromtimestamp(timestamp, MSK).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        for user in (actor, target):
            count = self.connection.execute("""SELECT COUNT(*) FROM arena_rating_results WHERE counted=1
                AND finished_at>=? AND (a_actor=? OR b_actor=?)""", (midnight, user, user)).fetchone()[0]
            if count >= RATING_DAILY_LIMIT:
                return "У одного из игроков уже 10 учтённых рейтинговых боёв за сегодня (МСК). Можно сыграть обычный /бой."
        return None

    def _rating_finish_locked(self, row, state, timestamp):
        if not row.get("ranked"):
            return
        old = self.connection.execute("SELECT result_json FROM arena_rating_results WHERE token=?", (row["token"],)).fetchone()
        if old:
            state["rating_result"] = json.loads(old[0])
            return
        a, b = row["a_owner"], row["b_owner"]
        season = rating_season(timestamp)
        profiles = {key: self._rating_profile_locked(season, user) for key, user in (("a", a), ("b", b))}
        actions = state.get("ranked_actions", {})
        played = all(actions.get(key, 0) > 0 for key in ("a", "b"))
        winner = state.get("winner")
        reason = self._rating_block_locked(a, b, timestamp)
        changes = {"a": 0, "b": 0}
        counted = not reason and (played or winner is not None)
        if counted:
            for key, other in (("a", "b"), ("b", "a")):
                # No free rating/win from an opponent who never acted. Quitting
                # still costs rating; a completely idle draw pays nobody.
                if not played and key == winner:
                    continue
                score = 0.5 if winner is None else int(winner == key)
                profile = profiles[key]
                delta = elo_delta(profile["rating"], profiles[other]["rating"], score)
                new_rating = max(0, profile["rating"] + delta)
                changes[key] = new_rating - profile["rating"]
                self.connection.execute("""INSERT INTO arena_ratings(season,actor_id,rating,games,wins,losses,draws)
                    VALUES(?,?,?,1,?,?,?) ON CONFLICT(season,actor_id) DO UPDATE SET
                    rating=excluded.rating,games=games+1,wins=wins+excluded.wins,
                    losses=losses+excluded.losses,draws=draws+excluded.draws""",
                    (season, profile["actor_id"], new_rating, int(score == 1), int(score == 0), int(score == 0.5)))
            reason = "Рейтинг учтён." if played else "Ранняя сдача/бездействие: проигравший теряет рейтинг, победитель без очков."
        reason = reason or "Бой без действий не меняет рейтинг."
        result = dict(season=season, counted=bool(counted), reason=reason, deltas=changes,
                      ratings={key: profiles[key]["rating"] + changes[key] for key in profiles})
        self.connection.execute("INSERT INTO arena_rating_results VALUES(?,?,?,?,?,?,?,?,?,?)",
            (row["token"], season, a, b, changes["a"], changes["b"], int(bool(counted)), reason, timestamp, json.dumps(result, ensure_ascii=False)))
        state["rating_result"] = result

    async def arena_leaderboard(self, actor, *, season=None, page=0, mine=False):
        from database import utc_timestamp
        current = rating_season(utc_timestamp())
        season = season or current
        try:
            if datetime.strptime(season, "%Y-%m").strftime("%Y-%m") != season or season > current:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("Некорректный сезон.")
        if type(page) is not int or page < 0:
            raise ValueError("Некорректная страница.")
        async with self._lock:
            rows = [dict(r) for r in self.connection.execute("""SELECT r.*,
                COALESCE((SELECT display_name FROM users u WHERE u.user_id=r.actor_id ORDER BY last_seen DESC,chat_id LIMIT 1),CAST(r.actor_id AS TEXT)) AS name
                FROM arena_ratings r WHERE season=? AND games>=? ORDER BY rating DESC,wins DESC,actor_id""",
                (season, RATING_PLACEMENT_GAMES))]
            for index, entry in enumerate(rows, 1):
                entry["place"] = index
                entry["title"] = ({1: "Чемпион арены", 2: "Серебряный дуэлянт", 3: "Бронзовый дуэлянт"}.get(index, "") if season < current else "")
            own = self._rating_profile_locked(season, actor)
            own["place"] = next((r["place"] for r in rows if r["actor_id"] == actor), None)
            if mine and own["place"]:
                page = (own["place"] - 1) // TOP_PAGE_SIZE
            pages = max(1, math.ceil(len(rows) / TOP_PAGE_SIZE))
            page = min(page, pages - 1)
            seasons = sorted({current, season} | {r[0] for r in self.connection.execute("SELECT DISTINCT season FROM arena_ratings")}, reverse=True)
            return dict(season=season, current_season=current, archived=season < current,
                entries=rows[page * TOP_PAGE_SIZE:(page + 1) * TOP_PAGE_SIZE], own=own,
                total=len(rows), page=page, pages=pages, seasons=seasons,
                placement_games=RATING_PLACEMENT_GAMES, daily_limit=RATING_DAILY_LIMIT)

    def _archive_enterprise_locked(self, site, timestamp):
        self.connection.execute("INSERT OR REPLACE INTO enterprise_site_archive VALUES(?,?,?,?,?)",
            (site["id"], site["chat_id"], site["owner_id"], json.dumps(dict(site), ensure_ascii=False), timestamp))

    def _expedition_income_locked(self, chat, start, end):
        """Expeditions share the tax ledger, but are not enterprise production."""
        begin = 0 if start == "0001-01-01" else int(datetime.fromisoformat(start).replace(tzinfo=MSK).timestamp())
        finish = int(datetime.fromisoformat(end).replace(tzinfo=MSK).timestamp())
        totals = {}
        for row in self.connection.execute("""SELECT owner_id,result_json FROM slave_expeditions
            WHERE chat_id=? AND finished_at>=? AND finished_at<? AND status='finished'""", (chat, begin, finish)):
            result = json.loads(row["result_json"])
            net, tax = totals.get(row["owner_id"], (0, 0))
            totals[row["owner_id"]] = (net + result.get("francs", 0), tax + result.get("tax", 0))
        return totals

    async def enterprise_owner_periods(self, chat, owner):
        from database import utc_timestamp
        async with self._lock:
            result = {}
            for period in ("day", "week"):
                start, end = income_period(utc_timestamp(), period)
                net = self.connection.execute("""SELECT COALESCE(SUM(owner_income),0) FROM business_income_daily
                    WHERE chat_id=? AND owner_id=? AND income_day>=? AND income_day<?""", (chat, owner, start, end)).fetchone()[0]
                tax = self.connection.execute("""SELECT COALESCE(SUM(tax_paid),0) FROM business_tax_daily
                    WHERE chat_id=? AND owner_id=? AND income_day>=? AND income_day<?""", (chat, owner, start, end)).fetchone()[0]
                expedition_net, expedition_tax = self._expedition_income_locked(chat, start, end).get(owner, (0, 0))
                result[period] = dict(net=max(0, net - expedition_net), tax=max(0, tax - expedition_tax))
            return result

    async def enterprise_leaderboard(self, chat, *, kind="owners", period="week", page=0, actor=None, mine=False):
        from database import utc_timestamp
        from enterprises import title, CAPACITIES
        if kind not in {"owners", "sites"} or type(page) is not int or page < 0:
            raise ValueError("Некорректный топ.")
        timestamp = utc_timestamp()
        start, end = income_period(timestamp, period)
        async with self._lock:
            with self.connection:
                sites = [dict(r) for r in self.connection.execute("SELECT * FROM businesses WHERE chat_id=?", (chat,))]
                for owner in {s["owner_id"] for s in sites}:
                    self._enterprise_settle_owner_locked(chat, owner, timestamp)
                archive = [dict(json.loads(r["data_json"]), closed=True) for r in self.connection.execute(
                    "SELECT * FROM enterprise_site_archive WHERE chat_id=?", (chat,))]
                sites = [dict(s, closed=False) for s in sites] + archive
                users = {r["user_id"]: dict(r) for r in self.connection.execute("SELECT * FROM users WHERE chat_id=?", (chat,))}
                staff = [dict(r) for r in self.connection.execute("""SELECT w.*,
                    COALESCE(w.business_id,(SELECT CASE WHEN COUNT(*)=1 THEN MIN(id) END FROM businesses b
                        WHERE b.chat_id=w.chat_id AND b.owner_id=w.owner_id)) AS effective_site
                    FROM business_workers w JOIN ownership o ON o.chat_id=w.chat_id AND o.slave_id=w.worker_id AND o.owner_id=w.owner_id
                    WHERE w.chat_id=?""", (chat,))]
                site_counts = Counter(s["owner_id"] for s in sites if not s["closed"])
                worker_counts = Counter(w["owner_id"] for w in staff)
                staff_counts = Counter(w["effective_site"] for w in staff)
                if kind == "owners":
                    income = {r["owner_id"]: r["amount"] for r in self.connection.execute("""SELECT owner_id,SUM(owner_income) AS amount
                        FROM business_income_daily WHERE chat_id=? AND income_day>=? AND income_day<? GROUP BY owner_id""", (chat, start, end))}
                    for owner, (net, _) in self._expedition_income_locked(chat, start, end).items():
                        income[owner] = max(0, income.get(owner, 0) - net)
                    ids = {owner for owner in income if income[owner] > 0} | {s["owner_id"] for s in sites if not s["closed"]}
                    rows = [dict(id=owner, owner_id=owner, amount=income.get(owner, 0),
                        name=users.get(owner, {}).get("display_name", str(owner)),
                        sites=site_counts[owner], workers=worker_counts[owner]) for owner in ids]
                else:
                    income = {r["business_id"]: dict(r) for r in self.connection.execute("""SELECT business_id,SUM(gross_income) AS amount,
                        SUM(net_income) AS net,SUM(tax_paid) AS tax FROM enterprise_income_daily
                        WHERE income_day>=? AND income_day<? AND business_id IN (
                            SELECT id FROM businesses WHERE chat_id=? UNION SELECT business_id FROM enterprise_site_archive WHERE chat_id=?)
                        GROUP BY business_id""", (start, end, chat, chat))}
                    rows = [dict(s, name=title(s), amount=income.get(s["id"], {}).get("amount", 0),
                        net=income.get(s["id"], {}).get("net", 0), tax=income.get(s["id"], {}).get("tax", 0),
                        owner_name=users.get(s["owner_id"], {}).get("display_name", str(s["owner_id"])),
                        workers=staff_counts[s["id"]] if not s["closed"] else 0,
                        capacity=CAPACITIES[s["level"]]) for s in sites]
                    rows = [r for r in rows if not r["closed"] or r["amount"] > 0]
                rows.sort(key=lambda r: (-r["amount"], r["id"]))
                for index, row in enumerate(rows, 1):
                    row["place"] = index
                own = next((r for r in rows if r["owner_id"] == actor), None)
                if mine and own:
                    page = (own["place"] - 1) // TOP_PAGE_SIZE
                pages = max(1, math.ceil(len(rows) / TOP_PAGE_SIZE))
                page = min(page, pages - 1)
                return dict(chat_id=chat, kind=kind, period=period, start=start, end=end,
                    entries=rows[page * TOP_PAGE_SIZE:(page + 1) * TOP_PAGE_SIZE],
                    all_entries=rows, own=own, page=page, pages=pages, total=len(rows))
