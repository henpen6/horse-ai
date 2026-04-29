"""Portfolio template selector (v6.7.6 §5).

Selects Lv/Case template and builds a bet list from available odds data.
Uses extra_odds (quinella / wide / trifecta / trio) when available;
hard-stops when required odds are missing.
WIN-only fallback is reserved for candidate-insufficient cases.

Key mapping (fetch_extra_odds → portfolio):
  "quinella"  → 馬連   [{horses: [A, B], odds}]
  "wide"      → ワイド [{horses: [A, B], odds_min, odds_max}]
  "trio"      → 3連複  [{horses: [A, B, C], odds}]
  "trifecta"  → 3連単  [{horses: [A, B, C], odds}]
  "exacta"    → 馬単   [{horses: [A, B], odds}]  (ordered)
  "place"     → 複勝   [{horse, odds_min, odds_max}]
"""
from __future__ import annotations

from itertools import combinations, permutations
from typing import Any

from src.engine.hard_stop import HardStopCode

BET_UNIT = 100
DEFAULT_BUDGET = 1200
BUDGET = DEFAULT_BUDGET  # mutated under _BUDGET_LOCK by build_portfolio()

import threading as _threading
_BUDGET_LOCK = _threading.Lock()
UNITS = BUDGET // BET_UNIT  # 12

ODDS_RANGE_POLICY = "LOW"  # v6.8.3 §0.26-E: conservative


def build_portfolio(
    *,
    candidates: list[dict[str, Any]],
    race_level: dict[str, Any],
    axis_type: str,
    extra_odds: dict[str, Any] | None = None,
    budget: int | None = None,
) -> dict[str, Any]:
    """Build portfolio with optional budget override (Phase 2 strategy router).

    Thread-safe: BUDGET / UNITS module-level constants are mutated only
    while holding _BUDGET_LOCK so concurrent /sim_historical / /future
    requests with different budgets cannot corrupt each other. Reverts on
    exit even when a plan helper raises.
    """
    target_budget = DEFAULT_BUDGET if budget is None else int(budget)
    lv = race_level["lv"]
    extra_odds = extra_odds or {}

    global BUDGET, UNITS
    with _BUDGET_LOCK:
        prev_budget = BUDGET
        prev_units = UNITS
        BUDGET = target_budget
        UNITS = target_budget // BET_UNIT
        try:
            if lv == "Lv3":
                return _plan_lv3(candidates, axis_type, extra_odds)
            if lv == "Lv2":
                return _plan_lv2(candidates, axis_type, extra_odds)
            return _plan_lv1(candidates, extra_odds)
        finally:
            BUDGET = prev_budget
            UNITS = prev_units


# ---------------------------------------------------------------------------
# Odds lookup helpers
# ---------------------------------------------------------------------------

def _find_quinella_odds(extra_odds: dict, a: int, b: int) -> float | None:
    """Find 馬連 odds for pair [a, b] (order doesn't matter)."""
    pair = sorted([a, b])
    for item in extra_odds.get("quinella", []):
        if sorted(item["horses"]) == pair:
            return item["odds"]
    return None


def _find_wide_odds(extra_odds: dict, a: int, b: int) -> tuple[float, float] | None:
    """Find ワイド odds for pair [a, b]. Returns (min, max) or None."""
    pair = sorted([a, b])
    for item in extra_odds.get("wide", []):
        if sorted(item["horses"]) == pair:
            return item["odds_min"], item["odds_max"]
    return None


def _wide_odds_used(odds_min: float, _odds_max: float) -> float:
    """Apply ODDS_RANGE_POLICY to wide odds range. LOW = use min."""
    return odds_min


def _find_trifecta_odds(extra_odds: dict, a: int, b: int, c: int) -> float | None:
    """Find 3連単 odds for ordered [1st, 2nd, 3rd]."""
    target = [a, b, c]
    for item in extra_odds.get("trifecta", []):
        if item["horses"] == target:
            return item["odds"]
    return None


def _find_trio_odds(extra_odds: dict, a: int, b: int, c: int) -> float | None:
    """Find 3連複 odds for sorted [a, b, c] (order doesn't matter)."""
    target = sorted([a, b, c])
    for item in extra_odds.get("trio", []):
        if sorted(item["horses"]) == target:
            return item["odds"]
    return None


def _find_exacta_odds(extra_odds: dict, first: int, second: int) -> float | None:
    """Find 馬単 odds for ordered [1st, 2nd]."""
    target = [first, second]
    for item in extra_odds.get("exacta", []):
        if item["horses"] == target:
            return item["odds"]
    return None


