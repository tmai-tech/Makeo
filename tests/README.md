# Tests

Unit tests prove one function. Integration tests prove HTTP + worker + DB
together. `test_proof_pipeline.py` is the full contract: enqueue → bind
`result.json` → approve override → publish caption. No Gemini, Flow, or
Instagram network.

```
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -q
```

| File | Kind | What it proves |
|---|---|---|
| `test_brand_config.py` | unit | JSON load, placeholders, feed allowlist |
| `test_db_unit.py` | unit | schema, Fernet, `auth_method` migrate |
| `test_daily_prompt.py` | unit | out-dir, history-dir, result.json, no unbranded job |
| `test_make_prompt_unit.py` | unit | parse, template vs fallback, SSRF skip |
| `test_flow_out.py` | unit | `flow-{job_id}.mp4` |
| `test_ig_scope.py` | unit | no `.env` / no `DEFAULT_IG_ID` on job path |
| `test_media_sched.py` / `test_media_range.py` | unit | Range, `../` 404, token TTL |
| `test_scheduler_unit.py` | unit | weekdays, dead IG token → failed job |
| `test_worker.py` / `test_worker_unit.py` | unit | bind-only, env pop, flow lock, crash timeout |
| `test_enqueue.py` | integration | snapshot dir + assets |
| `test_ops.py` | integration | 30-day retention |
| `test_app.py` / `test_integration_http.py` | integration | login, CSRF, compose, approve/reject/retry, owner isolation |
| `test_bot_parse.py` | unit | `makeo:{id}:approve` |
| `test_proof_pipeline.py` | proof | queued → awaiting_approval → posted with override caption |

## CI (must pass before merge to `main`)

`.github/workflows/ci.yml` runs on every **pull request into `main`** and on
every push to `main`. The check name is **unit-and-integration**.

To block merge until it is green: GitHub → Settings → Rules → Rulesets
(or Branches → Branch protection) → `main` → Require status checks to
pass → add `unit-and-integration`.
