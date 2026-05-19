"""
openclaw_bridge — receive dcli webhooks, forward each message to `openclaw agent`.

env vars:
  BRIDGE_HOST       default 127.0.0.1
  BRIDGE_PORT       default 8787
  OPENCLAW_AGENT    default 'main'
  OPENCLAW_DELIVER  '1' to add --deliver, default off (just runs the agent turn)
  OPENCLAW_BIN      path to openclaw binary, default 'openclaw'

run:
  python examples/openclaw_bridge.py
"""
import json
import logging
import os
import shlex
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s bridge: %(message)s",
)
log = logging.getLogger("bridge")

HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("BRIDGE_PORT", "8787"))
AGENT = os.environ.get("OPENCLAW_AGENT", "main")
DELIVER = os.environ.get("OPENCLAW_DELIVER", "0") == "1"
OPENCLAW = os.environ.get("OPENCLAW_BIN", "openclaw")


def format_message(payload: dict) -> str:
    msg = payload["message"]
    author = msg["author"].get("global_name") or msg["author"]["username"]
    channel = payload["channel_id"]
    content = msg.get("content") or "(no text)"
    parts = [
        f"discord message in channel {channel}",
        f"from {author}: {content}",
    ]
    atts = payload.get("attachments") or []
    if atts:
        for a in atts:
            ct = a.get("content_type") or "unknown"
            lp = a.get("local_path") or "(not downloaded)"
            parts.append(f"attachment: {a.get('filename')} ({ct}) -> {lp}")
    return "\n".join(parts)


def fire_openclaw(text: str) -> None:
    cmd = [OPENCLAW, "agent", "--agent", AGENT, "--message", text]
    if DELIVER:
        cmd.append("--deliver")
    log.info("spawning: %s", " ".join(shlex.quote(c) for c in cmd))
    # fire-and-forget so the webhook responds fast
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a, **_k):
        pass

    def do_POST(self):
        try:
            n = int(self.headers.get("content-length", 0))
            body = self.rfile.read(n).decode("utf-8")
            payload = json.loads(body)
        except Exception as e:
            log.warning("bad payload: %s", e)
            self.send_response(400)
            self.end_headers()
            return

        event = payload.get("event")
        if event in ("message.create", "message.update"):
            try:
                text = format_message(payload)
                log.info("[%s] %s", event, text.replace("\n", " | "))
                fire_openclaw(text)
            except Exception as e:
                log.exception("failed handling %s: %s", event, e)
        elif event == "message.delete":
            log.info("[message.delete] channel=%s id=%s",
                     payload.get("channel_id"), payload.get("message_id"))
        else:
            log.warning("unknown event: %s", event)

        self.send_response(204)
        self.end_headers()


def main() -> None:
    log.info("listening on http://%s:%d  (agent=%s, deliver=%s)", HOST, PORT, AGENT, DELIVER)
    HTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
