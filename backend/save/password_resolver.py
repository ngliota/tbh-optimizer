"""Resolve the current ES3 decryption password for Taskbar Hero saves.

The password is a constant baked into the game, but the game devs rotate it on updates
(the community tool's own code says "password can change after a game update"). We try a
known constant first, then auto-recover it from the public client-side JS of the wiki tool
exactly the way it was found by hand:

    GET /_app/immutable/entry/app.<hash>.js   -> enumerate ../chunks/*.js
    fetch each chunk, find the one containing `PBKDF2` + `AES-CBC`
    extract the module-level  var e=`<password>`  literal

The resolved password is cached to disk (with the game version it worked for) so we don't
hit the network on every launch.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

# Known-good as of game v1.00.19 (sourced from taskbarhero.wiki/my-save client-side JS).
KNOWN_PASSWORD = "emuMqG3bLYJ938ZDCfieWJ"

WIKI_BASE = "https://taskbarhero.wiki"
USER_AGENT = "tbh-optimizer/1.0 (personal read-only dashboard; contact: local user)"
CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "password_cache.json"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _load_cache() -> str | None:
    try:
        return json.loads(CACHE_FILE.read_text()).get("password")
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(password: str, game_version: str | None) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"password": password, "game_version": game_version}))
    except OSError:
        pass


def scrape_password_from_wiki(timeout: int = 20) -> str | None:
    """Best-effort recovery of the current password from the wiki tool's JS bundle."""
    try:
        page = _session.get(f"{WIKI_BASE}/my-save", timeout=timeout).text
        m = re.search(r"/_app/immutable/entry/app\.[A-Za-z0-9_]+\.js", page)
        if not m:
            return None
        app_js = _session.get(f"{WIKI_BASE}{m.group(0)}", timeout=timeout).text
        chunks = sorted(set(re.findall(r"chunks/([A-Za-z0-9_.-]+\.js)", app_js)))
        for chunk in chunks:
            body = _session.get(f"{WIKI_BASE}/_app/immutable/chunks/{chunk}", timeout=timeout).text
            if "PBKDF2" in body and "AES-CBC" in body:
                # The decrypt module defines  var e=`<password>`  as the default password.
                pw = re.search(r"var\s+\w+=`([A-Za-z0-9]{12,40})`[^`]*decryption", body)
                if pw:
                    return pw.group(1)
                # Fallback: first backtick literal that precedes the PBKDF2 importKey call.
                pw = re.search(r"var\s+\w+=`([A-Za-z0-9]{12,40})`", body)
                if pw:
                    return pw.group(1)
    except requests.RequestException:
        return None
    return None


def resolve_password(test_buf: bytes | None = None, game_version: str | None = None) -> str:
    """Return a working password. If `test_buf` is given, validates candidates against it.

    Order: cached -> known constant -> live scrape. Caches whatever works.
    """
    from .es3 import ES3Error, decrypt_to_text  # local import to avoid cycle

    def works(pw: str) -> bool:
        if not pw:
            return False
        if test_buf is None:
            return True
        try:
            text = decrypt_to_text(test_buf, pw)
            return text.lstrip().startswith("{")
        except ES3Error:
            return False

    for candidate in (_load_cache(), KNOWN_PASSWORD):
        if candidate and works(candidate):
            _save_cache(candidate, game_version)
            return candidate

    scraped = scrape_password_from_wiki()
    if scraped and works(scraped):
        _save_cache(scraped, game_version)
        return scraped

    raise RuntimeError(
        "Could not resolve the ES3 password. The game may have rotated it after an update; "
        "the wiki tool's JS structure may have changed. Check taskbarhero.wiki/my-save."
    )
