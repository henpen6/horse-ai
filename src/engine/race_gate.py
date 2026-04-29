"""Race-level gate: decides whether to bet or skip before ticket construction.

Returns (should_bet: bool, skip_reasons: list[str]).
Called from future_minimal.run_future_engine after ev candidates are computed.

v8.1.0 (2026-04-28) adds `should_hard_skip()` — deterministic engine-side
SKIP that REFUSES to bet on 4 empirically-validated loss-prone race types.
Distinguished from `should_bet_gate()` which is advisory only.
"""
from __future__ import annotations

from src.engine import ev as _ev_module


def _W():
    """v8.1.0 (2026-04-28): always read ev's live _W rather than caching
    a separate copy at module load time. Allows runtime mutation of
    weights (e.g., factor sweep harness, hard_skip.enabled toggle for
    A/B replay) to take effect without reload."""
    return _ev_module._W


def should_hard_skip(
    race: dict,
    ev_output: list[dict],
    advisory_reasons: list[str],
) -> tuple[bool, list[str]]:
    """v8.1.0 hard SKIP — deterministic refusal to bet.

    Empirical validation on 2024+2025 G1+G2+G3 (n=220, with v8.1 積極 factor
    patch applied): hit 37.7% → 41.8%, ROI 147.4% → 191.1%, profit
    +¥117k → +¥149.7k. 36% of races skipped.

    Rules (each individually toggleable via weights.json hard_skip block):
        A: axis_odds < rule_A_max_odds (default 2.5) — 本命過信
        B: grade == rule_B_grade (G3) AND axis_pop == rule_B_pop (2)
        C: any advisory race_gate reason already fired (engine self-warns)
        D: grade == rule_D_grade (G3) AND axis_pop == rule_D_pop (1)
        I: race date month in rule_I_months (default {2, 10}) —
           v8.2.0 finding on n=337: 月10 ROI 42.8% / 月2 ROI 54.9%,
           combined avoided -¥34k loss. 秋GIシーズン + フェブラリー期は
           本命荒れる + フォーム不確定の高ノイズ期間。
        K: grade == rule_K_grade (G3) AND axis horse age == rule_K_axis_age
           — G3 2歳軸 ROI 18.3% / -¥17.6k, 新馬戦に近く軸馬選定の
           信頼性が低い (n=18).

    Args:
        race: collector_result dict.
        ev_output: candidates from compute_win_ev_candidates,
            sorted by EV descending. ev_output[0] is the engine's axis.
        advisory_reasons: output of should_bet_gate() — used by rule C.

    Returns:
        (True, [reason_codes]) if engine should hard-skip the race.
        (False, []) if betting should proceed.

    Disable any rule via weights.json hard_skip.rule_X_enabled = false;
    disable entire gate via hard_skip.enabled = false (rollback to v8.0).
    """
    cfg = _W().get("hard_skip", {})
    if not cfg.get("enabled", True):
        return False, []
    if not ev_output:
        return False, []

    reasons: list[str] = []
    grade = race.get("grade")
    axis = ev_output[0]
    axis_odds = axis.get("odds") or 0.0
    axis_pop = axis.get("popularity")

    if cfg.get("rule_A_enabled", True):
        max_odds = float(cfg.get("rule_A_max_odds", 2.5))
        if 0 < axis_odds < max_odds:
            reasons.append(f"hard_skip_A_axis_odds_lt_{max_odds}")

    if cfg.get("rule_B_enabled", True):
        b_grade = cfg.get("rule_B_grade", "G3")
        b_pop = int(cfg.get("rule_B_pop", 2))
        if grade == b_grade and axis_pop == b_pop:
            reasons.append(f"hard_skip_B_{b_grade}_pop_{b_pop}")

    if cfg.get("rule_C_enabled", True):
        if advisory_reasons:
            reasons.append("hard_skip_C_advisory_gate_fired")

    if cfg.get("rule_D_enabled", True):
        d_grade = cfg.get("rule_D_grade", "G3")
        d_pop = int(cfg.get("rule_D_pop", 1))
        if grade == d_grade and axis_pop == d_pop:
            reasons.append(f"hard_skip_D_{d_grade}_pop_{d_pop}")

    # v8.2.0 — Rule I: month-of-year SKIP. race.date is "YYYY-MM-DD".
    if cfg.get("rule_I_enabled", True):
        date_str = race.get("date") or ""
        try:
            month = int(date_str.split("-")[1])
        except (IndexError, ValueError):
            month = 0
        i_months = cfg.get("rule_I_months", [])
        if month and month in i_months:
            reasons.append(f"hard_skip_I_month_{month:02d}")

    # v8.2.0 — Rule K: G3 with 2yo axis. axis age lookup via race["entries"]
    # (axis horse number → entry.age). Requires entries pre-populated by
    # collector — defensive fallback skips K if age unavailable.
    if cfg.get("rule_K_enabled", True):
        k_grade = cfg.get("rule_K_grade", "G3")
        k_age = int(cfg.get("rule_K_axis_age", 2))
        if grade == k_grade:
            axis_num = axis.get("number")
            entries = race.get("entries") or []
            ax_entry = next((e for e in entries if e.get("number") == axis_num), {})
            ax_age = ax_entry.get("age")
            try:
                if ax_age is not None and int(ax_age) == k_age:
                    reasons.append(f"hard_skip_K_{k_grade}_age_{k_age}")
            except (TypeError, ValueError):
                pass

    # v8.4.2 — Rule L: pop=2 axis + edge_ratio narrow band SKIP.
    # Empirical 4-year (n=199 BET races): axis_pop=2 AND
    # axis_edge_ratio ∈ [0.85, 0.87] yields -¥21,430 / 18 race / 17% hit
    # — worst single Kelly degradation cell. Combined with rule B (G3 pop2)
    # the system rejects pop=2 in the most fragile region. See
    # apps/horse-ai/data/kelly_redux/multidim_phase3.json for derivation.
    if cfg.get("rule_L_enabled", True):
        l_pop = int(cfg.get("rule_L_pop", 2))
        l_er_min = float(cfg.get("rule_L_edge_ratio_min", 0.85))
        l_er_max = float(cfg.get("rule_L_edge_ratio_max", 0.87))
        try:
            ax_pop_int = int(axis_pop) if axis_pop is not None else None
        except (TypeError, ValueError):
            ax_pop_int = None
        if ax_pop_int == l_pop:
            mp = axis.get("model_probability")
            ip = axis.get("implied_probability")
            try:
                if mp and ip and float(ip) > 0:
                    er = float(mp) / float(ip)
                    if l_er_min <= er <= l_er_max:
                        reasons.append(f"hard_skip_L_pop{l_pop}_edge{l_er_min}-{l_er_max}")
            except (TypeError, ValueError):
                pass

    return (len(reasons) > 0, reasons)


