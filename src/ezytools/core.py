import functools
from functools import wraps
import inspect
import json
import math
from pathlib import Path
import secrets
import tempfile
import unicodedata
import os
import random
import logging
from datetime import datetime, timezone
import time
import re
import shlex
import time

# ==================================================
# EZYBOT UTILITIES
# ==================================================

logger = logging.getLogger("ezybot")


# ==================================================
# CONFIGURATION
# ==================================================

def get_owner_id():
    """Get the bot owner's user ID from an environment variable."""
    return os.environ.get("EZYBOT_OWNER_ID", "")


def is_owner(user_id):
    """Check whether a user is the configured bot owner."""
    owner_id = get_owner_id()
    return bool(owner_id) and str(user_id) == str(owner_id)


# ==================================================
# LOGGING
# ==================================================

def log(message):
    logger.info(message)


def log_warning(message):
    logger.warning(message)


def log_error(message):
    logger.error(message)


def log_moderation(action, moderator, target, reason="No reason provided"):
    log(
        f"MODERATION | {action} | "
        f"Moderator: {moderator} | "
        f"Target: {target} | "
        f"Reason: {reason}"
    )


# ==================================================
# MODERATION
# ==================================================

# Stored warnings, separated by server and user.
# Note: these are stored in memory and reset when the bot restarts.
_warnings = {}


def _args(msg):
    """Get command arguments, respecting quoted text when possible."""
    raw = getattr(msg, "args", "") or ""

    try:
        return shlex.split(raw) if isinstance(raw, str) else list(raw)
    except ValueError:
        return raw.split()


def _reply(msg, text):
    msg.reply(text)


def _server_only(msg):
    """Ensure the command was used inside a server."""
    if not getattr(msg, "server_id", None):
        _reply(msg, "❌ This command only works in a server.")
        return False
    return True


def _duration(value):
    """Convert 10m, 2h, or 1d to minutes, with a 28-day maximum."""
    match = re.fullmatch(r"(\d+)([mhd]?)", str(value).lower())

    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2) or "m"
    minutes = amount * {"m": 1, "h": 60, "d": 1440}[unit]

    if not 1 <= minutes <= 40320:
        return None

    return minutes


def _run(msg, action, success):
    """Run a moderation action and provide a readable response."""
    try:
        action()
        _reply(msg, success)
    except Exception as exc:
        status = getattr(exc, "status", None)

        if status == 403:
            _reply(msg, "❌ I don't have permission to do that.")
        elif status == 404:
            _reply(msg, "❌ Member or ban not found.")
        else:
            log_error(f"Moderation action failed: {exc}")
            _reply(msg, f"❌ Action failed: {exc}")


def kick(bot, msg):
    """Kick a user. Usage: /kick <user_id>."""
    args = _args(msg)

    if not args:
        return _reply(msg, "Usage: /kick <user_id>")
    if not _server_only(msg):
        return

    user_id = get_target(bot, msg)

    if not user_id:
        return _reply(
              msg,
              "❌ User not found. Use a mention, username, or ID."
          )
    _run(
        msg,
        lambda: bot.kick(msg.server_id, user_id),
        f"✅ Kicked `{user_id}`."
    )


def ban(bot, msg):
    """Ban a user. Usage: /ban <user_id>."""
    args = _args(msg)

    if not args:
        return _reply(msg, "Usage: /ban <user_id>")
    if not _server_only(msg):
        return

    user_id = get_target(bot, msg)

    if not user_id:
        return _reply(
            msg,
            "❌ User not found. Use a mention, username, or ID."
        )
    _run(
        msg,
        lambda: bot.ban(msg.server_id, user_id),
        f"🔨 Banned `{user_id}`."
    )


def unban(bot, msg):
    """Unban a user. Usage: /unban <user_id>."""
    args = _args(msg)

    if not args:
        return _reply(msg, "Usage: /unban <user_id>")
    if not _server_only(msg):
        return

    user_id = args[0]
    _run(
        msg,
        lambda: bot.unban(msg.server_id, user_id),
        f"✅ Unbanned `{user_id}`."
    )


def mute(bot, msg):
    """Timeout a user. Usage: /mute <user_id> <duration> [reason]."""
    args = _args(msg)

    if len(args) < 2:
        return _reply(
            msg,
            "Usage: /mute <user_id> <duration> [reason]\n"
            "Example: /mute 12345 30m spamming"
        )
    if not _server_only(msg):
        return

    user_id, duration = args[0], args[1]
    minutes = _duration(duration)

    if minutes is None:
        return _reply(
            msg,
            "❌ Invalid duration. Use 10m, 2h, 1d, or a number of minutes "
            "(maximum 28 days)."
        )

    reason = " ".join(args[2:]) or "No reason provided"

    _run(
        msg,
        lambda: bot.timeout(msg.server_id, user_id, minutes, reason),
        f"🔇 Timed out `{user_id}` for {duration}. Reason: {reason}"
    )


