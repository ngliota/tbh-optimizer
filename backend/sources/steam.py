"""Steam Community Market prices for Taskbar Hero (appid 3678970).

Public endpoints, no auth. Heavily rate-limited and cached to prices.json; only refreshed
on an explicit call. The /market/search/render endpoint returns the full tradeable catalog
with sell prices in one shot, which we use as the primary source.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

APPID = 3678970
USER_AGENT = "tbh-optimizer/1.0 (personal read-only dashboard)"
CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "prices.json"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def refresh(max_items: int = 500, page_size: int = 100, throttle: float = 3.0) -> dict:
    """Page through the market search render endpoint, caching {hash_name: price_cents}."""
    prices: dict[str, dict] = {}
    start = 0
    while start < max_items:
        url = (f"https://steamcommunity.com/market/search/render/"
               f"?appid={APPID}&norender=1&count={page_size}&start={start}")
        try:
            resp = _session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            return {"error": str(exc), "fetched": len(prices)}
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            prices[r["hash_name"]] = {
                "price_cents": r.get("sell_price"),
                "price_text": r.get("sell_price_text"),
                "listings": r.get("sell_listings"),
            }
        total = data.get("total_count", 0)
        start += page_size
        if start >= total:
            break
        time.sleep(throttle)   # be gentle with Steam
    payload = {"fetched_at": time.time(), "appid": APPID, "prices": prices}
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")
    return {"fetched": len(prices), "appid": APPID}


def load() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"fetched_at": None, "prices": {}}


def price_for(name: str) -> dict | None:
    return load().get("prices", {}).get(name)
