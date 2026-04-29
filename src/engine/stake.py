from __future__ import annotations

import json as _json
import pathlib as _pathlib
from typing import Any


def _load_stake_weights() -> dict:
    """Load stake parameters from data/config/weights.json with hardcoded fallback."""
    here = _pathlib.Path(__file__).resolve()
    for parent in [
        here.parent,
        here.parent.parent,
        here.parent.parent.parent,
        here.parent.parent.parent.parent,
    ]:
        candidate = parent / "data" / "config" / "weights.json"
        if candidate.exists():
            try:
                with candidate.open(encoding="utf-8") as _f:
                    loaded = _json.load(_f)
                stake_weights = loaded.get("stake", {})
                return stake_weights if isinstance(stake_weights, dict) else {}
            except (FileNotFoundError, _json.JSONDecodeError):
                break
    return {}


_SW = _load_stake_weights()
FRACTIONAL_KELLY: float = _SW.get("fractional_kelly", 0.5)
BET_UNIT_YEN: int = int(_SW.get("bet_unit_yen", 100))
DEFAULT_BUDGET_YEN: int = int(_SW.get("default_budget_yen", 1200))


def normalize_stakes(
    *,
    candidates: list[dict[str, Any]],
    budget: int,
    budget_source: str,
) -> dict[str, Any]:
    target_budget = budget if budget > 0 else DEFAULT_BUDGET_YEN
    total_units = target_budget // BET_UNIT_YEN
    if total_units <= 0:
        raise ValueError("Budget is too small for 100-yen betting units")

    selected = candidates[: min(3, total_units)]
    weighted = []
    for candidate in selected:
        weight = max(float(candidate["kelly_fraction"]) * FRACTIONAL_KELLY, 0.000001)
        weighted.append((candidate, weight))

    total_weight = sum(weight for _, weight in weighted)
    if total_weight <= 0:
        raise ValueError("No positive Kelly weights")

    unit_allocations = []
    assigned_units = 0
    for candidate, weight in weighted:
        raw_units = (weight / total_weight) * total_units
        base_units = int(raw_units)
        unit_allocations.append(
            {
                "candidate": candidate,
                "raw_units": raw_units,
                "base_units": base_units,
                "remainder": raw_units - base_units,
            }
        )
        assigned_units += base_units

    remaining_units = total_units - assigned_units
    for item in sorted(unit_allocations, key=lambda record: record["remainder"], reverse=True):
        if remaining_units <= 0:
            break
        item["base_units"] += 1
        remaining_units -= 1

    bets = []
    for item in unit_allocations:
        stake_yen = item["base_units"] * BET_UNIT_YEN
        if stake_yen <= 0:
            continue
        candidate = item["candidate"]
        bets.append(
            {
                "bet_type": candidate["bet_type"],
                "number": candidate["number"],
                "name": candidate["name"],
                "stake_yen": stake_yen,
                "odds": candidate["odds"],
                "expected_value": candidate["expected_value"],
                "kelly_fraction": candidate["kelly_fraction"],
            }
        )

    total_stake = sum(item["stake_yen"] for item in bets)
    return {
        "budget_yen": target_budget,
        "budget_source": budget_source,
        "fractional_kelly": FRACTIONAL_KELLY,
        "bet_unit_yen": BET_UNIT_YEN,
        "bets": bets,
        "total_stake": total_stake,
    }