def unmute(bot, msg):
    """Remove a timeout. Usage: /unmute <user_id>."""
    args = _args(msg)

    if not args:
        return _reply(msg, "Usage: /unmute <user_id>")
    if not _server_only(msg):
        return

    user_id = args[0]
    _run(
        msg,
        lambda: bot.timeout(msg.server_id, user_id, 0, "Timeout removed"),
        f"🔊 Removed timeout for `{user_id}`."
    )


def warn(bot, msg):
    """Record a warning. Usage: /warn <user_id> <reason>."""
    args = _args(msg)

    if len(args) < 2:
        return _reply(msg, "Usage: /warn <user_id> <reason>")
    if not _server_only(msg):
        return

    user_id = str(args[0])
    reason = " ".join(args[1:])
    key = (str(msg.server_id), user_id)

    _warnings.setdefault(key, []).append(reason)
    count = len(_warnings[key])

    log_moderation("WARN", msg.author_id, user_id, reason)
    _reply(
        msg,
        f"⚠️ Warned `{user_id}`. Warnings: {count}. Reason: {reason}"
    )


def warnings(bot, msg):
    """Show recorded warnings. Usage: /warnings <user_id>."""
    args = _args(msg)

    if not args:
        return _reply(msg, "Usage: /warnings <user_id>")
    if not _server_only(msg):
        return

    user_id = str(args[0])
    items = _warnings.get((str(msg.server_id), user_id), [])

    if not items:
        return _reply(msg, f"✅ `{user_id}` has no recorded warnings.")

    listing = "\n".join(
        f"{number}. {reason}"
        for number, reason in enumerate(items, start=1)
    )
    _reply(msg, f"⚠️ Warnings for `{user_id}`:\n{listing}")


def clearwarnings(bot, msg):
    """Clear recorded warnings. Usage: /clearwarnings <user_id>."""
    args = _args(msg)

    if not args:
        return _reply(msg, "Usage: /clearwarnings <user_id>")
    if not _server_only(msg):
        return

    user_id = str(args[0])
    key = (str(msg.server_id), user_id)
    removed = len(_warnings.pop(key, []))

    log_moderation("CLEAR WARNINGS", msg.author_id, user_id)
    _reply(msg, f"✅ Cleared {removed} warning(s) for `{user_id}`.")


# ==================================================
# PERFORMANCE
# ==================================================

def get_latency(start_time):
    """Return elapsed time in milliseconds since start_time."""
    return round((time.perf_counter() - start_time) * 1000)


# ==================================================
# MESSAGE HELPERS
# ==================================================

def get_arguments(msg):
    """Return command arguments, preserving quoted phrases in msg.args."""
    if getattr(msg, 'args', None) is not None:
        return _args(msg)
    argv = getattr(msg, "argv", None)

    if argv is not None:
        return list(argv)

    content = getattr(msg, "content", "") or ""
    return content.split()


def get_argument_text(msg):
    """Return everything after the command name."""
    return getattr(msg, "args", "") or ""


def send_message(bot, message, channel_id=None, msg=None):
    """Send a message to a channel or the command's channel."""
    if channel_id is None and msg is not None:
        channel_id = msg.channel_id

    if channel_id is None:
        raise ValueError("A channel ID or message object is required.")

    return bot.send(channel_id, message)


# ==================================================
# SERVER HELPERS
# ==================================================

def get_server_owner_id(bot, msg):
    """Get the owner ID of the server where the command was used."""
    if not getattr(msg, "server_id", None):
        return None

    server = bot.server(msg.server_id)
    return server.get("owner_id")


def is_server_owner(bot, msg):
    """Check whether the person using the command owns the server."""
    owner_id = get_server_owner_id(bot, msg)

    if owner_id is None:
        return False

    return str(msg.author_id) == str(owner_id)


# ==================================================
# ARGUMENT AND REASON HELPERS
# ==================================================

def get_reason(arguments, start=1):
    """Get a moderation reason from a list of command arguments."""
    reason = " ".join(arguments[start:]).strip()
    return reason or "No reason provided"


def parse_target_and_reason(arguments):
    """Return a target user ID and reason from command arguments."""
    if not arguments:
        return None, "No reason provided"

    return arguments[0], get_reason(arguments)


