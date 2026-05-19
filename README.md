# dcli

a tiny python cli that signs into discord as a user, watches channels, and POSTs every new/edited/deleted message (plus downloaded image attachments) to a local webhook.

useful when you want some other process to react to discord activity. point the webhook at whatever you want — a bot, a script, an editor, doesn't matter.

> selfbots violate discord ToS. your account can get banned. your call.

## install

```
pip install -e ".[dev]"
cp .env.example .env   # fill in DISCORD_TOKEN and WEBHOOK_URL
```

grab your token from the discord web client: devtools → network → any request → `Authorization` header.

## commands

```
dcli listen <channel_id> [<channel_id> ...]   # poll loop, posts events to webhook
dcli fetch  <channel_id> [--limit 50] [--json]
dcli send   <channel_id> <message>             # use '-' to read stdin
dcli channels [--guild GUILD_ID]               # list guilds + text channels
dcli dms                                       # list active DM channels
```

`listen` keeps a rolling window of recent message ids per channel in `.dcli-state.json` and diffs each poll cycle. detects:

* `message.create` — new message
* `message.update` — content changed
* `message.delete` — gone, with a single confirm-fetch on ambiguous cases

attachments get downloaded to `./attachments/{message_id}/{filename}`. payload includes both the absolute local path and the original cdn url.

## webhook payload

```json
{
  "event": "message.create",
  "channel_id": "1421689373786898543",
  "guild_id": null,
  "message": {
    "id": "...",
    "author": {"id": "...", "username": "...", "global_name": "..."},
    "content": "...",
    "timestamp": "2026-05-19T...",
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

`message.update` is identical shape with the new content.
`message.delete` is `{event, channel_id, message_id, last_known_content}`.

if the webhook is down, failed deliveries get buffered to `.dcli-failed-deliveries.jsonl` so nothing is silently dropped.

## flags worth knowing

```
--interval 3              # poll cadence (seconds)
--window 50               # rolling window per channel
--no-download             # skip attachment download, url only
--webhook URL             # override WEBHOOK_URL env
--state-file PATH         # override .dcli-state.json
```

## openclaw bridge

a ready-made integration lives in `examples/openclaw_bridge.py`. it receives dcli webhooks and pipes each create/update event into `openclaw agent --message ...`.

```
# terminal 1: bridge
python examples/openclaw_bridge.py

# terminal 2: dcli listening on a channel, posting to the bridge
dcli listen 1421689373786898543
```

env knobs for the bridge:

```
BRIDGE_PORT=8787          # default
OPENCLAW_AGENT=main       # which agent to invoke
OPENCLAW_DELIVER=1        # add --deliver so openclaw also sends a reply back
OPENCLAW_BIN=openclaw     # binary path
```

## smoke test

terminal one — a webhook receiver that just prints what it gets:

```
python -c "
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('content-length', 0))
        print(self.rfile.read(n).decode())
        self.send_response(204); self.end_headers()
HTTPServer(('127.0.0.1', 8787), H).serve_forever()
"
```

terminal two:

```
dcli channels                       # find a channel id
dcli fetch <channel_id> --limit 5   # confirm token works
dcli listen <channel_id>            # post in discord, watch it appear
```

post a message, edit it, delete it. drop an image in. each action shows up as a json line on the receiver.

## tests

```
pytest -q
```

35 unit tests, no live discord calls. the diff algorithm is a pure function (`dcli.listener.diff_window`) so the trickiest logic gets hammered with synthetic inputs.
