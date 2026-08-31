# What has been built

This is the completion report for the [DESIGN.md](DESIGN.md) PR plan (PRs 1–12)
plus the leftover slice and the catalog experiment. It is meant to be read
after the product [README](README.md).

**Short answer:** the twelve design PRs are already on `main`. They were not
re-done. One leftover pull request (RSS builder, no unbranded Makeo publish,
OAuth-ready `auth_method`, caption-override test) is the only remaining
design slice. Catalog virtual try-on is extra work on another branch.

---

## Design PRs 1–12 — on `main`

| PR | Title | Commit on `main` | Status |
|---|---|---|---|
| 1 | Repo hygiene: gitignore `data/`, `.env.example`, Makeo README | `531bcff` | Done |
| 2 | `brand_config.py` + `brands/buzzit.json` | `733b70d` | Done |
| 3 | `make_prompt.py` / `daily.py` `--config` `--out-dir` `--history-dir` + `result.json` | `65c8b6f` | Done (leftovers below) |
| 4 | `flow_video.py --profile-dir`; daily forwards `--out` / `--project` / prompt file | `22b3e52` | Done |
| 5 | Tenant brand assets; job-scoped IG env; no `DEFAULT_IG_ID` | `66fe0fc` | Done |
| 6a | SQLite jobs, enqueue CLI, job-private snapshot dir | `5f2b5a9` | Done |
| 6b | Worker claims `queued` XOR `publishing`; binds video only from `result.json` | `60f585d` | Done |
| 7 | Catch-up scheduler + one-file Range media URLs | `7084046` | Done |
| 8–10 | Waitlisted FastAPI app: brand CRUD, compose, approve, IG paste | `043cfb1` | Done |
| 11 | Multi-tenant Discord approval (`makeo:{job_id}:…`) | `d6ba976` | Done |
| 12 | Token slide-refresh, 30-day retention, n8n moved to `legacy/` | `62a92ed` | Done |

After that, `main` also grew the public GitHub Pages demo (signup → brand →
generate → inbox) and fal preview slot. That is product/demo work, not a
thirteenth design PR.

### What each PR actually gave you

**PR 1 — repo**  
`.gitignore` covers `.env`, `data/`, `out/`, `.chrome-profile/`. Buzzit is
the reference tenant, not the product name.

**PR 2 — BrandConfig**  
Every Buzzit constant (instructions, feeds, model, slogan, gold PiP) lives
in `brands/buzzit.json`. Unknown template placeholders fail load. `CROP`
stays in `brand.py`.

**PR 3 — prompts and results**  
`--config` / `--out-dir` / `--history-dir`. Sibling job dirs feed
“Already covered.” `MAKEO_JOB_ID` writes `result.json` and prints
`MAKEO_RESULT=`. No `--config` still behaves like the old Buzzit repo-root
path. Hardcoded `INSTRUCTIONS` in `make_prompt.py` is that fallback, not a
missed extraction.

**PR 4 — Flow isolation**  
Chrome profile and output dir are per job. Videos are `flow-{job_id}.mp4`.

**PR 5 — brand + IG isolation**  
Tenant logo/splash/PiP. Job-scoped publish does not `load_env()` and does
not fall back to Buzzit’s IG id.

**PR 6a / 6b — queue + worker**  
`python -m makeo.enqueue` then `python worker.py`. One generate **or** one
publish per tick. Missing `result.json` → `failed`, never yesterday’s clip.

**PR 7 — schedule + media**  
Brand-timezone catch-up. Signed Range URL for Graph (no per-job Cloudflare
page). Path `../` is 404.

**PR 8–10 — website**  
Waitlisted login, brand wizard, compose (custom or trends), inbox
approve/reject, IG token paste. Caption edit is `jobs.caption_override`
only. Nothing posts without a click.

**PR 11 — Discord (optional)**  
Buttons call the same job row over HTTP. Bot does not write `jobs` and
does not call `newest_video()`.

**PR 12 — ops**  
`python -m makeo.ops` slides IG tokens and deletes videos older than 30
days. `legacy/n8n-genz-daily.json` is unsupported.

---

## Leftover design slice (PR #1)

GitHub: https://github.com/tmai-tech/Makeo/pull/1  
Branch: `feat/pr3-leftovers`

These were gaps **inside** PRs already merged, not new plan numbers:

| Leftover | Why it existed | What landed |
|---|---|---|
| RSS query builder | DESIGN: feeds come from `locale.region`, not free-form RSS | `brand_config.build_feeds()`; fetch skips non-allowlisted hosts |
| `--config` must use `instructions_template` | Hardcoded template was still the only tested path | `llm_prompt()` + tests |
| No unbranded Makeo publish (Q5) | `--no-brand` still worked on `MAKEO_JOB_ID` | Hard fail; PiP can stay off via `pip_enabled` |
| OAuth later without a dump (Q4) | Paste-only `ig_accounts` | `auth_method` column, default `paste` |
| Caption override test (PR 10) | Spec required it; it was missing | Worker publish uses override, not sidecar |

Still **intentionally not built** (open questions in DESIGN.md):

- Instagram Facebook-Login OAuth (needs a Meta app in review). Paste stays v1.
- Flow UI in languages other than English.
- Second seat / team access on a brand.

---

## Extra: catalog virtual try-on (not in PRs 1–12)

This is a **stills** lab for Indian ethnic wear (saree / lehenga / kurta),
not the Reel pipeline.

- Branch: `explore-catalog-vton` (also pushed to `explore/fal-ai` for the preview).
- Preview: https://tmai-tech.github.io/Makeo/preview/fal/
- Notebook: https://colab.research.google.com/github/tmai-tech/Makeo/blob/explore-catalog-vton/notebooks/fashn_vton_colab.ipynb
- Worker: `notebooks/colab_worker.py` on a Colab T4. Paste the
  `https://….colab.dev` URL (the one that loads). Do **not** use a
  trycloudflare link that shows Cloudflare 1033. Do **not** add `/ui` on
  an old worker.

Status: usable for testing after the worker cell prints `(json-v5)` and
the catalog page is on `app.js?v=cat10` or newer. Dead trycloudflare
tunnels and `/ui` 404s were worker/URL issues, not missing design PRs.

---

## How to run the product today

Clone on a machine with Chrome (Windows first). Two processes:

```
set MAKEO_MASTER_KEY=...    # Fernet key
python -m makeo.create_user you@brand.com "password"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8780 --workers 1
python worker.py
```

Public demo (no GPU): https://tmai-tech.github.io/Makeo/

Buzzit local path with no flags still works: `python daily.py --public`

---

## What “done” means

- **Design plan PRs 1–12:** done on `main`. Do not re-implement them.
- **Leftover slice:** this file + PR #1. Merge that PR to fold leftovers into `main`.
- **Catalog try-on:** separate experiment; keep it on `explore-catalog-vton` until you want it on `main`.
- **Not v1:** Meta OAuth, non-English Flow, team seats, billing, public signup.
