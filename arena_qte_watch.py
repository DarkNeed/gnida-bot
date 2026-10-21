"""Ephemeral, demand-driven QTE relay. Never settles combat or writes replays."""
import asyncio
from dataclasses import dataclass, field
import json
import math
import time

from aiohttp import web, WSMsgType

MAX_ROOMS = 32
MAX_CONNECTIONS = 128
MAX_ROOM_CONNECTIONS = 24
MAX_FRAME_BYTES = 128 * 1024
MAX_INPUTS = 2000
MAX_TICKS = 3600
HUB_KEY = web.AppKey('qte_watch_hub', object)


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Некорректное время трансляции.')
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Некорректное управление трансляции.')
    return value


@dataclass
class Stream:
    stage: dict
    socket: object
    tick: int = 0
    inputs: list = field(default_factory=list)
    clicks: list = field(default_factory=list)
    ended: bool = False
    aborted: bool = False
    retire_at: float = 0
    last_packet: float = 0

    def packet(self):
        return dict(type='data', id=self.stage['id'], tick=self.tick,
                    inputs=self.inputs, clicks=self.clicks, reset=True,
                    ended=self.ended, aborted=self.aborted)

    def accept(self, data):
        if self.ended or not isinstance(data, dict) or data.get('type') != 'data' or data.get('id') != self.stage['id']:
            raise ValueError('Мини-игра трансляции устарела.')
        now = time.monotonic()
        if now - self.last_packet < .075 and data.get('ended') is not True:
            raise ValueError('Слишком частые пакеты трансляции.')
        if self.stage['expires'] < time.time():
            raise ValueError('Трансляция истекла.')
        reset = data.get('reset', False)
        ended, aborted = data.get('ended', False), data.get('aborted', False)
        if any(type(x) is not bool for x in (reset, ended, aborted)):
            raise ValueError('Некорректный пакет трансляции.')
        if self.stage.get('version') == 3:
            total = 1140
        else:
            from arena_qte_patterns import duration
            total = math.ceil(duration(self.stage) * 120 - 1e-7)
        tick = integer(data.get('tick'), self.tick, min(MAX_TICKS, total))
        # Visual packets cannot claim that unplayed future time already elapsed.
        if tick / 120 > time.time() - self.stage['started'] + .5:
            raise ValueError('Трансляция обгоняет время мини-игры.')
        incoming, clicks = data.get('inputs', []), data.get('clicks', [])
        if not isinstance(incoming, list) or not isinstance(clicks, list):
            raise ValueError('Некорректная запись трансляции.')
        old_inputs, old_clicks = ([], []) if reset else (self.inputs, self.clicks)
        if len(incoming) + len(old_inputs) > min(MAX_INPUTS, total) or len(clicks) + len(old_clicks) > self.stage['strikes']:
            raise ValueError('Переполнен буфер трансляции.')
        if self.stage['kind'] == 'attack' and incoming or self.stage['kind'] != 'attack' and clicks:
            raise ValueError('Неподходящий вид управления.')
        previous = old_inputs[-1]['t'] if old_inputs else -1
        clean = []
        for item in incoming:
            if not isinstance(item, dict):
                raise ValueError('Некорректное управление.')
            t = integer(item.get('t'), previous + 1, min(tick, total - 1))
            previous = t
            if self.stage.get('version') == 3:
                if type(item.get('active')) is not bool:
                    raise ValueError('Некорректное состояние щита.')
                value = dict(t=t, angle=number(item.get('angle'), -math.pi, math.pi), active=item['active'])
            elif 'target' in item:
                target = item['target']
                if not isinstance(target, list) or len(target) != 2:
                    raise ValueError('Некорректная цель движения.')
                value = dict(t=t, target=[number(target[0], 0, 720), number(target[1], 0, 320)])
            else:
                value = dict(t=t, x=number(item.get('x', 0), -1, 1), y=number(item.get('y', 0), -1, 1))
            clean.append(value)
        previous = old_clicks[-1] if old_clicks else -1
        clean_clicks = []
        for item in clicks:
            previous = integer(item, previous + 1, tick)
            clean_clicks.append(previous)
        self.inputs = old_inputs + clean
        self.clicks = old_clicks + clean_clicks
        self.tick, self.ended, self.aborted, self.last_packet = tick, ended, aborted, now
        if ended:
            self.retire_at = now + 2
        return dict(type='data', id=self.stage['id'], tick=tick, inputs=clean,
                    clicks=clean_clicks, reset=reset, ended=ended, aborted=aborted)