# ==================================================
# DURATION HELPERS
# ==================================================

def parse_duration(value):
    """
    Convert a duration into seconds.

    Examples:
        parse_duration("30s") -> 30
        parse_duration("10m") -> 600
        parse_duration("2h")  -> 7200
        parse_duration("1d")  -> 86400
    """
    match = re.fullmatch(r"(\d+)([smhd]?)", str(value).lower().strip())

    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2) or "s"
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]

    return seconds if amount > 0 else None


def format_duration(seconds):
    """Format a duration in seconds into a readable string."""
    seconds = max(0, int(seconds))

    units = (
        ("day", 86400),
        ("hour", 3600),
        ("minute", 60),
        ("second", 1),
    )

    parts = []

    for name, size in units:
        amount, seconds = divmod(seconds, size)

        if amount:
            label = name if amount == 1 else f"{name}s"
            parts.append(f"{amount} {label}")

    return ", ".join(parts) if parts else "0 seconds"

#//////Other//////


def embed(title, description=None, color=0x5865F2, fields=None, footer=None):
    """Create a reusable embed dictionary for Yapper messages."""
    result = {
        "title": str(title),
        "color": color,
    }

    if description:
        result["description"] = str(description)

    if fields:
        result["fields"] = fields

    if footer:
        result["footer"] = {"text": str(footer)}

    return result


def send_embed(msg, title, description=None, color=0x5865F2,
               fields=None, footer="Ezybot"):
    """Create and send an embed as a reply to a message."""
    msg.reply(
        " ",
        embeds=[embed(title, description, color, fields, footer)]
    )

def dm(bot, user_id, message):
    """Open a DM and send a message."""
    try:
        channel_id = bot.dm(user_id)
        bot.send(channel_id, str(message))
        return True

    except Exception as e:
        log_error(f"Failed to DM user {user_id}: {e}")
        return False

def require_owner(bot, msg):
    """Return True if the server owner is running the command."""
    if not is_server_owner(bot, msg):
        msg.reply("❌ Only the server owner can use this command.")
        return False
    return True

def get_target(bot, msg):
    """Extract a target user ID from the first command argument."""
    import re

    args = _args(msg)

    if not args:
        return None

    target = args[0]

    # Support mentions such as <@123456> and <@!123456>
    match = re.fullmatch(r"<@!?([^<>]+)>", target)

    if match:
        return match.group(1)

    # Otherwise, assume the argument is a raw user ID
    return target


def _get_name(data, *keys):
    """Find the first available name field in an API response."""
    if not data:
        return None

    for key in keys:
        value = data.get(key)

        if value and isinstance(value, str):
            return value

    return None


def format_name(name, item_id=None, show_id=False):
    """Format a name, optionally displaying its ID alongside it."""
    name = str(name or "Unknown")

    if show_id and item_id:
        return f"{name} ({item_id})"

    return name


def get_server_name(bot, server_id):
    """Resolve a server ID to its name."""
    try:
        server = bot.server(server_id)
        return _get_name(server, "name") or str(server_id)
    except Exception:
        return str(server_id)


def get_user_name(bot, user_id):
    """Resolve a user ID to their username."""
    try:
        user = bot.user(user_id)
        return _get_name(
            user, "username", "display_name", "name"
        ) or str(user_id)
    except Exception:
        return str(user_id)


def get_role_name(bot, server_id, role_id):
    """Resolve a role ID to its name."""
    try:
        for role in bot.roles(server_id):
            if str(role.get("id")) == str(role_id):
                return _get_name(role, "name") or str(role_id)

        return str(role_id)
    except Exception:
        return str(role_id)


def server_label(bot, server_id, show_id=False):
    """Return a readable server name, optionally with its ID."""
    name = get_server_name(bot, server_id)
    return format_name(name, server_id, show_id)


def user_label(bot, user_id, show_id=False):
    """Return a readable username, optionally with its ID."""
    name = get_user_name(bot, user_id)
    return format_name(name, user_id, show_id)


def role_label(bot, server_id, role_id, show_id=False):
    """Return a readable role name, optionally with its ID."""
    name = get_role_name(bot, server_id, role_id)
    return format_name(name, role_id, show_id)

def success_embed(msg, title, description=None):
    """Send a standard green success embed."""
    send_embed(
        msg,
        title=f"✅ {title}",
        description=description,
        color=0x57F287
    )

def error_embed(msg, title, description=None):
    """Send a standard red error embed."""
    send_embed(
        msg,
        title=f"❌ {title}",
        description=description,
        color=0xED4245
    )



