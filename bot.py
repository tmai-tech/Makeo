"""Makeo Discord bot: remote control over the job row. Never writes jobs.

    python bot.py

Buttons use custom_id=makeo:{job_id}:approve|reject. Clicks ACK first
(Discord 3s deadline), then POST /internal/jobs/{id}/discord-approve.
The bot does not call daily.py, does not watch .trigger, and does not
use newest_video().
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import discord
    from discord import app_commands
except ImportError:  # parse_custom_id is unit-tested without discord.py
    discord = None
    app_commands = None

HERE = Path(__file__).parent
API = os.environ.get("MAKEO_API", "http://127.0.0.1:8780")


def load_env():
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def parse_custom_id(cid: str) -> tuple[str, str] | None:
    # makeo:{job_id}:approve|reject
    parts = (cid or "").split(":")
    if len(parts) != 3 or parts[0] != "makeo":
        return None
    if parts[2] not in ("approve", "reject"):
        return None
    return parts[1], parts[2]


def notify_api(job_id: str, decision: str) -> tuple[bool, str]:
    url = f"{API}/internal/jobs/{job_id}/discord-approve"
    req = urllib.request.Request(
        url, data=b"{}", method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Makeo-Worker-Key": os.environ.get("MAKEO_WORKER_KEY", ""),
            "X-Makeo-Decision": decision,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, r.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return False, e.read().decode()[:200]
    except Exception as e:
        return False, str(e)


if discord is not None:
    class Bot(discord.Client):
        def __init__(self):
            super().__init__(intents=discord.Intents.default())
            self.tree = app_commands.CommandTree(self)

        async def setup_hook(self):
            await self.tree.sync()

        async def on_ready(self):
            print(f"logged in as {self.user} -- Makeo buttons live", flush=True)

        async def on_interaction(self, itx: discord.Interaction):
            if itx.type is not discord.InteractionType.component:
                return
            cid = itx.data.get("custom_id") if itx.data else None
            parsed = parse_custom_id(cid or "")
            if not parsed:
                return
            job_id, decision = parsed
            await itx.response.defer()
            ok, tail = await itx.client.loop.run_in_executor(
                None, notify_api, job_id, decision)
            ig = os.environ.get("IG_USERNAME") or "your brand"
            if ok:
                await itx.followup.send(
                    f"{'Approved — publishing' if decision == 'approve' else 'Rejected'}"
                    f" for @{ig}.")
            else:
                await itx.followup.send(f"API error:\n```\n{tail}\n```")

    bot = Bot()

    @bot.tree.command(name="status", description="Makeo bot is up")
    async def status(itx: discord.Interaction):
        await itx.response.send_message(
            "Makeo Discord is a remote control. Generate and approve in the app; "
            "buttons here call the same job row.", ephemeral=True)

    def approval_view(job_id: str) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(
            label="Approve & post", style=discord.ButtonStyle.success,
            custom_id=f"makeo:{job_id}:approve"))
        view.add_item(discord.ui.Button(
            label="Reject", style=discord.ButtonStyle.secondary,
            custom_id=f"makeo:{job_id}:reject"))
        return view
else:
    bot = None

    def approval_view(job_id: str):
        raise RuntimeError("discord.py is not installed")


def main():
    if discord is None:
        sys.exit("discord.py is not installed")
    load_env()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.exit("set DISCORD_BOT_TOKEN in .env")
    bot.run(token)


if __name__ == "__main__":
    main()
