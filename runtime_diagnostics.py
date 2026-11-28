"""Small, read-only production probes and bounded private error notifications."""

import asyncio
from collections import OrderedDict, deque
from hashlib import blake2s
import logging
import os
from pathlib import Path, PurePosixPath
import time

MEMORY_LOG = logging.getLogger("runtime.memory")
ERROR_LOG = logging.getLogger("runtime.errors")


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fields(text, *, proc=False):
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and (number := _number(parts[1])) is not None:
            result[parts[0].rstrip(":")] = number * (1024 if proc else 1)
    return result


def _cgroup_memory(proc, root):
    for line in _read(proc / "cgroup").splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hierarchy, controllers, member = parts
        path = PurePosixPath(member)
        if not path.is_absolute() or ".." in path.parts:
            continue
        if hierarchy == "0" and not controllers:
            base, version = root, 2
        elif "memory" in controllers.split(","):
            base, version = root / "memory", 1
        else:
            continue
        nested = base.joinpath(*path.parts[1:])
        if _read(nested / "memory.stat"):
            return nested, version
        if nested != base and _read(base / "memory.stat"):
            # A delegated mount can present the process's cgroup as its root.
            if str(os.getpid()) in _read(base / "cgroup.procs").split():
                return base, version
    return None, None


class MemoryProbe:
    def __init__(self, proc=Path("/proc/self"), cgroup=Path("/sys/fs/cgroup")):
        self.proc = proc
        self.cgroup, self.version = _cgroup_memory(proc, cgroup)
        self.started = time.monotonic()
        self.initial = {}
        self.peaks = {}

    def sample(self):
        status = _fields(_read(self.proc / "status"), proc=True)
        result = dict(rss=status.get("VmRSS"), rss_anon=status.get("RssAnon"))
        if self.cgroup is None:
            return result
        base = self.cgroup
        stats = _fields(_read(base / "memory.stat"))
        if self.version == 2:
            result.update(cg_anon=stats.get("anon"), cg_file=stats.get("file"),
                          cg_shmem=stats.get("shmem"),
                          cg_current=_number(_read(base / "memory.current").strip()),
                          cg_limit=_number(_read(base / "memory.max").strip()))
        else:
            limit = _number(_read(base / "memory.limit_in_bytes").strip())
            result.update(cg_anon=stats.get("total_rss", stats.get("rss")),
                          cg_file=stats.get("total_cache", stats.get("cache")),
                          cg_shmem=stats.get("total_shmem", stats.get("shmem")),
                          cg_current=_number(_read(base / "memory.usage_in_bytes").strip()),
                          cg_limit=limit if limit is not None and limit < (1 << 60) else None)
        events = _fields(_read(base / ("memory.events" if self.version == 2 else "memory.oom_control")))
        result.update(cg_oom=events.get("oom"), cg_oom_kill=events.get("oom_kill"))
        return result

    def capture(self):
        values = self.sample()
        for key in ("rss", "rss_anon", "cg_current", "cg_anon", "cg_file"):
            if (value := values.get(key)) is not None:
                self.initial.setdefault(key, value)
                self.peaks[key] = max(value, self.peaks.get(key, value))
        return values

    def telegram_summary(self):
        values = self.capture()
        minutes, seconds = divmod(int(time.monotonic() - self.started), 60)
        lines = ["📊 Память Гнида-бота", f"После запуска: {minutes} мин {seconds} с"]
        scale = 1024 * 1024

        def metric(key, label, *, peak=False):
            value = values.get(key)
            if value is None:
                return
            line = f"{label}: {value / scale:.1f} МиБ"
            if key in self.initial:
                line += f" ({(value - self.initial[key]) / scale:+.1f} со старта)"
            if peak:
                line += f" · пик по замерам {self.peaks[key] / scale:.1f}"
            lines.append(line)

        metric("rss", "Процесс Python (RSS)", peak=True)
        metric("rss_anon", "Анонимная память Python")
        metric("cg_current", "Всего в контейнере", peak=True)
        metric("cg_anon", "Анонимная память контейнера")
        metric("cg_file", "Память файлов контейнера (включая кэш)")
        metric("cg_limit", "Лимит контейнера")
        if (kills := values.get("cg_oom_kill")) is not None:
            lines.append(f"Завершений из-за нехватки памяти (OOM): {kills}")
        if len(lines) == 2:
            lines.append("Хостинг не открыл системные счётчики памяти.")
        elif values.get("cg_current") is None:
            lines.append("Общий счётчик контейнера недоступен.")
        lines.append(f"Задач asyncio: {len(asyncio.all_tasks())}")
        return "\n".join(lines)

    def log(self, stage):
        fields = []
        for name, value in self.capture().items():
            if value is None:
                continue
            if name in ("cg_oom", "cg_oom_kill"):
                fields.append(f"{name}={value}")
            else:
                fields.append(f"{name}_mib={value / (1024 * 1024):.1f}")
        MEMORY_LOG.info("MEMORY stage=%s pid=%d uptime_sec=%d tasks=%d %s", stage, os.getpid(),
                        time.monotonic() - self.started, len(asyncio.all_tasks()),
                        " ".join(fields) if fields else "memory_counters=unavailable")

    async def run(self, interval):
        # Sample early enough to catch warm-up/catch-up steps in the first minute.
        last = 0
        for second in (10, 30):
            if second >= interval:
                break
            await asyncio.sleep(second - last)
            self.log("warmup")
            last = second
        await asyncio.sleep(interval - last)
        while True:
            self.log("periodic")
            await asyncio.sleep(interval)


