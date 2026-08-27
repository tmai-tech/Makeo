"""Materialize a job-private snapshot dir and insert a queued job.

    python -m makeo.enqueue --brand buzzit
    python -m makeo.enqueue --brand buzzit --prompt "8s vertical..."
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import brand_config as bc
from makeo import db

HERE = Path(__file__).resolve().parent.parent


def tenant_root(slug: str) -> Path:
    return HERE / "data" / "tenants" / slug


def snapshot_job(slug: str, job_id: str, cfg: bc.BrandConfig) -> Path:
    """Copy live brand.json + logo/splash/pip into the job dir. Worker uses only this."""
    dest = tenant_root(slug) / "jobs" / job_id
    assets_dest = dest / "assets"
    dest.mkdir(parents=True, exist_ok=True)
    assets_dest.mkdir(parents=True, exist_ok=True)

    live_assets = Path(cfg.assets_dir) if cfg.assets_dir else (HERE / "screenshot")
    mapping = {
        "logo": cfg.assets.logo,
        "splash": cfg.assets.splash,
        "pip_image": cfg.assets.pip_image,
    }
    copied = {}
    for key, rel in mapping.items():
        if not rel:
            continue
        src = None
        for cand in (live_assets / Path(rel).name, HERE / rel):
            if cand.exists():
                src = cand
                break
        if src is None:
            continue
        target = assets_dest / src.name
        shutil.copy2(src, target)
        copied[key] = f"assets/{src.name}"

    snap = bc.to_dict(cfg)
    snap["assets"] = {**(snap.get("assets") or {}), **copied}
    snap["assets_dir"] = str(assets_dest)
    snap["out_dir"] = str(dest)
    snap["flow_profile_dir"] = str(tenant_root(slug) / "chrome-profile")
    (dest / "brand.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return dest


def enqueue(slug: str, prompt: str | None = None, caption: str | None = None,
            source: str | None = None, conn=None) -> str:
    close = False
    if conn is None:
        conn = db.connect()
        close = True
    uid = db.ensure_operator(conn)
    json_path = HERE / "brands" / f"{slug}.json"
    if not json_path.exists():
        brand = db.get_brand(conn, slug)
        if not brand:
            sys.exit(f"no brand {slug!r} and no {json_path}")
        cfg = bc.load(_write_live_config(brand))
        bid = brand["id"]
    else:
        bid = db.upsert_brand_from_json(conn, json_path, uid)
        cfg = bc.load(json_path)

    src = source or ("ui_custom" if prompt else "ui_trend")
    jid = db.insert_job(
        conn, brand_id=bid, user_id=uid, source=src,
        prompt=prompt, caption=caption,
        config_snapshot=json.dumps(bc.to_dict(cfg)),
    )
    dest = snapshot_job(cfg.slug, jid, cfg)
    conn.commit()
    if close:
        conn.close()
    print(f"queued {jid} -> {dest}")
    return jid


def _write_live_config(brand) -> Path:
    p = tenant_root(brand["slug"]) / "brand.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(brand["config"], encoding="utf-8")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True, help="brand slug (e.g. buzzit)")
    ap.add_argument("--prompt", help="custom Veo prompt; omit for trend path")
    ap.add_argument("--caption")
    args = ap.parse_args(argv)
    enqueue(args.brand, prompt=args.prompt, caption=args.caption)


if __name__ == "__main__":
    main()
