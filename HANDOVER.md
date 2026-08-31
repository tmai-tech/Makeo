# Makeo handover

**Who this is for:** the next person who has to run, fix, or extend Makeo.  
**How to read it:** start at the top. You do not need to know the repo yet.  
**What “every line of code” means here:** every *file* and every *important function* is explained in plain language. Reprinting thousands of source lines would hide the story. The source itself is the line-by-line truth; this file is the map.

**Repo:** [tmai-tech/Makeo](https://github.com/tmai-tech/Makeo)  
**Live site:** https://tmai-tech.github.io/Makeo/?v=atelier2#/  
**Preview (catalog lab):** https://tmai-tech.github.io/Makeo/preview/fal/?v=atelier2#/  
**Date of this handover:** 31 August 2026

---

## 1. The story, from the beginning

Makeo did not start as a website. It started as **one brand’s daily ad machine**.

That brand is **Buzzit** (a creator / “buzz and earn” app in India). On one Windows PC, a chain of Python scripts ran once a day:

1. Read Google News + Google Trends for India.  
2. Ask Gemini to write an 8-second video idea (Hinglish, India-only).  
3. Open **Google Flow** in a real Chrome window (Playwright) and wait for Veo to render a vertical clip.  
4. Stamp the Buzzit logo / phone screen / gold end-card on with ffmpeg.  
5. Ask a human on **Discord** to Approve or Reject.  
6. If approved, post the clip to **@buzzit_official** on Instagram as a Reel.

The rule that has never changed: **nothing goes to Instagram unless a human clicks Approve.** Reject means nothing is posted.

That one-machine chain is still in the repo (`daily.py` and friends). It still works if you run it with no flags.

Then the product goal became: **any brand** should be able to do the same thing, without sharing Buzzit’s Instagram, Chrome login, or Gemini key.

So the work split into three layers that now live together:

| Layer | What it is | Where |
|---|---|---|
| **A. Pipeline scripts** | The original Buzzit engine | `daily.py`, `make_prompt.py`, `flow_video.py`, `brand.py`, `post_instagram.py` |
| **B. Makeo product** | Queue + website + one worker process | `makeo/`, `app/`, `worker.py` |
| **C. Catalog lab** | Indian ethnic-wear virtual try-on (stills, not Reels) | `notebooks/`, `web/` catalog page |

A fourth surface was added for people who only have a browser:

| Layer | What it is | Where |
|---|---|---|
| **D. GitHub Pages studio** | Clickable demo / catalog UI | `web/` → tmai-tech.github.io/Makeo |

Google AI Studio / Nano Banana / Veo-from-the-browser was tried and dropped (quota). **fal.ai** was added on the Pages demo as another way to make a short video. **Catalog try-on** uses a free Colab T4, not fal.

---

## 2. What Makeo is, in one paragraph

Makeo is a **studio for Indian brands**. A person creates a login, adds a brand, then can:

- **Reels path:** write a prompt (or use today’s trends) → a worker makes an 8-second 9:16 video → a human approves → Instagram Reel.  
- **Catalog path:** upload a model photo + a garment photo (saree, lehenga, kurta…) → Colab puts the garment on the model → the still is saved for quality review.

Two different outputs (video vs still). Same product name. Same “human stays in control” idea.

---

## 3. The one picture you should keep in your head

```
                         ┌─────────────────────────────┐
                         │  Browser (GitHub Pages)     │
                         │  web/assets/app.js          │
                         │  #/signup  #/home  #/catalog│
                         └──────────┬──────────────────┘
                                    │
              paste Makeo server URL│        paste Colab worker URL
                                    │
              ┌─────────────────────▼──────────┐     ┌─────────────────────┐
              │  FastAPI  :8780                │     │  Colab T4  :8766    │
              │  app/main.py                   │     │  colab_worker.py    │
              │  accounts, brands, compose,    │     │  FASHN / IDM / …    │
              │  inbox approve                 │     │  returns a PNG      │
              └──────────┬─────────────────────┘     └─────────────────────┘
                         │
                         │  SQLite  data/makeo.db
                         │
              ┌──────────▼─────────────────────┐
              │  worker.py  (one process)      │
              │  claims a job                  │
              │  runs daily.py → Flow → brand  │
              │  then post_instagram.py        │
              └────────────────────────────────┘
```

**Important:** GitHub Pages cannot store real accounts or run Python. Accounts live on the FastAPI process. Try-on lives on Colab. Video generation lives on a machine that has Chrome.

---

## 4. How a human actually uses it today

### 4.1 Create an account (real, on the server)

1. Start the API on a computer:

```text
set MAKEO_MASTER_KEY=<fernet key>
python -m uvicorn app.main:app --host 0.0.0.0 --port 8780 --workers 1
```

2. Either open http://127.0.0.1:8780/signup  
   **or** open https://tmai-tech.github.io/Makeo/?v=atelier2#/signup and paste `http://127.0.0.1:8780` as **Makeo server URL**.

3. Fill **name, email, password, confirm password** (8+ characters).  
4. The server stores an Argon2 hash in SQLite and sets a session cookie.

Sign-in is email + password. Forgot-password is **not** built (no email sender).

Old Pages accounts that lived only in the browser (`localStorage`) are **not** migrated.

### 4.2 Make a Reel (real worker)

1. Add a brand (name, pitch, hook…).  
2. Paste that brand’s Gemini / Flow / fal key (Makeo does not give you one).  
3. Optionally paste Instagram user id + long-lived token.  
4. Compose a prompt → job row `queued`.  
5. `python worker.py` on a Chrome machine picks it up.  
6. Inbox: watch, edit caption if needed, **Approve & post** or **Reject**.

### 4.3 Catalog try-on (Colab)

1. Brand → Catalog.  
2. Open the notebook from GitHub (not a Drive copy):  
   https://colab.research.google.com/github/tmai-tech/Makeo/blob/explore-catalog-vton/notebooks/fashn_vton_colab.ipynb  
3. Runtime → T4 GPU → Run all. Wait until the last cell prints a `https://….colab.dev` URL (often 5–15 minutes).  
4. Paste that URL (no `/ui` on the end) → Save.  
5. Drop a model photo + garment photo → pick outfit type + try-on model → **Create look**.  
6. Wait 1–3 minutes. Result + inputs are logged.

---

## 5. Entire Reels flow, step by step

This is the original product. Status of a job moves like this:

```
queued
  → running          (worker is generating)
  → awaiting_approval
  → publishing       (human approved)
  → posted
     or rejected
     or failed
```

### 5.1 A job is born

- **Website compose** (`POST /brands/{id}/compose`) or  
- **CLI** `python -m makeo.enqueue --brand buzzit` or  
- **Scheduler** (`makeo/scheduler.py`) if the brand has a daily time set.

`makeo/enqueue.py` does **not** generate video. It:

1. Loads `brands/<slug>.json` (or the brand’s saved config).  
2. Copies that JSON + logo/splash into  
   `data/tenants/<slug>/jobs/<job_id>/`.  
3. Inserts a `jobs` row: `status=queued`, `source=ui_custom` or `ui_trend` or `schedule`.

The worker is only allowed to read **that job folder**. It must not wander into another brand’s files.

### 5.2 The worker claims it

`worker.py` is a single loop. **One process. Never `uvicorn --workers 2`.**  
Each tick it may do **one** generate **or** one publish, not both, not two generates.

It:

1. Writes a heartbeat (`worker_heartbeats`).  
2. Marks jobs that have been `running` too long as `failed`.  
3. Kills leftover Chrome that still points at a known `chrome-profile`.  
4. Claims the next `queued` job (`UPDATE … WHERE status='queued'`).  
5. Builds a **clean environment**: strips the host’s `IG_USER_ID` / `IG_ACCESS_TOKEN` / `GEMINI_API_KEY`, then puts **this brand’s** values back. That is how Buzzit’s Instagram never leaks onto another brand.  
6. Runs `daily.py` as a **subprocess** with `MAKEO_JOB_ID=<id>` and `--out-dir` pointing at the job folder.  
7. When `daily.py` finishes, it looks **only** at `result.json` in that folder. If the file is missing, the job is `failed`. It never picks “the newest mp4 in out/” (that old bug posted yesterday’s video).

### 5.3 What `daily.py` actually runs

`daily.py` is a conductor. It does not import the other scripts as libraries. It **starts them as separate Python processes** so one crash does not kill the rest.

Typical generate path:

1. **Prompt**  
   - Custom text → `write_manual_prompt()` writes `prompt.txt` + `today.json`.  
   - Trend mode → `make_prompt.py --config … --out-dir …`.  
2. **Video** → `flow_video.py --profile-dir data/tenants/<slug>/chrome-profile --out <job> --prompt-file <job>/prompt.txt`.  
3. **Brand stamp** → `brand.py --config … --assets-dir …` (logo, PiP phone, gold end-card).  
4. Writes `result.json` with the final video path. Prints `MAKEO_RESULT=…`.

`flow_video.py` drives a real Chrome profile that is already signed into Google Flow (`python flow_video.py --login` once per brand). It is scraping a website, not calling an official Veo API. Only **one** Flow job at a time on the machine.

`brand.py` uses ffmpeg. Crop numbers for the phone PiP stay in this file (Buzzit defaults). CRF 23 keeps the file small enough for Discord’s 8 MB limit if Discord is used.

### 5.4 Approve

The job is now `awaiting_approval`.

- **In-app (the real path):** Inbox plays the video. Human can edit the caption. That edit writes **only** `jobs.caption_override`. Approve → `publishing`. Reject → `rejected` and stop.  
- **Discord (optional, Phase 4):** buttons `makeo:<job_id>:approve|reject`. The bot only HTTP-calls the API. It does not write the database itself.

There is **no** public unauthenticated approve URL on the product path. The old `approve.py` phone page is frozen leftover.

### 5.5 Publish

Worker sees `publishing`, claims it, runs `post_instagram.py` with:

- this job’s video  
- caption = `caption_override` if set, else sidecar caption  
- `IG_USER_ID` / `IG_ACCESS_TOKEN` from **this brand only**

Instagram Graph needs a URL it can download. `makeo/media.py` gives a short-lived signed URL with HTTP Range (Instagram fetches in chunks). Paths with `../` are 404.

On success: `posted` + permalink. On failure: error on the job, not a silent retry of another brand’s clip.

---

## 6. Entire catalog (try-on) flow, step by step

This is **not** in the original 12 design PRs. It lives mainly on branch `explore-catalog-vton` (also pushed to `explore/fal-ai` so `/preview/fal/` updates).

Goal: put a **real Indian garment** (saree pallu, zari, print) on a **real model photo**. Not a white packshot.

```
Browser Catalog page
   → opens Colab notebook from GitHub
   → Colab Run all
        1. Check T4
        2. pip + clone fashn-vton-1.5
        3. download ~2.2 GB weights
        4. load TryOnPipeline on GPU (fp32; T4 cannot bf16)
        5. last cell: fetch colab_worker.py?v=json9 and serve :8766
   → Colab prints https://….colab.dev
   → user pastes that URL on Catalog (no /ui)
   → Save opens the URL; should show {"ok":true}
   → Create look
        if URL is colab.dev: open /ui in window name makeo-colab-ui
        (never reuse the Save tab name — that tab is raw JSON)
        else: POST JSON {person, garment, category, model, …} to /tryon
   → worker runs the chosen model
   → PNG comes back
   → quality log written on Colab + in the browser
```

### Models in the dropdown

| Id | Role | Where it runs |
|---|---|---|
| `fashn-vton-1.5` | Default. Apache. Tops / bottoms / one-pieces | Local T4 |
| `idm-vton` | Strong single garment. Non-commercial | Hugging Face Space |
| `catvton` | Lighter. Non-commercial | Local if clone works, else Space |
| `leffa` | Fabric / pose | Space |
| `kolors` | Most-used Space | Space |

Spaces need `gradio_client` on Colab. A free T4 will OOM if you try to load IDM locally.

### URLs that look right but are wrong

| You pasted | What it actually is |
|---|---|
| `colab.research.google.com/.../fashn_vton_colab.ipynb` | The notebook tab, not the worker |
| `….trycloudflare.com` that shows Cloudflare **1033** | Dead tunnel; ignore it |
| Worker URL + `/ui` on an **old** worker | FastAPI 404 |
| `raw.githubusercontent.com/...` | Source code, not a worker |

Prefer the `https://….colab.dev` line that loads `{"ok":true}`.

---

## 7. Entire website / auth flow

There are **two** UIs that look similar (gold on near-black, Fraunces + Plus Jakarta Sans):

1. **GitHub Pages SPA** (`web/`) — hash routes, one `app.js`.  
2. **FastAPI Jinja** (`app/templates/`) — real server pages on port 8780.

### Pages routes (`web/assets/app.js`)

| Hash | Page |
|---|---|
| `#/` | Landing (“Lookbooks and Reels from one studio”) |
| `#/help` | Click-by-click tutorial |
| `#/signup` / `#/login` | Account (talks to FastAPI if server URL is saved) |
| `#/home` | Brand cards |
| `#/brands/new` | New brand |
| `#/brands/:id` | Edit brand |
| `#/brands/:id/keys` | fal + Flow keys (stay in this browser) |
| `#/brands/:id/compose` | Generate video (fal or Veo) |
| `#/brands/:id/catalog` | Try-on studio |
| `#/brands/:id/inbox` | Approve / reject demo jobs |
| `#/brands/:id/instagram` | Handle (token not uploaded from Pages) |
| `#/logout` | Clears session; POST `/v1/auth/logout` if API URL set |

State key in `localStorage`: `makeo-demo-v2`. Brands/jobs/keys for the **demo** still live there. **Identity** (`s.me`) comes from the server after login.

### FastAPI routes (`app/main.py`)

| Method | Path | Meaning |
|---|---|---|
| GET | `/health` | `{"ok":true,"auth":true}` |
| GET/POST | `/signup` `/login` | HTML forms + CSRF |
| GET | `/logout` | Clear cookie |
| POST | `/v1/auth/signup` `/login` `/logout` | JSON for Pages |
| GET | `/v1/auth/me` | Current user or 401 |
| GET/POST | `/brands/new` `/brands/{id}` | Brand wizard |
| GET/POST | `/brands/{id}/compose` | Enqueue generate |
| GET/POST | `/brands/{id}/catalog` | Save Colab URL + try-on page |
| GET | `/brands/{id}/inbox` | Approvals |
| POST | `/v1/jobs/{id}/approve` `/reject` | Must own the brand |
| GET | `/brands/{id}/instagram` | Paste token (encrypted) |
| GET | `/public/media/{job}/{token}` | Signed video for Graph |
| POST | `/internal/jobs/{id}/discord-approve` | Worker-key only |

Every brand/job read checks `brand.user_id == session.user_id`. Another user gets 404/403.

Passwords: **Argon2**. Sessions: Starlette cookie. Cross-site Pages → API needs `MAKEO_COOKIE_SAMESITE=none` and HTTPS.

---

## 8. Database (simple)

File: `data/makeo.db` (gitignored). WAL mode.

| Table | In one sentence |
|---|---|
| `users` | Login: email, Argon2 hash, display name |
| `brands` | One user owns many brands; `config` is JSON |
| `brand_alerts` | “token dying”, “last job failed” |
| `ig_accounts` | Encrypted Instagram token |
| `discord_targets` | Optional channel |
| `schedules` | Timezone + local time + days |
| `jobs` | The queue. `caption_override` is the only caption edit |
| `approvals` | Who clicked what |
| `media_tokens` | Short-lived download tokens |
| `flow_locks` | One Flow generate at a time |
| `worker_heartbeats` | Is the worker alive? |
| `secrets` | Encrypted Gemini (and similar) keys |

`MAKEO_MASTER_KEY` is a Fernet key. Without it, tokens cannot be encrypted or read.

---

## 9. Every file in the repo (what it is for)

### Root pipeline (the original Buzzit engine)

| File | What it does, in simple words |
|---|---|
| `daily.py` | The conductor. Runs the other scripts as child processes. Flags: `--public`, `--prompt`, `--skip-generate`, `--no-brand`, `--config`, `--out-dir`. When `MAKEO_JOB_ID` is set it writes `result.json` and does **not** guess the video by “newest file”. |
| `make_prompt.py` | Reads news/trends, calls Gemini, writes `prompt.txt` + `today.json`. With `--config` it uses that brand’s pitch and feeds. Without `--config` it still behaves like old Buzzit (hardcoded `INSTRUCTIONS` is that fallback). |
| `flow_video.py` | Opens Google Flow in Chrome. `--login` once. `--profile-dir` per brand. Downloads the clip. Copies `today.json` onto a sidecar next to the mp4 so captions cannot drift. |
| `brand.py` | ffmpeg: phone PiP, gold border, splash end-card. Assets from `--assets-dir` or `screenshot/`. |
| `post_instagram.py` | Instagram Graph v21. Paste token, exchange to long-lived, publish Reel. Job path **must not** read repo `.env` or Buzzit’s default IG id. |
| `bot.py` | Discord bot. Buttons are `makeo:{job_id}:approve`. Talks HTTP to the API. Must not call `newest_video()`. |
| `approve.py` | Old phone-approve page + cloudflared. **Frozen.** Do not build on it. |
| `brand_config.py` | Loads `brands/*.json`. Unknown `{placeholders}` fail. `build_feeds()` builds RSS from region. |
| `brands/buzzit.json` | The reference brand: pitch, hook, tone, slogan, feeds, assets. |

### Makeo package (queue + ops)

| File | What it does |
|---|---|
| `makeo/db.py` | Creates tables, `connect()`, encrypt/decrypt, `new_id()`, `now()`, insert helpers, `users.name` migrate. |
| `makeo/enqueue.py` | CLI to create a job folder + `queued` row. |
| `makeo/scheduler.py` | Once a minute: if a brand’s local time has arrived and they have no job today, enqueue. |
| `makeo/media.py` | Signed Range URLs. Rejects `../`. |
| `makeo/ops.py` | Nightly: slide-refresh IG tokens; delete videos older than 30 days. |
| `makeo/create_user.py` | `python -m makeo.create_user EMAIL PASSWORD [NAME]` |
| `makeo/__main__.py` | Allows `python -m makeo enqueue …` |
| `worker.py` | The one background process. Claim generate **xor** publish. Clean env. Bind `result.json` only. |

### Website (server)

| File | What it does |
|---|---|
| `app/main.py` | FastAPI app: auth, brands, compose, inbox, catalog, media, Discord internal. Session + CSRF + CORS + rate limit. |
| `app/templates/base.html` | Chrome: fonts, nav, name or email. |
| `app/templates/signup.html` | Name, email, password, confirm, show/hide. |
| `app/templates/login.html` | Email, password, show/hide. |
| `app/templates/home.html` | Brand cards. |
| `app/templates/brand_form.html` | Wizard including Gemini key + Flow URL + assets. |
| `app/templates/compose.html` | Prompt + generate. |
| `app/templates/inbox.html` | Player + approve/reject. |
| `app/templates/instagram.html` | Paste token. |
| `app/templates/catalog.html` | Colab URL + upload + Create look. |
| `app/static/app.css` | Atelier theme (void + gold). |
| `app/static/auth.js` | Show/hide password buttons. |

### Website (GitHub Pages)

| File | What it does |
|---|---|
| `web/index.html` | Empty `#app` + fonts + `app.js?v=atelier2`. |
| `web/assets/app.js` | The whole SPA: storage, auth client, brand forms, fal generate, catalog, inbox. One IIFE, no framework. |
| `web/assets/styles.css` | Same atelier look as the server. |
| `web/assets/icon.svg` | Gold “M” stamp. |
| `web/manifest.webmanifest` | Add-to-home-screen. |
| `web/colab/fashn-vton/index.html` | Tiny page that points at the notebook. |

**How `app.js` is organized (top to bottom):**

- `KEY` / `load` / `save` / `state` — read/write `localStorage`.  
- `apiUrl` / `cleanApiUrl` / `user` / `whoLabel` — server session vs leftover local users.  
- `hash` — old SHA-256 (no longer used for new logins).  
- `falModels` / `hasVideoKey` — which video engine a brand can use.  
- `shell` — header + footer. Footer says `Studio UI · atelier2` so you know you have the new build.  
- `landing` / `tutorial` / `authForm` / `home` / `brandForm` / `keysForm` / `igForm` / `compose` / `inbox` / `catalogPage` — HTML strings.  
- `bindAuth` / `bindBrand` / `bindKeys` / `bindCompose` / `bindCatalogPage` — click handlers.  
- `paint` — looks at `location.hash` and draws the right page. Restores `/v1/auth/me` once if a server URL is saved.

### Catalog GPU worker

| File | What it does |
|---|---|
| `notebooks/fashn_vton_colab.ipynb` | The Colab the user runs. Last required cell is “Start worker”. Do not put `files.upload()` before that (it blocks Run all). |
| `notebooks/colab_worker.py` | FastAPI on port 8766. `GET /` JSON ok. `GET /ui` HTML bridge (postMessage). `POST /tryon` JSON images. `GET /models` `GET /health` `GET /logs`. Lazy-loads one model. Writes quality logs. Prefers Colab `proxyPort` over flaky trycloudflare. |
| `notebooks/check_notebook.py` | CI-style check: notebook still mentions T4, FASHN, worker; no leaked keys. |
| `notebooks/README.md` | How to open Colab from GitHub. |

### Tests

| File | What it proves |
|---|---|
| `tests/test_auth.py` | Signup, login, logout, duplicate, CSRF, CORS, `users.name`. |
| `tests/test_app.py` | Waitlisted unknown login 401; owner-only approve; owner-only catalog. |
| `tests/test_colab_worker.py` | Image decode, five models, quality log, /ui, dead tunnel. |
| `tests/test_brand_config.py` | Buzzit loads; SSRF feeds blocked; placeholders. |
| `tests/test_daily_prompt.py` | Manual prompt, result.json, history dirs. |
| `tests/test_enqueue.py` | Tables exist; job folder snapshot. |
| `tests/test_flow_out.py` | Video named `flow-{job_id}.mp4`. |
| `tests/test_ig_scope.py` | Job path does not use Buzzit IG id. |
| `tests/test_media_sched.py` | Range URL; `../` 404; schedule catch-up. |
| `tests/test_ops.py` | Old job dirs deleted. |
| `tests/test_worker.py` | Bind only manifest; claim publish first; env pop. |
| `tests/test_bot_parse.py` | `makeo:` custom_id only. |

Run: `PYTHONPATH=. python -m unittest discover -s tests`

### Windows leftovers (dev only)

`run_daily.ps1`, `schedule_daily.ps1`, `run_bot.ps1`, `schedule_bot.ps1` — old Task Scheduler helpers for Buzzit on one PC. Not the product runner.

### Other

| File | What it does |
|---|---|
| `DESIGN.md` | The original 12-PR design. Source of truth for “why”, not always for “what shipped last week”. |
| `STATUS.md` | What actually landed. |
| `README.md` | How to run. |
| `HANDOVER.md` | This file. |
| `requirements.txt` | Python deps (Playwright, FastAPI, Argon2, Discord, cryptography…). |
| `.env.example` | Names of secrets. Never commit `.env`. |
| `screenshot/` | Buzzit logo, splash GIF, phone feed image. |
| `legacy/n8n-genz-daily.json` | Dead n8n workflow. Do not run. |
| `scripts/try_fal.py` | Small fal experiment helper. |
| `.github/workflows/deploy-pages.yml` | Push `main` → live site. Push `explore/fal-ai` → `/preview/fal/`. |
| `data/` | SQLite + tenant jobs. **Gitignored.** |

---

## 10. Branches and what is live

| Branch | Role |
|---|---|
| `main` | Product + live Pages (`/` ). Protected: PRs + `unit-and-integration`. |
| `explore-catalog-vton` | Catalog + auth + atelier UI lab. |
| `explore/fal-ai` | Same lab, but Pages workflow copies `web/` to `/preview/fal/`. |

Live UI cache bust: `app.js?v=atelier2`. If the footer does not say **Studio UI · atelier2**, you are on an old tab. Hard-refresh or add `?v=atelier2`.

---

## 11. Rules that must not be broken

1. **No post without Approve.**  
2. **One Flow generate at a time** on the worker host.  
3. **Never mix brand A’s Chrome profile, Gemini key, or IG token with brand B.**  
4. **Never `load_env()` on a `MAKEO_JOB_ID` publish.**  
5. **Never pick a video by “newest file”.** Only `result.json`.  
6. **Never `uvicorn --workers 2`.** One API process, one worker process.  
7. **Do not File → Save a copy in Drive** of the Colab notebook. Always open from GitHub.  
8. **Do not commit** `.env`, `data/`, `.chrome-profile/`, `out/`.  
9. Caption edits = `jobs.caption_override` only.  
10. Catalog Create look on `colab.dev` must open `/ui` in window name `makeo-colab-ui`, not the Save JSON tab.

---

## 12. How to run the whole thing (checklist)

On a machine with Chrome (Windows first):

```text
# 1. Secrets
set MAKEO_MASTER_KEY=   # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
set MAKEO_SESSION=      # any long random string

# 2. Website
python -m uvicorn app.main:app --host 0.0.0.0 --port 8780 --workers 1

# 3. Worker
python worker.py

# 4. Optional: create an operator user
python -m makeo.create_user you@brand.com "a-long-password" "Your Name"

# 5. Optional: enqueue Buzzit by hand
python -m makeo.enqueue --brand buzzit

# 6. Optional: old one-shot Buzzit (no queue)
python daily.py --public
```

Then open:

- API UI: http://127.0.0.1:8780/signup  
- Pages UI: https://tmai-tech.github.io/Makeo/?v=atelier2#/  (paste the API URL)  
- Catalog notebook: link in §4.3  

For Pages on a **phone** talking to this API, the API must be **HTTPS** and started with `MAKEO_COOKIE_SAMESITE=none`.

---

## 13. What is intentionally not built

- Forgot password / verify email (no mailer).  
- Google / Instagram login for Makeo itself.  
- Instagram Facebook-Login OAuth (paste token is v1).  
- Billing.  
- Team seats (one user owns the brands).  
- Public unlimited signup abuse controls beyond a per-IP rate limit.  
- Hosted “log into Flow in our cloud desktop”. Operator helps with `flow_video.py --login` on the worker PC.  
- Moving brands/jobs off `localStorage` on Pages (only the **login** is on the server).

---

## 14. Known sharp edges (from the last weeks of work)

- **trycloudflare** often prints a hostname that never answers (Cloudflare 1033). Use `colab.dev`.  
- **Save** used to open `url + /ui` and hit 404 on old workers. Save now opens the root JSON.  
- **Create look** used to reuse the Save window (`makeo-colab-worker`) and show raw JSON. It now uses `makeo-colab-ui`.  
- T4 is Turing 7.5: FASHN must run **fp32**, not bf16.  
- fal.ai new accounts are **$0**. Website sandbox clips are not the API. Generate will say locked until billing has a real balance.  
- Live site `/` and preview `/preview/fal/` are **different deploys**. If one looks old, check the footer for `atelier2`.

---

## 15. If you only remember five things

1. Makeo = Buzzit’s daily Reel machine, opened to many brands, plus a saree try-on lab.  
2. Approve is mandatory. Auto-post is forbidden.  
3. Three computers: **browser** (Pages), **API+SQLite** (port 8780), **Chrome worker** (Flow) and/or **Colab T4** (try-on).  
4. `DESIGN.md` is the why; `STATUS.md` is what shipped; this file is the tour.  
5. Tests: `PYTHONPATH=. python -m unittest discover -s tests` — keep them green before merging to `main`.
