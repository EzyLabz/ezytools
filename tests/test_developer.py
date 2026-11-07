import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ezytools as e


class DeveloperTests(unittest.TestCase):
    def test_public_imports(self):
        self.assertTrue(callable(e.kick))
        for name in e.__all__:
            self.assertTrue(callable(getattr(e, name)))

    def test_collections(self):
        self.assertEqual(e.chunk_list(iter(range(5)), 2), [[0, 1], [2, 3], [4]])
        self.assertEqual(e.chunk_list([], 2), [])
        self.assertEqual(e.paginate(range(5), 2, 2), [2, 3])
        self.assertEqual(e.paginate([], 3), [])
        self.assertEqual(e.unique([2, 1, 2]), [2, 1])
        for invalid in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                e.chunk_list([], invalid)
            with self.assertRaises(ValueError):
                e.paginate([], invalid)

    def test_text(self):
        self.assertEqual(e.slugify('  Café & Tools! '), 'cafe-tools')
        self.assertEqual(e.truncate('abcdef', 5), 'ab...')
        self.assertEqual(e.truncate('abcdef', 2), '..')
        self.assertEqual(e.truncate('abc', 3), 'abc')
        self.assertEqual(e.truncate('abcdef', 3, ''), 'abc')
        text = 'a\n🙂 bc'
        chunks = e.split_message(text, 2)
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(len(chunk) <= 2 for chunk in chunks))
        self.assertEqual(e.split_message(''), [])

    def test_data(self):
        data = {'users': [{'name': 'Ada'}], 'a.b': None}
        self.assertEqual(e.get_nested(data, 'users.0.name'), 'Ada')
        self.assertEqual(e.get_nested(data, 'users.9', 'missing'), 'missing')
        self.assertEqual(e.get_nested(data, 'users.-1', 'missing'), 'missing')
        self.assertIsNone(e.get_nested(data, ['a.b'], 'missing'))
        self.assertEqual(e.clamp(12, 0, 10), 10)
        with self.assertRaises(ValueError):
            e.clamp(1, 5, 2)

    def test_environment(self):
        with patch.dict(os.environ, {'FLAG': ' YES ', 'COUNT': '12'}, clear=True):
            self.assertTrue(e.env_bool('FLAG'))
            self.assertEqual(e.env_int('COUNT'), 12)
            self.assertEqual(e.env_int('MISSING', 5), 5)
            self.assertFalse(e.env_bool('MISSING'))
            with self.assertRaises(ValueError):
                e.env_bool('COUNT')
            with self.assertRaises(ValueError):
                e.env_int('FLAG')

    def test_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested' / 'data.json'
            self.assertEqual(e.load_json(path, {}), {})
            e.save_json(path, {'name': 'café'})
            self.assertEqual(e.load_json(path), {'name': 'café'})
            with self.assertRaises(TypeError):
                e.save_json(path, object())
            self.assertEqual(e.load_json(path), {'name': 'café'})
            with patch('ezytools.core.os.replace', side_effect=OSError):
                with self.assertRaises(OSError):
                    e.save_json(path, {})
            self.assertEqual(list(path.parent.iterdir()), [path])
            path.write_text('{broken', encoding='utf-8')
            with self.assertRaises(json.JSONDecodeError):
                e.load_json(path, {})

    def test_tokens(self):
        token = e.generate_token()
        self.assertRegex(token, r'^[A-Za-z0-9_-]+$')
        self.assertNotEqual(token, e.generate_token())
        with self.assertRaises(ValueError):
            e.generate_token(0)

    def test_retries(self):
        calls = []

        @e.retry(attempts=3, delay=0.25, exceptions=ValueError)
        def flaky(value):
            calls.append(value)
            if len(calls) < 3:
                raise ValueError('temporary')
            return value

        with patch('ezytools.core.time.sleep') as sleep:
            self.assertEqual(flaky(4), 4)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.25, 0.5])
        self.assertEqual(flaky.__name__, 'flaky')

        @e.retry(attempts=2, delay=0, exceptions=ValueError)
        def fail():
            raise ValueError('final')

        with patch('ezytools.core.time.sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'final'):
                fail()
            self.assertEqual(sleep.call_count, 1)
        with self.assertRaises(TypeError):
            async def async_function():
                pass
            e.retry()(async_function)
        for kwargs in ({'attempts': 0}, {'delay': -1}, {'backoff': 0},
                       {'exceptions': ()}, {'delay': float('nan')}):
            with self.assertRaises(ValueError):
                e.retry(**kwargs)


if __name__ == '__main__':
    unittest.main()