# ==================================================
# COOLDOWNS
# ==================================================

_cooldowns = {}


def cooldown(user_id, command, seconds=5):
    """Return remaining cooldown seconds, or 0 if ready."""
    now = time.monotonic()

    if seconds < 0:
        raise ValueError("Cooldown duration cannot be negative")

    key = (str(user_id), str(command))
    expires = _cooldowns.get(key, 0)

    if now < expires:
        return round(expires - now, 1)

    _cooldowns[key] = now + seconds

    # Remove expired cooldowns to prevent unlimited dictionary growth
    if len(_cooldowns) > 1000:
        _cleanup_cooldowns(now)

    return 0


def _cleanup_cooldowns(now):
    """Remove expired cooldown entries."""
    expired = [
        key for key, expires in _cooldowns.items()
        if expires <= now
    ]

    for key in expired:
        del _cooldowns[key]

# GENERAL UTILITIES

def _positive(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('Expected a positive integer')


def chunk_list(items, size):
    """Return lists of at most size items from an iterable."""
    _positive(size)
    result, chunk = [], []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            result.append(chunk)
            chunk = []
    if chunk:
        result.append(chunk)
    return result


def paginate(items, page=1, per_page=10):
    """Return a 1-based page as a list; beyond the end returns []."""
    _positive(page)
    _positive(per_page)
    start = (page - 1) * per_page
    return list(items)[start:start + per_page]


def truncate(text, max_length=100, suffix='...'):
    """Shorten text, counting the suffix within max_length."""
    _positive(max_length)
    text = str(text)
    if len(text) <= max_length:
        return text
    if len(suffix) >= max_length:
        return suffix[:max_length]
    return text[:max_length - len(suffix)] + suffix


def slugify(text):
    """Make a lowercase ASCII slug; unsupported characters are discarded."""
    text = unicodedata.normalize('NFKD', str(text))
    text = text.encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


def split_message(text, max_length=2000):
    """Split text without losing characters; empty input returns []."""
    _positive(max_length)
    text = str(text)
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]


def unique(items):
    """Remove duplicates in order; items must be hashable."""
    return list(dict.fromkeys(items))


def get_nested(data, path, default=None):
    """Read dotted dict keys/list indices, or a sequence of literal keys."""
    for key in path.split('.') if isinstance(path, str) else path:
        if isinstance(data, dict):
            if key not in data:
                return default
            data = data[key]
        elif isinstance(data, (list, tuple)):
            try:
                index = int(key)
            except (TypeError, ValueError):
                return default
            if index < 0 or index >= len(data):
                return default
            data = data[index]
        else:
            return default
    return data


def clamp(value, minimum, maximum):
    """Constrain a comparable value to inclusive bounds."""
    if minimum > maximum:
        raise ValueError('minimum cannot exceed maximum')
    return max(minimum, min(value, maximum))


def env_bool(name, default=False):
    """Read true/false, yes/no, on/off or 1/0; reject other values."""
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {'true', 'yes', 'on', '1'}:
        return True
    if value in {'false', 'no', 'off', '0'}:
        return False
    raise ValueError(f'{name} must be a boolean')