def should_bet_gate(
    race: dict,
    ev_output: list[dict],
    lv: str,
) -> tuple[bool, list[str]]:
    """
    Args:
        race: collector_result dict (has n_field, enrichment_coverage, course, etc.)
        ev_output: list of candidate dicts from compute_win_ev_candidates
        lv: "Lv1" | "Lv2" | "Lv3"

    Returns:
        (True, []) if bet should proceed
        (False, [reason1, ...]) if race should be skipped
    """
    reasons: list[str] = []
    entries = race.get("entries") or []
    n_field = len(entries)

    coverage_fields = sum(
        1 for e in entries if e.get("past_performances")
    )
    coverage = coverage_fields / n_field if n_field > 0 else 1.0

    # Compute sum_top3: sum of model_probability for top-3 SAFE candidates
    sorted_by_prob = sorted(ev_output, key=lambda c: c["model_probability"], reverse=True)
    sum_top3 = sum(c["model_probability"] for c in sorted_by_prob[:3])

    # (a) Heavy favorite quinella trigami trap — Lv3 only
    # COO-approved replacement for top_odds < 1.6 check (rebuttal §4)
    # If minimum expected quinella payout < bet_unit, skip
    if lv == "Lv3" and len(sorted_by_prob) >= 2:
        top1_odds = sorted_by_prob[0]["odds"]
        top2_odds = sorted_by_prob[1]["odds"]
        # Approximate quinella min payout: harmonic of win odds × vig correction
        # If top1 odds < 1.6 AND top2 odds < 3.0 → likely quinella < ¥200 → trigami
        if top1_odds < 1.6 and top2_odds < 3.0:
            reasons.append("quinella_trigami_risk")

    # (b) Confused race: low sum_top3 + X-High axis
    if sum_top3 < 0.55:
        top_axis = sorted_by_prob[0] if sorted_by_prob else {}
        if top_axis.get("unknown_x") == "X-High":
            reasons.append("low_confidence_confused_race")

    # (c) All candidates below EV threshold
    min_ev = _W().get("race_gate", {}).get("min_ev_threshold", 0.05)
    if ev_output:
        max_ev = max(c.get("expected_value", 0.0) for c in ev_output)
        if max_ev < min_ev:
            reasons.append("no_positive_ev_candidate")

    # (d) Data coverage insufficient
    min_cov = _W().get("race_gate", {}).get("min_coverage", 0.70)
    if coverage < min_cov:
        reasons.append(f"insufficient_data_coverage:{coverage:.0%}")

    # (e) Tiny field top-heavy
    if n_field <= 8 and sum_top3 >= 0.80:
        reasons.append("tiny_field_topheavy")

    return (len(reasons) == 0, reasons)
