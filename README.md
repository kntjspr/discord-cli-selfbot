# dcli — Discord CLI Selfbot

A small Python CLI that signs into a Discord user account, watches channels, and forwards every new/edited/deleted message (plus downloaded image attachments) to a local HTTP webhook. Designed to notify `claude code` / `openclaw` / any local listener about Discord activity.

> **Warning:** Discord's Terms of Service prohibit self-bots. Use at your own risk — your account can be flagged or banned.

## Install

    pip install -e ".[dev]"
    cp .env.example .env  # then fill in DISCORD_TOKEN and WEBHOOK_URL

## Commands

    dcli listen <channel_id> [<channel_id> ...]
    dcli fetch <channel_id> [--limit 50] [--json]
    dcli send <channel_id> <message>
    dcli channels [--guild GUILD_ID]
    dcli dms

See `docs/superpowers/specs/2026-05-19-discord-cli-selfbot-design.md` for the full design.

## Smoke test

In one terminal, run a trivial webhook receiver:

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

In another:

```
dcli channels                                    # find a channel id
dcli fetch <channel_id> --limit 5                # sanity check
dcli listen <channel_id>                         # post a message in Discord, watch it print
```

Post a message, edit it, delete it — each should produce a `message.create`, `message.update`, then `message.delete` JSON line on the receiver's stdout. Attach an image and `attachments/<msg_id>/<filename>` appears locally; the payload's `local_path` points at it.
