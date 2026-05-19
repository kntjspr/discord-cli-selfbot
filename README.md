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