def env_int(name, default=None):
    """Read an integer environment variable; missing values use default."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f'{name} must be an integer') from None


def load_json(path, default=None):
    """Load UTF-8 JSON; only missing files return default."""
    try:
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default


def save_json(path, data):
    """Atomically replace JSON, creating parents. Concurrent updates need locking."""
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def generate_token(nbytes=32):
    """Return a URL-safe secret; nbytes is random bytes, not output length."""
    _positive(nbytes)
    return secrets.token_urlsafe(nbytes)


def retry(attempts=3, delay=1.0, backoff=2.0, exceptions=(Exception,)):
    """Retry synchronous functions. attempts includes the initial call.

    Only use for operations safe to repeat. Async functions are rejected.
    """
    _positive(attempts)
    if not math.isfinite(delay) or delay < 0:
        raise ValueError('delay must be finite and nonnegative')
    if not math.isfinite(backoff) or backoff < 1:
        raise ValueError('backoff must be finite and at least 1')
    if isinstance(exceptions, type):
        exceptions = (exceptions,)
    if not isinstance(exceptions, tuple) or not exceptions or not all(
        isinstance(exc, type) and issubclass(exc, Exception) for exc in exceptions
    ):
        raise ValueError('exceptions must contain Exception subclasses')

    def decorate(function):
        if inspect.iscoroutinefunction(function) or inspect.isasyncgenfunction(function):
            raise TypeError('retry supports synchronous functions only')

        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            wait = delay
            for attempt in range(attempts):
                try:
                    return function(*args, **kwargs)
                except exceptions:
                    if attempt == attempts - 1:
                        raise
                    time.sleep(wait)
                    wait *= backoff
        return wrapped
    return decorate


# BOT HELPERS

def command_arguments(msg, minimum=0, maximum=None, usage=None):
    """Parse quoted msg.args; reply and return None for invalid input.

    An empty valid argument list returns [], so check the result with `is None`.
    """
    if minimum < 0 or (maximum is not None and maximum < minimum):
        raise ValueError('Invalid argument bounds')
    try:
        raw = getattr(msg, 'args', '') or ''
        args = shlex.split(raw) if isinstance(raw, str) else list(raw)
    except ValueError:
        msg.reply('Unclosed quote in arguments.' + (f' Usage: {usage}' if usage else ''))
        return None
    if len(args) < minimum or (maximum is not None and len(args) > maximum):
        msg.reply(f'Usage: {usage}' if usage else f'Expected at least {minimum} arguments.'
                  + (f' At most {maximum} allowed.' if maximum is not None else ''))
        return None
    return args


def reply_long(msg, text, max_length=2000):
    """Reply in bounded chunks and return the SDK responses."""
    return [msg.reply(part) for part in split_message(text, max_length)]


def has_role(bot, server_id, user_id, role_id):
    """Check role IDs returned by bot.member; API failures propagate."""
    return str(role_id) in member_role_ids(bot.member(server_id, user_id))


def command_guard(bot, *, server_only=False, owner_only=False, roles=(),
                  cooldown=0, scope='user'):
    """Guard a command with server/owner/any-role checks and a cooldown.

    Place below @bot.command. owner_only means server owner. All checks must
    pass before a cooldown is consumed. API failures propagate and deny execution.
    Cooldowns are per decorated function, scoped to user+server, server, or channel.
    """
    if not math.isfinite(cooldown) or cooldown < 0:
        raise ValueError('cooldown must be finite and nonnegative')
    if scope not in {'user', 'server', 'channel'}:
        raise ValueError('scope must be user, server, or channel')
    roles = tuple(roles)

    def decorate(function):
        expires = {}

        @wraps(function)
        def wrapped(msg, *args, **kwargs):
            server_id = getattr(msg, 'server_id', None)
            if (server_only or owner_only or roles or scope == 'server') and not server_id:
                msg.reply('This command only works in a server.')
                return None
            if owner_only:
                owner = bot.server(server_id).get('owner_id')
                if owner is None or str(owner) != str(msg.author_id):
                    msg.reply('Only the server owner can use this command.')
                    return None
            if roles and not any(has_role(bot, server_id, msg.author_id, role) for role in roles):
                msg.reply('You do not have a required role for this command.')
                return None
            if cooldown:
                if scope == 'user':
                    key = (str(server_id), str(msg.author_id))
                elif scope == 'server':
                    key = str(server_id)
                else:
                    key = str(msg.channel_id)
                now = time.monotonic()
                remaining = expires.get(key, 0) - now
                if remaining > 0:
                    msg.reply(f'Try again in {math.ceil(remaining)} seconds.')
                    return None
                for old in [k for k, until in expires.items() if until <= now]:
                    del expires[old]
                expires[key] = now + cooldown
            return function(msg, *args, **kwargs)
        return wrapped
    return decorate


def toggle_role(bot, server_id, user_id, role_id):
    """Add a missing role or remove an existing one; return True if added.

    Call only after checking the caller's authority to manage the chosen role.
    """
    if has_role(bot, server_id, user_id, role_id):
        bot.remove_role(server_id, user_id, role_id)
        return False
    bot.add_role(server_id, user_id, role_id)
    return True


def install_welcome(bot, channel_id, *, server_id, role_id=None,
                    template='Welcome {mention} to {server_name}!'):
    """Register a member_join listener for one server and return the handler.

    Fields: mention, username, user_id, server_name, server_id. channel_id can
    instead be a callable(event) returning a channel ID. Role/API failures
    propagate to the SDK error handler; messages are sent after role assignment.
    """
    def welcome(event):
        if str(event.server_id) != str(server_id):
            return
        user_id = event.user_id
        content = template.format(
            mention=f'<@{user_id}>', username=event.username or str(user_id),
            user_id=user_id, server_name=bot.server(server_id).get('name', str(server_id)),
            server_id=server_id,
        )
        target = channel_id(event) if callable(channel_id) else channel_id
        if not target:
            raise ValueError('Welcome channel is required')
        if role_id is not None:
            bot.add_role(server_id, user_id, role_id)
        return bot.send(target, content)

    bot.on('member_join', welcome)
    return welcome


def register_help(bot, name='help', title='Bot commands', *, hidden=()):
    """Register help generated from the SDK command registry at call time.

    hidden affects display only; command guards still enforce access separately.
    """
    hidden = set(hidden)

    def help_command(msg):
        lines = [title]
        for command, entry in sorted(bot.commands.items()):
            if command not in hidden:
                lines.append(f'/{command} - {entry.get("description") or "No description"}')
        return reply_long(msg, '\n'.join(lines))

    bot.command(name, 'Show available commands')(help_command)
    return help_command


class ButtonPaginator:
    """Send text pages with Previous/Next buttons and owner-only navigation.

    Create one instance per bot. Sessions are in memory, expire after timeout,
    and are capped by max_sessions. Expired clicks receive an ephemeral reply.
    One handler is registered; no background threads or timers are started.
    """

    def __init__(self, bot, *, timeout=120, max_sessions=100, prefix=None):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be positive and finite')
        if isinstance(max_sessions, bool) or not isinstance(max_sessions, int) or max_sessions < 1:
            raise ValueError('max_sessions must be a positive integer')
        self.bot = bot
        self.timeout = timeout
        self.max_sessions = max_sessions
        self.prefix = prefix or f'ezy-pages:{secrets.token_hex(6)}:'
        self._sessions = {}
        bot.button(self.prefix)(self._handle)

    def _cleanup(self):
        now = time.monotonic()
        for token in [key for key, session in self._sessions.items() if session['expires'] <= now]:
            del self._sessions[token]

    def _components(self, token, index, total):
        return [{'type': 'row', 'components': [
            {'type': 'button', 'style': 'secondary', 'label': 'Previous',
             'custom_id': f'{self.prefix}{token}:prev', 'disabled': index == 0},
            {'type': 'button', 'style': 'secondary', 'label': 'Next',
             'custom_id': f'{self.prefix}{token}:next', 'disabled': index == total - 1},
        ]}]

    @staticmethod
    def _content(pages, index):
        return f'{pages[index]}\n\nPage {index + 1}/{len(pages)}'

    def send(self, msg, pages):
        """Reply with nonempty text pages; return the sent SDK message.

        Keep each page within your platform's message limit, including footer.
        """
        if isinstance(pages, str):
            raise ValueError('pages must be an iterable of strings, not one string')
        pages = list(pages)
        if not pages or not all(isinstance(page, str) and page for page in pages):
            raise ValueError('Provide at least one nonempty text page')
        self._cleanup()
        if len(pages) == 1:
            return msg.reply(self._content(pages, 0))
        if len(self._sessions) >= self.max_sessions:
            raise RuntimeError('Too many active pagination sessions')
        token = secrets.token_hex(8)
        self._sessions[token] = {'pages': pages, 'index': 0, 'owner': str(msg.author_id),
                                 'expires': time.monotonic() + self.timeout}
        try:
            return msg.reply(self._content(pages, 0), components=self._components(token, 0, len(pages)))
        except Exception:
            self._sessions.pop(token, None)
            raise

    def _handle(self, interaction):
        self._cleanup()
        custom_id = str(interaction.custom_id or '')
        token, separator, action = custom_id[len(self.prefix):].rpartition(':')
        session = self._sessions.get(token)
        if not separator or action not in {'prev', 'next'} or session is None:
            return interaction.ephemeral('These pages have expired. Run the command again.')
        if str(interaction.user_id) != session['owner']:
            return interaction.ephemeral('Only the person who opened these pages can change them.')
        index = max(0, min(session['index'] + (1 if action == 'next' else -1), len(session['pages']) - 1))
        result = interaction.update(content=self._content(session['pages'], index),
                                    components=self._components(token, index, len(session['pages'])))
        session['index'] = index
        return result


# ==================================================
# MEMBER, ROLE, CHANNEL AND MESSAGE WORKFLOWS
# ==================================================

def resolve_member(bot, server_id, target):
    """Fetch a member by raw ID or <@ID>/<@!ID> mention.

    Return None for empty input or HTTP 404. Permission/network errors propagate.
    Usernames are not searched; use a stable ID or mention.
    """
    target = str(target).strip() if target is not None else ''
    match = re.fullmatch(r'<@!?([^<>\s]+)>', target)
    if match:
        target = match.group(1)
    elif not target or re.search(r'[<>\s]', target):
        return None
    try:
        return bot.member(server_id, target)
    except Exception as exc:
        if getattr(exc, 'status', None) == 404:
            return None
        raise


def _find_server_item(items, query, mention_pattern):
    query = str(query).strip() if query is not None else ''
    if not query:
        return None
    match = re.fullmatch(mention_pattern, query)
    item_id = match.group(1) if match else query
    for item in items:
        if str(item.get('id')) == item_id:
            return item
    # Mentions only match IDs; duplicate names must be disambiguated by ID.
    if match:
        return None
    matches = [item for item in items if str(item.get('name', '')).casefold() == query.casefold()]
    if len(matches) > 1:
        raise ValueError('Multiple matches; use an ID or mention instead')
    return matches[0] if matches else None


def find_role(bot, server_id, query):
    """Find a role by ID, <@&ID> mention, or exact case-insensitive name.

    Returns its SDK dictionary or None. Duplicate names raise ValueError.
    """
    return _find_server_item(bot.roles(server_id), query, r'<@&([^<>\s]+)>')


def find_channel(bot, server_id, query, *, channel_type=None):
    """Find a channel by ID, <#ID> mention, or exact name (optional type filter).

    Returns its SDK dictionary or None. Duplicate names raise ValueError.
    """
    channels = bot.channels(server_id) if channel_type is None else bot.channels(server_id, type=channel_type)
    return _find_server_item(channels, query, r'<#([^<>\s]+)>')


def member_role_ids(member):
    """Normalize a member's role_ids/roles list to distinct string IDs.

    Accepts IDs or role dictionaries; malformed entries raise ValueError.
    """
    roles = member.get('role_ids', member.get('roles', [])) or []
    result = []
    for role in roles:
        role_id = role.get('id') if isinstance(role, dict) else role
        if role_id is None or not str(role_id).strip():
            raise ValueError('Member role has no ID')
        result.append(str(role_id))
    return unique(result)


def require_roles(bot, msg, role_ids, *, match_all=False, message=None):
    """Return access decision, replying on denial; does not register a command.

    Require any listed role by default, or all with match_all=True. Owner access
    is not implicit. API failures propagate. Empty required roles are rejected.
    """
    if isinstance(role_ids, (str, bytes)):
        raise ValueError('Pass a collection of role IDs, not one string')
    required = {str(role_id) for role_id in role_ids}
    if not required:
        raise ValueError('At least one required role is needed')
    if not getattr(msg, 'server_id', None):
        msg.reply('This command only works in a server.')
        return False
    actual = set(member_role_ids(bot.member(msg.server_id, msg.author_id)))
    allowed = required <= actual if match_all else bool(required & actual)
    if not allowed:
        msg.reply(message or 'You do not have the required roles for this command.')
    return allowed


def update_roles(bot, server_id, user_id, *, add=(), remove=()):
    """Apply only necessary role additions/removals after one membership lookup.

    Return {'added': [...], 'removed': [...]}. Unrelated roles are preserved.
    Conflicting requests raise before API calls. Removals happen first. This is
    not a transaction: an API failure propagates and earlier changes remain.
    Caller is responsible for deciding who may change which roles.
    """
    if isinstance(add, (str, bytes)) or isinstance(remove, (str, bytes)):
        raise ValueError('Pass collections of role IDs, not strings')
    add, remove = unique(str(role) for role in add), unique(str(role) for role in remove)
    if set(add) & set(remove):
        raise ValueError('Cannot add and remove the same role')
    if not add and not remove:
        return {'added': [], 'removed': []}
    current = set(member_role_ids(bot.member(server_id, user_id)))
    removed = [role for role in remove if role in current]
    added = [role for role in add if role not in current]
    for role in removed:
        bot.remove_role(server_id, user_id, role)
    for role in added:
        bot.add_role(server_id, user_id, role)
    return {'added': added, 'removed': removed}


def render_message(template, **values):
    """Replace literal {name} placeholders; leave unknown braces untouched.

    No attribute evaluation, formatting expressions, or recursive substitutions.
    Useful for welcome/leave templates inside your own event handlers. Values
    are inserted as supplied; mentions and Markdown remain active.
    """
    return re.sub(r'\{([A-Za-z_][A-Za-z0-9_]*)\}',
                  lambda match: str(values[match.group(1)]) if match.group(1) in values else match.group(0),
                  str(template))



# ==================================================
# VOICE SHORTCUTS (Yapper SDK)
# ==================================================

def _voice_id(value, label):
    if value is None or isinstance(value, bool) or not str(value).strip():
        raise ValueError(f'{label} must be a non-empty ID')
    return str(value).strip()


def voice_channels(bot, server_id):
    """Return the SDK voice snapshot, including visible empty channels."""
    return bot.voice(_voice_id(server_id, 'server_id'))


def voice_members(bot, server_id, channel_id):
    """Return distinct member IDs in a channel; empty if absent from snapshot."""
    channel_id = _voice_id(channel_id, 'channel_id')
    return unique(str(user) for channel in voice_channels(bot, server_id)
                  if str(channel['channel_id']) == channel_id
                  for user in channel.get('user_ids', []))


def member_voice_channel(bot, server_id, user_id):
    """Return the member's current voice channel ID, or None."""
    user_id = _voice_id(user_id, 'user_id')
    for channel in voice_channels(bot, server_id):
        if user_id in {str(user) for user in channel.get('user_ids', [])}:
            return str(channel['channel_id'])
    return None


