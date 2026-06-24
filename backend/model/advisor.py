"""Build Advisor — gap analysis of equipped gear vs an editable target loadout.

This is NOT an objective "best build": targets come from build_targets.json, which the
user edits / imports from a community tier list. We read EQUIPPED gear from the live save
(equippedItemIds -> itemSaveDatas.ItemKey -> wiki items.json grade/slot), compare to the
target grade per slot, and flag the weakest slots.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..sources import wiki

TARGETS_FILE = Path(__file__).resolve().parents[2] / "data" / "build_targets.json"


def _load_targets() -> dict:
    try:
        return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_targets(targets: dict) -> None:
    TARGETS_FILE.write_text(json.dumps(targets, indent=2), encoding="utf-8")


def set_targets_to_current(snapshot: dict) -> dict:
    """Snapshot the player's currently-equipped grades as the target per slot/hero.
    Useful as a 'lock in what I have' baseline the user can then raise."""
    items_cat = wiki.items_by_key()
    items_by_id = snapshot.get("_items_by_id", {})
    targets: dict[str, dict] = {}
    for hero in snapshot.get("heroes", []):
        hk = str(hero.get("heroKey"))
        per_slot: dict[str, str] = {}
        for uid in hero.get("equippedItemIds", []):
            if uid in (-1, 0, None):
                continue
            save_item = items_by_id.get(uid)
            cat = items_cat.get(save_item.get("ItemKey")) if save_item else None
            if not cat:
                continue
            gear = cat.get("gear") or cat.get("type")
            if gear and cat.get("grade"):
                per_slot[gear] = cat["grade"]
        targets[hk] = per_slot
    _save_targets(targets)
    return targets


def reset_targets() -> dict:
    """Clear all targets back to empty (gap analysis goes dormant until refilled)."""
    empty = {str(k): {} for k in (101, 201, 301, 401, 501, 601)}
    _save_targets(empty)
    return empty


def analyze(snapshot: dict) -> dict:
    """Compare each hero's equipped gear grades against target grades per slot/type."""
    items_cat = wiki.items_by_key()
    ranks = wiki.grade_rank()
    targets = _load_targets()
    items_by_id = snapshot.get("_items_by_id", {})

    heroes_out = []
    for hero in snapshot.get("heroes", []):
        hk = str(hero.get("heroKey"))
        target = targets.get(hk, {})           # {gear_type: target_grade}
        slots = []
        for uid in hero.get("equippedItemIds", []):
            if uid in (-1, 0, None):
                continue
            save_item = items_by_id.get(uid)
            if not save_item:
                continue
            cat = items_cat.get(save_item.get("ItemKey"))
            if not cat:
                continue
            gear = cat.get("gear") or cat.get("type")
            grade = cat.get("grade")
            tgt_grade = target.get(gear)
            gap = None
            if tgt_grade and grade in ranks and tgt_grade in ranks:
                gap = ranks[tgt_grade] - ranks[grade]
            slots.append({
                "gear": gear, "name": wiki.item_name(cat), "grade": grade,
                "target_grade": tgt_grade, "grade_gap": gap,
            })
        weakest = max((s for s in slots if s["grade_gap"]), key=lambda s: s["grade_gap"], default=None)
        # "What's my build" snapshot: grade counts across equipped slots.
        grade_counts: dict[str, int] = {}
        for s in slots:
            if s["grade"]:
                grade_counts[s["grade"]] = grade_counts.get(s["grade"], 0) + 1
        heroes_out.append({"heroKey": hero.get("heroKey"),
                           "name": wiki.hero_name(hero.get("heroKey")),
                           "level": hero.get("level"),
                           "equipped_count": len(slots),
                           "grade_counts": grade_counts,
                           "slots": slots, "weakest_slot": weakest})

    return {
        "heroes": heroes_out,
        "has_targets": bool(targets),
        "provenance": {"equipped": "save (live)", "grades": "wiki (scraped)",
                       "targets": "my assumption (editable build_targets.json)"},
        "note": "Targets are an editable assumption from build_targets.json, not an objective meta.",
    }
