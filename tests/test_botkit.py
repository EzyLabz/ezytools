from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import ezytools as e


def message(**fields):
    return SimpleNamespace(server_id='s', author_id='u', channel_id='c',
                           reply=Mock(return_value={'id': 'sent'}), **fields)


class BotKitTests(unittest.TestCase):
    def test_arguments(self):
        msg = message(args='123 "two words"')
        self.assertEqual(e.command_arguments(msg, 2, 2), ['123', 'two words'])
        msg.args = '"unfinished'
        self.assertIsNone(e.command_arguments(msg, usage='/warn user reason'))
        msg.reply.assert_called_once()
        msg.args = ''
        self.assertEqual(e.command_arguments(msg), [])
        self.assertIsNone(e.command_arguments(msg, minimum=1))

    def test_guard_and_cooldown(self):
        bot = Mock()
        bot.member.return_value = {'role_ids': ['staff']}
        callback = Mock(return_value='ran')
        guarded = e.command_guard(bot, roles=['staff'], cooldown=5)(callback)
        msg = message()
        with patch('ezytools.core.time.monotonic', return_value=10):
            self.assertEqual(guarded(msg), 'ran')
            self.assertIsNone(guarded(msg))
        callback.assert_called_once_with(msg)
        with patch('ezytools.core.time.monotonic', return_value=16):
            guarded(msg)
        self.assertEqual(callback.call_count, 2)
        msg.server_id = None
        guarded(msg)
        self.assertEqual(callback.call_count, 2)

    def test_guard_denies_before_consuming_cooldown(self):
        bot = Mock()
        bot.server.return_value = {'owner_id': 'other'}
        callback = Mock()
        guarded = e.command_guard(bot, owner_only=True, cooldown=10)(callback)
        msg = message()
        guarded(msg)
        callback.assert_not_called()
        bot.server.return_value = {'owner_id': 'u'}
        guarded(msg)
        callback.assert_called_once()
        bot.server.side_effect = RuntimeError('API unavailable')
        with self.assertRaises(RuntimeError):
            guarded(msg)
        self.assertEqual(callback.call_count, 1)

    def test_roles(self):
        bot = Mock()
        bot.member.return_value = {'roles': [{'id': 'r'}]}
        self.assertFalse(e.toggle_role(bot, 's', 'u', 'r'))
        bot.remove_role.assert_called_once_with('s', 'u', 'r')
        bot.member.return_value = {'role_ids': []}
        self.assertTrue(e.toggle_role(bot, 's', 'u', 'r'))
        bot.add_role.assert_called_once_with('s', 'u', 'r')

    def test_welcome(self):
        bot = Mock()
        bot.server.return_value = {'name': 'Test server'}
        handler = e.install_welcome(bot, 'c', server_id='s', role_id='r')
        bot.on.assert_called_once_with('member_join', handler)
        event = SimpleNamespace(server_id='other', user_id='u', username='Ada')
        handler(event)
        bot.send.assert_not_called()
        event.server_id = 's'
        handler(event)
        bot.add_role.assert_called_once_with('s', 'u', 'r')
        bot.send.assert_called_once_with('c', 'Welcome <@u> to Test server!')

    def test_help_and_long_replies(self):
        bot = Mock()
        bot.commands = {'ping': {'description': 'Pong'}, 'secret': {}}
        help_command = e.register_help(bot, hidden=['secret'])
        bot.commands['new'] = {'description': 'New command'}
        msg = message()
        help_command(msg)
        text = msg.reply.call_args.args[0]
        self.assertIn('/new - New command', text)
        self.assertNotIn('/secret', text)
        msg.reply.reset_mock()
        self.assertEqual(len(e.reply_long(msg, 'abcde', 2)), 3)

    def test_paginator_ownership_expiry_and_bounds(self):
        bot = Mock()
        with patch('ezytools.core.time.monotonic', return_value=10):
            pages = e.ButtonPaginator(bot, timeout=5)
            msg = message()
            pages.send(msg, ['one', 'two'])
            components = msg.reply.call_args.kwargs['components']
            self.assertTrue(components[0]['components'][0]['disabled'])
            next_id = components[0]['components'][1]['custom_id']
            interaction = SimpleNamespace(custom_id=next_id, user_id='other',
                                          ephemeral=Mock(), update=Mock())
            pages._handle(interaction)
            interaction.update.assert_not_called()
            interaction.user_id = 'u'
            pages._handle(interaction)
            self.assertEqual(interaction.update.call_args.kwargs['content'], 'two\n\nPage 2/2')
            self.assertTrue(interaction.update.call_args.kwargs['components'][0]['components'][1]['disabled'])
            pages._handle(interaction)
            self.assertEqual(interaction.update.call_args.kwargs['content'], 'two\n\nPage 2/2')
        interaction.update.reset_mock()
        with patch('ezytools.core.time.monotonic', return_value=16):
            pages._handle(interaction)
        interaction.update.assert_not_called()
        self.assertFalse(pages._sessions)

    def test_paginator_failed_send_and_limits(self):
        pages = e.ButtonPaginator(Mock(), max_sessions=1)
        msg = message()
        msg.reply.side_effect = RuntimeError('send failed')
        with self.assertRaises(RuntimeError):
            pages.send(msg, ['one', 'two'])
        self.assertFalse(pages._sessions)
        msg.reply.side_effect = None
        pages.send(msg, ['one', 'two'])
        with self.assertRaises(RuntimeError):
            pages.send(msg, ['three', 'four'])
        for invalid in ([], '', ['']):
            with self.assertRaises(ValueError):
                pages.send(msg, invalid)


if __name__ == '__main__':
    unittest.main()