def memory_log_interval(raw):
    interval = _number(raw or "60")
    if interval == 0 or interval is not None and 10 <= interval <= 3600:
        return interval
    MEMORY_LOG.warning("Invalid MEMORY_LOG_INTERVAL_SECONDS; using 60")
    return 60


class ErrorNotifier:
    """Keep only small strings in a bounded queue; never store an update or traceback."""

    def __init__(self, bot, owner_id, *, enabled=True, clock=time.monotonic):
        self.bot = bot
        self.owner_id = owner_id
        self.enabled = enabled
        self.clock = clock
        self.queue = asyncio.Queue(maxsize=8)
        self.recent = OrderedDict()
        self.next_send = 0
        self.suppressed = 0

    def report(self, source, error):
        frames = deque(maxlen=4)
        frame = error.__traceback__
        while frame is not None:
            code = frame.tb_frame.f_code
            frames.append(f"{Path(code.co_filename).name}:{frame.tb_lineno} · {code.co_name}")
            frame = frame.tb_next
        error_type = type(error).__name__
        key = blake2s("\n".join((source, error_type, *frames)).encode(), digest_size=5).hexdigest()
        ERROR_LOG.error("Unhandled error [%s] %s", key, source,
                        exc_info=(type(error), error, error.__traceback__))
        if not self.enabled:
            return
        now = self.clock()
        if self.recent.get(key, float("-inf")) + 900 > now or self.queue.full():
            self.suppressed += 1
            return
        self.recent[key] = now
        self.recent.move_to_end(key)
        if len(self.recent) > 128:
            self.recent.popitem(last=False)
        # Do not forward str(error), locals, source lines, headers or user data.
        text = "\n".join((f"⚠️ Ошибка Гнида-бота · {key}", source, error_type, *frames,
                          "Подробности — в логах BotHost по этому коду."))
        self.queue.put_nowait(text)

    async def run(self):
        while True:
            text = await self.queue.get()
            try:
                delay = self.next_send - self.clock()
                if delay > 0:
                    await asyncio.sleep(delay)
                self.next_send = self.clock() + 60
                if self.suppressed:
                    text += f"\nПовторных/лишних уведомлений пропущено: {self.suppressed}."
                    self.suppressed = 0
                await asyncio.wait_for(self.bot.send_message(self.owner_id, text, parse_mode=None), timeout=10)
            except Exception as error:
                # A blocked DM or broken Telegram connection must not recurse.
                ERROR_LOG.warning("Private error notification not delivered (%s)", type(error).__name__)
            finally:
                self.queue.task_done()
