"""Load and validate a BrandConfig JSON file.

PR 2: scripts do not import this yet. Later PRs pass --config. Secrets
(IG tokens, Gemini keys) must never appear in this file.
"""

from __future__ import annotations

import json
import string
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = 1
HERE = Path(__file__).resolve().parent

REQUIRED_PLACEHOLDERS = (
    "brand",
    "headlines",
    "recent",
    "hook",
    "setting_rule",
    "phone_screen_rule",
    "caption_template",
)
OPTIONAL_PLACEHOLDERS = ("tone", "audience", "forbidden_topics")
ALLOWED_PLACEHOLDERS = set(REQUIRED_PLACEHOLDERS) | set(OPTIONAL_PLACEHOLDERS)
ALLOWED_FEED_HOSTS = frozenset({"news.google.com", "trends.google.com"})
ASSET_KEYS = ("logo", "splash", "pip_image")


class BrandConfigError(ValueError):
    pass


@dataclass
class Locale:
    language: str = "en-IN"
    region: str = "IN"
    setting_rule: str = ""


@dataclass
class Assets:
    logo: str = ""
    splash: str = ""
    pip_image: str = ""


@dataclass
class BrandConfig:
    schema_version: int = SCHEMA_VERSION
    brand_id: str = ""
    name: str = ""
    slug: str = ""
    pitch: str = ""
    hook: str = ""
    tone: str = ""
    locale: Locale = field(default_factory=Locale)
    audience: str = ""
    forbidden_topics: list[str] = field(default_factory=list)
    phone_screen_rule: str = ""
    instructions_template: str = ""
    feeds: list[str] = field(default_factory=list)
    rss_query: str = ""
    headline_limit: int = 25
    dedup_max_topics: int = 10
    caption_template: str = ""
    caption_max_chars: int = 120
    hashtag_max: int = 3
    model: str = "gemini-3.6-flash"
    manual_caption: str = ""
    pip_enabled: bool = True
    pip_from_s: float = 4.0
    pip_border_color: str = "0xE8B84B"
    endcard_seconds: float = 3.0
    endcard_mode: str = "splash"
    assets: Assets = field(default_factory=Assets)
    assets_dir: str = ""
    out_dir: str = ""
    flow_project_url: str = ""
    flow_profile_dir: str = ""

    def format_instructions(self, headlines: str, recent: str) -> str:
        return self.instructions_template.format(
            brand=self.pitch,
            headlines=headlines,
            recent=recent,
            hook=self.hook,
            setting_rule=self.locale.setting_rule,
            phone_screen_rule=self.phone_screen_rule,
            caption_template=self.caption_template,
            tone=self.tone,
            audience=self.audience,
            forbidden_topics=", ".join(self.forbidden_topics),
        )


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _require(data: dict, *keys: str) -> None:
    missing = [k for k in keys if not str(data.get(k, "")).strip()]
    if missing:
        raise BrandConfigError(f"missing required field(s): {', '.join(missing)}")


def feed_host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ALLOWED_FEED_HOSTS


def build_feeds(locale: Locale | None = None, rss_query: str = "") -> list[str]:
    """Allowlisted Google News + Trends URLs from locale.region. No arbitrary RSS."""
    loc = locale or Locale()
    region = (loc.region or "IN").upper()
    lang = loc.language or "en-IN"
    lang_short = lang.split("-", 1)[0] or "en"
    q = rss_query or "when:1d+gen+z+OR+viral+OR+trending"
    news = (
        f"https://news.google.com/rss/search?q={q}"
        f"&hl={lang}&gl={region}&ceid={region}:{lang_short}"
    )
    trends = f"https://trends.google.com/trending/rss?geo={region}"
    return [news, trends]


def _check_feeds(feeds: list[str]) -> None:
    for url in feeds:
        if not feed_host_allowed(url):
            host = (urlparse(url).hostname or "").lower()
            raise BrandConfigError(
                f"feed host not allowlisted: {host or url!r} "
                f"(allowed: {', '.join(sorted(ALLOWED_FEED_HOSTS))})"
            )


def _check_rel_path(label: str, value: str, root: Path) -> None:
    if not value:
        return
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        raise BrandConfigError(f"{label} must be a relative path inside the repo: {value!r}")
    resolved = (root / p).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise BrandConfigError(f"{label} escapes repo root: {value!r}") from None