def is_in_voice(bot, server_id, user_id, channel_id=None):
    """Check membership in any voice channel, or a specified channel."""
    if channel_id is not None:
        channel_id = _voice_id(channel_id, 'channel_id')
    current = member_voice_channel(bot, server_id, user_id)
    return current is not None and (channel_id is None or current == channel_id)


def voice_member_count(bot, server_id, channel_id):
    """Count distinct users in a voice channel."""
    return len(voice_members(bot, server_id, channel_id))


def move_member(bot, server_id, user_id, channel_id):
    """Move a member already in voice; requires SDK/server permission.

    This cannot force an offline member to join. API errors propagate.
    Caller must authorise the command user before invoking this helper.
    """
    return bot.move_member(_voice_id(server_id, 'server_id'),
                           _voice_id(user_id, 'user_id'),
                           _voice_id(channel_id, 'channel_id'))


def disconnect_member(bot, server_id, user_id):
    """Disconnect a voice member. Caller authorises access; API errors propagate."""
    return bot.disconnect_member(_voice_id(server_id, 'server_id'),
                                 _voice_id(user_id, 'user_id'))


def join_voice(bot, server_id, channel_id):
    """Request a bot voice ticket; this alone does not connect audio.

    Treat the returned ticket as a secret. For audio use await connect_voice.
    """
    return bot.join_voice(_voice_id(server_id, 'server_id'),
                          _voice_id(channel_id, 'channel_id'))


