import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import ezytools as e


class FeaturesTests(unittest.TestCase):
    def test_typed_arguments(self):
        specs = [e.Argument('user', 'user'), e.Argument('time', 'duration', maximum=3600),
                 e.Argument('reason', optional=True, default='none', rest=True)]
        self.assertEqual(e.parse_arguments('<@!abc> 10m two words', specs),
                         {'user': 'abc', 'time': 600, 'reason': 'two words'})
        self.assertEqual(e.parse_arguments('abc 1s', specs)['reason'], 'none')
        for text in ('<@&abc> 1m', 'abc 0s', 'abc 2h', 'abc', '"unfinished'):
            with self.assertRaises(e.ArgumentError):
                e.parse_arguments(text, specs)
        self.assertEqual(e.parse_arguments('<#c> 4 yes', [e.Argument('c', 'channel'),
                         e.Argument('n', int, minimum=1, choices=[4]), e.Argument('b', bool)]),
                         {'c': 'c', 'n': 4, 'b': True})
        for text in ('nan', 'inf', '-inf'):
            with self.assertRaises(e.ArgumentError):
                e.parse_arguments(text, [e.Argument('n', float)])
        with self.assertRaises(e.ArgumentError):
            e.parse_arguments('one extra', [e.Argument('one')])
        with self.assertRaises(ValueError):
            e.parse_arguments('', [e.Argument('x', optional=True), e.Argument('y')])

    def test_roles_and_permissions(self):
        bot = Mock()
        bot.member.return_value = {'roles': [{'id': 'staff'}]}
        self.assertTrue(e.has_any_role(bot, 's', 'u', ['staff', 'admin']))
        self.assertFalse(e.has_all_roles(bot, 's', 'u', ['staff', 'admin']))
        self.assertEqual(e.missing_roles(bot, 's', 'u', ['admin', 'admin']), ['admin'])
        with self.assertRaises(ValueError):
            e.has_all_roles(bot, 's', 'u', [])
        self.assertEqual(e.missing_permissions({'kick': True, 'ban': False}, ['kick', 'ban']), ['ban'])
        self.assertFalse(e.has_permissions({}, ['kick']))
        self.assertTrue(e.has_permissions(['kick'], ['kick']))
        bot.member.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            e.has_any_role(bot, 's', 'u', ['staff'])

    def test_persistence_validation_and_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bot.sqlite3'
            with e.ServerStore(path, defaults={'prefix': '!'},
                               validators={'prefix': lambda v: isinstance(v, str) and bool(v)}) as store:
                store.update_settings('s', prefix='?')
                with self.assertRaises(ValueError):
                    store.update_settings('s', prefix='')
                self.assertEqual(store.settings('s'), {'prefix': '?'})
                self.assertEqual(store.settings('other'), {'prefix': '!'})
                self.assertEqual(store.record_case('s', 'warn', 'mod', 'user')['case_id'], 1)
                self.assertEqual(store.record_case('s', 'ban', 'mod', 'other')['case_id'], 2)
                self.assertEqual(store.record_case('other', 'warn', 'mod', 'user')['case_id'], 1)
                self.assertEqual(len(store.list_cases('s', target='user')), 1)
                self.assertEqual(store.list_cases('s', action='ban')[0]['target'], 'other')
                self.assertEqual(store.list_cases('s', limit=1, offset=1)[0]['case_id'], 1)
                self.assertIsNone(store.get_case('missing', 1))
            with e.ServerStore(path, defaults={'prefix': '!'}) as store:
                self.assertEqual(store.settings('s')['prefix'], '?')
                self.assertEqual(len(store.list_cases('s')), 2)
                self.assertEqual(store.reset_settings('s'), {'prefix': '!'})

    def test_errors_and_interactions(self):
        error = RuntimeError('original')
        error.status = 429
        error.retry_after = 5
        info = e.classify_error(error)
        self.assertIs(info.original, error)
        self.assertEqual((info.category, info.retry_after), ('rate_limited', 5))
        self.assertEqual(e.classify_error(TimeoutError()).category, 'timeout')
        interaction = SimpleNamespace(user_id='u', ephemeral=Mock(), update=Mock())
        self.assertEqual(e.check_interaction(interaction, 'u', expires_at=10, now=9), 'allowed')
        self.assertEqual(e.check_interaction(interaction, 'u', expires_at=10, now=10), 'expired')
        self.assertEqual(e.check_interaction(interaction, 'other'), 'not_owner')
        interaction.update.assert_not_called()
        e.acknowledge_interaction(interaction)
        interaction.update.assert_called_once_with()
        e.acknowledge_interaction(interaction, 'Done')
        interaction.ephemeral.assert_called_once_with('Done')


if __name__ == '__main__':
    unittest.main()