class WatchHub:
    def __init__(self):
        self.rooms = {}
        self.connections = set()

    async def send(self, socket, data):
        if socket.closed:
            return
        try:
            await asyncio.wait_for(socket.send_json(data), 1)
        except (ConnectionError, RuntimeError, asyncio.TimeoutError):
            await socket.close()

    def join(self, key, socket, actor, role, selected):
        if key not in self.rooms:
            if len(self.rooms) >= MAX_ROOMS:
                raise ValueError('Слишком много трансляций. Попробуй позже.')
            self.rooms[key] = dict(peers={}, streams={})
        room = self.rooms[key]
        if len(room['peers']) >= MAX_ROOM_CONNECTIONS:
            raise ValueError('В этой трансляции уже много зрителей.')
        if sum(p['actor'] == actor for p in room['peers'].values()) >= 3:
            raise ValueError('Закрой лишние окна трансляции.')
        room['peers'][socket] = dict(actor=actor, role=role, selected=selected)
        return room

    async def broadcast(self, room, actor, data):
        sockets = [s for s, p in room['peers'].items() if p['role'] == 'watch' and p['selected'] == actor]
        await asyncio.gather(*(self.send(s, data) for s in sockets))

    async def demand(self, room, actor):
        stream = room['streams'].get(actor)
        if stream and not stream.ended:
            wanted = any(p['role'] == 'watch' and p['selected'] == actor for p in room['peers'].values())
            await self.send(stream.socket, dict(type='demand', active=wanted))

    async def select(self, room, socket, actor):
        peer = room['peers'][socket]
        previous, peer['selected'] = peer['selected'], actor
        stream = room['streams'].get(actor)
        if stream:
            await self.send(socket, dict(type='begin', stage=stream.stage))
            await self.send(socket, stream.packet())
        else:
            await self.send(socket, dict(type='waiting'))
        await self.demand(room, previous)
        if previous != actor:
            await self.demand(room, actor)

    async def leave(self, key, socket):
        self.connections.discard(socket)
        room = self.rooms.get(key)
        if not room:
            return
        peer = room['peers'].pop(socket, None)
        if peer and peer['role'] == 'source':
            stream = room['streams'].get(peer['actor'])
            if stream and stream.socket is socket:
                if not stream.ended:
                    stream.ended, stream.aborted = True, True
                    await self.broadcast(room, peer['actor'], dict(type='end', id=stream.stage['id']))
                stream.retire_at = time.monotonic() + 2
        if peer and peer['role'] == 'watch':
            await self.demand(room, peer['selected'])
        if not room['peers']:
            self.rooms.pop(key, None)

    async def prune(self):
        while True:
            await asyncio.sleep(1)
            for key, room in list(self.rooms.items()):
                for actor, stream in list(room['streams'].items()):
                    if stream.stage['expires'] <= time.time() or stream.retire_at and stream.retire_at <= time.monotonic():
                        room['streams'].pop(actor, None)
                        await self.broadcast(room, actor, dict(type='end', id=stream.stage['id']))
                if not room['peers']:
                    self.rooms.pop(key, None)


