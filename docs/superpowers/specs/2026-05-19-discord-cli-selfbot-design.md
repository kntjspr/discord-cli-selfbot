# Discord CLI Selfbot — Design

**Status**: Draft
**Date**: 2026-05-19
**Author**: xo (kntjspr26@gmail.com)

## Caveat

Discord's Terms of Service prohibit self-bots (automating user accounts). Running this can get the account flagged or banned. This is a personal tool; the risk is the operator's.

## Goal

A small Python CLI that signs in as a Discord user account, watches one or more channels, and forwards every new / edited / deleted message — including downloaded image attachments — to a local HTTP webhook so that `openclaw`, `claude code`, or any other local consumer can react to Discord activity.

## Non-goals (YAGNI)

- discord.py / discord.js wrappers — direct REST only
- WebSocket gateway support
- Typing indicators, reactions, presence, voice, threads, slash commands
- Multi-account / account switching
- Encrypted credential storage beyond `.env`
- Web UI / TUI dashboard
- Anti-fingerprinting (browser-like headers, jitter, etc.)

## Stack

- Python 3.10+
- `httpx` (sync, already in use)
- `click` for the CLI
- `python-dotenv` for config
- Standard library for everything else (`json`, `pathlib`, `time`, `signal`, `logging`)

## Project layout

```
discord-cli-selfbot/
├── .env                          # DISCORD_TOKEN=..., WEBHOOK_URL=...
├── .env.example                  # committed, no real values
├── .gitignore                    # .env, attachments/, .dcli-state.json, .dcli-failed-deliveries.jsonl
├── pyproject.toml                # installs `dcli` console_script
├── README.md                     # quickstart
├── dcli/
│   ├── __init__.py
│   ├── __main__.py               # python -m dcli -> cli.main
│   ├── cli.py                    # click commands: listen, fetch, send, channels, dms
│   ├── client.py                 # DiscordClient: thin REST wrapper over /api/v9
│   ├── listener.py               # poll loop + diff logic + state persistence
│   ├── notifier.py               # webhook POST + failed-delivery buffer
│   ├── attachments.py            # download to ./attachments/{message_id}/{filename}
│   └── state.py                  # load/save .dcli-state.json
├── attachments/                  # gitignored, populated at runtime
├── tests/                        # pytest, see Testing section
└── docs/superpowers/specs/2026-05-19-discord-cli-selfbot-design.md
```

## Commands

### `dcli listen <channel_id> [<channel_id> ...] [options]`

Long-running poll loop. Detects `message.create`, `message.update`, `message.delete` and POSTs each to the webhook.

Options:
- `--interval SECONDS` (default `3`) — poll cadence per channel
- `--window N` (default `50`) — rolling window of recent message IDs kept per channel for diffing
- `--webhook URL` — overrides `WEBHOOK_URL` env
- `--no-download` — skip attachment download; URL-only payload
- `--state-file PATH` (default `.dcli-state.json`)

Exits on SIGINT cleanly (flushes state).

### `dcli fetch <channel_id> [--limit N] [--json]`

One-shot fetch. Default `--limit 50`, max 100 per Discord. Pretty-prints by default; `--json` for machine consumption.

### `dcli send <channel_id> <message>`

Sends a single message. Reads from stdin if `<message>` is `-`.

### `dcli channels [--guild GUILD_ID]`

Lists guilds the user is in, with their text channels (id, name, guild_name). Filters to one guild if `--guild` supplied.

### `dcli dms`

Lists active DM channels with recipient info.

## Discord REST endpoints used

All under `https://discord.com/api/v9`. `Authorization: <user_token>` (no `Bot ` prefix).

| Purpose | Endpoint |
|---|---|
| List recent messages | `GET /channels/{cid}/messages?limit=100[&after={id}]` |
| Verify single message | `GET /channels/{cid}/messages/{mid}` (404 → deleted) |
| Send message | `POST /channels/{cid}/messages` `{"content": "..."}` |
| List guilds | `GET /users/@me/guilds` |
| List guild channels | `GET /guilds/{gid}/channels` |
| List DMs | `GET /users/@me/channels` |
| Current user | `GET /users/@me` (used for token validation on startup) |

## Listen loop — algorithm

State per channel (persisted to `.dcli-state.json`):
```json
{
  "channels": {
    "1421689373786898543": {
      "window": [
        {"id": "...", "edited_timestamp": null, "content_hash": "sha1..."}
      ]
    }
  }
}
```

**First run for a channel** (no prior state): fetch the window, seed state, emit nothing. No replay of history.

**Every subsequent cycle**, for each channel:

