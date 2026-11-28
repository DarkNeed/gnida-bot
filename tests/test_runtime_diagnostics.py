import asyncio
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from arena_web import create_arena_app
from handlers.runtime_diagnostics import CUSTOM_COMMAND_OWNER_ID, create_runtime_diagnostics_router
from runtime_diagnostics import ErrorNotifier, MemoryProbe, memory_log_interval


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_current_nested_cgroup_and_process(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            proc, cg = root / 'proc', root / 'cg'
            proc.mkdir()
            inner = cg / 'docker' / 'bot'
            inner.mkdir(parents=True)
            (proc / 'status').write_text('VmRSS:\t102400 kB\nRssAnon:\t81920 kB\n')
            (proc / 'cgroup').write_text('0::/docker/bot\n')
            (cg / 'memory.stat').write_text('anon 999999999\n')
            (inner / 'memory.stat').write_text('anon 83886080\nfile 314572800\nshmem 0\n')
            (inner / 'memory.current').write_text('419430400\n')
            (inner / 'memory.max').write_text('1073741824\n')
            (inner / 'memory.events').write_text('oom 1\noom_kill 1\n')
            probe = MemoryProbe(proc, cg)
            with self.assertLogs('runtime.memory', level='INFO') as logs:
                probe.log('ready')
            for value in ('stage=ready', 'rss_mib=100.0', 'rss_anon_mib=80.0', 'cg_file_mib=300.0',
                          'cg_current_mib=400.0', 'cg_limit_mib=1024.0', 'cg_oom_kill=1'):
                self.assertIn(value, logs.output[0])

    async def test_legacy_cgroup_and_missing_files(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(MemoryProbe(root / 'missing', root).sample(), {'rss':None,'rss_anon':None})
            (root / 'cgroup').write_text('3:memory:/\n')
            inner = root / 'memory'
            inner.mkdir()
            (inner / 'memory.stat').write_text('total_rss 123\ntotal_cache 456\n')
            (inner / 'memory.limit_in_bytes').write_text('9223372036854771712\n')
            sample = MemoryProbe(root, root).sample()
            self.assertEqual((sample['cg_anon'], sample['cg_file'], sample['cg_limit']), (123, 456, None))

    async def test_intervals_and_warmup(self):
        self.assertEqual([memory_log_interval(x) for x in ('', '0', '10')], [60, 0, 10])
        with self.assertLogs('runtime.memory', level='WARNING'):
            self.assertEqual(memory_log_interval('bogus'), 60)
        probe = MemoryProbe()
        timeline = []

        async def sleep(seconds):
            timeline.append(seconds)
            if len(timeline) == 4:
                raise asyncio.CancelledError

        with patch('runtime_diagnostics.asyncio.sleep', side_effect=sleep), patch.object(probe, 'log') as log:
            with self.assertRaises(asyncio.CancelledError):
                await probe.run(60)
        self.assertEqual(timeline, [10, 20, 30, 60])
        self.assertEqual([call.args[0] for call in log.call_args_list], ['warmup', 'warmup', 'periodic'])

    @unittest.skipUnless(os.name == 'nt', 'requires Windows process counters')
    async def test_windows_exposes_real_process_rss_and_private_commit(self):
        probe = MemoryProbe()
        snapshot = probe.sample()
        self.assertGreater(snapshot['rss'], 0)
        self.assertGreater(snapshot['private_commit'], 0)
        self.assertIn('Частная выделенная память Python (Windows)', probe.telegram_summary())

    async def test_private_summary_compares_with_start_and_previous_peak(self):
        probe = MemoryProbe()
        unit = 1024 * 1024
        with patch.object(probe, "sample", side_effect=[
            dict(rss=100 * unit, cg_current=120 * unit),
            dict(rss=600 * unit, cg_current=905 * unit),
            dict(rss=500 * unit, cg_current=800 * unit, cg_oom_kill=2),
        ]):
            probe.capture()
            probe.capture()
            report = probe.telegram_summary()
        self.assertIn("500.0 МиБ (+400.0 со старта) · пик по замерам 600.0", report)
        self.assertIn("800.0 МиБ (+680.0 со старта) · пик по замерам 905.0", report)
        self.assertIn("(OOM): 2", report)
        with patch.object(probe, "sample", return_value={}):
            self.assertIn("не открыл системные счётчики", probe.telegram_summary())

    async def test_command_is_only_for_owner_in_private_chat(self):
        probe = Mock(telegram_summary=Mock(return_value="only the owner should see this"))
        dispatcher = Dispatcher()
        dispatcher.include_router(create_runtime_diagnostics_router(probe))
        bot = Bot(token="1:test")
        serial = 0

        async def update(actor, chat_type, text):
            nonlocal serial
            serial += 1
            return await dispatcher.feed_update(bot, Update.model_validate(dict(
                update_id=serial, message={
                    "message_id": serial, "date": 1, "text": text,
                    "chat": {"id": actor if chat_type == "private" else -1001, "type": chat_type},
                    "from": {"id": actor, "is_bot": False, "first_name": "Example"},
                })))

        try:
            with patch.object(Bot, "__call__", autospec=True, return_value=None) as request:
                await update(CUSTOM_COMMAND_OWNER_ID + 1, "private", "/память")
                await update(CUSTOM_COMMAND_OWNER_ID, "supergroup", "/memory")
                await update(CUSTOM_COMMAND_OWNER_ID, "private", "/память")
                await update(CUSTOM_COMMAND_OWNER_ID, "private", "/memory")
                self.assertEqual(request.await_count, 2)
                self.assertTrue(all(call.args[1].chat_id == CUSTOM_COMMAND_OWNER_ID
                                    and call.args[1].text == "only the owner should see this"
                                    for call in request.await_args_list))
            self.assertEqual(probe.telegram_summary.call_count, 2)
        finally:
            await bot.session.close()


class ErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_notification_redacts_and_deduplicates(self):
        bot = Mock(send_message=AsyncMock())
        notifier = ErrorNotifier(bot, 42, clock=lambda: 10)
        with self.assertLogs('runtime.errors', level=logging.ERROR) as logs:
            for _ in range(2):
                try:
                    raise RuntimeError('secret initData and token')
                except RuntimeError as error:
                    notifier.report('Тест', error)
        self.assertEqual(notifier.queue.qsize(), 1)
        task = asyncio.create_task(notifier.run())
        try:
            await asyncio.wait_for(notifier.queue.join(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        bot.send_message.assert_awaited_once()
        actor, message = bot.send_message.await_args.args
        self.assertEqual(actor, 42)
        self.assertIsNone(bot.send_message.await_args.kwargs['parse_mode'])
        self.assertIn('RuntimeError', message)
        self.assertIn('test_runtime_diagnostics.py', message)
        self.assertIn('пропущено: 1', message)
        self.assertNotIn('secret initData', message)
        self.assertIn(message.splitlines()[0].rsplit(' ', 1)[-1], logs.output[0])

    async def test_queue_bound_and_opt_out(self):
        bot = Mock(send_message=AsyncMock())
        notifier = ErrorNotifier(bot, 42)
        disabled = ErrorNotifier(bot, 42, enabled=False)
        with self.assertLogs('runtime.errors', level=logging.ERROR):
            for index in range(100):
                notifier.report(f'test-{index}', RuntimeError())
            disabled.report('disabled', RuntimeError())
        self.assertEqual(notifier.queue.qsize(), 8)
        self.assertEqual(notifier.suppressed, 92)
        self.assertTrue(disabled.queue.empty())

    async def test_failed_dm_does_not_enqueue_another_notice(self):
        bot = Mock(send_message=AsyncMock(side_effect=RuntimeError('private')))
        notifier = ErrorNotifier(bot, 42)
        with self.assertLogs('runtime.errors') as logs:
            notifier.report('test', RuntimeError())
            task = asyncio.create_task(notifier.run())
            try:
                await asyncio.wait_for(notifier.queue.join(), 1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertIn('not delivered', logs.output[-1])
        self.assertNotIn('private\n', logs.output[-1])
        self.assertTrue(notifier.queue.empty())

    async def test_mini_app_reports_500_but_not_expected_404(self):
        report = Mock()
        app = create_arena_app(Mock(), Mock(), 'test', report_error=report)
        failure = RuntimeError('secret raw error')

        async def crash(request):
            raise failure

        app.router.add_get('/test-crash', crash)
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/test-crash')
            self.assertEqual(response.status, 500)
            self.assertNotIn('secret', await response.text())
            self.assertEqual((await client.get('/not-found')).status, 404)
        report.assert_called_once_with('HTTP-сервер мини-приложения', failure)

    async def test_main_routes_update_errors_to_the_existing_owner(self):
        from main import CUSTOM_COMMAND_OWNER_ID, main

        notice_sent = asyncio.Event()

        async def send(*args, **kwargs):
            notice_sent.set()

        bot = SimpleNamespace(id=1, get_me=AsyncMock(return_value=SimpleNamespace(username='test_bot')),
                              send_message=AsyncMock(side_effect=send),
                              session=SimpleNamespace(close=AsyncMock()))

        async def polling(dispatcher, actual_bot, **kwargs):
            @dispatcher.message()
            async def fail(message):
                raise RuntimeError('test update private text')

            update = Update.model_validate(dict(update_id=1, message=dict(
                message_id=1, date=1, chat=dict(id=77,type='private'), text='test')))
            await dispatcher.feed_update(actual_bot, update)
            await asyncio.wait_for(notice_sent.wait(), timeout=2)

        with TemporaryDirectory() as temp, patch.dict(os.environ, dict(
            BOT_TOKEN='1:test', DATABASE_PATH=str(Path(temp) / 'bot.sqlite3')
        ), clear=True), patch('main.load_dotenv'), patch('main.Bot', return_value=bot), \
            patch('main.Dispatcher.start_polling', autospec=True, side_effect=polling):
            with self.assertLogs('runtime.errors', level='ERROR'), self.assertLogs('runtime.memory') as memory:
                await main()

        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], CUSTOM_COMMAND_OWNER_ID)
        self.assertIn('Обработка обновления Telegram', bot.send_message.await_args.args[1])
        self.assertNotIn('private text', bot.send_message.await_args.args[1])
        self.assertEqual([line.split('stage=')[1].split()[0] for line in memory.output],
                         ['before_database', 'after_database', 'ready'])
        bot.session.close.assert_awaited_once()