def add_qte_watch_routes(app, db, read_member, authenticate):
    hub = WatchHub()
    app[HUB_KEY] = hub

    async def row_for(scope, token):
        row = await (db.arena_get(token) if scope == 'battle' else db.arena_raid_get(token))
        if row['status'] != 'active':
            raise ValueError('Бой уже завершён.')
        return row

    async def endpoint(request):
        scope, token = request.match_info['scope'], request.match_info['token']
        if len(hub.connections) >= MAX_CONNECTIONS:
            raise web.HTTPServiceUnavailable(text='Слишком много трансляций.')
        ws = web.WebSocketResponse(heartbeat=15, max_msg_size=MAX_FRAME_BYTES)
        hub.connections.add(ws)
        key, health = (scope, token), None
        try:
            await ws.prepare(request)
            hello = await ws.receive_json(timeout=5)
            if not isinstance(hello, dict) or hello.get('role') not in ('source', 'watch'):
                raise ValueError('Некорректное подключение трансляции.')
            if not isinstance(hello.get('auth'), str):
                raise ValueError('Нет авторизации Telegram.')
            actor = authenticate(hello['auth'])
            row = await row_for(scope, token)
            await read_member(row['chat_id'], actor)
            role = hello['role']
            stage = None
            if role == 'source':
                stage = await db.arena_qte_stream_stage(scope, token, actor, hello.get('challenge'))
                selected = actor
            else:
                selected = integer(hello.get('actor'), 1, 2**63 - 1)
                available = await db.arena_qte_watchables(scope, token, actor)
                if selected not in {s['actor'] for s in available}:
                    raise ValueError('У этого игрока нет доступной мини-игры.')
            room = hub.join(key, ws, actor, role, selected)
            if role == 'source':
                old = room['streams'].get(actor)
                if old and not old.ended and not old.socket.closed:
                    raise ValueError('Трансляция этого игрока уже открыта.')
                room['streams'][actor] = Stream(stage, ws)
                await hub.broadcast(room, actor, dict(type='begin', stage=stage))
                await hub.demand(room, actor)
            else:
                await hub.select(room, ws, selected)

            async def recheck():
                while not ws.closed:
                    await asyncio.sleep(12)
                    try:
                        current = await row_for(scope, token)
                        await read_member(current['chat_id'], actor)
                    except Exception:
                        await ws.close(code=1008, message=b'Access expired')
                        return
            health = asyncio.create_task(recheck())
            last_select = 0
            rate_at, rate_count = time.monotonic(), 0
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    if message.type == WSMsgType.ERROR:
                        break
                    continue
                if time.monotonic() - rate_at >= 1:
                    rate_at, rate_count = time.monotonic(), 0
                rate_count += 1
                if rate_count > 25:
                    raise ValueError('Слишком много пакетов трансляции.')
                data = json.loads(message.data)
                if not isinstance(data, dict):
                    raise ValueError('Некорректный пакет.')
                if data.get('type') == 'ping':
                    continue
                if role == 'source':
                    stream = room['streams'].get(actor)
                    if not stream or stream.socket is not ws:
                        raise ValueError('Трансляция уже закрыта.')
                    packet = stream.accept(data)
                    await hub.broadcast(room, actor, packet)
                elif data.get('type') == 'select':
                    if time.monotonic() - last_select < .3:
                        raise ValueError('Слишком частое переключение.')
                    last_select = time.monotonic()
                    selected = integer(data.get('actor'), 1, 2**63 - 1)
                    available = await db.arena_qte_watchables(scope, token, actor)
                    if selected not in {s['actor'] for s in available}:
                        raise ValueError('Мини-игра уже завершена.')
                    await hub.select(room, ws, selected)
                else:
                    raise ValueError('Зритель не может передавать управление.')
        except (ValueError, TypeError, KeyError, asyncio.TimeoutError) as error:
            await hub.send(ws, dict(type='error', message=str(error)))
            await ws.close(code=1008)
        except (ConnectionError, RuntimeError):
            pass
        finally:
            if health:
                health.cancel()
            # aiohttp may cancel the handler on TCP disconnect even while this
            # finally block is running. Detach peers and notify sources anyway.
            await asyncio.shield(hub.leave(key, ws))
            if health:
                await asyncio.gather(health, return_exceptions=True)
        return ws

    async def lifecycle(_):
        task = asyncio.create_task(hub.prune())
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(*(s.close(code=1001) for s in list(hub.connections)))
        hub.rooms.clear()
        hub.connections.clear()

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/qte-stream/{scope:battle|raid}/{token}', endpoint)
