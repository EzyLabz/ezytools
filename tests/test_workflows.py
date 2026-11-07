from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import ezytools as e


class APIError(Exception):
    def __init__(self, status):
        self.status = status


class WorkflowTests(unittest.TestCase):
    def test_member_lookup(self):
        bot = Mock()
        bot.member.return_value = {'id': '123'}
        for target in ('123', '<@123>', ' <@!123> '):
            self.assertEqual(e.resolve_member(bot, 's', target), {'id': '123'})
            bot.member.assert_called_with('s', '123')
        bot.member.reset_mock()
        for target in ('', None, '<@>', '<@wrong name>'):
            self.assertIsNone(e.resolve_member(bot, 's', target))
        bot.member.assert_not_called()
        bot.member.side_effect = APIError(404)
        self.assertIsNone(e.resolve_member(bot, 's', 'missing'))
        bot.member.side_effect = APIError(403)
        with self.assertRaises(APIError):
            e.resolve_member(bot, 's', 'forbidden')

    def test_role_and_channel_lookup(self):
        bot = Mock()
        role = {'id': 'r', 'name': 'Moderator'}
        bot.roles.return_value = [role]
        for query in ('r', '<@&r>', 'MODERATOR'):
            self.assertEqual(e.find_role(bot, 's', query), role)
        self.assertIsNone(e.find_role(bot, 's', 'missing'))
        bot.roles.return_value.append({'id': 'r2', 'name': 'moderator'})
        with self.assertRaises(ValueError):
            e.find_role(bot, 's', 'Moderator')
        self.assertEqual(e.find_role(bot, 's', 'r'), role)
        channel = {'id': 'c', 'name': 'general'}
        bot.channels.return_value = [channel]
        self.assertEqual(e.find_channel(bot, 's', '<#c>', channel_type='text'), channel)
        bot.channels.assert_called_with('s', type='text')
        self.assertEqual(e.find_channel(bot, 's', 'GENERAL'), channel)

    def test_normalized_roles(self):
        self.assertEqual(e.member_role_ids({'roles': [1, {'id': '2'}, '1']}), ['1', '2'])
        self.assertEqual(e.member_role_ids({}), [])
        self.assertEqual(e.member_role_ids({'role_ids': [], 'roles': ['ignored']}), [])
        with self.assertRaises(ValueError):
            e.member_role_ids({'roles': [{}]})

    def test_explicit_access_check(self):
        bot = Mock()
        bot.member.return_value = {'role_ids': ['staff']}
        msg = SimpleNamespace(server_id='s', author_id='u', reply=Mock())
        self.assertTrue(e.require_roles(bot, msg, ['staff', 'admin']))
        self.assertFalse(e.require_roles(bot, msg, ['staff', 'admin'], match_all=True, message='Denied'))
        msg.reply.assert_called_once_with('Denied')
        bot.member.side_effect = APIError(403)
        with self.assertRaises(APIError):
            e.require_roles(bot, msg, ['staff'])
        msg.server_id = None
        self.assertFalse(e.require_roles(bot, msg, ['staff']))
        with self.assertRaises(ValueError):
            e.require_roles(bot, msg, [])

    def test_minimal_role_updates(self):
        bot = Mock()
        bot.member.return_value = {'role_ids': ['keep', 'old', 'already']}
        result = e.update_roles(bot, 's', 'u', add=['new', 'new', 'already'], remove=['old', 'absent'])
        self.assertEqual(result, {'added': ['new'], 'removed': ['old']})
        bot.member.assert_called_once_with('s', 'u')
        bot.remove_role.assert_called_once_with('s', 'u', 'old')
        bot.add_role.assert_called_once_with('s', 'u', 'new')
        bot.reset_mock()
        with self.assertRaises(ValueError):
            e.update_roles(bot, 's', 'u', add=['r'], remove=['r'])
        bot.member.assert_not_called()
        self.assertEqual(e.update_roles(bot, 's', 'u'), {'added': [], 'removed': []})
        bot.member.assert_not_called()

    def test_failed_role_update_is_not_hidden(self):
        bot = Mock()
        bot.member.return_value = {'role_ids': ['old']}
        bot.remove_role.side_effect = APIError(403)
        with self.assertRaises(APIError):
            e.update_roles(bot, 's', 'u', add=['new'], remove=['old'])
        bot.add_role.assert_not_called()

    def test_literal_template(self):
        self.assertEqual(e.render_message('Hi {user}! {unknown} {user.name} {"json": 1}', user='Ada'),
                         'Hi Ada! {unknown} {user.name} {"json": 1}')
        self.assertEqual(e.render_message('{user} {next}', user='{next}', next='value'), '{next} value')

    def test_quoted_arguments_take_precedence_over_sdk_argv(self):
        msg = SimpleNamespace(args='123 "two words"', argv=['123', '"two', 'words"'])
        self.assertEqual(e.get_arguments(msg), ['123', 'two words'])


if __name__ == '__main__':
    unittest.main()
