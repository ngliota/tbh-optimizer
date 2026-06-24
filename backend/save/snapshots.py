"""Gentle save polling, timestamped snapshot store, and diffing -> drop/gain events.

Safety (non-negotiable, per project constraints):
  - Never lock or modify the live save. Copy-then-parse only.
  - Validate that a copy decrypts+parses as COMPLETE data before using it; discard and
    retry on truncated / mid-write reads (Easy Save 3 can be caught mid-write).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

from .es3 import ES3Error, decrypt_save
from .parser import normalize
from .password_resolver import resolve_password

DEFAULT_SAVE_PATH = Path(
    os.path.expandvars(r"%USERPROFILE%\AppData\LocalLow\TesseractStudio\TaskbarHero\SaveFile_Live.es3")
)


def read_snapshot(save_path: Path, password: str) -> dict | None:
    """Copy-then-parse one snapshot. Returns None on a truncated/mid-write read."""
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".es3")
    os.close(tmp_fd)
    try:
        # shutil.copy opens the source with shared read access (no exclusive lock).
        shutil.copy2(save_path, tmp_name)
        buf = Path(tmp_name).read_bytes()
        if len(buf) <= 16:
            return None
        return normalize(decrypt_save(buf, password))
    except (ES3Error, OSError, ValueError):
        return None  # mid-write / truncated / transient — caller retries
    finally:
        try:
            os.remove(tmp_name)
        except OSError:
            pass


def diff(prev: dict, cur: dict) -> dict:
    """Compute attributable deltas between two snapshots -> a drop/gain event record."""
    gold_delta = (cur.get("gold") or 0) - (prev.get("gold") or 0)

    prev_ids = set(prev.get("_items_by_id", {}))
    cur_ids = set(cur.get("_items_by_id", {}))
    gained = [cur["_items_by_id"][i] for i in (cur_ids - prev_ids)]
    lost_ids = list(prev_ids - cur_ids)

    box_delta = cur["boxes"]["total"] - prev["boxes"]["total"]

    agg_changes = {}
    pa, ca = prev.get("aggregates", {}), cur.get("aggregates", {})
    for k, v in ca.items():
        if v != pa.get(k):
            agg_changes[k] = v - pa.get(k, 0)

    hero_exp = {}
    prev_h = {h["heroKey"]: h for h in prev.get("heroes", [])}
    for h in cur.get("heroes", []):
        ph = prev_h.get(h["heroKey"])
        if ph and (h.get("exp") or 0) != (ph.get("exp") or 0):
            hero_exp[h["heroKey"]] = (h.get("exp") or 0) - (ph.get("exp") or 0)

    return {
        "t_prev": prev["captured_at"],
        "t_cur": cur["captured_at"],
        "dt": cur["captured_at"] - prev["captured_at"],
        "gold_delta": gold_delta,
        "items_gained": [{"ItemKey": it.get("ItemKey"), "UniqueId": it.get("UniqueId")} for it in gained],
        "items_lost": lost_ids,
        "box_delta": box_delta,
        "hero_exp_delta": hero_exp,
        "aggregate_deltas": agg_changes,
    }


class SnapshotStore:
    """Background poller holding a rolling history of snapshots + derived events."""

    def __init__(self, save_path: Path | None = None, interval: float = 5.0, maxlen: int = 4320):
        self.save_path = Path(save_path) if save_path else DEFAULT_SAVE_PATH
        self.interval = interval
        self.snapshots: deque[dict] = deque(maxlen=maxlen)   # ~6h at 5s
        self.events: deque[dict] = deque(maxlen=5000)
        self.password: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def _ensure_password(self, buf_provider) -> None:
        if self.password is None:
            self.password = resolve_password(test_buf=buf_provider())

    def poll_once(self) -> dict | None:
        if not self.save_path.exists():
            self.last_error = f"save not found: {self.save_path}"
            return None
        if self.password is None:
            try:
                self.password = resolve_password(test_buf=self.save_path.read_bytes())
            except RuntimeError as exc:
                self.last_error = str(exc)
                return None
        snap = read_snapshot(self.save_path, self.password)
        if snap is None:
            return None
        with self._lock:
            prev = self.snapshots[-1] if self.snapshots else None
            self.snapshots.append(snap)
            if prev is not None:
                ev = diff(prev, snap)
                if any((ev["gold_delta"], ev["items_gained"], ev["items_lost"],
                        ev["box_delta"], ev["aggregate_deltas"])):
                    self.events.append(ev)
            self.last_error = None
        return snap

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # keep the poller alive
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._stop.wait(self.interval)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="snapshot-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ---- read helpers for the API ------------------------------------------------
    def latest(self) -> dict | None:
        with self._lock:
            return _public(self.snapshots[-1]) if self.snapshots else None

    def rates(self, window_s: float = 600.0) -> dict:
        """Gold/hr, EXP/hr, item-gain/hr over the most recent `window_s` seconds."""
        with self._lock:
            snaps = list(self.snapshots)
        if len(snaps) < 2:
            return {"gold_per_hr": None, "exp_per_hr": None, "items_per_hr": None, "samples": len(snaps)}
        cur = snaps[-1]
        cutoff = cur["captured_at"] - window_s
        base = next((s for s in snaps if s["captured_at"] >= cutoff), snaps[0])
        dt = cur["captured_at"] - base["captured_at"]
        if dt <= 0:
            return {"gold_per_hr": None, "exp_per_hr": None, "items_per_hr": None, "samples": len(snaps)}
        scale = 3600.0 / dt
        exp_base = sum(h.get("exp") or 0 for h in base["heroes"])
        exp_cur = sum(h.get("exp") or 0 for h in cur["heroes"])
        return {
            "gold_per_hr": round(((cur.get("gold") or 0) - (base.get("gold") or 0)) * scale),
            "exp_per_hr": round((exp_cur - exp_base) * scale),
            "items_per_hr": round((cur["item_count"] - base["item_count"]) * scale, 2),
            "window_s": round(dt), "samples": len(snaps),
        }

    def history(self, limit: int = 720) -> list[dict]:
        with self._lock:
            snaps = list(self.snapshots)[-limit:]
        total = lambda s: sum(h.get("exp") or 0 for h in s["heroes"])
        return [{"t": s["captured_at"], "gold": s.get("gold"), "exp": total(s),
                 "items": s["item_count"], "boxes": s["boxes"]["total"]} for s in snaps]

    def recent_events(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return list(self.events)[-limit:]


def _public(snap: dict) -> dict:
    """Strip the heavy raw item map before sending a snapshot to the client."""
    return {k: v for k, v in snap.items() if not k.startswith("_")}