def leave_voice(bot, server_id):
    """Remove the bot from voice. Close any active audio call separately."""
    return bot.leave_voice(_voice_id(server_id, 'server_id'))


async def connect_voice(bot, server_id, channel_id, *, sample_rate=48000, channels=2):
    """Connect audio via the SDK; returns its VoiceCall, not an audio player.

    Requires the SDK's optional livekit and cryptography dependencies.
    Release the returned call with await call.leave() when finished.
    """
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError('sample_rate must be a positive integer')
    if isinstance(channels, bool) or channels not in (1, 2):
        raise ValueError('channels must be 1 or 2')
    return await bot.connect_voice(_voice_id(server_id, 'server_id'),
                                   _voice_id(channel_id, 'channel_id'),
                                   sample_rate=sample_rate, channels=channels)


def _voice_targets(user_ids):
    if isinstance(user_ids, (str, bytes)):
        raise ValueError('Pass a collection of user IDs, not a string')
    return unique(_voice_id(user, 'user_id') for user in user_ids)


def move_members(bot, server_id, user_ids, channel_id):
    """Move distinct members sequentially, returning completed user IDs.

    Stops on first API failure; previous moves remain applied. No retries,
    rollback, permission bypass, or rate-limit bypass. Keep batches within
    the platform's limits. All input IDs are validated before any moves.
    """
    server_id = _voice_id(server_id, 'server_id')
    channel_id = _voice_id(channel_id, 'channel_id')
    targets = _voice_targets(user_ids)
    for user_id in targets:
        move_member(bot, server_id, user_id, channel_id)
    return targets


def disconnect_members(bot, server_id, user_ids):
    """Disconnect distinct members sequentially; stop on first API error.

    Earlier disconnections remain applied. Validate all IDs before starting.
    Caller must authorise this operation and respect platform rate limits.
    """
    server_id = _voice_id(server_id, 'server_id')
    targets = _voice_targets(user_ids)
    for user_id in targets:
        disconnect_member(bot, server_id, user_id)
    return targets


# Keep implementation in this file; package __init__.py only re-exports it.
__all__ = [
    name for name, value in list(globals().items())
    if not name.startswith('_') and callable(value)
    and getattr(value, '__module__', None) == __name__
]


