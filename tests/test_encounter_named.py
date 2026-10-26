"""Named private RP mobs in the existing /встреча command."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from arena_encounters import parse_named_roster
from handlers.raids import RaidPublisher, create_raid_router
import test_arena_rp as rp_tests


def template(ident, name, kind='mob'):
    return dict(id=ident, kind=kind, definition=dict(name=name))


class NamedRosterTests(unittest.TestCase):
    def test_multiword_names_case_spaces_counts_and_builtin_mix(self):
        own = [template('wolf', 'Лесной разбойник'), template('hero', 'Персонаж', 'character')]
        self.assertEqual(parse_named_roster('  ЛЕСНОЙ   разбойник  ', own), [dict(kind='mob', id='wolf')])
        self.assertEqual(parse_named_roster('Лесной разбойник 2, шаман', own),
                         [dict(kind='mob', id='wolf')]*2 + [dict(kind='builtin', id='shaman')])
        self.assertEqual(parse_named_roster('гоблин 2, шаман', own),
                         [dict(kind='builtin', id='goblin')]*2 + [dict(kind='builtin', id='shaman')])
        for text in ('Персонаж', 'Неизвестный', '', 'Лесной разбойник 0',
                     'Лесной разбойник 4', 'гоблин,', 'Лесной разбойник 2, гоблин 2'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_named_roster(text, own)

    def test_exact_saved_names_take_precedence_and_duplicates_are_rejected(self):
        own = [template('a', 'Гоблин'), template('b', 'Гоблин 2'), template('c', 'Дым, пепел')]
        self.assertEqual(parse_named_roster('гоблин', own), [dict(kind='mob', id='a')])
        self.assertEqual(parse_named_roster('гоблин 2', own), [dict(kind='mob', id='b')])
        self.assertEqual(parse_named_roster('Дым, пепел', own), [dict(kind='mob', id='c')])
        own.append(template('d', ' ГОБЛИН '))
        with self.assertRaisesRegex(ValueError, 'несколько мобов'):
            parse_named_roster('гоблин', own)


class NamedEncounterTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = rp_tests.RPTests.asyncSetUp
    asyncTearDown = rp_tests.RPTests.asyncTearDown

    def handler(self):
        publisher = RaidPublisher(self.db, self.bot, 'TestBot')
        router = create_raid_router(self.db, self.bot, True, publisher)
        return next(h.callback for h in router.message.handlers if h.callback.__name__ == 'encounter_command')

    def message(self, text, actor=10, message_id=101):
        return SimpleNamespace(text=text, caption=None, message_id=message_id,
            from_user=SimpleNamespace(id=actor, is_bot=False), chat=SimpleNamespace(id=-100, type='supergroup'),
            answer=AsyncMock(return_value=SimpleNamespace(message_id=202)))

    async def mob(self, actor=10, name='Лесной разбойник'):
        return await self.db.arena_rp_save(actor, 'mob',
            dict(rp_tests.definition(), name=name, stats=dict(max_hp=777), ai='sequence'))

    def rows(self):
        return list(self.db.connection.execute("SELECT * FROM arena_raids WHERE boss_id='encounter'"))

    async def test_custom_command_publishes_mixed_rp_lobby_and_starts_saved_enemy(self):
        mob = await self.mob()
        message = self.message('/встреча@GnidoBot ЛЕСНОЙ разбойник 2, шаман')
        handler = self.handler()
        await handler(message)
        message.answer.assert_awaited_once()
        row = await self.db.arena_raid_get(self.rows()[0]['token'])
        config = json.loads(row['encounter_json'])
        self.assertTrue(config['rp'])
        self.assertEqual([i['id'] for i in config['roster']], [mob['id'], mob['id'], 'shaman'])
        self.assertEqual(row['message_id'], 202)
        self.assertEqual(row['participants'], [])
        self.assertIn('Лесной разбойник', message.answer.await_args.args[0])
        self.assertIn('не участвует в бою', message.answer.await_args.args[0])
        await handler(message)
        self.assertEqual(len(self.rows()), 1)
        message.answer.assert_awaited_once()
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(row['token'], 10, 'join')
        hero = await self.db.arena_rp_save(20, 'character', rp_tests.definition())
        await self.db.arena_raid_setup(row['token'], 20, 'join', rp_template=hero['id'])
        row = await self.db.arena_raid_setup(row['token'], 10, 'start')
        data = json.loads(row['data_json'])
        self.assertEqual(data['enemies']['e1']['hp'], 777)
        self.assertEqual(data['enemies']['e2']['hp'], 777)
        self.assertEqual(len(data['enemies']), 3)
        self.assertEqual(data['rewards'], {})
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM personal_profiles WHERE user_id=10').fetchone())

    async def test_foreign_template_and_character_name_are_not_usable(self):
        await self.mob(20, 'Чужой монстр')
        await self.db.arena_rp_save(10, 'character', dict(rp_tests.definition(), name='Мой герой'))
        handler = self.handler()
        for name in ('Чужой монстр', 'Мой герой'):
            message = self.message('/встреча ' + name)
            await handler(message)
            self.assertIn('Неизвестный моб', message.answer.await_args.args[0])
        self.assertEqual(self.rows(), [])

    async def test_ambiguous_names_do_not_create_lobby(self):
        await self.mob(name='Тень');await self.mob(name='ТЕНЬ')
        message = self.message('/встреча тень')
        await self.handler()(message)
        self.assertIn('несколько мобов', message.answer.await_args.args[0])
        self.assertEqual(self.rows(), [])

    async def test_failed_publication_cancels_custom_lobby(self):
        await self.mob()
        message = self.message('/встреча Лесной разбойник')
        message.answer = AsyncMock(side_effect=RuntimeError('publication failed'))
        with self.assertRaisesRegex(RuntimeError, 'publication failed'):
            await self.handler()(message)
        self.assertEqual(self.rows()[0]['status'], 'cancelled')

    async def test_concurrent_redelivery_publishes_only_once(self):
        await self.mob()
        message = self.message('/встреча Лесной разбойник')
        handler = self.handler()
        await asyncio.gather(handler(message), handler(message))
        self.assertEqual(len(self.rows()), 1)
        message.answer.assert_awaited_once()

    async def test_builtin_only_command_preserves_legacy_encounter(self):
        message = self.message('/встреча гоблин 2, шаман')
        await self.handler()(message)
        row = self.rows()[0]
        self.assertFalse(json.loads(row['encounter_json']).get('rp'))
        self.assertEqual(json.loads(row['encounter_json'])['roster'], ['goblin', 'goblin', 'shaman'])


if __name__ == '__main__':
    unittest.main()