def _required_odds_missing(reason: str) -> dict[str, Any]:
    return {
        "hard_stop": True,
        "hard_stop_code": HardStopCode.REQUIRED_ODDS_MISSING,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Lv3: Solid
# ---------------------------------------------------------------------------

def _plan_lv3(
    candidates: list[dict[str, Any]],
    axis_type: str,
    extra_odds: dict[str, Any],
) -> dict[str, Any]:
    notes: list[str] = []

    if axis_type == "A":
        # CaseA Plan-S: 3連単 6点 × 200円 = 1200円
        if len(candidates) < 4:
            notes.append("CaseA Plan-S: 候補4頭未満 → WIN軸集中に代替")
            return _win_heavy(candidates, lv="Lv3", case="A", notes=notes)

        if not extra_odds.get("trifecta"):
            return _required_odds_missing("Lv3 CaseA: 3連単オッズ未取得")
        else:
            top3 = candidates[:3]
            if len(top3) < 3:
                notes.append("CaseA Plan-S: 候補3頭未満 → WIN軸集中に代替")
                return _win_heavy(candidates, lv="Lv3", case="A", notes=notes)

            bets = []
            for perm in permutations([c["number"] for c in top3]):
                odds = _find_trifecta_odds(extra_odds, perm[0], perm[1], perm[2])
                if odds is None:
                    continue
                names = {c["number"]: c["name"] for c in top3}
                bets.append({
                    "bet_type": "TRIFECTA",
                    "numbers": list(perm),
                    "label": f"{perm[0]}-{perm[1]}-{perm[2]}",
                    "name": f"{names[perm[0]]}→{names[perm[1]]}→{names[perm[2]]}",
                    "odds": odds,
                    "stake_yen": 200,
                })

            if len(bets) < 3:
                return _required_odds_missing(f"Lv3 CaseA: 3連単オッズ不足 ({len(bets)}点)")
            else:
                # Top 3 horses → 3!=6 permutations; keep up to 6
                bets = bets[:6]
                # Adjust stakes to total 1200
                for b in bets:
                    b["stake_yen"] = 200
                total = sum(b["stake_yen"] for b in bets)
                if total != BUDGET:
                    bets[0]["stake_yen"] += BUDGET - total

                return _multi_result("Lv3", "A", "Lv3 CaseA Plan-S（3連単6点）", bets, notes)

    # CaseB Plan-P: 馬連 7点 (1×300 + 3×200 + 3×100 = 1200円)
    others = candidates[1:8]  # up to 7 pairings
    if len(others) < 4:
        notes.append("CaseB Plan-P: 候補4頭未満 → WIN分散に代替")
        return _win_spread(candidates, lv="Lv3", case="B", n=3, notes=notes)

    if not extra_odds.get("quinella"):
        return _required_odds_missing("Lv3 CaseB: 馬連オッズ未取得")

    axis = candidates[0]
    bets = []
    for c in others:
        odds = _find_quinella_odds(extra_odds, axis["number"], c["number"])
        if odds is None:
            continue
        bets.append({
            "bet_type": "QUINELLA",
            "numbers": sorted([axis["number"], c["number"]]),
            "label": f"{min(axis['number'], c['number'])}-{max(axis['number'], c['number'])}",
            "name": f"{axis['name']}={c['name']}",
            "odds": odds,
            "stake_yen": 0,
        })

    if len(bets) < 4:
        return _required_odds_missing(f"Lv3 CaseB: 馬連オッズ不足 ({len(bets)}点)")

    # Sort by odds asc (lower odds = more likely partner), take top 7
    bets.sort(key=lambda b: b["odds"])
    bets = bets[:7]

    # Allocate: 1×300 + 3×200 + 3×100 = 1200
    stakes = [300] + [200] * min(3, len(bets) - 1) + [100] * max(0, len(bets) - 4)
    stakes = stakes[:len(bets)]
    # Pad if fewer than 7
    remaining = BUDGET - sum(stakes)
    if remaining > 0:
        stakes[0] += remaining
    for i, b in enumerate(bets):
        b["stake_yen"] = stakes[i] if i < len(stakes) else 100

    result = _multi_result("Lv3", "B", "Lv3 CaseB Plan-P（馬連7点）", bets, notes)
    if result["m_main"] < 3.0:
        notes.append(f"Lv3 CaseB: M_main={result['m_main']:.3f}<3.0 (PlanP_small threshold not met)")
    if result["m_floor"] < 1.0:
        notes.append(f"Lv3 CaseB: M_floor={result['m_floor']:.3f}<1.0 (M_floor警告)")
    return result


# ---------------------------------------------------------------------------
# Lv2: Standard
# ---------------------------------------------------------------------------

def _plan_lv2(
    candidates: list[dict[str, Any]],
    axis_type: str,
    extra_odds: dict[str, Any],
) -> dict[str, Any]:
    notes: list[str] = []
    axis = candidates[0]
    all_others = candidates[1:]

    if axis_type == "A":
        # CaseA: 馬連3点×200円 + 3連単(1着固定)6点×100円 = 1200円
        if len(all_others) < 2:
            notes.append("CaseA: 候補2頭未満で3連単構築不可 → WIN軸集中に代替")
            return _win_heavy(candidates, lv="Lv2", case="A", notes=notes)

        has_quinella = bool(extra_odds.get("quinella"))
        has_trifecta = bool(extra_odds.get("trifecta"))

        if not has_quinella and not has_trifecta:
            return _required_odds_missing("Lv2 CaseA: 馬連/3連単オッズ未取得")
        if not has_quinella:
            return _required_odds_missing("Lv2 CaseA: 馬連オッズ未取得")
        if not has_trifecta:
            return _required_odds_missing("Lv2 CaseA: 3連単オッズ未取得")

        bets = []

        # [コア] 馬連 3点 × 200円
        for c in all_others[:3]:
            odds = _find_quinella_odds(extra_odds, axis["number"], c["number"])
            if odds is None:
                continue
            bets.append({
                "bet_type": "QUINELLA",
                "numbers": sorted([axis["number"], c["number"]]),
                "label": f"{min(axis['number'], c['number'])}-{max(axis['number'], c['number'])}",
                "name": f"{axis['name']}={c['name']}",
                "odds": odds,
                "stake_yen": 200,
            })

        # [ボーナス] 3連単(1着固定) 6点 × 100円
        if len(all_others) >= 2:
            second_third = all_others[:4]
            for p in permutations([c["number"] for c in second_third], 2):
                odds = _find_trifecta_odds(extra_odds, axis["number"], p[0], p[1])
                if odds is None:
                    continue
                names = {c["number"]: c["name"] for c in candidates}
                bets.append({
                    "bet_type": "TRIFECTA",
                    "numbers": [axis["number"], p[0], p[1]],
                    "label": f"{axis['number']}-{p[0]}-{p[1]}",
                    "name": f"{names.get(axis['number'], '?')}→{names.get(p[0], '?')}→{names.get(p[1], '?')}",
                    "odds": odds,
                    "stake_yen": 100,
                })

        if not bets:
            return _required_odds_missing("Lv2 CaseA: 馬連/3連単オッズ不足 (0点)")

        # Sort trifecta bets by odds desc, keep top 6
        quinella_bets = [b for b in bets if b["bet_type"] == "QUINELLA"]
        trifecta_bets = [b for b in bets if b["bet_type"] == "TRIFECTA"]
        trifecta_bets.sort(key=lambda b: b["odds"])
        trifecta_bets = trifecta_bets[:6]
        bets = quinella_bets + trifecta_bets

        if len(bets) < 3:
            return _required_odds_missing(f"Lv2 CaseA: 馬連/3連単オッズ不足 ({len(bets)}点)")

        # Adjust total to 1200
        total = sum(b["stake_yen"] for b in bets)
        if total < BUDGET and bets:
            bets[0]["stake_yen"] += BUDGET - total
        elif total > BUDGET and trifecta_bets:
            # Remove lowest-odds trifecta bets until within budget
            while sum(b["stake_yen"] for b in bets) > BUDGET and trifecta_bets:
                bets.remove(trifecta_bets.pop())

        return _multi_result("Lv2", "A", "Lv2 CaseA（馬連3点+3連単6点）", bets, notes)

    # CaseB: 3連複10点×100円 + ワイド1点×200円 = 1200円
    if len(all_others) < 2:
        notes.append("CaseB: 候補2頭未満で3連複構築不可 → WIN分散に代替")
        return _win_spread(candidates, lv="Lv2", case="B", n=3, notes=notes)

    has_trio = bool(extra_odds.get("trio"))
    has_wide = bool(extra_odds.get("wide"))

    if not has_trio:
        return _required_odds_missing("Lv2 CaseB: 3連複オッズ未取得")

    bets = []

    # [守備] 3連複 軸1頭ながし
    if has_trio and len(all_others) >= 2:
        trio_bets = []
        names = {c["number"]: c["name"] for c in candidates}

        # Check all pairs from top candidates
        top_others = all_others[:7]  # top 7 candidates for trio coverage
        for pair in combinations([c["number"] for c in top_others], 2):
            odds = _find_trio_odds(extra_odds, axis["number"], pair[0], pair[1])
            if odds is None:
                return {
                    "hard_stop": True,
                    "hard_stop_code": HardStopCode.REQUIRED_ODDS_MISSING,
                    "reason": "Lv2 CaseB: 3連複オッズ不足",
                }
            nums = sorted([axis["number"], pair[0], pair[1]])
            trio_bets.append({
                "bet_type": "TRIO",
                "numbers": nums,
                "label": f"{nums[0]}-{nums[1]}-{nums[2]}",
                "name": f"{names.get(nums[0], '?')}={names.get(nums[1], '?')}={names.get(nums[2], '?')}",
                "odds": odds,
                "stake_yen": 100,
            })
        # Sort by odds asc (守備的), take top 10
        trio_bets.sort(key=lambda b: b["odds"])
        bets.extend(trio_bets[:10])
    # [追] ワイド 1点 × 200円
    if has_wide:
        best_wide = None
        best_wide_odds = 0
        for c in all_others[:5]:
            result = _find_wide_odds(extra_odds, axis["number"], c["number"])
            if result is None:
                continue
            odds_used = _wide_odds_used(result[0], result[1])
            if odds_used > best_wide_odds:
                best_wide_odds = odds_used
                best_wide = {
                    "bet_type": "WIDE",
                    "numbers": sorted([axis["number"], c["number"]]),
                    "label": f"{min(axis['number'], c['number'])}-{max(axis['number'], c['number'])}",
                    "name": f"{axis['name']}={c['name']}",
                    "odds": odds_used,
                    "odds_range": f"{result[0]}-{result[1]}",
                    "stake_yen": 200,
                }
        if best_wide:
            bets.append(best_wide)

    if not bets:
        return _required_odds_missing("Lv2 CaseB: 3連複/ワイドオッズ不足 (0点)")

    if len(bets) < 3:
        return _required_odds_missing(f"Lv2 CaseB: 3連複/ワイドオッズ不足 ({len(bets)}点)")

    # Adjust total
    total = sum(b["stake_yen"] for b in bets)
    if total < BUDGET and bets:
        bets[0]["stake_yen"] += BUDGET - total
    elif total > BUDGET:
        # Remove lowest-value trio bets first before trimming the WIDE add-on.
        trio_bets_in_portfolio = [b for b in bets if b["bet_type"] == "TRIO"]
        trio_bets_in_portfolio.sort(key=lambda b: b["odds"])  # remove lowest odds (most common = least value)
        while sum(b["stake_yen"] for b in bets) > BUDGET and trio_bets_in_portfolio:
            to_remove = trio_bets_in_portfolio.pop(0)
            bets.remove(to_remove)

    return _multi_result("Lv2", "B", "Lv2 CaseB（3連複10点+ワイド1点）", bets, notes)


# ---------------------------------------------------------------------------
# Lv1: Chaos
# ---------------------------------------------------------------------------

def _build_lv1_wide_bets(
    pool: list[dict[str, Any]],
    extra_odds: dict[str, Any],
    min_wide_odds: float = 4.0,
) -> list[dict[str, Any]]:
    """Build Lv1 wide coverage, excluding pairs below min_wide_odds."""
    wide_bets: list[dict[str, Any]] = []
    names = {c["number"]: c["name"] for c in pool}
    for pair in combinations([c["number"] for c in pool], 2):
        result = _find_wide_odds(extra_odds, pair[0], pair[1])
        if result is None:
            continue
        odds_used = _wide_odds_used(result[0], result[1])
        if odds_used < min_wide_odds:
            continue
        wide_bets.append({
            "bet_type": "WIDE",
            "numbers": sorted(list(pair)),
            "label": f"{min(pair)}-{max(pair)}",
            "name": f"{names[pair[0]]}={names[pair[1]]}",
            "odds": odds_used,
            "odds_range": f"{result[0]}-{result[1]}",
            "stake_yen": 100,
        })
    return wide_bets


def _build_lv1_follow_bets(
    candidates: list[dict[str, Any]],
    extra_odds: dict[str, Any],
    *,
    has_exacta: bool,
    has_quinella: bool,
) -> list[dict[str, Any]]:
    """Build Lv1 follow-up exacta/quinella bets."""
    axis = candidates[0]
    bets: list[dict[str, Any]] = []
    for c in candidates[1:6]:
        if len(bets) >= 2:
            break
        # v6.7.6: cheap insurance is forbidden.
        if axis["odds"] < 5.0 and c["odds"] < 5.0:
            continue
        wide_check = _find_wide_odds(extra_odds, axis["number"], c["number"])
        if wide_check and _wide_odds_used(wide_check[0], wide_check[1]) < 6.0:
            continue

        p_axis = axis.get("model_probability", 0)
        p_other = c.get("model_probability", 0)
        order_edge = p_axis / (p_axis + p_other) if (p_axis + p_other) > 0 else 0.5

        if order_edge >= 0.65 and has_exacta:
            odds = _find_exacta_odds(extra_odds, axis["number"], c["number"])
            if odds:
                bets.append({
                    "bet_type": "EXACTA",
                    "numbers": [axis["number"], c["number"]],
                    "label": f"{axis['number']}→{c['number']}",
                    "name": f"{axis['name']}→{c['name']}",
                    "odds": odds,
                    "stake_yen": 100,
                })
                continue

        if has_quinella:
            odds = _find_quinella_odds(extra_odds, axis["number"], c["number"])
            if odds:
                bets.append({
                    "bet_type": "QUINELLA",
                    "numbers": sorted([axis["number"], c["number"]]),
                    "label": f"{min(axis['number'], c['number'])}-{max(axis['number'], c['number'])}",
                    "name": f"{axis['name']}={c['name']}",
                    "odds": odds,
                    "stake_yen": 100,
                })
                continue

    return bets


def _plan_lv1(
    candidates: list[dict[str, Any]],
    extra_odds: dict[str, Any],
) -> dict[str, Any]:
    notes: list[str] = []
    pool = candidates[:5]

    if len(pool) < 3:
        notes.append("Lv1: 候補3頭未満 → WIN均等に代替")
        return _win_spread(candidates, lv="Lv1", case="B", n=3, notes=notes)

    has_wide = bool(extra_odds.get("wide"))
    has_exacta = bool(extra_odds.get("exacta"))
    has_quinella = bool(extra_odds.get("quinella"))

    if not has_wide:
        return _required_odds_missing("Lv1: ワイドオッズ未取得")
    if not has_quinella:
        return _required_odds_missing("Lv1: 馬連オッズ未取得")

    for attempt in range(3):
        min_wide_odds = 4.0 + attempt
        wide_bets = _build_lv1_wide_bets(pool, extra_odds, min_wide_odds=min_wide_odds)

        if len(wide_bets) < 3:
            return _required_odds_missing(f"Lv1: ワイドオッズ不足 ({len(wide_bets)}点)")

        # [網] ワイド: 5頭候補 → C(5,2) = 10ペア × 100円 = 1000円
        wide_bets.sort(key=lambda b: b["odds"], reverse=True)
        wide_bets = wide_bets[:10]

        # [追] 2点 × 100円 = 200円 (馬単 or 馬連)
        # v6.7.6: OrderEdge ≥ 0.65 → 馬単, else → 馬連
        # v6.7.6: 安目保険禁止: 単勝5倍未満同士 or ワイド<6.0 は追加禁止
        follow_bets = _build_lv1_follow_bets(
            candidates,
            extra_odds,
            has_exacta=has_exacta,
            has_quinella=has_quinella,
        )
        bets = wide_bets + follow_bets

        # Adjust total to 1200
        total = sum(b["stake_yen"] for b in bets)
        if total < BUDGET and bets:
            bets[0]["stake_yen"] += BUDGET - total
        elif total > BUDGET:
            while sum(b["stake_yen"] for b in bets) > BUDGET and len(bets) > 3:
                bets.pop()

        result = _multi_result(
            "Lv1",
            "B",
            f"Lv1（ワイド{len(wide_bets)}点+追{len(follow_bets)}点）",
            bets,
            notes,
        )
        m_floor = result["m_floor"]

        if m_floor >= 0.60:
            return result

        if attempt < 2:
            next_min_wide_odds = 4.0 + (attempt + 1)
            notes.append(
                f"Lv1 M_floor={m_floor:.3f}<0.60: "
                f"ワイド最低倍率を{next_min_wide_odds:.1f}倍に引き上げ "
                f"(attempt {attempt + 1})"
            )
            continue

        wide_bets = wide_bets[:8]
        for bet in wide_bets:
            bet["stake_yen"] = 100
        for bet in follow_bets:
            bet["stake_yen"] = 100
        if follow_bets:
            follow_bets[0]["stake_yen"] += 200
        bets = wide_bets + follow_bets
        total = sum(b["stake_yen"] for b in bets)
        if total < BUDGET and bets:
            bets[0]["stake_yen"] += BUDGET - total
        elif total > BUDGET:
            while sum(b["stake_yen"] for b in bets) > BUDGET and len(bets) > 3:
                bets.pop()
        notes.append("Lv1 M_floor<0.60: 点数削減(10→8)+Floor-Hedge")
        return _multi_result(
            "Lv1",
            "B",
            f"Lv1（ワイド{len(wide_bets)}点+追{len(follow_bets)}点 Floor-Hedge）",
            bets,
            notes,
        )

    return _required_odds_missing("Lv1: ポートフォリオ生成失敗")


# ---------------------------------------------------------------------------
# Helpers: WIN-only candidate-insufficient fallback plans
# ---------------------------------------------------------------------------

def _win_heavy(
    candidates: list[dict[str, Any]],
    *,
    lv: str,
    case: str,
    notes: list[str],
) -> dict[str, Any]:
    """Single-horse WIN, full 1200円 on top candidate."""
    top = candidates[0]
    bets = [_win_bet(top, BUDGET)]
    return _result(lv, case, f"{lv} Case{case} (WIN軸集中)", bets, notes, win_only=True)


def _win_spread(
    candidates: list[dict[str, Any]],
    *,
    lv: str,
    case: str,
    n: int,
    notes: list[str],
) -> dict[str, Any]:
    """Top-N WIN bets, equal 400円 each (N=3) or adjusted."""
    top_n = candidates[:n]
    if not top_n:
        top_n = candidates[:1]
    unit = BUDGET // len(top_n) // BET_UNIT * BET_UNIT
    remainder = BUDGET - unit * len(top_n)
    bets = []
    for i, c in enumerate(top_n):
        stake = unit + (BET_UNIT if i == 0 and remainder > 0 else 0)
        bets.append(_win_bet(c, stake))
    return _result(lv, case, f"{lv} Case{case} (WIN分散{len(top_n)}頭)", bets, notes, win_only=True)


def _win_bet(candidate: dict[str, Any], stake_yen: int) -> dict[str, Any]:
    return {
        "bet_type": "WIN",
        "number": candidate["number"],
        "name": candidate["name"],
        "odds": candidate["odds"],
        "stake_yen": stake_yen,
        "expected_value": candidate["expected_value"],
        "model_probability": candidate["model_probability"],
    }


# ---------------------------------------------------------------------------
# Result builders
# ---------------------------------------------------------------------------

def _multi_result(
    lv: str,
    case: str,
    plan_label: str,
    bets: list[dict[str, Any]],
    notes: list[str],
) -> dict[str, Any]:
    total_stake = sum(b["stake_yen"] for b in bets)
    if not bets:
        return _result(lv, case, plan_label, bets, notes, win_only=False)

    best_return = max(b["stake_yen"] * b["odds"] for b in bets)
    worst_return = min(b["stake_yen"] * b["odds"] for b in bets)
    m_main = round(best_return / BUDGET, 3)
    m_floor = round(worst_return / BUDGET, 3)

    return {
        "lv": lv,
        "case": case,
        "plan_label": plan_label,
        "bets": bets,
        "total_stake": total_stake,
        "m_main": m_main,
        "m_floor": m_floor,
        "notes": notes,
        "win_only": False,
    }


def _result(
    lv: str,
    case: str,
    plan_label: str,
    bets: list[dict[str, Any]],
    notes: list[str],
    *,
    win_only: bool,
) -> dict[str, Any]:
    total_stake = sum(b["stake_yen"] for b in bets)
    m_main = round(max(b["stake_yen"] * b["odds"] for b in bets) / BUDGET, 3) if bets else 0
    m_floor = round(min(b["stake_yen"] * b["odds"] for b in bets) / BUDGET, 3) if bets else 0
    return {
        "lv": lv,
        "case": case,
        "plan_label": plan_label,
        "bets": bets,
        "total_stake": total_stake,
        "m_main": m_main,
        "m_floor": m_floor,
        "notes": notes,
        "win_only": win_only,
    }