def _check_template(template: str) -> None:
    if not template.strip():
        raise BrandConfigError("instructions_template is required")
    names = _placeholders(template)
    unknown = names - ALLOWED_PLACEHOLDERS
    if unknown:
        raise BrandConfigError(
            f"unknown placeholder(s) in instructions_template: {', '.join(sorted(unknown))}"
        )
    missing = [n for n in REQUIRED_PLACEHOLDERS if n not in names]
    if missing:
        raise BrandConfigError(
            f"instructions_template missing placeholder(s): {', '.join(missing)}"
        )


def load(path: str | Path, repo_root: Path | None = None) -> BrandConfig:
    """Read JSON, validate, return BrandConfig. Does not interpolate headlines."""
    path = Path(path)
    repo_root = (repo_root or HERE).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BrandConfigError(f"cannot read {path}: {e}") from e
    if not isinstance(data, dict):
        raise BrandConfigError("config root must be an object")

    _require(data, "name", "slug", "pitch", "hook", "instructions_template")
    _check_template(data["instructions_template"])
    feeds = list(data.get("feeds") or [])
    _check_feeds(feeds)

    loc = data.get("locale") or {}
    if not isinstance(loc, dict):
        raise BrandConfigError("locale must be an object")
    assets = data.get("assets") or {}
    if not isinstance(assets, dict):
        raise BrandConfigError("assets must be an object")
    extra = set(assets) - set(ASSET_KEYS)
    if extra:
        raise BrandConfigError(f"unknown assets key(s): {', '.join(sorted(extra))}")
    for key in ASSET_KEYS:
        _check_rel_path(f"assets.{key}", assets.get(key, ""), repo_root)

    known = {f.name for f in fields(BrandConfig)} - {"locale", "assets"}
    extra_top = set(data) - known - {"locale", "assets"}
    if extra_top:
        raise BrandConfigError(f"unknown field(s): {', '.join(sorted(extra_top))}")

    cfg = BrandConfig(
        schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        brand_id=str(data.get("brand_id") or data["slug"]),
        name=data["name"],
        slug=data["slug"],
        pitch=data["pitch"],
        hook=data["hook"],
        tone=str(data.get("tone") or ""),
        locale=Locale(
            language=str(loc.get("language") or "en-IN"),
            region=str(loc.get("region") or "IN"),
            setting_rule=str(loc.get("setting_rule") or ""),
        ),
        audience=str(data.get("audience") or ""),
        forbidden_topics=list(data.get("forbidden_topics") or []),
        phone_screen_rule=str(data.get("phone_screen_rule") or ""),
        instructions_template=data["instructions_template"],
        feeds=feeds,
        rss_query=str(data.get("rss_query") or ""),
        headline_limit=int(data.get("headline_limit", 25)),
        dedup_max_topics=int(data.get("dedup_max_topics", 10)),
        caption_template=str(data.get("caption_template") or ""),
        caption_max_chars=int(data.get("caption_max_chars", 120)),
        hashtag_max=int(data.get("hashtag_max", 3)),
        model=str(data.get("model") or "gemini-3.6-flash"),
        manual_caption=str(data.get("manual_caption") or ""),
        pip_enabled=bool(data.get("pip_enabled", True)),
        pip_from_s=float(data.get("pip_from_s", 4.0)),
        pip_border_color=str(data.get("pip_border_color") or "0xE8B84B"),
        endcard_seconds=float(data.get("endcard_seconds", 3.0)),
        endcard_mode=str(data.get("endcard_mode") or "splash"),
        assets=Assets(
            logo=str(assets.get("logo") or ""),
            splash=str(assets.get("splash") or ""),
            pip_image=str(assets.get("pip_image") or ""),
        ),
        assets_dir=str(data.get("assets_dir") or ""),
        out_dir=str(data.get("out_dir") or ""),
        flow_project_url=str(data.get("flow_project_url") or ""),
        flow_profile_dir=str(data.get("flow_profile_dir") or ""),
    )
    if cfg.schema_version != SCHEMA_VERSION:
        raise BrandConfigError(f"unsupported schema_version {cfg.schema_version}")
    if cfg.endcard_mode not in ("splash", "static"):
        raise BrandConfigError("endcard_mode must be splash or static")
    return cfg


def default_path() -> Path:
    return HERE / "brands" / "buzzit.json"


def to_dict(cfg: BrandConfig) -> dict[str, Any]:
    return asdict(cfg)
