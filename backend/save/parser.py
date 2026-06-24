"""Normalize a decrypted Taskbar Hero save into a flat, stable snapshot model.

All field locations were confirmed firsthand against a real save (game v1.00.19):
  PlayerSaveData.currenySaveDatas  -> [{Key, Quantity}]            (gold = Key 100001)
  PlayerSaveData.commonSaveData    -> version/maxCompletedStage/currentStageKey/...
  PlayerSaveData.heroSaveDatas     -> [{heroKey, HeroLevel, HeroExp, equippedItemIds[10], ...}]
  PlayerSaveData.itemSaveDatas     -> [{ItemKey, UniqueId, EnchantData, ...}]
  PlayerSaveData.inventorySaveDatas-> [{Index, ItemUniqueId, ...}]
  PlayerSaveData.BoxData           -> {BoxTypes[], BoxUniqueId[], BoxQuantity[]}  (unopened chests)
  PlayerSaveData.aggregateSaveDatas-> [{Type, SubKey, Value}]      (113 lifetime counters)
"""
from __future__ import annotations

import time
from typing import Any

GOLD_KEY = 100001


def _section(player: dict, name: str, default: Any) -> Any:
    val = player.get(name, default)
    return val if val is not None else default


def normalize(save: dict) -> dict:
    """Turn a decrypted+unwrapped save dict into a normalized snapshot."""
    player = save.get("PlayerSaveData", {}) or {}
    account = save.get("AccountSaveData", {}) or {}
    common = _section(player, "commonSaveData", {})

    currencies = {c["Key"]: c["Quantity"] for c in _section(player, "currenySaveDatas", [])}

    items_by_id: dict[int, dict] = {}
    for it in _section(player, "itemSaveDatas", []):
        uid = it.get("UniqueId")
        if uid is not None:
            items_by_id[uid] = it

    heroes = []
    for h in _section(player, "heroSaveDatas", []):
        heroes.append({
            "heroKey": h.get("heroKey"),
            "level": h.get("HeroLevel"),
            "exp": h.get("HeroExp"),
            "unlocked": h.get("IsUnLock"),
            "equippedItemIds": h.get("equippedItemIds", []),
        })

    box = _section(player, "BoxData", {}) or {}
    box_qty = box.get("BoxQuantity", []) or []
    boxes = {
        "types": box.get("BoxTypes", []) or [],
        "uniqueIds": box.get("BoxUniqueId", []) or [],
        "quantities": box_qty,
        "total": sum(box_qty),
    }

    aggregates = {
        f"{a['Type']}:{a['SubKey']}": a["Value"]
        for a in _section(player, "aggregateSaveDatas", [])
        if "Type" in a and "SubKey" in a and "Value" in a
    }

    return {
        "captured_at": time.time(),
        "game_version": common.get("version") or account.get("version"),
        "last_saved_time": common.get("lastSavedTime"),
        "play_time": common.get("playTime") or account.get("playTime"),
        "gold": currencies.get(GOLD_KEY),
        "currencies": currencies,
        "max_completed_stage": common.get("maxCompletedStage"),
        "current_stage_key": common.get("currentStageKey"),
        "current_stage_wave": common.get("currentStageWave"),
        "arranged_hero_key": common.get("arrangedHeroKey"),
        "heroes": heroes,
        "item_count": len(items_by_id),
        "inventory_count": len(_section(player, "inventorySaveDatas", [])),
        "boxes": boxes,
        "aggregates": aggregates,
        # Raw item map kept for the Build Advisor's equipped-gear -> grade join.
        "_items_by_id": items_by_id,
        "owner_steam_id": account.get("ownerSteamId"),
        "player_id": account.get("playerId"),
    }
