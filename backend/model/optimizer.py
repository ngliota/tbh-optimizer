"""Interval-based farm optimizer.

Core idea (the mechanic changed): chest frequency is gated by `drop_interval`, NOT by
clear speed. So:
  chests_per_hour ~= min(3600 / drop_interval, 3600 / clear_time)   # interval caps it
and the lever is VALUE-PER-CHEST (higher stage tier = better loot), not clear count.

Continuous kill income (gold/EXP) still scales with clears, so we report both:
  - clear income/hr = perClear * clears_per_hour
  - chest yield/hr   = interval-gated chests * (value per chest)

Stage reference data (goldPerClear, expPerClear, boss) is from the wiki catalog; the
drop_interval should come from the Drop Test (measured beats the wiki/assumed default).
"""
from __future__ import annotations

from ..sources import wiki

DEFAULT_INTERVAL = 430.0   # s; override with measured value from the Drop Test


def _stage_clearable(stage: dict, max_completed: int | None) -> bool:
    # Stage keys are monotonic across difficulty/act/no (difficulty*1000 + act*100 + no),
    # and max_completed_stage is itself a key — so a plain key comparison is correct.
    if max_completed is None:
        return True
    return (stage.get("key") or 0) <= max_completed


def rank_stages(goal: str = "gold", drop_interval: float = DEFAULT_INTERVAL,
                clear_time: float = 90.0, max_completed_stage: int | None = None,
                shared_cooldown: bool | None = None, limit: int = 20,
                stats: dict | None = None) -> dict:
    """Rank clearable stages for a goal in {'gold','exp','chest_value'}.

    `stats` (optional) is the player's manually-entered Stat List numbers; when present,
    boss-gold/exp bonuses are added per clear so gold/EXP-per-hr reflect THEIR character.
    """
    stages = wiki.load("stages") or []
    clears_per_hr = 3600.0 / max(clear_time, 1.0)
    chests_per_hr = min(3600.0 / max(drop_interval, 1.0), clears_per_hr)
    stats = stats or {}
    g_stage_boss = float(stats.get("gold_stage_boss") or 0)
    g_act_boss = float(stats.get("gold_act_boss") or 0)
    e_stage_boss = float(stats.get("exp_stage_boss") or 0)
    e_act_boss = float(stats.get("exp_act_boss") or 0)

    rows = []
    for s in (stages if isinstance(stages, list) else stages.values()):
        if not _stage_clearable(s, max_completed_stage):
            continue
        is_act_boss = s.get("type") == "ACTBOSS"
        gpc = (s.get("goldPerClear") or 0) + (g_act_boss if is_act_boss else g_stage_boss)
        epc = (s.get("expPerClear") or 0) + (e_act_boss if is_act_boss else e_stage_boss)
        tier = s.get("level") or s.get("key") or 0
        rows.append({
            "key": s.get("key"),
            "name": wiki._en(s.get("name")),
            "label": wiki.stage_label(s),
            "difficulty": wiki.DIFFICULTY.get((s.get("key", 0) // 1000), s.get("difficulty")),
            "act": s.get("act"), "no": s.get("no"), "level": s.get("level"),
            "boss": is_act_boss,
            "gold_per_hr": round(gpc * clears_per_hr),
            "exp_per_hr": round(epc * clears_per_hr),
            "chests_per_hr": round(chests_per_hr, 2),
            # value-per-chest proxy = stage tier (better loot tables deeper in) until the
            # per-stage loot-table join is wired; clearly an assumption.
            "chest_value_proxy": tier,
            "chest_value_per_hr": round(tier * chests_per_hr),
        })

    keymap = {"gold": "gold_per_hr", "exp": "exp_per_hr", "chest_value": "chest_value_per_hr"}
    sort_key = keymap.get(goal, "gold_per_hr")
    rows.sort(key=lambda r: r[sort_key], reverse=True)

    notes = [
        "Chest frequency is interval-gated; clearing faster than the interval does NOT add chests.",
        "Drop-rate runes have reduced value — the interval caps drop frequency.",
        "Favor the highest stage you clear RELIABLY (survival > speed) for better loot tables.",
    ]
    if g_stage_boss or e_stage_boss:
        notes.insert(0, "Gold/EXP-per-hr include your Stat List boss bonuses (manual input).")
    rotation = _rotation_advice(shared_cooldown, rows[:3])
    best = rows[0] if rows else None
    return {
        "goal": goal, "drop_interval": drop_interval, "clear_time": clear_time,
        "chests_per_hr": round(chests_per_hr, 2),
        "best": best,
        "max_completed_stage": max_completed_stage,
        "ranking": rows[:limit], "notes": notes, "rotation": rotation,
        "uses_stats": bool(g_stage_boss or e_stage_boss),
        "provenance": {"stage_stats": "wiki (scraped)", "drop_interval": "Drop Test (measured) or assumption",
                       "chest_value_proxy": "my assumption (stage tier)",
                       "boss_bonuses": "manual (your in-game Stat List)" if stats else "n/a"},
    }


def _rotation_advice(shared_cooldown: bool | None, top: list[dict]) -> dict:
    if shared_cooldown is None:
        return {"verdict": "unknown",
                "advice": "Run the Drop Test's shared-vs-independent check first. "
                          "If cooldowns are independent, rotating stages runs parallel timers; "
                          "if shared, sit on the single best stage."}
    if shared_cooldown:
        return {"verdict": "shared",
                "advice": "Cooldown is shared — rotation does NOT help. Sit on the single best stage: "
                          + (top[0]["label"] if top else "n/a")}
    names = ", ".join(t["label"] or str(t["key"]) for t in top)
    return {"verdict": "independent",
            "advice": f"Cooldowns are independent — rotate to run parallel timers across: {names}. "
                      "Clear one until its drop, move to the next, return when the first timer expires."}
