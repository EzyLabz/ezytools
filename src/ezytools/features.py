"""Explicit, dependency-free building blocks for developer-owned commands."""
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
import shlex
import sqlite3


class ArgumentError(ValueError):
    """Invalid command input; safe to display to the command user."""


@dataclass(frozen=True)
class Argument:
    """A positional argument. Optional arguments must follow required ones.

    kind: str, int, float, bool, 'user', 'channel', or 'duration' (seconds).
    rest consumes remaining tokens. Defaults are returned as supplied.
    """
    name: str
    kind: object = str
    optional: bool = False
    default: object = None
    minimum: object = None
    maximum: object = None
    choices: object = None
    rest: bool = False


def parse_arguments(source, arguments):
    """Parse a string, token iterable, or SDK message into a named dictionary.

    Raises ArgumentError without replying or invoking bot actions.
    Duration accepts positive integer s/m/h/d units, defaulting to seconds.
    IDs accept letters, digits, underscores and hyphens; no network lookup.
    """
    specs = list(arguments)
    optional = False
    names = set()
    for index, spec in enumerate(specs):
        if not isinstance(spec, Argument) or not spec.name or spec.name in names:
            raise ValueError('Arguments need unique nonempty names')
        if spec.kind not in (str, int, float, bool, 'user', 'channel', 'duration'):
            raise ValueError('Unsupported argument kind')
        if optional and not spec.optional:
            raise ValueError('Required arguments must precede optional arguments')
        if spec.rest and (index != len(specs) - 1 or spec.kind is not str):
            raise ValueError('Only the final string argument may consume remaining tokens')
        optional = optional or spec.optional
        names.add(spec.name)
    if hasattr(source, 'args'):
        source = source.args or ''
    try:
        tokens = shlex.split(source) if isinstance(source, str) else list(source)
    except ValueError as exc:
        raise ArgumentError(f'Invalid quoting: {exc}') from exc
    result = {}
    for spec in specs:
        if not tokens:
            if not spec.optional:
                raise ArgumentError(f'{spec.name}: required argument is missing')
            result[spec.name] = copy.deepcopy(spec.default)
            continue
        raw = ' '.join(tokens) if spec.rest else tokens[0]
        tokens = [] if spec.rest else tokens[1:]
        try:
            if spec.kind in ('user', 'channel'):
                pattern = r'<@!?([\w-]+)>|([\w-]+)' if spec.kind == 'user' else r'<#([\w-]+)>|([\w-]+)'
                match = re.fullmatch(pattern, raw, flags=re.ASCII)
                if not match:
                    raise ValueError('expected an ID or mention')
                value = match.group(1) or match.group(2)
            elif spec.kind == 'duration':
                match = re.fullmatch(r'([0-9]+)([smhd]?)', raw.lower())
                if not match or int(match.group(1)) <= 0:
                    raise ValueError('expected a positive duration such as 10m')
                value = int(match.group(1)) * {'': 1, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[match.group(2)]
            elif spec.kind is bool:
                if raw.lower() not in ('true', 'false', 'yes', 'no', '1', '0'):
                    raise ValueError('expected true/false, yes/no, or 1/0')
                value = raw.lower() in ('true', 'yes', '1')
            else:
                value = spec.kind(raw)
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError('expected a finite number')
            if spec.minimum is not None and value < spec.minimum:
                raise ValueError(f'must be at least {spec.minimum}')
            if spec.maximum is not None and value > spec.maximum:
                raise ValueError(f'must be at most {spec.maximum}')
            if spec.choices is not None and value not in spec.choices:
                raise ValueError(f'expected one of {list(spec.choices)}')
        except (ValueError, TypeError) as exc:
            raise ArgumentError(f'{spec.name}: {exc}') from exc
        result[spec.name] = value
    if tokens:
        raise ArgumentError('Too many arguments')
    return result


def _ids(values):
    if isinstance(values, (str, bytes)):
        raise ValueError('Pass a collection of IDs, not a string')
    result = list(dict.fromkeys(str(value) for value in values))
    if not result or any(not value.strip() for value in result):
        raise ValueError('Provide at least one nonempty ID')
    return result


def missing_roles(bot, server_id, user_id, role_ids):
    """Return missing role IDs in requested order. SDK errors propagate."""
    from .core import member_role_ids
    required = _ids(role_ids)
    actual = set(member_role_ids(bot.member(server_id, user_id)))
    return [role for role in required if role not in actual]


def has_all_roles(bot, server_id, user_id, role_ids):
    return not missing_roles(bot, server_id, user_id, role_ids)


def has_any_role(bot, server_id, user_id, role_ids):
    required = _ids(role_ids)
    return len(missing_roles(bot, server_id, user_id, required)) < len(required)


def missing_permissions(permissions, required):
    """Check SDK-exposed names, supplied as a collection or bool mapping.

    No guessed bit flags, role inference, administrator or owner bypass.
    Pass the SDK's effective permissions for the relevant member/channel.
    """
    required = _ids(required)
    if isinstance(permissions, dict):
        actual = {str(key) for key, value in permissions.items() if value is True}
    else:
        if isinstance(permissions, (str, bytes)) or permissions is None:
            raise ValueError('Provide permission names or a boolean mapping')
        actual = set(map(str, permissions))
    return [name for name in required if name not in actual]


def has_permissions(permissions, required):
    return not missing_permissions(permissions, required)


@dataclass(frozen=True)
class ErrorInfo:
    category: str
    original: Exception
    status: object = None
    retry_after: object = None


def classify_error(error):
    """Preserve the error; categorize HTTP status or standard network errors.

    Does not retry actions, log secrets, or send a reply.
    """
    status = getattr(error, 'status', getattr(error, 'status_code', None))
    category = {400: 'invalid_request', 401: 'unauthorized', 403: 'forbidden',
                404: 'not_found', 409: 'conflict', 429: 'rate_limited'}.get(status)
    if category is None:
        category = ('server_error' if isinstance(status, int) and 500 <= status <= 599
                    else 'timeout' if isinstance(error, TimeoutError)
                    else 'network' if isinstance(error, ConnectionError) else 'unknown')
    return ErrorInfo(category, error, status, getattr(error, 'retry_after', None))


def check_interaction(interaction, owner_id, *, expires_at=None, now=None):
    """Return allowed/expired/not_owner without acknowledging. Times are Unix seconds."""
    import time
    if expires_at is not None and (time.time() if now is None else now) >= expires_at:
        return 'expired'
    return 'allowed' if str(interaction.user_id) == str(owner_id) else 'not_owner'


def acknowledge_interaction(interaction, content=None):
    """Explicitly acknowledge via SDK ephemeral(content) or update(). Call once.

    The caller owns acknowledgement state; SDK failures propagate.
    """
    return interaction.update() if content is None else interaction.ephemeral(content)


class ServerStore:
    """SQLite settings and moderation history. Use a file for persistence.

    Each instance belongs to its creating thread; use a context manager or close().
    Settings updates are transactional. No bot actions are automatically recorded.
    validators maps setting names to callables returning True for valid values.
    """
    def __init__(self, path, *, defaults=None, validators=None):
        self.defaults = copy.deepcopy(defaults or {})
        self.validators = dict(validators or {})
        self._validate(self.defaults)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS ezy_settings (
                server TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ezy_cases (
                server TEXT NOT NULL, case_id INTEGER NOT NULL,
                action TEXT NOT NULL, moderator TEXT NOT NULL, target TEXT NOT NULL,
                reason TEXT NOT NULL, timestamp TEXT NOT NULL,
                PRIMARY KEY (server, case_id));
            CREATE INDEX IF NOT EXISTS ezy_case_target ON ezy_cases(server, target);
        ''')

    def _validate(self, values):
        json.dumps(values, allow_nan=False)
        for key, value in values.items():
            if key in self.validators and self.validators[key](value) is not True:
                raise ValueError(f'Invalid setting: {key}')

    def settings(self, server_id):
        row = self._db.execute('SELECT data FROM ezy_settings WHERE server=?', (str(server_id),)).fetchone()
        return {**copy.deepcopy(self.defaults), **(json.loads(row[0]) if row else {})}

    def update_settings(self, server_id, **changes):
        self._validate(changes)
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            values = self.settings(server_id)
            values.update(changes)
            self._validate(values)
            self._db.execute('INSERT OR REPLACE INTO ezy_settings VALUES (?,?)',
                             (str(server_id), json.dumps(values, allow_nan=False)))
        return values

    def reset_settings(self, server_id):
        """Remove server overrides and return independent defaults."""
        with self._db:
            self._db.execute('DELETE FROM ezy_settings WHERE server=?', (str(server_id),))
        return self.settings(server_id)

    def record_case(self, server_id, action, moderator, target, reason='No reason provided'):
        """Allocate a per-server case ID atomically; return the saved dictionary."""
        if any(value is None or not str(value).strip() for value in (server_id, action, moderator, target)):
            raise ValueError('Server, action, moderator and target are required')
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            case_id = self._db.execute('SELECT COALESCE(MAX(case_id),0)+1 FROM ezy_cases WHERE server=?',
                                       (str(server_id),)).fetchone()[0]
            self._db.execute('INSERT INTO ezy_cases VALUES (?,?,?,?,?,?,?)',
                             (str(server_id), case_id, str(action), str(moderator), str(target),
                              str(reason), datetime.now(timezone.utc).isoformat()))
        return self.get_case(server_id, case_id)

    def get_case(self, server_id, case_id):
        row = self._db.execute('SELECT * FROM ezy_cases WHERE server=? AND case_id=?',
                               (str(server_id), case_id)).fetchone()
        return dict(row) if row else None

    def list_cases(self, server_id, *, target=None, action=None, limit=100, offset=0):
        """Newest first, with optional target/action filters and bounded pagination."""
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ValueError('limit must be 1..1000 and offset a nonnegative integer')
        query, params = 'SELECT * FROM ezy_cases WHERE server=?', [str(server_id)]
        for field, value in (('target', target), ('action', action)):
            if value is not None:
                query += f' AND {field}=?'
                params.append(str(value))
        return [dict(row) for row in self._db.execute(query + ' ORDER BY case_id DESC LIMIT ? OFFSET ?',
                                                     [*params, limit, offset])]

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


__all__ = [name for name, value in list(globals().items())
           if not name.startswith('_') and callable(value) and getattr(value, '__module__', None) == __name__]
