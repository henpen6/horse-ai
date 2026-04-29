from __future__ import annotations

from math import comb
from typing import Any

from src.engine import ev as _ev_module
from src.engine.budget_sweep import budget_sweep, format_sweep_table
from src.engine.ev import classify_unknown_x, compute_win_ev_candidates, compute_race_level, find_missing_win_odds_entries
from src.engine.ev_factors import _kelly_stake_multiplier
from src.engine.hard_stop import HardStopCode, SoftStopCode
from src.engine.portfolio import build_portfolio
from src.engine.race_gate import should_bet_gate, should_hard_skip
from src.engine.stake import normalize_stakes


def _is_waiting_on_jra_odds(collector_result: dict[str, Any]) -> bool:
    """Return True if the race date+post_time is still in the future and the
    odds gap is consistent with normal JRA progressive publishing (JRA emits
    馬連/3連複/3連単 odds in waves up to ~5min before post). When True, the
    caller should treat REQUIRED_ODDS_MISSING as soft (retry) instead of
    hard-stop.
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _zi
    date_str = collector_result.get("date")
    post_time_str = collector_result.get("post_time")
    if not date_str or not post_time_str:
        return False
    try:
        post_dt = _dt.combine(
            _dt.fromisoformat(date_str).date(),
            _dt.strptime(post_time_str, "%H:%M").time(),
            tzinfo=_zi("Asia/Tokyo"),
        )
        now = _dt.now(_zi("Asia/Tokyo"))
        return (post_dt - now).total_seconds() > 0
    except Exception:
        return False


def _validate_extra_odds_completeness(collector_result: dict[str, Any]) -> dict[str, Any] | None:
    """Return stop-result dict if any bet type has fewer combos than expected,
    else None.

    When odds are incomplete AND post_time is still in the future, returns
    a SOFT stop (`WAITING_ON_DATA`) — JRA publishes odds progressively up
    to ~5min before post, so the bot should retry rather than surface a
    fatal error. After post_time, treat as genuine HARD_STOP.
    """
    n = len(collector_result.get("entries") or [])
    if n < 2:
        return None
    extra_odds = collector_result.get("extra_odds") or {}

    expected = {
        "quinella": comb(n, 2),
        "wide": comb(n, 2),
        "exacta": n * (n - 1),
        "trio": comb(n, 3),
        "trifecta": int(n * (n - 1) * (n - 2) * 0.90),  # allow up to 10% zero-bet combos (JRA normal)
    }
    gaps = {}
    for key, exp in expected.items():
        actual = len(extra_odds.get(key) or [])
        if actual < exp:
            gaps[key] = {"expected": exp, "actual": actual, "missing": exp - actual}

    if gaps:
        if _is_waiting_on_jra_odds(collector_result):
            return {
                "ok": False,
                "soft_stop_code": SoftStopCode.WAITING_ON_DATA,
                "details": {
                    "gaps": gaps,
                    "reason": "JRA がオッズを順次公開中です。発走 5 分前まで待って再試行してください。",
                    "missing_bet_types": list(gaps.keys()),
                },
            }
        return {
            "ok": False,
            "hard_stop_code": HardStopCode.REQUIRED_ODDS_MISSING,
            "details": {"gaps": gaps, "reason": "オッズデータが不完全です（収集バグの可能性）。3連単は10%超の欠損で停止。"},
        }
    return None


def run_future_engine(
    *,
    collector_result: dict[str, Any],
    budget: int,
    budget_source: str,
    strategy_router: bool = False,
) -> dict[str, Any]:
    entries = collector_result.get("entries") or []
    if not entries:
        return {
            "ok": False,
            "hard_stop_code": HardStopCode.COLLECTOR_RESULT_MISSING,
            "details": {"entries": entries},
        }

    missing_win_odds = find_missing_win_odds_entries(collector_result)
    if missing_win_odds:
        return {
            "ok": False,
            "hard_stop_code": HardStopCode.REQUIRED_WIN_ODDS_MISSING,
            "details": {"missing_win_odds": missing_win_odds},
        }

    odds_check = _validate_extra_odds_completeness(collector_result)
    if odds_check:
        return odds_check

    candidates = compute_win_ev_candidates(collector_result)
    # Note: candidates may all have negative EV — JRA vig ~25% is expected.
    # The system always outputs the best available portfolio (v6.7.6 design).
    if not candidates:
        return {
            "ok": False,
            "hard_stop_code": HardStopCode.REQUIRED_WIN_ODDS_MISSING,
            "details": {"entry_count": len(entries)},
        }

    race_level = compute_race_level(collector_result)
    top_odds = candidates[0]["odds"]
    top_number = candidates[0]["number"]

    # Find the entry for the top candidate to check Unknown-X
    top_entry = next(
        (e for e in collector_result.get("entries", []) if e.get("number") == top_number),
        {},
    )
    top_unknown_x, x_reasons = classify_unknown_x(
        top_entry,
        race_date=collector_result.get("date"),
        current_surface=(collector_result.get("course") or {}).get("surface"),
        current_distance=(collector_result.get("course") or {}).get("meters"),
        current_class_tier=top_entry.get("class_tier"),
        current_weight_kg=top_entry.get("current_weight_kg") or top_entry.get("carried_weight"),
        dominant_style=top_entry.get("dominant_style"),
        all_entries=entries,
        race=collector_result,
        top_entry=top_entry,
        past=top_entry.get("past_performances") or [],
    )

    # axis_type: A if strong favorite AND no X-High risk; X-High forces CaseB (v6.7.6 §4-C)
    if top_unknown_x == "X-High":
        axis_type = "B"  # X-High → CaseA禁止、強制CaseB
    else:
        axis_type = "A" if top_odds <= 2.5 else "B"

    for candidate in candidates:
        if candidate.get("number") == top_number:
            candidate["unknown_x"] = top_unknown_x
            candidate["unknown_x_reasons"] = x_reasons
            break

    # Race Gate is now ADVISORY ONLY. Earlier design treated `should_bet=False`
    # as a hard stop (RACE_GATE_SKIP), forcing the user to read a "would have
    # bet" hypothetical report — but the user always bets every race anyway,
    # so the binary cliff was self-defeating: the SKIP fallback strategy was
    # under-developed relative to the BET path, and on this race
    # (青葉賞 G2 2026-04-25) the metadata-richness change between v7.7.4 →
    # v7.7.6f flipped Race Gate from SKIP→BET and the strategy switched from
    # 3連単 box (which would have hit) to 3連複 axis #15 (which missed).
    # Going forward: gate_reasons are passed through as advisories. Phase 2
    # (separate spec) will route gate_reasons to portfolio-strategy adjustments
    # (e.g. tiny_field_topheavy → force Lv3 CaseA top-EV box). For now, keep
    # the existing portfolio builder behavior so the engine ALWAYS emits a
    # real BET portfolio.
    _, gate_reasons = should_bet_gate(collector_result, candidates, race_level["lv"])

    # v8.1.0: deterministic hard SKIP gate. Empirically validated on
    # 2024+2025 G1+G2+G3 stakes (n=220) — hit 37.7% → 41.8%, ROI 147.4% →
    # 191.1%. When fired, engine returns an empty-portfolio result (stake
    # 0, no bets). Downstream review_bets and bot output handle empty
    # portfolio gracefully. Rules in race_gate.should_hard_skip(),
    # toggleable via weights.json hard_skip.* flags.
    hard_skip, hard_skip_reasons = should_hard_skip(
        collector_result, candidates, gate_reasons
    )
    if hard_skip:
        return {
            "ok": True,
            "engine_skip": True,
            "engine_skip_reasons": hard_skip_reasons,
            "strategy": "future_minimal_hard_skip",
            "candidate_count": len(candidates),
            "candidates": candidates,
            "top_candidate": candidates[0] if candidates else None,
            "portfolio": {
                "bets": [],
                "total_stake": 0,
                "lv": race_level["lv"],
                "case": "SKIP",
                "plan_label": "v8.1 hard skip",
                "m_main": 0.0,
                "m_floor": 0.0,
            },
            "sweep_rows": [],
            "sweep_optimal": {},
            "sweep_table": "(skipped — hard SKIP gate fired)",
            "race_level": race_level,
            "axis_type": axis_type,
            "top_unknown_x": top_unknown_x,
            "top_unknown_x_reasons": x_reasons,
            "m_main": 0.0,
            "m_floor": 0.0,
            "gate_pass": len(gate_reasons) == 0,
            "gate_reasons": gate_reasons,
        }

    # Phase 2 strategy router (opt-in via `strategy_router=True`). For specific
    # gate_reasons that have proven structurally-correct strategies, override
    # race_level / axis_type before portfolio construction:
    #
    #   tiny_field_topheavy  (n_field≤8, sum_top3≥0.80)
    #     → force Lv3 CaseA (3連単 top-3 EV box). The 青葉賞 G2 2026-04-25
    #       case showed this strategy was the winner when small fields with
    #       concentrated probabilities decide; the previous default
    #       (Lv2 CaseB 3連複 axis on highest-edge) drew the same axis from a
    #       low-prob horse and missed every bet.
    routed_lv = race_level["lv"]
    routed_axis = axis_type
    routed_strategy_note = None
    routed_budget = budget
    if strategy_router and "tiny_field_topheavy" in gate_reasons:
        routed_lv = "Lv3"
        routed_axis = "A"
        race_level = {"lv": "Lv3", "tag": race_level.get("tag"), "sum_top3": race_level.get("sum_top3"), "gap": race_level.get("gap")}
        axis_type = "A"
        routed_strategy_note = "tiny_field_topheavy → Lv3 CaseA forced"

    # insufficient_data_coverage: 14-signal coverage thin → uncertainty high.
    # Force Lv1 (lower-variance ワイド-heavy plan) regardless of base lv,
    # AND halve budget so a thin-data race doesn't cost full stake. ¥600 is
    # the minimum responsible size for a Lv1 plan; build_portfolio scales bet
    # stakes proportionally when total_budget < default 1200.
    elif strategy_router and any(r.startswith("insufficient_data_coverage") for r in gate_reasons):
        routed_lv = "Lv1"
        # Keep axis_type as engine determined; Lv1 uses ワイド-heavy plan
        # which doesn't strongly depend on A/B distinction
        race_level = {"lv": "Lv1", "tag": race_level.get("tag"), "sum_top3": race_level.get("sum_top3"), "gap": race_level.get("gap")}
        routed_budget = max(600, budget // 2)
        routed_strategy_note = f"insufficient_data_coverage → Lv1 ¥{routed_budget} (was ¥{budget})"

    # v8.4.0 Kelly fractional stake sizing. Compose after strategy routing.
    # Selection (axis pick) is unchanged — multiplier only affects stake.
    kelly_stake_multiplier, kelly_stake_breakdown = _kelly_stake_multiplier(
        candidates,
        collector_result,
        _ev_module._W,
    )

    # Pass routed_budget directly (thread-safe; build_portfolio holds an
    # internal lock while mutating module-level BUDGET).
    portfolio = build_portfolio(
        candidates=candidates,
        race_level=race_level,
        axis_type=axis_type,
        extra_odds=collector_result.get("extra_odds"),
        budget=routed_budget,
    )
    if portfolio.get("hard_stop"):
        return {
            "ok": False,
            "hard_stop_code": portfolio["hard_stop_code"],
            "details": {"reason": portfolio.get("reason")},
        }

    # v8.4.1 Kelly fix: apply multiplier UNIFORMLY across all bets after
    # build_portfolio, preserving diversification ratio. Pre-multiplying budget
    # caused build_portfolio to concentrate extra stake on top-EV bet
    # (-¥13,950 closed-loop regression in v8.4.0). Uniform scaling matches
    # the canonical Kelly-fractional intent: total exposure scales with edge,
    # but per-ticket allocation ratios are preserved.
    if kelly_stake_multiplier != 1.0 and portfolio.get("bets"):
        new_total_stake = 0
        for _bet in portfolio["bets"]:
            _scaled = int(round(_bet.get("stake_yen", 0) * kelly_stake_multiplier / 100.0)) * 100
            _scaled = max(100, _scaled)  # JRA minimum ¥100/ticket
            _bet["stake_yen"] = _scaled
            new_total_stake += _scaled
        portfolio["total_stake"] = new_total_stake

    sweep_rows, sweep_optimal = budget_sweep(
        ev_output=candidates,
        lv=race_level["lv"],
        axis_type=axis_type,
        stance="BALANCE",
        extra_odds=collector_result.get("extra_odds"),
    )
    sweep_table_str = format_sweep_table(sweep_rows, sweep_optimal)

    return {
        "ok": True,
        "strategy": "future_minimal" if not portfolio.get("win_only") else "future_minimal_win_only",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "top_candidate": candidates[0],
        "portfolio": portfolio,
        "sweep_rows": sweep_rows,
        "sweep_optimal": sweep_optimal,
        "sweep_table": sweep_table_str,
        "race_level": race_level,
        "axis_type": axis_type,
        "top_unknown_x": top_unknown_x,
        "top_unknown_x_reasons": x_reasons,
        "m_main": portfolio["m_main"],
        "m_floor": portfolio["m_floor"],
        "kelly_stake_multiplier": kelly_stake_multiplier,
        "kelly_stake_breakdown": kelly_stake_breakdown,
        # Race Gate is advisory: even when reasons fire, the portfolio still
        # ships. Phase 2 will use these to adjust strategy / budget.
        "gate_pass": len(gate_reasons) == 0,
        "gate_reasons": gate_reasons,
    }
