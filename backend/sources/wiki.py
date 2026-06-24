"""Reference catalog from taskbarhero.wiki's static JSON API (cached, refresh-only).

The wiki serves plain JSON at /data/*.json and /data/t/*.json (confirmed: Allow:/ in
robots.txt; this is personal reference use, not training). No scraping/headless browser
needed. We cache raw responses and only re-fetch on an explicit refresh.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

WIKI_BASE = "https://taskbarhero.wiki"
USER_AGENT = "tbh-optimizer/1.0 (personal read-only dashboard)"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "catalog"

# Catalog files we use, mapped to local cache names.
FILES = {
    "items": "/data/items.json",
    "items_detail": "/data/items_detail.json",
    "stages": "/data/stages.json",
    "heroes": "/data/heroes.json",
    "monsters": "/data/monsters.json",
    "grades": "/data/grades.json",
    "gear_types": "/data/gear_types.json",
    "runes": "/data/runes.json",
    "drops": "/data/t/drops.json",        # loot-table weights
    "materials": "/data/t/materials.json",
}

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def refresh(throttle: float = 0.5) -> dict:
    """Fetch all catalog files to cache. Returns {name: count|error}. Refresh-only."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, path in FILES.items():
        try:
            resp = _session.get(f"{WIKI_BASE}{path}", timeout=30)
            resp.raise_for_status()
            data = resp.json()
            payload = {"fetched_at": time.time(), "source": f"{WIKI_BASE}{path}", "data": data}
            _cache_path(name).write_text(json.dumps(payload), encoding="utf-8")
            result[name] = len(data) if hasattr(data, "__len__") else "ok"
        except (requests.RequestException, ValueError) as exc:
            result[name] = f"error: {exc}"
        time.sleep(throttle)
    _reset_indexes()
    return result


def load(name: str) -> dict | list | None:
    """Load a cached catalog file's `data`, or None if not cached."""
    try:
        return json.loads(_cache_path(name).read_text(encoding="utf-8"))["data"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def meta(name: str) -> dict:
    try:
        p = json.loads(_cache_path(name).read_text(encoding="utf-8"))
        return {"fetched_at": p.get("fetched_at"), "source": p.get("source"),
                "version": _detect_version()}
    except (OSError, json.JSONDecodeError):
        return {"fetched_at": None, "source": FILES.get(name), "version": None}


def _detect_version() -> str | None:
    """Best-effort game version stamp (the save carries it; wiki tracks current build)."""
    return None


def items_by_key() -> dict[int, dict]:
    """Index items.json by `id` (== the save's ItemKey) for equipped-gear lookups."""
    items = load("items") or []
    out = {}
    for it in items if isinstance(items, list) else items.values():
        key = it.get("id")
        if key is not None:
            out[key] = it
    return out


def grade_rank() -> dict[str, int]:
    """Map GRADE name -> ordinal (higher = better), from grades.json order."""
    grades = load("grades") or []
    return {g["GRADE"]: i for i, g in enumerate(grades) if "GRADE" in g}


def item_name(it: dict) -> str:
    n = it.get("name")
    if isinstance(n, dict):
        return n.get("en-US") or next(iter(n.values()), "?")
    return n or "?"


def _en(name) -> str | None:
    """Pull the en-US string from an i18n dict (or pass through a plain string)."""
    if isinstance(name, dict):
        return name.get("en-US") or next(iter(name.values()), None)
    return name


# Stage key scheme (verified): key = difficulty*1000 + act*100 + no.
#   1=NORMAL, 2=NIGHTMARE, 3=HELL, 4=TORMENT ; no==10 is the act boss.
DIFFICULTY = {1: "Normal", 2: "Nightmare", 3: "Hell", 4: "Torment"}

_heroes_idx: dict | None = None
_stages_idx: dict | None = None


def hero_name(hero_key: int | str | None) -> str:
    """Map a heroKey (101..601) to its English name. Falls back to 'Hero <key>'."""
    global _heroes_idx
    if _heroes_idx is None:
        _heroes_idx = {}
        for h in (load("heroes") or []):
            _heroes_idx[h.get("HeroKey")] = _en(h.get("HeroNameKey_i18n"))
    try:
        hk = int(hero_key)
    except (TypeError, ValueError):
        return f"Hero {hero_key}"
    return _heroes_idx.get(hk) or f"Hero {hk}"


def stage_by_key(key: int | None) -> dict | None:
    global _stages_idx
    if _stages_idx is None:
        _stages_idx = {s.get("key"): s for s in (load("stages") or [])}
    return _stages_idx.get(key)


def stage_label(stage_or_key) -> str:
    """Human label disambiguating the 4 difficulties, e.g.
    'Torment · Act 3-9 · Core of the Abyss'. Accepts a stage dict or a key."""
    s = stage_or_key if isinstance(stage_or_key, dict) else stage_by_key(stage_or_key)
    if not s:
        return str(stage_or_key) if stage_or_key is not None else "—"
    diff = DIFFICULTY.get((s.get("key", 0) // 1000), str(s.get("difficulty", "?")).title())
    name = _en(s.get("name")) or "?"
    return f"{diff} · Act {s.get('act')}-{s.get('no')} · {name}"


def _reset_indexes() -> None:
    """Drop cached indexes so a catalog refresh is picked up."""
    global _heroes_idx, _stages_idx
    _heroes_idx = None
    _stages_idx = None
