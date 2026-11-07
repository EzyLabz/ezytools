import unittest
from unittest.mock import Mock, AsyncMock, call
import ezytools as e


class VoiceTests(unittest.TestCase):
    def test_snapshot_lookup_and_counts(self):
        bot = Mock()
        bot.voice.return_value = [{'channel_id': 'a', 'user_ids': [1, '1', '2']},
                                  {'channel_id': 'empty', 'user_ids': []}]
        self.assertEqual(e.voice_members(bot, 's', 'a'), ['1', '2'])
        self.assertEqual(e.voice_member_count(bot, 's', 'a'), 2)
        self.assertEqual(e.voice_members(bot, 's', 'missing'), [])
        self.assertEqual(e.member_voice_channel(bot, 's', 1), 'a')
        self.assertIsNone(e.member_voice_channel(bot, 's', 'absent'))
        self.assertTrue(e.is_in_voice(bot, 's', 1, 'a'))
        self.assertFalse(e.is_in_voice(bot, 's', 1, 'empty'))
        self.assertFalse(e.is_in_voice(bot, 's', 'absent'))

    def test_single_actions_preserve_results(self):
        bot = Mock()
        self.assertIs(e.move_member(bot, 's', 'u', 'c'), bot.move_member.return_value)
        bot.move_member.assert_called_once_with('s', 'u', 'c')
        self.assertIs(e.disconnect_member(bot, 's', 'u'), bot.disconnect_member.return_value)
        bot.disconnect_member.assert_called_once_with('s', 'u')
        self.assertIs(e.join_voice(bot, 's', 'c'), bot.join_voice.return_value)
        bot.join_voice.assert_called_once_with('s', 'c')
        self.assertIs(e.leave_voice(bot, 's'), bot.leave_voice.return_value)
        bot.leave_voice.assert_called_once_with('s')

    def test_bulk_validation_before_side_effects(self):
        bot = Mock()
        for targets in ('user', ['good', ''], [None], [False]):
            with self.assertRaises(ValueError):
                e.move_members(bot, 's', targets, 'c')
            with self.assertRaises(ValueError):
                e.disconnect_members(bot, 's', targets)
        self.assertEqual(bot.mock_calls, [])
        self.assertEqual(e.move_members(bot, 's', ['a', 'a', 'b'], 'c'), ['a', 'b'])
        self.assertEqual(bot.move_member.call_args_list, [call('s', 'a', 'c'), call('s', 'b', 'c')])

    def test_failure_stops_batch_without_retry(self):
        bot = Mock()
        error = RuntimeError('permission denied')
        bot.disconnect_member.side_effect = [None, error]
        with self.assertRaisesRegex(RuntimeError, 'permission denied'):
            e.disconnect_members(bot, 's', ['a', 'b', 'c'])
        self.assertEqual(bot.disconnect_member.call_args_list, [call('s', 'a'), call('s', 'b')])


class AudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_forwarding_and_validation(self):
        bot = Mock()
        bot.connect_voice = AsyncMock()
        result = await e.connect_voice(bot, 's', 'c', sample_rate=24000, channels=1)
        self.assertIs(result, bot.connect_voice.return_value)
        bot.connect_voice.assert_awaited_once_with('s', 'c', sample_rate=24000, channels=1)
        for kwargs in ({'channels': 3}, {'sample_rate': 0}, {'sample_rate': True}):
            with self.assertRaises(ValueError):
                await e.connect_voice(bot, 's', 'c', **kwargs)
        self.assertEqual(bot.connect_voice.await_count, 1)