1. `GET /channels/{cid}/messages?limit={window}` (no `after` — we need the whole window to detect edits/deletes).
2. Build `current = {m.id: m for m in fetched}` (chronological order, newest last).
3. Build `state_ids = {entry.id: entry for entry in state.window}`.
4. **Creates**: ids in `current` not in `state_ids` → emit `message.create` (oldest first).
5. **Edits**: ids in both, but `edited_timestamp` differs OR `content_hash` differs → emit `message.update`.
6. **Deletes**: for each id in `state_ids` not in `current`:
   - **Case A — gap inside the window**: the missing id is between two ids that ARE in current (i.e. `min(current) < missing_id < max(current)`) → confirmed deleted, emit `message.delete`.
   - **Case B — fell off the bottom**: `missing_id < min(current)` AND `len(current) == window` → ambiguous (could have scrolled off). Verify with `GET /channels/{cid}/messages/{missing_id}`: 404 → emit `message.delete`; 200 → ignore (it just scrolled off naturally).
   - **Case C — past the top**: `missing_id > max(current)` → confirmed deleted (only possible if it was the newest and got removed), emit `message.delete`.
7. Replace state window with entries built from `current`. Discard any state entries not in `current` (they have either been emitted as deletes or scrolled off).
8. Persist state atomically (write `.dcli-state.json.tmp`, then rename), sleep `interval`.

`content_hash` is `sha1(content).hexdigest()` — small, deterministic, lets us detect edits even if Discord forgets to set `edited_timestamp` on certain edit types.

## Attachment handling

For each message with `attachments`:
- Create dir `./attachments/{message_id}/`
- For each attachment, download via `httpx.get(att.url)` and save as `{att.filename}`
- Sanitize filename (strip path separators, fallback to `attachment_{i}` if empty)
- Skip download if file already exists and size matches (idempotent on replay)
- On download failure: log, include `local_path: null, download_error: "..."` in payload — do not block the event

`--no-download` skips this entirely; `local_path` is omitted.

## Webhook payload contract

POST `application/json` to `WEBHOOK_URL` for every event.

### `message.create`
```json
{
  "event": "message.create",
  "channel_id": "1421689373786898543",
  "guild_id": null,
  "message": {
    "id": "...",
    "author": {"id": "...", "username": "...", "global_name": "..."},
    "content": "...",
    "timestamp": "2026-05-19T20:00:00.000000+00:00",
    "edited_timestamp": null,
    "referenced_message_id": null
  },
  "attachments": [
    {
      "filename": "screenshot.png",
      "url": "https://cdn.discordapp.com/...",
      "local_path": "/abs/path/attachments/.../screenshot.png",
      "content_type": "image/png",
      "size": 12345
    }
  ]
}
```

### `message.update`
Same shape as `create`, with `event: "message.update"` and `edited_timestamp` populated.

### `message.delete`
Minimal — Discord doesn't return content for deleted messages, so we send what we knew last:
```json
{
  "event": "message.delete",
  "channel_id": "...",
  "guild_id": null,
  "message_id": "...",
  "last_known_content": "..."
}
```

## Error handling

| Condition | Behavior |
|---|---|
| `401 Unauthorized` from Discord | Log fatal "token invalid/expired", exit 1 |
| `429 Too Many Requests` | Read `retry_after` from body, sleep that long, retry the same request |
| `5xx` from Discord | Exponential backoff (1s, 2s, 4s, 8s, cap 30s), retry up to 5 times, then log and continue |
| Network error (DNS, connection reset) | Same backoff as 5xx |
| Webhook POST fails (non-2xx, timeout, conn refused) | Append payload as one JSON line to `.dcli-failed-deliveries.jsonl`, log warning, continue. No retry loop — receiver-side replay tool is out of scope. |
| Attachment download fails | Log, set `local_path: null, download_error: "..."` in payload, keep going |
| State file corrupt on load | Log warning, treat as first run for affected channel |

## Config

`.env` (gitignored):
```
DISCORD_TOKEN=MTEy...
WEBHOOK_URL=http://localhost:8787/discord
```

`.env.example` (committed):
```
DISCORD_TOKEN=your_user_token_here
WEBHOOK_URL=http://localhost:8787/discord
```

CLI flags override env vars; env vars override defaults.

## Testing

- `tests/test_client.py` — mock httpx, assert each endpoint method builds correct URL/headers/body
- `tests/test_listener_diff.py` — feed synthetic message lists into the diff algorithm, assert correct create/update/delete events emitted (this is the highest-risk logic)
- `tests/test_state.py` — round-trip state save/load, corruption recovery
- `tests/test_notifier.py` — mock webhook, assert payload shape and failed-delivery buffering
- `tests/test_attachments.py` — mock download, assert sanitization and idempotency

No live Discord calls in tests.

## Open questions

None — all answered during brainstorming.
