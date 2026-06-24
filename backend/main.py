"""TBH Optimizer — FastAPI backend serving the dashboard + live save data.

Run:  .venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
Open: http://localhost:8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from backend.model import advisor, mystats, optimizer, simulator
from backend.save.snapshots import SnapshotStore
from backend.sources import steam, wiki

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

store = SnapshotStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.poll_once()   # prime once so the UI has data immediately (and resolves password)
    store.start()
    yield
    store.stop()


app = FastAPI(title="TBH Optimizer", lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/status")
def status():
    return {
        "save_path": str(store.save_path),
        "save_exists": store.save_path.exists(),
        "password_resolved": store.password is not None,
        "snapshots": len(store.snapshots),
        "events": len(store.events),
        "interval_s": store.interval,
        "last_error": store.last_error,
        "provenance": "save (live, decrypted locally via community ES3 method)",
    }


def _enrich(snap: dict | None) -> dict | None:
    """Add human names/labels (hero names, current/max stage labels) to a snapshot."""
    if not snap:
        return snap
    for h in snap.get("heroes", []):
        h["name"] = wiki.hero_name(h.get("heroKey"))
    if snap.get("current_stage_key") is not None:
        snap["current_stage_label"] = wiki.stage_label(snap["current_stage_key"])
    if snap.get("max_completed_stage") is not None:
        snap["max_stage_label"] = wiki.stage_label(snap["max_completed_stage"])
    return snap


@app.get("/api/live")
def live():
    return {
        "snapshot": _enrich(store.latest()),
        "rates": store.rates(),
        "provenance": {"totals": "save (live)", "rates": "save-diff (observed)",
                       "names": "wiki (scraped)"},
    }


@app.get("/api/history")
def history(limit: int = Query(720, ge=2, le=4320)):
    return {"series": store.history(limit), "provenance": "save (live)"}


@app.get("/api/events")
def events(limit: int = Query(200, ge=1, le=2000)):
    return {"events": store.recent_events(limit), "provenance": "save-diff (observed)"}


def _stats_rates(stats: dict) -> tuple[list[float] | None, dict[float, str], dict]:
    """Turn the player's Stat List into chart rate bands + emphasis + context.

    'Increased drop chance X%' is a +X% multiplier => effective rate = 100 + X (so the
    sim's rate_pct axis matches the in-game stat). Auto-open times / capacities don't change
    the interval-gated drop frequency, so they ride along as labelled context, not model inputs.
    """
    rates: list[float] = []
    highlight: dict[float, str] = {}
    common = stats.get("common_chest_drop_pct")
    boss = stats.get("stageboss_chest_drop_pct")
    if common:
        r = 100.0 + float(common)
        rates.append(r); highlight[r] = f"your common chest (+{int(common)}%)"
    if boss:
        r = 100.0 + float(boss)
        rates.append(r); highlight[r] = f"your stage-boss chest (+{int(boss)}%)"
    # a couple of reference bands below the player's values for comparison
    if rates:
        lo = min(rates)
        rates += [round(lo * f) for f in (0.5, 0.75)]
    context = {k: stats[k] for k in (
        "autoopen_normal_s", "autoopen_stageboss_s", "autoopen_act_s",
        "common_chest_capacity", "stageboss_chest_capacity", "offline_gold_pct") if k in stats}
    return (sorted(set(rates)) or None), highlight, context


@app.get("/api/simulate")
def simulate(
    drop_interval: float | None = None,
    drop_window: float | None = None,
    base_catch: float | None = None,
    clear_jitter: float | None = None,
    trials: int = Query(100, ge=10, le=1000),
    use_stats: bool = True,
):
    overrides = {k: v for k, v in {
        "drop_interval": drop_interval, "drop_window": drop_window,
        "base_catch": base_catch, "clear_jitter": clear_jitter, "trials": trials,
    }.items() if v is not None}
    rates, highlight, context = (None, None, {})
    if use_stats:
        rates, highlight, context = _stats_rates(mystats.load())
    data = simulator.default_sweep(rates=rates, highlight=highlight, **overrides)
    data["uses_stats"] = bool(rates)
    data["stats_context"] = context
    data["provenance"] = ("model; rate bands from your Stat List drop-chance "
                          if rates else "model (assumption; ") + \
                          "override interval/window with Drop Test measurements)"
    return JSONResponse(data)


@app.get("/api/optimizer")
def optimize(goal: str = "gold", drop_interval: float = optimizer.DEFAULT_INTERVAL,
             clear_time: float = 90.0, shared_cooldown: bool | None = None,
             use_stats: bool = True):
    snap = store.latest()
    max_stage = snap.get("max_completed_stage") if snap else None
    stats = mystats.load() if use_stats else None
    return optimizer.rank_stages(goal=goal, drop_interval=drop_interval, clear_time=clear_time,
                                 max_completed_stage=max_stage, shared_cooldown=shared_cooldown,
                                 stats=stats)


def _raw_snapshot():
    with store._lock:
        return store.snapshots[-1] if store.snapshots else None


@app.get("/api/advisor")
def advise():
    raw = _raw_snapshot()
    if raw is None:
        return JSONResponse({"error": "no snapshot yet"}, status_code=503)
    return advisor.analyze(raw)


@app.post("/api/advisor/targets/from-current")
def targets_from_current():
    raw = _raw_snapshot()
    if raw is None:
        return JSONResponse({"error": "no snapshot yet"}, status_code=503)
    advisor.set_targets_to_current(raw)
    return advisor.analyze(raw)


@app.post("/api/advisor/targets/reset")
def targets_reset():
    advisor.reset_targets()
    raw = _raw_snapshot()
    return advisor.analyze(raw) if raw else {"ok": True}


@app.get("/api/stats")
def get_stats():
    return {"fields": mystats.FIELDS, "values": mystats.load(),
            "provenance": "manual (typed from the in-game Stat List)",
            "note": "The Stat List is computed by the game at runtime and is not stored in the "
                    "save, so it can't be auto-read. These few numbers feed the Optimizer/Simulator."}


class StatsIn(BaseModel):
    values: dict


@app.post("/api/stats")
def set_stats(body: StatsIn):
    return {"values": mystats.save(body.values or {})}


@app.post("/api/refresh/wiki")
def refresh_wiki():
    return {"result": wiki.refresh()}


@app.post("/api/refresh/steam")
def refresh_steam():
    return {"result": steam.refresh()}


@app.get("/api/catalog/status")
def catalog_status():
    return {
        "wiki": {name: wiki.meta(name) for name in ("items", "stages", "drops", "grades")},
        "steam": {"fetched_at": steam.load().get("fetched_at"),
                  "count": len(steam.load().get("prices", {}))},
    }


# Static assets (if any are added later); index is served at "/".
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
