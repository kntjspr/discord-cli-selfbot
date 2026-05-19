import json
import logging
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from dcli.client import DiscordAuthError, DiscordClient
from dcli.listener import Listener
from dcli.notifier import Notifier
from dcli.state import State


def _load_env() -> None:
    load_dotenv()


def _require_token() -> str:
    tok = os.environ.get("DISCORD_TOKEN")
    if not tok:
        click.echo("error: DISCORD_TOKEN not set (in env or .env)", err=True)
        sys.exit(2)
    return tok


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Debug logging.")
def main(verbose: bool):
    """dcli — Discord user-account CLI."""
    _load_env()
    _setup_logging(verbose)


@main.command()
@click.argument("channel_ids", nargs=-1, required=True)
@click.option("--interval", default=3.0, show_default=True, help="Poll interval (seconds).")
@click.option("--window", default=50, show_default=True, help="Rolling window size per channel.")
@click.option("--webhook", default=None, help="Webhook URL (overrides WEBHOOK_URL env).")
@click.option("--no-download", is_flag=True, help="Skip attachment download; URL-only payload.")
@click.option("--state-file", default=".dcli-state.json", show_default=True)
@click.option("--attachments-dir", default="attachments", show_default=True)
@click.option("--failures-file", default=".dcli-failed-deliveries.jsonl", show_default=True)
def listen(channel_ids, interval, window, webhook, no_download, state_file, attachments_dir, failures_file):
    """Watch CHANNEL_IDS and POST events to the webhook."""
    token = _require_token()
    webhook_url = webhook or os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        click.echo("error: --webhook or WEBHOOK_URL must be set", err=True)
        sys.exit(2)

    client = DiscordClient(token=token)
    notifier = Notifier(webhook_url=webhook_url, failures_path=Path(failures_file))
    state = State.load(Path(state_file))

    listener = Listener(
        client=client,
        notifier=notifier,
        state=state,
        channel_ids=list(channel_ids),
        interval=interval,
        window=window,
        attachments_dir=Path(attachments_dir),
        download=not no_download,
    )
    try:
        listener.run()
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()
        notifier.close()


@main.command()
@click.argument("channel_id")
@click.option("--limit", default=50, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def fetch(channel_id, limit, as_json):
    """One-shot fetch of last LIMIT messages."""
    token = _require_token()
    client = DiscordClient(token=token)
    try:
        msgs = client.get_messages(channel_id, limit=min(limit, 100))
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()
    if as_json:
        click.echo(json.dumps(list(reversed(msgs)), indent=2))
        return
    for m in reversed(msgs):
        author = m["author"].get("global_name") or m["author"]["username"]
        click.echo(f"{author}: {m.get('content', '')}")


@main.command()
@click.argument("channel_id")
@click.argument("message")
def send(channel_id, message):
    """Send MESSAGE to CHANNEL_ID. Pass '-' to read from stdin."""
    token = _require_token()
    if message == "-":
        message = sys.stdin.read()
    client = DiscordClient(token=token)
    try:
        result = client.send_message(channel_id, message)
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()
    click.echo(f"sent: id={result['id']}")


@main.command()
@click.option("--guild", default=None, help="Filter to one guild id.")
def channels(guild):
    """List guilds and their text channels."""
    token = _require_token()
    client = DiscordClient(token=token)
    try:
        guilds = client.list_guilds()
        if guild:
            guilds = [g for g in guilds if g["id"] == guild]
        for g in guilds:
            click.echo(f"[{g['id']}] {g['name']}")
            for ch in client.list_guild_channels(g["id"]):
                if ch.get("type") != 0:
                    continue
                click.echo(f"  {ch['id']}  #{ch['name']}")
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()


@main.command()
def dms():
    """List active DM channels."""
    token = _require_token()
    client = DiscordClient(token=token)
    try:
        for dm in client.list_dms():
            recipients = ", ".join(
                r.get("global_name") or r.get("username", "?")
                for r in dm.get("recipients", [])
            )
            click.echo(f"{dm['id']}  {recipients}")
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
