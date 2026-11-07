# Ezytools

Build Yapper bots faster with reusable Python utilities for repetitive bot code.
Keep your command handlers and application logic; use Ezytools for argument
parsing, validation, moderation, role checks, embeds, and other common tasks.

Install with `python -m pip install .`. The package exports helpers from
`core.py` and `features.py`. Copying only `core.py` provides the older helpers;
install the package to use all 0.4.0 features.

## What's new

**0.4.0:** typed positional arguments, extended role and permission checks,
persistent server settings and moderation cases, interaction checks and explicit
acknowledgements, and structured error categories. Additional conveniences include
argument ranges/choices, resetting settings, and filtered, paginated case history.
Existing helpers retain their behavior, including `parse_duration` returning None
for invalid input. New typed parsing raises `ArgumentError` instead.

### 0.4.0 command building blocks

```python
import ezytools as e

store = e.ServerStore('bot.sqlite3', defaults={'prefix': '!'},
                    validators={'prefix': lambda value: isinstance(value, str) and bool(value)})

# Inside your own synchronous SDK command:
def warn_command(msg):
    if not e.has_any_role(bot, msg.server_id, msg.author_id, ['staff', 'admin']):
        return msg.reply('Staff only')
    try:
        values = e.parse_arguments(msg, [
            e.Argument('target', 'user'),
            e.Argument('reason', optional=True, default='No reason provided', rest=True),
        ])
    except e.ArgumentError as error:
        return msg.reply(str(error))
    case = store.record_case(msg.server_id, 'warn', msg.author_id,
                             values['target'], values['reason'])
    msg.reply(f"Recorded warning case #{case['case_id']}")

store.update_settings('server-id', prefix='?')
settings = store.settings('server-id')
history = store.list_cases('server-id', target='user-id', limit=10, offset=0)
# Call store.close() at application shutdown, or use it as a context manager.
```

`Argument` supports `str`, `int`, `float`, `bool`, `'user'`, `'channel'`, and
`'duration'` (seconds). Use `minimum`, `maximum`, and `choices` for validation.
Quoted phrases are preserved. Optional arguments follow required arguments;
only a final string argument may use `rest=True`. Defaults are already-typed
values. ID parsing validates syntax without fetching a member/channel.

`has_any_role`, `has_all_roles`, and `missing_roles` accept bot, server ID,
user ID, and a nonempty collection of role IDs. SDK failures propagate.
`is_server_owner(bot, msg)` remains available for an explicit ownership check.
`has_permissions(effective_permissions, ['kick'])` and `missing_permissions`
accept permission names or a mapping of names to literal booleans. Supply
effective permissions from your SDK; EzyTools does not guess permission flags
or treat an owner/admin role as an implicit bypass.

For button handlers, check ownership and expiry before handling an action:

```python
decision = e.check_interaction(interaction, owner_id, expires_at=unix_expiry)
if decision != 'allowed':
    e.acknowledge_interaction(interaction, 'Expired or owned by another user.')
else:
    e.acknowledge_interaction(interaction)  # SDK update(); acknowledge once
    # Perform your own action.
```

`check_interaction` returns `allowed`, `expired`, or `not_owner` without sending
anything. Acknowledgement calls SDK `ephemeral(content)` or `update()`; callers
track whether an interaction has already been acknowledged. For page navigation,
the existing `ButtonPaginator` manages ownership and expiry automatically.

`classify_error(error)` returns `ErrorInfo` with `category`, `status`,
`retry_after`, and the unchanged `original` exception. Categories include
invalid_request, unauthorized, forbidden, not_found, conflict, rate_limited,
server_error, timeout, network, and unknown. No automatic retries occur.

SQLite storage isolates servers and allocates case IDs per server. Cases contain
action, moderator, target, reason, and a UTC timestamp. Recording is explicit;
after a moderation API action succeeds, call `record_case` if desired. The API
action and database write are separate operations. Settings validators return
True for accepted values; invalid changes leave saved settings intact.
`reset_settings(server_id)` removes overrides. Use one store per thread, a local
database path with an existing parent directory, and back up the database as
needed. Settings and history survive restarts; paginator sessions do not.

**0.3.1 — documentation update:** voice documentation is now near the top,
with navigation links below. No runtime behavior changed from 0.3.0.

**Added in 0.3.0:** 12 voice helpers for moving/disconnecting members,
bulk actions, voice membership lookups, and bot voice connections.

