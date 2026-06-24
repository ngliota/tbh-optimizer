"""Monte-Carlo simulation of Taskbar Hero's interval-based chest drops.

Mechanic modelled (the empirically-supported interpretation, all params tunable):
  - A drop OPPORTUNITY becomes available every `drop_interval` seconds.
  - It stays catchable for `drop_window` seconds after it opens.
  - You CATCH an opportunity by completing a stage clear while the window is open
    (clears complete every `clear_time` seconds).
  - On a catch you roll a success with probability derived from your drop-rate %.
    Rate has diminishing returns (so 500% -> 750% adds only a little), and frequency
    is hard-capped by the interval -> this is why drop-rate runes are weak.

This reproduces the reference chart's two signatures: the sawtooth vs clear time
(window/clear-cadence phase aliasing) and the compressed rate bands.

These defaults are ASSUMPTIONS. Override `drop_interval`/`drop_window`/`base_catch`
with values measured in the Drop Test — measured beats modelled.
"""
from __future__ import annotations

import random
from statistics import mean

# Defaults chosen to land in the reference chart's ~5-8 drops/hr range.
DEFAULTS = {
    "drop_interval": 430.0,   # s between opportunities  (3600/430 ~= 8.4/hr cap)
    "drop_window": 110.0,     # s an opportunity stays catchable
    "base_catch": 0.92,       # per-catch base success at ref_rate (diminishing w/ rate above)
    "ref_rate": 500.0,        # rate_pct at which base_catch applies
    "clear_jitter": 0.10,     # +/- fractional gaussian jitter on each clear's duration
    "duration": 3600.0,       # 1 hour
    "trials": 100,
}


def _catch_probability(rate_pct: float, base_catch: float, ref_rate: float) -> float:
    """Success prob for a caught opportunity, with diminishing returns above ref_rate."""
    # At ref_rate -> base_catch; higher rate closes the remaining gap to 1 with sqrt falloff.
    extra = max(rate_pct - ref_rate, 0.0) / ref_rate
    return min(0.99, base_catch + (1.0 - base_catch) * (1.0 - 1.0 / (1.0 + 0.6 * extra)))


def simulate_one(clear_time: float, rate_pct: float, *, drop_interval: float, drop_window: float,
                 base_catch: float, ref_rate: float, clear_jitter: float, duration: float,
                 rng: random.Random) -> int:
    p = _catch_probability(rate_pct, base_catch, ref_rate)
    drops = 0
    opp_open = drop_interval     # opportunities open on a FIXED cadence (not reset by catches)
    caught = False               # at most one catch per opportunity
    tc = 0.0
    while tc <= duration:
        step = clear_time * (1.0 + rng.gauss(0.0, clear_jitter)) if clear_jitter else clear_time
        tc += max(step, 1.0)
        # advance past any opportunities whose window has fully closed
        while tc > opp_open + drop_window:
            opp_open += drop_interval
            caught = False
        # if this clear lands inside the current open window, try to catch it (once)
        if opp_open <= tc <= opp_open + drop_window and not caught:
            if rng.random() < p:
                drops += 1
            caught = True
    return drops


def average_drops(clear_time: float, rate_pct: float, *, trials: int | None = None, **kw) -> float:
    params = {**DEFAULTS, **kw}
    trials = trials or params["trials"]
    rng = random.Random(int(clear_time * 1000 + rate_pct))   # reproducible per cell
    vals = [simulate_one(clear_time, rate_pct,
                         drop_interval=params["drop_interval"], drop_window=params["drop_window"],
                         base_catch=params["base_catch"], ref_rate=params["ref_rate"],
                         clear_jitter=params["clear_jitter"], duration=params["duration"],
                         rng=rng) for _ in range(trials)]
    return round(mean(vals), 2)


def sweep(clear_times: list[float], rates: list[float],
          highlight: dict[float, str] | None = None, **kw) -> dict:
    """Build chart-ready data: one series per rate, plus a table (rows = clear_time).

    `highlight` maps a rate value -> label (e.g. {361: "your common chest"}); those series
    are flagged `yours: True` so the frontend can emphasise them.
    """
    highlight = highlight or {}
    series = []
    for r in rates:
        series.append({"rate": r, "points": [average_drops(ct, r, **kw) for ct in clear_times],
                       "yours": r in highlight, "label": highlight.get(r)})
    table = []
    for i, ct in enumerate(clear_times):
        row = {"clear_time": ct}
        for s in series:
            row[str(int(s["rate"]))] = s["points"][i]
        table.append(row)
    return {
        "clear_times": clear_times,
        "rates": rates,
        "series": series,
        "table": table,
        "params": {**DEFAULTS, **kw},
    }


def default_sweep(rates: list[float] | None = None, highlight: dict[float, str] | None = None,
                  **kw) -> dict:
    clear_times = [float(x) for x in range(70, 240, 10)]
    rates = rates if rates else [500.0, 550.0, 600.0, 650.0, 700.0, 750.0]
    return sweep(clear_times, sorted(set(rates)), highlight=highlight, **kw)
