"""Discord bot: run the whole pipeline from chat, approve with a button.

    python bot.py

Commands (slash commands, type / in any channel the bot can see):
    /post              pick today's trend, generate, then ask for approval
    /post prompt:...   generate from your own Veo prompt instead
    /status            what the bot is doing, IG token lifetime

Needs DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID in .env -- see .env.example.

ponytail: replaces the cloudflared tunnel + local approval page entirely. The
bot uploads the mp4 straight into the channel (plays inline) and puts real
Approve/Reject buttons on it, so there is no public URL to die mid-wait -- which
already lost one approval click to a 502.

ponytail: one job at a time, guarded by a flag rather than a queue. This is a
daily pipeline; two concurrent Veo renders would just burn credits twice.
"""

import asyncio
import functools
import json
import os
import subprocess
import sys
from pathlib import Path

import discord
from discord import app_commands

HERE = Path(__file__).parent
MAX_UPLOAD = 8 * 1024 * 1024  # Discord's limit for unboosted servers

_busy = asyncio.Lock()


def load_env():
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def sh(*cmd, timeout=1800):
    """Run a pipeline step. Returns (ok, tail_of_output)."""
    r = subprocess.run([sys.executable, *[str(c) for c in cmd]],
                       cwd=str(HERE), capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace")
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode == 0, out[-1500:]


def newest_video(branded=True):
    pat = "flow-*-branded.mp4" if branded else "flow-*.mp4"
    vids = [p for p in (HERE / "out").glob(pat)
            if branded or not p.stem.endswith("-branded")]
    return max(vids, key=lambda p: p.stat().st_mtime) if vids else None


class Approval(discord.ui.View):
    """Approve/Reject buttons attached to the uploaded video."""

    # ponytail: timeout=None + custom_id on each button makes this a PERSISTENT
    # view. Without it, restarting the bot orphans every button already sitting
    # in the channel -- the click has no handler and Discord shows "This
    # interaction failed". The bot restarts on its own (crash loop, logon), so
    # non-persistent buttons are a guaranteed dead end.
    def __init__(self, video: Path = None, meta: dict = None):
        super().__init__(timeout=None)
        self.video = video or newest_video()
        self.meta = meta or {}

    @discord.ui.button(label="Approve & post", style=discord.ButtonStyle.success,
                       emoji="\N{WHITE HEAVY CHECK MARK}", custom_id="buzzit:approve")
    async def approve(self, itx: discord.Interaction, _b: discord.ui.Button):
        # ponytail: ack within Discord's 3-second interaction deadline, THEN do
        # the slow work. Publishing takes minutes (tunnel + Instagram fetching
        # and transcoding the video), so replying after it finishes shows the
        # user "This interaction failed" even when the post succeeds.
        for c in self.children:
            c.disabled = True
        await itx.response.edit_message(view=self)

        ch = itx.channel
        await ch.send("Publishing to Instagram -- this takes a couple of minutes...")

        ok, out = await asyncio.to_thread(
            functools.partial(sh, "post_instagram.py", "--video", self.video,
                              "--serve", timeout=900))
        if ok:
            link = next((w for w in out.split() if "instagram.com" in w), "")
            await ch.send(f"Posted to @buzzit_official. {link}".strip())
        else:
            await ch.send(f"Publish FAILED:\n```\n{out[-900:]}\n```")
        self.stop()

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.secondary,
                       emoji="\N{CROSS MARK}", custom_id="buzzit:reject")
    async def reject(self, itx: discord.Interaction, _b: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await itx.response.edit_message(view=self)
        await itx.channel.send("Rejected. Nothing posted; the file stays in out/.")
        self.stop()


async def generate_and_offer(dest, prompt=None, caption=None):
    """Generate a video and post it with approval buttons.

    `dest` is anything with .send() -- a TextChannel (scheduled run) or an
    Interaction.followup (/post). Caller holds _busy.
    """
    cmd = ["daily.py", "--skip-approve"]
    if prompt:
        cmd += ["--prompt", prompt]
        if caption:
            cmd += ["--caption", caption]

    ok, out = await asyncio.to_thread(functools.partial(sh, *cmd, timeout=2400))
    if not ok:
        await dest.send(f"Generation FAILED:\n```\n{out[-900:]}\n```")
        return

    video = newest_video()
    if not video:
        await dest.send("No video produced -- check the logs.")
        return

    sidecar = video.with_suffix(".json")
    meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
    size = video.stat().st_size

    body = (f"**{meta.get('topic', 'Video ready')}**\n"
            f"{meta.get('caption', '')}\n\n"
            f"Approve to post to @buzzit_official.")

    if size <= MAX_UPLOAD:
        await dest.send(body, file=discord.File(video), view=Approval(video, meta))
    else:
        # ponytail: too big to upload -- name the file rather than silently
        # dropping the preview. Approval still works.
        await dest.send(
            f"{body}\n(video is {size/1e6:.1f}MB, over Discord's limit -- "
            f"preview it at `out/{video.name}`)",
            view=Approval(video, meta))


class Bot(discord.Client):
    def __init__(self):
        # ponytail: default intents only. Slash commands and buttons need no
        # privileged intents, so there is nothing to enable in the portal.
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Re-register the persistent view so buttons from before a restart still
        # work. Falls back to the newest video, which is what they referred to.
        self.add_view(Approval())
        await self.tree.sync()
        self.loop.create_task(watch_trigger())

    async def on_ready(self):
        print(f"logged in as {self.user} -- /post is live", flush=True)


TRIGGER = HERE / ".trigger"


async def watch_trigger():
    """Run the pipeline when Task Scheduler drops a .trigger file.

    ponytail: a file, not an HTTP endpoint or a second Discord client. The
    scheduler and the bot are on the same machine, so `New-Item .trigger` is the
    whole IPC -- no port, no auth, nothing to leak. The bot already owns the
    Discord connection; the scheduler just needs to say "go".
    """
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(10)
        if not TRIGGER.exists():
            continue
        try:
            body = TRIGGER.read_text(encoding="utf-8").strip()
        except OSError:
            body = ""
        TRIGGER.unlink(missing_ok=True)

        ch = bot.get_channel(int(os.environ.get("DISCORD_CHANNEL_ID", 0) or 0))
        if ch is None:
            print("DISCORD_CHANNEL_ID unset or wrong -- scheduled run has nowhere "
                  "to post", flush=True)
            continue
        if _busy.locked():
            await ch.send("Scheduled run skipped -- already generating.")
            continue
        async with _busy:
            await ch.send("Scheduled run: picking today's trend...")
            await generate_and_offer(ch, prompt=body or None)


bot = Bot()


@bot.tree.command(name="post", description="Generate a Buzzit video and approve it")
@app_commands.describe(
    prompt="Your own Veo prompt (leave blank to use today's trending topic)",
    caption="Instagram caption (only used with a custom prompt)")
async def post(itx: discord.Interaction, prompt: str = None, caption: str = None):
    if _busy.locked():
        await itx.response.send_message("Already generating -- one at a time.",
                                        ephemeral=True)
        return

    await itx.response.send_message(
        "Using your prompt..." if prompt else "Picking today's trend...")

    async with _busy:
        await itx.followup.send("Generating the video -- a few minutes.")
        await generate_and_offer(itx.followup, prompt=prompt, caption=caption)


@bot.tree.command(name="status", description="Bot and Instagram token status")
async def status(itx: discord.Interaction):
    await itx.response.defer(thinking=True)
    ok, out = await asyncio.to_thread(
        functools.partial(sh, "post_instagram.py", "--whoami", timeout=120))
    busy = "generating a video" if _busy.locked() else "idle"
    await itx.followup.send(f"Bot is **{busy}**.\n```\n{out[-800:]}\n```")


def main():
    load_env()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        sys.exit("set DISCORD_BOT_TOKEN in .env (Developer Portal -> Bot -> Reset Token)")
    bot.run(token)


if __name__ == "__main__":
    main()
