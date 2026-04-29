"""Budget sweep: for each bet size b in [100..5000], compute P_hit, E_payout, ROI.

Uses Monte Carlo simulation from model_probability (p_fair estimates).
Outputs a table of rows plus the optimal b* (argmax ROI subject to constraints).

COO-approved parameters (rebuttal §2):
  min_ROI  = -0.02  (market-beating filter: JRA vig 25% → -2% means 23pp above market)
  min_P_hit = 0.30
"""
from __future__ import annotations

import random

from src.engine.ev import _load_weights

_W = _load_weights()


def _sample_race_outcome(model_probs: dict[int, float], bet_type: str) -> tuple:
    """Sample a race outcome from model probabilities. Returns tuple of horse numbers."""
    nums = list(model_probs.keys())
    probs = [model_probs[n] for n in nums]
    total = sum(probs)
    probs = [p / total for p in probs]

    n_draw = 3 if "三連" in bet_type else 2
    n_draw = min(n_draw, len(nums))

    chosen = random.choices(nums, weights=probs, k=n_draw * 3)  # oversample for unique
    seen: list[int] = []
    for c in chosen:
        if c not in seen:
            seen.append(c)
        if len(seen) == n_draw:
            break
    while len(seen) < n_draw:
        seen.append(nums[len(seen) % len(nums)])

    if n_draw == 2:
        return (seen[0], seen[1])
    return (seen[0], seen[1], seen[2])


def _build_extra_odds_index(extra_odds: dict) -> dict:
    """Build lookup index from extra_odds for O(1) combo payout lookup.

    Keys:
      ('place', horse_number)           -> odds (mid of min/max)
      ('quinella', frozenset({h1,h2}))  -> odds
      ('wide', frozenset({h1,h2}))      -> odds_min (conservative)
      ('exacta', (h1, h2))              -> odds  (h1=1st, h2=2nd)
      ('trio', frozenset({h1,h2,h3}))   -> odds
      ('trifecta', (h1,h2,h3))          -> odds  (h1=1st, h2=2nd, h3=3rd)
    """
    index: dict = {}
    if not extra_odds:
        return index

    for entry in extra_odds.get("place") or []:
        h = entry.get("horse")
        lo = entry.get("odds_min") or 0.0
        hi = entry.get("odds_max") or lo
        if h is not None:
            index[("place", h)] = (lo + hi) / 2.0

    for entry in extra_odds.get("quinella") or []:
        horses = entry.get("horses") or []
        odds = entry.get("odds")
        if len(horses) == 2 and odds is not None:
            index[("quinella", frozenset(horses))] = float(odds)

    for entry in extra_odds.get("wide") or []:
        horses = entry.get("horses") or []
        odds_min = entry.get("odds_min")
        if len(horses) == 2 and odds_min is not None:
            index[("wide", frozenset(horses))] = float(odds_min)

    for entry in extra_odds.get("exacta") or []:
        horses = entry.get("horses") or []
        odds = entry.get("odds")
        if len(horses) == 2 and odds is not None:
            index[("exacta", (horses[0], horses[1]))] = float(odds)

    for entry in extra_odds.get("trio") or []:
        horses = entry.get("horses") or []
        odds = entry.get("odds")
        if len(horses) == 3 and odds is not None:
            index[("trio", frozenset(horses))] = float(odds)

    for entry in extra_odds.get("trifecta") or []:
        horses = entry.get("horses") or []
        odds = entry.get("odds")
        if len(horses) == 3 and odds is not None:
            index[("trifecta", (horses[0], horses[1], horses[2]))] = float(odds)

    return index


def _estimate_payout(
    combo: tuple,
    extra_odds_index: dict,
    bet_type: str,
    market_odds: dict[int, float] | None = None,
) -> float:
    """Return payout odds (倍) for combo. Falls back to win-odds approximation if index missing.

    Args:
        combo: tuple of horse numbers (ordered by finish for exacta/trifecta)
        extra_odds_index: built by _build_extra_odds_index
        bet_type: Japanese bet type string
        market_odds: fallback win odds dict {horse_num: odds}

    Returns:
        Odds value (倍). Multiply by stake_per_point to get yen payout.
    """
    if extra_odds_index:
        key: tuple | None = None
        if "三連単" in bet_type:
            if len(combo) >= 3:
                key = ("trifecta", (combo[0], combo[1], combo[2]))
        elif "三連複" in bet_type:
            if len(combo) >= 3:
                key = ("trio", frozenset(combo[:3]))
        elif "馬単" in bet_type:
            if len(combo) >= 2:
                key = ("exacta", (combo[0], combo[1]))
        elif "馬連" in bet_type:
            if len(combo) >= 2:
                key = ("quinella", frozenset(combo[:2]))
        elif "ワイド" in bet_type:
            if len(combo) >= 2:
                key = ("wide", frozenset(combo[:2]))
        elif "複勝" in bet_type:
            if combo:
                key = ("place", combo[0])

        if key is not None:
            odds = extra_odds_index.get(key)
            if odds is not None:
                return odds

    # Fallback: win-odds product approximation (used when extra_odds unavailable)
    if not market_odds:
        return 1.0
    product = 1.0
    for num in combo:
        product *= market_odds.get(num, 1.0)
    if "三連単" in bet_type:
        return product * 0.6
    if "三連複" in bet_type:
        return product * 0.4
    if "馬単" in bet_type:
        return product * 0.8
    if "馬連" in bet_type or "ワイド" in bet_type:
        return product * 0.75
    return product * 0.7


def budget_sweep(
    ev_output: list[dict],
    lv: str,
    axis_type: str,
    stance: str = "BALANCE",
    b_min: int = 100,
    b_max: int = 5000,
    step: int = 100,
    mc_trials: int = 10_000,
    extra_odds: dict | None = None,
) -> tuple[list[dict], dict]:
    """Diagnostic-only stub. Ticket-builder concept removed (INC-20260423-001)."""
    return [], {}


def format_sweep_table(rows: list[dict], optimal: dict | None = None, max_rows: int = 8) -> str:
    """Format sweep results for Discord output. COO rebuttal §6 format."""
    if not rows:
        return "(budget_sweep: diagnostic stub — no rows)"

    optimal = optimal or {}
    lines = ["【予算スイープ】"]
    lines.append(f"{'n(円)':>6}  {'bet_type':35}  {'P_hit':>6}  {'E_payout':>9}  {'ROI':>7}")

    # Show every 2nd row up to max_rows, always include optimal
    sample_ns = set()
    for i, r in enumerate(rows):
        if i % 2 == 0 or r["n"] == optimal["n"]:
            sample_ns.add(r["n"])
    sample_ns.add(optimal["n"])

    shown = 0
    for r in rows:
        if r["n"] not in sample_ns or shown >= max_rows:
            continue
        bet_label = f"{r['bet_type_main']}+{r['bet_type_sniper']}"
        marker = " ←推奨" if r["n"] == optimal["n"] else ""
        lines.append(
            f"{r['n']:>6}  {bet_label:35}  {r['P_hit']*100:>5.1f}%  "
            f"¥{r['E_payout']:>8,.0f}  {r['ROI']*100:>+6.1f}%{marker}"
        )
        shown += 1

    lines.append(f"推奨: {optimal['n']:,}円 (ROI{optimal['ROI']*100:+.1f}% / P_hit{optimal['P_hit']*100:.1f}%)")
    return "\n".join(lines)
