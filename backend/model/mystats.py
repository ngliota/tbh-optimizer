"""Persisted 'Stat List' numbers, typed in manually from the in-game Stat List screen.

WHY MANUAL: the global Stat List (e.g. "190% Increased Gold Per Kill",
"361% Increased Common Chest Drop Chance", "Gold From Stage Boss Kill +43180",
"Auto-Open Stage Boss Chest Time -75s") is a value the game COMPUTES at runtime from
cube alchemy + the attribute tree + runes + gear. It is NOT stored as a flat list in the
save, and the wiki's attribute/recipe JSON only defines tree *structure*, not effect
magnitudes — so it cannot be auto-derived. But these numbers ARE the simulator/optimizer
input parameters, so letting the user type the handful that matter makes those tabs reflect
their actual character. Provenance is always 'manual (in-game Stat List)'.

LIVE gold/hr stays ground truth (measured from save-diffs); these never override it.
"""
from __future__ import annotations

import json
from pathlib import Path

STATS_FILE = Path(__file__).resolve().parents[2] / "data" / "my_stats.json"

# Fields the optimizer/simulator can actually consume, with the in-game label.
FIELDS = {
    "gold_stage_boss":   "Gold From Stage Boss Kill (+)",
    "gold_act_boss":     "Gold From Act Boss Kill (+)",
    "exp_stage_boss":    "Exp From Stage Boss Kill (+)",
    "exp_act_boss":      "Exp From Act Boss Kill (+)",
    "common_chest_drop_pct":     "Increased Common Chest Drop Chance (%)",
    "stageboss_chest_drop_pct":  "Increased Stage Boss Chest Drop Chance (%)",
    "autoopen_normal_s":         "Auto-Open Normal Chest Time (-s)",
    "autoopen_stageboss_s":      "Auto-Open Stage Boss Chest Time (-s)",
    "autoopen_act_s":            "Auto-Open Act Boss Chest Time (-s)",
    "common_chest_capacity":     "Common Chest Max Capacity (+)",
    "stageboss_chest_capacity":  "Stage Boss Chest Max Capacity (+)",
    "offline_gold_pct":          "Offline Reward Gold (%)",
}


def load() -> dict:
    try:
        data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(values: dict) -> dict:
    """Persist only known fields, coercing to numbers; ignore junk."""
    clean: dict[str, float] = {}
    for k in FIELDS:
        if k in values and values[k] not in (None, ""):
            try:
                clean[k] = float(values[k])
            except (TypeError, ValueError):
                continue
    STATS_FILE.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean
