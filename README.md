# Makeo

Makeo is a multi-brand content pipeline: a user (or a schedule) supplies a
prompt, Google Flow renders an 8-second 9:16 clip, the brand's end-card is
appended, a human approves, and the clip publishes to **that brand's**
Instagram as a Reel.

Nothing posts without a click. Rejecting publishes nothing.

This repo is the product. The architecture and PR plan live in
[`DESIGN.md`](DESIGN.md).

**v1 is waitlisted.** Each brand brings its own Gemini key and Google Flow
login. Approval is in-app (Discord comes later). The worker is this git
checkout plus Chrome — clone and run. Not GitHub Actions. Not Task Scheduler
as the product runner.

The scripts still run the original **Buzzit** path with no flags. Buzzit is
the reference tenant, not the product name. Brand-specific copy, assets, and
tokens become `--config`.

## Jobs (Makeo worker)

Clone this repo onto a machine that has Chrome (Windows first). Two processes,
never `uvicorn --workers 2`, never GitHub Actions, never Task Scheduler as the
only runner:

```
set MAKEO_MASTER_KEY=...          # Fernet key from cryptography.fernet.Fernet.generate_key()
python -m makeo.enqueue --brand buzzit
python worker.py
```

Site (one API process, port 8780):

```
python -m makeo.create_user you@brand.com 'password'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8780 --workers 1
```

Each enqueue copies brand.json + assets into `data/tenants/<slug>/jobs/<id>/`.
The worker must use only that prefix.

`legacy/n8n-genz-daily.json` is an unsupported leftover (old n8n + Postiz path).
Do not run it; do not build on it.

Nightly ops (token slide-refresh + 30-day video retention):

```
python -m makeo.ops
```

## Reference tenant: Buzzit

Picks a real trending topic in India, turns it into an 8-second vertical ad
for the Buzzit app, appends the branded splash card, sends it to Discord for
human approval, and publishes the approved clip to Instagram as a Reel.

```
python daily.py --public
```

```
trend feeds -> Gemini -> Veo (Google Flow) -> splash end-card
            -> Discord approval card -> [you click Approve] -> Instagram Reel
```

Nothing posts without a click. Rejecting publishes nothing.

## Setup

```powershell
copy .env.example .env      # then fill in, see below
```

| Variable | How to get it |
|---|---|
| `GEMINI_API_KEY` | aistudio.google.com (env var, not .env) |
| `IG_USER_ID` / `IG_ACCESS_TOKEN` | `python post_instagram.py --setup` |
| `CHAT_WEBHOOK` | Discord: Channel -> Integrations -> Webhooks -> Copy URL |
| `DISCORD_BOT_TOKEN` | Discord Developer Portal -> Bot -> Reset Token |
| `DISCORD_CHANNEL_ID` | Server settings -> channel -> Copy Channel ID |

Google Flow uses the logged-in Chrome profile in `.chrome-profile/`:

```powershell
python flow_video.py --login     # sign in once, session persists
```

## Scripts

| File | Does |
|---|---|
| `make_prompt.py` | Google News + Trends RSS -> Gemini -> `prompt.txt` + `today.json` |
| `flow_video.py` | drives labs.google/fx Flow, downloads the mp4 to `out/` |
| `brand.py` | appends `screenshot/splash_video.gif` as an end-card |
| `approve.py` | serves an approval page, notifies Discord, blocks until decided |
| `post_instagram.py` | Graph API publish; `--whoami` checks token + expiry |
| `daily.py` | runs all of the above in order |

Each video gets a `.json` sidecar holding its own caption, so the caption can
never drift from the clip it describes.

## Scheduling

Runs on the local machine via Task Scheduler (`schedule_daily.ps1`), **not**
GitHub Actions -- the pipeline needs the logged-in Chrome profile for Flow, and
the approval step blocks on a human, which a CI runner cannot provide.

## Token upkeep

`IG_ACCESS_TOKEN` expires every ~60 days. `python post_instagram.py --whoami`
prints the remaining lifetime and warns under 48h. To refresh:

```powershell
python post_instagram.py --finish-setup "<SHORT_TOKEN>" "<APP_ID>" "<APP_SECRET>"
```

## Not committed

`.env` (IG token, Discord webhook), `.chrome-profile/` (live Google session),
`out/` / `shots/` / `logs/` (generated), and `data/` (Makeo tenant jobs,
assets, sqlite — later PRs). All are gitignored and must stay that way.