```shell
python -m pip install --upgrade ezytools
```

## Documentation

- [Voice shortcuts and examples](#voice-shortcuts)
- [Member, role, and channel workflows](#workflows)
- [Bot-building helpers](#bot-building)
- [Developer utilities](#developer-utilities)
- [Moderation utilities](#moderation-utilities)
- [License](https://github.com/Adecode-23/ezytools/blob/main/LICENSE)

<a id="voice-shortcuts"></a>

## Voice shortcuts


Requires a Yapper SDK exposing `voice`, `move_member`, `disconnect_member`,
`join_voice`, `leave_voice`, and (for audio) `connect_voice`.
Existing utilities remain available. Implementations stay in `src/ezytools/core.py`.

```python
import ezytools as e

members = e.voice_members(bot, server_id, channel_id)
count = e.voice_member_count(bot, server_id, channel_id)
current = e.member_voice_channel(bot, server_id, user_id)  # ID or None
present = e.is_in_voice(bot, server_id, user_id)
snapshot = e.voice_channels(bot, server_id)

# Authorise the command user first (e.g. command_guard / require_roles).
e.move_member(bot, server_id, user_id, destination_channel_id)
e.disconnect_member(bot, server_id, user_id)
e.move_members(bot, server_id, [user_id, other_id], destination_channel_id)
e.disconnect_members(bot, server_id, [user_id, other_id])

# A ticket alone does not connect audio; do not log its secret fields.
ticket = e.join_voice(bot, server_id, channel_id)
e.leave_voice(bot, server_id)

# Inside an async function, with SDK audio dependencies installed:
call = await e.connect_voice(bot, server_id, channel_id)
try:
    pass  # Use the SDK call.source to supply audio frames.
finally:
    await call.leave()
```

Moving requires a member already connected to voice; helpers cannot force
someone to join a call. Server permissions and SDK errors still apply.
Bulk actions validate all IDs first and deduplicate them; execution stops at
the first failure, leaving earlier successful actions applied. Respect platform
rate limits; there are no automatic retries or background moderation actions.
Voice snapshots can change between lookup and action. Audio connections require
the Yapper SDK's optional `livekit` and `cryptography` dependencies.

<a id="workflows"></a>

## Faster workflows inside your handlers

You write the command, decide who can run it, handle missing data, and choose the
response. These helpers remove repetitive lookup and validation code.

```python
@bot.command("roleinfo", "Look up a server role")
def roleinfo(msg):
    if not msg.server_id:
        return msg.reply("Use this in a server.")
    role = ezytools.find_role(bot, msg.server_id, msg.args)
    if role is None:
        return msg.reply("Role not found. Use a name, ID, or mention.")
    msg.reply(f'{role["name"]}: {role["id"]}')
```

| Helper | Repetitive work removed |
|---|---|
| `resolve_member(bot, server_id, target)` | Parse a user mention/ID, fetch membership, distinguish missing members from API failures |
| `find_role(bot, server_id, query)` | Fetch roles and find an ID, role mention, or exact name |
| `find_channel(bot, server_id, query, channel_type=None)` | Fetch/filter channels and find an ID, channel mention, or exact name |
| `member_role_ids(member)` | Normalize role IDs/dictionaries and remove duplicates |
| `require_roles(bot, msg, role_ids, match_all=False, message=None)` | Check server context and roles, reply on denial, return your branching decision |
| `update_roles(bot, server_id, user_id, add=(), remove=())` | Fetch membership once, skip unnecessary changes, preserve unrelated roles |
| `render_message(template, **values)` | Replace literal placeholders while preserving unrelated braces |

For example, inside your own authorized command:

```python
if not ezytools.require_roles(bot, msg, [STAFF_ROLE_ID]):
    return
changes = ezytools.update_roles(bot, msg.server_id, target_id, add=[MEMBER_ROLE_ID], remove=[GUEST_ROLE_ID])
msg.reply(f'Added {len(changes["added"])} roles; removed {len(changes["removed"])}.')
```

Inside your own `member_join` or `member_leave` event handler:

```python
text = ezytools.render_message(template, user=f"<@{event.user_id}>", username=event.username)
bot.send(channel_id, text)
```

Lookups return SDK dictionaries or `None`. Role/channel names match exactly,
ignoring case; duplicate names raise `ValueError` so you can request an ID.
Member lookup accepts IDs or mentions, not usernames. Only a member lookup's
404 is treated as missing; permission/network errors propagate.

`require_roles` defaults to any listed role; use `match_all=True` to require all.
It does not automatically authorize owners. `update_roles` applies removals before
additions and returns the IDs actually changed. It is not transactional: earlier
changes remain if a later API call fails. Your handler must decide which callers,
targets, and roles are allowed. `render_message` does no recursive substitution
or expression evaluation; supplied mentions and Markdown stay active.

`get_arguments(msg)` now reads quoted `msg.args` before the SDK's space-split
`msg.argv`. For strict quote validation with usage feedback, use
`command_arguments(msg, ...)` instead.

<a id="bot-building"></a>

## Yapper bot-building helpers

These helpers use the synchronous Yapper SDK's command, event, member, role,
message, and interaction methods. They were checked against the `yapper.py`
SDK in this workspace; the live developer website could not be retrieved during
implementation. No extra runtime dependencies are added.

| Helper | Bot code it handles |
|---|---|
| `command_guard(bot, ...)` | Server-only commands, server-owner or any-role checks, and scoped cooldowns |
| `command_arguments(msg, ...)` | Quoted arguments, usage replies, and argument count validation |
| `reply_long(msg, text)` | Splitting and sending long replies |
| `has_role(bot, server_id, user_id, role_id)` | Checking member role IDs |
| `toggle_role(bot, server_id, user_id, role_id)` | Adding a missing role or removing an existing one |
| `install_welcome(bot, channel_id, server_id=..., ...)` | Server-specific welcome messages and optional autoroles |
| `register_help(bot, ...)` | Generating help from registered commands |
| `ButtonPaginator(bot)` | Sending pages with working Previous/Next buttons |

```python
import ezytools
import yapper

bot = yapper.Bot()  # reads YAPPER_BOT_TOKEN
pages = ezytools.ButtonPaginator(bot, timeout=120)

@bot.command("announce", "Post an announcement")
@ezytools.command_guard(bot, owner_only=True, cooldown=10)
def announce(msg):
    args = ezytools.command_arguments(
        msg, minimum=1, usage='/announce "your announcement"'
    )
    if args is None:
        return
    ezytools.reply_long(msg, " ".join(args))

@bot.command("guide", "Browse the guide")
@ezytools.command_guard(bot, cooldown=5)
def guide(msg):
    pages.send(msg, ["Getting started...", "Available features...", "Need help?..."])

ezytools.install_welcome(
    bot, "WELCOME_CHANNEL_ID", server_id="YOUR_SERVER_ID", role_id="MEMBER_ROLE_ID",
    template="Welcome {mention} to {server_name}!",
)
ezytools.register_help(bot)
bot.run()
```

Replace the example IDs with your IDs. The bot needs the platform permissions for
each action. `owner_only` means the **server owner**. Place `command_guard` below
`@bot.command`; `roles=["STAFF_ROLE_ID", "MOD_ROLE_ID"]` allows any listed role.
Cooldown `scope` can be `"user"` (per server and user), `"server"`, or `"channel"`.
Checks run before cooldowns are consumed, and API errors propagate to the SDK.
Guards apply to ordinary functions taking a message, not Cog instance methods.

`command_arguments` returns `None` after replying to invalid input; a valid empty
argument list returns `[]`. Role checks accept member `role_ids` or `roles` lists
of IDs or role dictionaries. `toggle_role` returns `True` when added and `False`
when removed. Check command access before allowing users to change roles.

Welcome fields are `{mention}`, `{username}`, `{user_id}`, `{server_name}`, and
`{server_id}`. Register one welcome listener per server. Role assignment happens
before sending the message; failures reach the SDK error handler.

Create one paginator per bot. Navigation belongs to the command author. Sessions
expire after a fixed timeout and are limited to 100 by default; old buttons then
reply with an expiry notice. Sessions and cooldowns reset on restart. Buttons stay
visible after expiry; no background timer edits messages. Keep page text, including
the page footer, within the platform's message limit. API errors propagate.

Help reads the command list when invoked, so later commands appear automatically.
`hidden=["internal"]` hides names from help only; guards enforce access.
See [the runnable example](examples/yapper_bot.py) for environment-based setup.

<a id="developer-utilities"></a>

## Developer utilities

Install the package from this checkout (Python 3.10+):

```bash
python -m pip install .
```

All existing bot helpers and the following utilities are available through
`import ezytools`. These additions require no third-party runtime dependencies.

| Function | Purpose |
|---|---|
| `chunk_list(items, size)` | Split an iterable into lists |
| `paginate(items, page=1, per_page=10)` | Select a page, starting at page 1 |
| `truncate(text, max_length=100, suffix="...")` | Shorten text within a character limit |
| `slugify(text)` | Make a lowercase ASCII slug |
| `split_message(text, max_length=2000)` | Split text without losing characters |
| `unique(items)` | Remove duplicate hashable items, preserving order |
| `get_nested(data, path, default=None)` | Read nested dictionaries and lists |
| `clamp(value, minimum, maximum)` | Keep a value within inclusive bounds |
| `env_bool(name, default=False)` | Read a boolean environment setting |
| `env_int(name, default=None)` | Read an integer environment setting |
| `load_json(path, default=None)` | Read JSON, using a default for missing files |
| `save_json(path, data)` | Atomically replace a JSON file, creating parents |
| `generate_token(nbytes=32)` | Generate a URL-safe secret token |
| `retry(attempts=3, delay=1.0, backoff=2.0, exceptions=(Exception,))` | Retry a synchronous function |

```python
import ezytools

settings = ezytools.load_json("data/settings.json", default={})
settings["debug"] = ezytools.env_bool("DEBUG", default=False)
ezytools.save_json("data/settings.json", settings)

name = ezytools.get_nested({"users": [{"name": "Ada"}]}, "users.0.name")
for part in ezytools.split_message("A long response...", max_length=1000):
    print(part)

@ezytools.retry(attempts=3, delay=0.2, exceptions=(ConnectionError,))
def fetch_status(client):
    return client.get_status()
```

Sizes and page numbers must be positive integers. Pagination materializes the
iterable, and pages past the end return an empty list. Text limits count Python
characters rather than encoded bytes; splitting does not preserve Markdown blocks.
Slug generation discards characters that cannot be converted to ASCII.
Nested paths may also be lists of literal keys, such as `["key.with.dots", 0]`.

Boolean settings accept `true/false`, `yes/no`, `on/off`, and `1/0`, ignoring case
and surrounding whitespace. Invalid environment values raise `ValueError`.
Malformed JSON and permission errors propagate; they do not return the default.
Atomic saving prevents partially written files, but concurrent read/modify/write
operations still need caller-side locking. Existing in-memory moderation warnings
are not automatically persisted by these helpers.

Token size specifies random bytes, not the resulting string length. Retries include
the initial call in `attempts`, wait only between failed attempts, and re-raise the
last exception. Retry only operations that are safe to repeat. Async functions are
not supported by this decorator.

Run the test suite from the project directory without installing:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Ezytools is a Python utility library designed to make bot development simpler by handling repetitive tasks in reusable functions. It currently includes moderation helpers built to work with the Yapper Python SDK.

Instead of writing the same command logic over and over, you can call an Ezytools function and let it handle argument parsing, basic validation, API calls, and user-facing responses.

## ✨ Features

- 🛡️ **Moderation commands** — kick, ban, unban, mute, and unmute users
- ⚠️ **Warning system** — warn users, view their warnings, and clear warnings
- 🧩 **Yapper SDK integration** — designed to work with your existing Yapper bot
- 💬 **Argument handling** — parses command arguments and supports quoted text where possible
- ⏱️ **Duration parsing** — supports minute, hour, and day formats for timeouts
- 🛠️ **Reusable functions** — keep your bot's main file cleaner and easier to maintain
- 🚨 **Error handling** — provides readable responses for common moderation errors

## 📦 Project Structure

Your project can be organised like this:

```text
your-project/
├── ezytools.py
├── yapper.py
└── ezybot.py
```

- `ezytools.py` contains the reusable utility functions
- `yapper.py` provides the Yapper Python SDK
- `ezybot.py` contains your bot's commands and main logic

## ⚙️ Requirements

- Python 3.10 or later recommended
- The Yapper Python SDK for Yapper-specific moderation helpers

Ezytools uses Python's standard library for its current functionality.

## 🚀 Installation

### 1. Download Ezytools

Clone this repository:

```bash
git clone YOUR_REPOSITORY_URL
```

Replace `YOUR_REPOSITORY_URL` with the actual URL of this repository.

### 2. Add it to your project

Place `ezytools.py` in the same directory as your bot file.

```text
your-project/
├── ezytools.py
├── yapper.py
└── ezybot.py
```

### 3. Import Ezytools

```python
import ezytools
```

<a id="moderation-utilities"></a>

## 🛡️ Moderation Utilities

Ezytools currently provides these moderation helpers:

| Function | Description |
|---|---|
| `ezytools.kick(bot, msg)` | Kicks a user from the server |
| `ezytools.ban(bot, msg)` | Bans a user |
| `ezytools.unban(bot, msg)` | Removes a user's ban |
| `ezytools.mute(bot, msg)` | Times out a user |
| `ezytools.unmute(bot, msg)` | Removes a user's timeout |
| `ezytools.warn(bot, msg)` | Records a warning for a user |
| `ezytools.warnings(bot, msg)` | Displays a user's recorded warnings |
| `ezytools.clearwarnings(bot, msg)` | Clears a user's recorded warnings |
| `ezytools.help_text()` | Returns a list of the moderation commands |

## 💻 Usage

Ezytools is designed to work with command handlers from the Yapper Python SDK.

### Example: Registering a Kick Command

```python
import ezytools

@bot.command("kick", "Kick a member")
def kick_command(msg):
    ezytools.kick(bot, msg)
```

### Example: Registering Moderation Commands

```python
import ezytools

@bot.command("kick", "Kick a member")
def kick_command(msg):
    ezytools.kick(bot, msg)

@bot.command("ban", "Ban a member")
def ban_command(msg):
    ezytools.ban(bot, msg)

@bot.command("unban", "Unban a user")
def unban_command(msg):
    ezytools.unban(bot, msg)

@bot.command("mute", "Timeout a member")
def mute_command(msg):
    ezytools.mute(bot, msg)

@bot.command("unmute", "Remove a member's timeout")
def unmute_command(msg):
    ezytools.unmute(bot, msg)

@bot.command("warn", "Warn a member")
def warn_command(msg):
    ezytools.warn(bot, msg)

@bot.command("warnings", "View a member's warnings")
def warnings_command(msg):
    ezytools.warnings(bot, msg)

@bot.command("clearwarnings", "Clear a member's warnings")
def clearwarnings_command(msg):
    ezytools.clearwarnings(bot, msg)
```

**Important:** This example assumes you have already created your Yapper `bot` instance. The bot must have the permissions required for each moderation action.

## ⏱️ Timeout Durations

The mute helper accepts durations in these formats:

| Format | Meaning |
|---|---|
| `10m` | 10 minutes |
| `2h` | 2 hours |
| `1d` | 1 day |
| `30` | 30 minutes |

The maximum supported duration is **28 days**.

Example command:

```text
/mute 123456789 30m Spamming
```

Replace the example user ID with the actual user's ID.

## ⚠️ Warning System

Warnings are currently stored **in memory**.

This means:
- Warnings can be viewed using the warnings helper
- Warnings can be cleared using the clearwarnings helper
- Warnings are separated by server and user
- **Warnings are lost when the bot restarts**

Persistent warning storage would require a database or file-based storage system.

## 🧰 Error Handling

Ezytools handles common errors returned by moderation requests, including:

- Missing permissions
- Users or bans that cannot be found
- Invalid requests
- Incorrect command arguments

The bot still needs the correct server permissions, and the Yapper SDK must be configured correctly.

## 🔒 Security

- Keep your bot token private
- Store sensitive configuration in environment variables
- Never commit tokens or passwords to GitHub
- Give your bot only the permissions it needs
- Test moderation commands in a safe test server before using them in a real community

## 🛠️ Troubleshooting

### Ezytools cannot be imported

Make sure `ezytools.py` is in the same directory as your bot file, or installed in a location Python can import from.

### Moderation commands fail

Check that:
- The bot is running and connected
- The bot has the required server permissions
- The user ID is correct
- The command is being used inside a server

### Timeout duration is rejected

Use a valid duration such as `10m`, `2h`, `1d`, or a number of minutes. The maximum is 28 days.

### Warnings disappear

Warnings are stored in memory, so restarting the bot clears them.

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome.

When contributing:
1. Keep functions reusable
2. Follow standard Python formatting conventions
3. Test changes before submitting them
4. Update the README when features or usage change

## 📄 License

Ezytools is distributed under the [Ezytools Proprietary License](LICENSE).
See that file for the terms governing use, modification, and redistribution.

## 📌 About

Ezytools is a developing Python utility library focused on making bot development cleaner, simpler, and more reusable.

**Current focus:** moderation helpers and Yapper SDK integration.

More utilities can be added as the library develops.




