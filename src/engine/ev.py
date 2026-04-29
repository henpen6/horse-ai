from __future__ import annotations

import json as _json
import pathlib as _pathlib
import re as _re
from typing import Any

from .ev_factors import (
    _class_step_factor,
    _condition_aptitude_factor,
    _dslr_factor,
    _gate_factor,
    _last_3f_factor,
    _owner_breeder_factor,
    _pedigree_factor,
    _style_condition_factor,
    _weight_trend_factor,
)

_WEIGHTS_DEFAULTS: dict = {
    "race_level": {
        "lv1_lv2_boundary": 0.60,
        "lv3_base_threshold": 0.75,
        "lv3_max_threshold": 0.80,
        "small_field_correction_rate": 0.015,
        "small_field_reference_size": 10,
    },
    "unknown_x": {
        "weight_change_threshold_kg": 10,
        "layoff_threshold_days": 90,
        "distance_change_threshold_m": 400,
    },
    "ev_model": {
        "popularity_boost_divisor": 4,
        "weight_factor_min": 0.88,
        "weight_factor_base": 1.02,
        "weight_factor_scale": 100,
    },
    "ability": {
        "scale": 0.04,
        "career_weight": 0.6,
        "class_weight": 0.4,
    },
    "qualitative": {
        "fitness_factor_scale": 0.02,
        "pace_factor_scale": 0.03,
        "cause_factor_scale": 0.02,
    },
    "form_degradation": {
        "rt_drop_threshold": 5.0,
        "min_prior_races": 2,
    },
    "weight_delta": {
        "xlow_kg": 2.0,
        "xhigh_kg": 4.0,
    },
    "career_density": {
        "heavy_threshold": 4.5,
    },
    "class_up": {
        "tier_order": {"C": 0, "B": 1, "A": 2, "S": 3},
    },
    "race_gate": {
        "min_ev_threshold": 0.05,
        "min_coverage": 0.70,
    },
    "budget_sweep": {
        "min_P_hit": 0.30,
        "min_ROI": -0.02,
    },
}


def _load_weights() -> dict:
    """Load tunable parameters from data/config/weights.json.

    Walks up from __file__ to find the directory containing a 'data/' subdirectory
    (project root). Falls back to hardcoded defaults if the file is missing or invalid.
    """
    here = _pathlib.Path(__file__).resolve()
    for parent in [here.parent, here.parent.parent, here.parent.parent.parent,
                   here.parent.parent.parent.parent]:
        candidate = parent / "data" / "config" / "weights.json"
        if candidate.exists():
            try:
                with candidate.open(encoding="utf-8") as _f:
                    loaded = _json.load(_f)
                # Merge loaded over defaults (shallow per top-level key)
                result = {}
                for k, v in _WEIGHTS_DEFAULTS.items():
                    result[k] = {**v, **loaded.get(k, {})}
                for k, v in loaded.items():
                    if k not in result:
                        result[k] = v
                return result
            except (OSError, _json.JSONDecodeError):
                break
    return {k: dict(v) for k, v in _WEIGHTS_DEFAULTS.items()}


_W: dict = _load_weights()

_PACE_ROLES_FRONT = {"逃げ", "先行"}
_PACE_ROLES_BACK = {"差し", "追込"}


def _infer_race_pace(valid_entries: list[dict]) -> str:
    """Estimate overall race pace: 'fast', 'slow', or 'neutral'."""
    front_count = sum(
        1
        for e in valid_entries
        if (e.get("qualitative_features") or {}).get("pace_projection_role") in _PACE_ROLES_FRONT
        or e.get("dominant_style") in _PACE_ROLES_FRONT
    )
    if len(valid_entries) == 0:
        return "neutral"
    ratio = front_count / len(valid_entries)
    if ratio >= 0.5:
        return "fast"
    if ratio <= 0.25:
        return "slow"
    return "neutral"


def _qualitative_factor(entry: dict, race_pace: str, cfg: dict) -> float:
    """Compute combined qualitative multiplier for one entry.

    Returns value in [0.93, 1.09] range.
    LOW confidence applies half-weight to each sub-factor.
    Missing qualitative_features returns neutral 1.0.
    """
    qf = entry.get("qualitative_features") or {}
    if not qf:
        return 1.0

    confidence = qf.get("extraction_confidence", "LOW")
    weight = 0.5 if confidence == "LOW" else 1.0

    fitness_scale = cfg.get("fitness_factor_scale", 0.02) * weight
    pace_scale = cfg.get("pace_factor_scale", 0.03) * weight
    cause_scale = cfg.get("cause_factor_scale", 0.02) * weight

    fitness = qf.get("recent_fitness_score", 0.5)
    fitness_factor = 1.0 + fitness_scale * (fitness - 0.5) * 2

    pace_role = qf.get("pace_projection_role", "uncertain")
    if pace_role == "uncertain":
        pace_factor = 1.0
    elif race_pace == "fast" and pace_role in _PACE_ROLES_BACK:
        pace_factor = 1.0 + pace_scale
    elif race_pace == "slow" and pace_role in _PACE_ROLES_FRONT:
        pace_factor = 1.0 + pace_scale
    elif race_pace == "fast" and pace_role in _PACE_ROLES_FRONT:
        pace_factor = 1.0 - pace_scale
    elif race_pace == "slow" and pace_role in _PACE_ROLES_BACK:
        pace_factor = 1.0 - pace_scale
    else:
        pace_factor = 1.0

    loss_causes = qf.get("loss_cause_distribution") or {}
    other_weight = loss_causes.get("other", 0.5)
    cause_factor = 1.0 - cause_scale * max(0.0, other_weight - 0.5)

    combined = fitness_factor * pace_factor * cause_factor
    return max(0.93, min(1.09, combined))


def find_missing_win_odds_entries(collector_result: dict[str, Any]) -> list[dict[str, Any]]:
    entries = collector_result.get("entries", [])
    missing = []
    for entry in entries:
        if entry.get("win_odds") in (None, 0):
            missing.append(
                {
                    "number": entry.get("number"),
                    "name": entry.get("name"),
                }
            )
    return missing


def compute_race_level(collector_result: dict[str, Any]) -> dict[str, Any]:
    """Compute race-level classification from v6.7.7 §4-B.

    Returns:
        sum_top3: normalized p_fair sum of top-3 favorites (by p_fair desc)
        t_lv3:    Lv3 threshold (small-field corrected)
        lv:       "Lv1" | "Lv2" | "Lv3"
        n_field:  total entry count (including entries missing odds)
    """
    entries = collector_result.get("entries", [])
    n_field = len(entries)

    # Implied probabilities for entries with valid odds only
    valid_pairs = [
        (entry, 1.0 / float(entry["win_odds"]))
        for entry in entries
        if entry.get("win_odds") not in (None, 0)
    ]
    if not valid_pairs:
        return {"sum_top3": 0.0, "t_lv3": _W["race_level"]["lv3_base_threshold"], "lv": "Lv1", "n_field": n_field}

    total_implied = sum(p for _, p in valid_pairs)
    # Normalize (remove vig) to get p_fair
    p_fairs = sorted(
        [(entry, p / total_implied) for entry, p in valid_pairs],
        key=lambda x: x[1],
        reverse=True,
    )
    sum_top3 = round(sum(p for _, p in p_fairs[:3]), 6)

    # Small-field correction: T_Lv3 = min(base + rate × max(0, ref_size - N_field), max)
    t_lv3 = round(
        min(
            _W["race_level"]["lv3_base_threshold"]
            + _W["race_level"]["small_field_correction_rate"]
            * max(0, _W["race_level"]["small_field_reference_size"] - n_field),
            _W["race_level"]["lv3_max_threshold"],
        ),
        6,
    )

    if sum_top3 < _W["race_level"]["lv1_lv2_boundary"]:
        lv = "Lv1"
    elif sum_top3 < t_lv3:
        lv = "Lv2"
    else:
        lv = "Lv3"

    return {"sum_top3": sum_top3, "t_lv3": t_lv3, "lv": lv, "n_field": n_field}


def classify_unknown_x(
    entry: dict[str, Any],
    *,
    race_date: str | None = None,
    current_surface: str | None = None,
    current_distance: int | None = None,
    current_class_tier: str | None = None,
    current_weight_kg: float | None = None,
    dominant_style: str | None = None,
    all_entries: list[dict] | None = None,
    race: dict | None = None,
    top_entry: dict | None = None,
    past: list | None = None,
) -> tuple[str, list[str]]:
    """Classify Unknown-X strength for a single entry (v6.7.6 §4-A).

    Returns ("X-High" | "X-Low" | "X-None", reasons).

    X-High triggers:
      - |weight_change| >= 10kg
      - Layoff >= 90 days since last race
      - First time on current surface (初ダート/初芝)
      - Jockey change from most recent race
      - Distance change >= 400m from most recent race

    X-Low triggers:
      - Jockey change but minor (same surface/distance history)
    """
    from datetime import date as _date

    reasons_high: list[str] = []
    reasons_low: list[str] = []

    # 1. Weight change
    weight_change = _as_int(entry.get("weight_change"))
    if weight_change is not None and abs(weight_change) >= _W["unknown_x"]["weight_change_threshold_kg"]:
        reasons_high.append(f"weight_change={weight_change:+d}kg")

    top_entry = top_entry or entry
    past = past if past is not None else (entry.get("past_performances") or [])
    race = race or {}
    most_recent = past[0] if past else {}

    # 2. Layoff (休養明け): >= 90 days
    if past and race_date and most_recent.get("date"):
        try:
            ref = _date.fromisoformat(race_date)
            last = _date.fromisoformat(most_recent["date"])
            days_ago = (ref - last).days
            if days_ago >= _W["unknown_x"]["layoff_threshold_days"]:
                reasons_high.append(f"layoff={days_ago}days")
        except ValueError:
            pass

    # 3. First time on current surface (初ダート/初芝)
    if past and current_surface:
        past_surfaces = {p["surface"] for p in past if p.get("surface")}
        if past_surfaces and current_surface not in past_surfaces:
            reasons_high.append(f"first_{current_surface}")

    # 4. Jockey change (乗替り)
    current_jockey = entry.get("jockey") or ""
    past_jockey = most_recent.get("jockey") or ""
    if past and current_jockey and past_jockey and current_jockey != past_jockey:
        reasons_low.append(f"jockey_change:{past_jockey}→{current_jockey}")

    # 5. Distance change >= 400m
    current_distance_int = _as_int(current_distance)
    most_recent_distance = _as_int(most_recent.get("distance"))
    if past and current_distance_int and most_recent_distance:
        dist_diff = abs(current_distance_int - most_recent_distance)
        if dist_diff >= _W["unknown_x"]["distance_change_threshold_m"]:
            reasons_high.append(f"dist_change={most_recent_distance}→{current_distance_int}")

    # 6. 昇級初戦 — class step-up on debut at new level
    tier_order = _W.get("class_up", {}).get("tier_order", {"C": 0, "B": 1, "A": 2, "S": 3})
    current_tier = tier_order.get(current_class_tier, -1)
    past_tier = tier_order.get((past[0].get("class_tier") if past else None), -1)
    if current_tier > past_tier >= 0:
        reasons_high.append("class_up")

    # 7. 代替開催/順延
    if race.get("substitute_venue") or race.get("date_shifted"):
        reasons_high.append("substitute_race")

    # 8. form_degradation (Rt 急落)
    rt_recent = (past[0].get("jra_rating") if past else None)
    prior_rts = [p["jra_rating"] for p in (past[1:4] if past else []) if p.get("jra_rating")]
    if rt_recent is not None and prior_rts:
        rt_prior_avg = sum(prior_rts) / len(prior_rts)
        drop_threshold = _W.get("form_degradation", {}).get("rt_drop_threshold", 5.0)
        if (rt_prior_avg - rt_recent) >= drop_threshold:
            reasons_high.append(f"rt_drop={rt_prior_avg - rt_recent:.1f}")

    # 9. style_mismatch (差し/追込 × no front-runners in field)
    dominant_style = dominant_style or entry.get("dominant_style")
    if dominant_style in ("差し", "追込"):
        front_count = sum(
            1 for e in (all_entries or [])
            if e.get("dominant_style") in ("逃げ", "先行")
        )
        if front_count <= 1:
            reasons_high.append("slow_pace_against_closer")

    # 10. weight_load_delta
    wld_xhigh = _W.get("weight_delta", {}).get("xhigh_kg", 4.0)
    wld_xlow = _W.get("weight_delta", {}).get("xlow_kg", 2.0)
    current_wkg = _as_float(current_weight_kg)
    if current_wkg is not None and past:
        past_weight = _as_float(past[0].get("weight_kg") or past[0].get("carried_weight"))
        if past_weight is not None:
            wd = abs(current_wkg - past_weight)
            if wd >= wld_xhigh:
                reasons_high.append(f"load_delta={wd:.1f}kg")
            elif wd >= wld_xlow:
                reasons_low.append(f"load_delta={wd:.1f}kg")

    # 11. career_density_heavy
    heavy_threshold = _W.get("career_density", {}).get("heavy_threshold", 4.5)
    career_density_val = _as_float(top_entry.get("career_density") if top_entry else None)
    if career_density_val is not None and career_density_val >= heavy_threshold:
        reasons_low.append(f"density={career_density_val:.1f}")

    # 12. first_race_as_gelding
    current_sex = top_entry.get("sex") if top_entry else None
    past_sex = past[0].get("sex") if past else None
    if current_sex == "セン" and past_sex == "牡":
        reasons_low.append("first_gelding_race")

    # 13. disappointed_favorite
    if past:
        pop_recent = _as_int(past[0].get("popularity"))
        pos_recent = _as_int(past[0].get("position") or past[0].get("finish_position"))
        if pop_recent is not None and pop_recent <= 3 and pos_recent is not None and pos_recent >= 6:
            reasons_high.append(f"disappointed_fav:pop{pop_recent}->pos{pos_recent}")

    if reasons_high:
        return "X-High", reasons_high
    if reasons_low:
        return "X-Low", reasons_low
    return "X-None", []


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    match = _re.search(r"-?\d+", str(value).replace(",", ""))
    return int(match.group(0)) if match else None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    match = _re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _rank_norm(values: list) -> list[float]:
    """Normalize list of values to [0,1] range. None → 0.5."""
    valid = [v for v in values if v is not None]
    if not valid or max(valid) == min(valid):
        return [0.5] * len(values)
    vmin, vmax = min(valid), max(valid)
    return [(v - vmin) / (vmax - vmin) if v is not None else 0.5 for v in values]


def _tier_to_numeric(tier: str | None) -> int:
    return {"S": 4, "A": 3, "B": 2, "C": 1}.get(tier or "C", 2)


def compute_win_ev_candidates(collector_result: dict[str, Any]) -> list[dict[str, Any]]:
    # v8.0.0: collector_result stores race meta as flat top-level keys (see
    # server._build_collector_result_from_snapshot). Build a synthetic race
    # dict so ev_factors can read surface/distance/track_condition without
    # depending on the API response shape.
    _course_for_race = collector_result.get("course") or {}
    race = collector_result.get("race") or {
        "date": collector_result.get("date"),
        "venue": collector_result.get("venue"),
        "race_number": collector_result.get("race_number"),
        "race_name": collector_result.get("race_name"),
        "grade": collector_result.get("grade"),
        "race_class": collector_result.get("race_class"),
        "weather": collector_result.get("weather"),
        "track_condition": collector_result.get("track_condition"),
        "surface": _course_for_race.get("surface") if isinstance(_course_for_race, dict) else None,
        "distance": _course_for_race.get("meters") if isinstance(_course_for_race, dict) else None,
        "post_time": collector_result.get("post_time"),
        "course": _course_for_race,
    }
    entries = collector_result.get("entries", [])
    valid_entries = [
        entry for entry in entries
        if (odds := _as_float(entry.get("win_odds"))) is not None and odds > 0
    ]
    if not valid_entries:
        return []

    field_size = len(entries)

    _ability_cfg = _W.get("ability", {"scale": 0.04, "career_weight": 0.6, "class_weight": 0.4})
    _qual_cfg = _W.get("qualitative", {})
    race_pace = _infer_race_pace(valid_entries)
    _class_tier_num = {"C": 0.25, "B": 0.50, "A": 0.75, "S": 1.0}

    career_rates = []
    class_nums = []
    for entry in valid_entries:
        rec = entry.get("career_record") or {}
        wins = _as_float(rec.get("wins")) or 0.0
        total = max(_as_float(rec.get("total")) or 1.0, 1.0)
        career_rates.append(wins / total)
        class_nums.append(_class_tier_num.get(entry.get("class_tier"), 0.5))

    def _rank_norm(vals: list[float]) -> list[float]:
        n = len(vals)
        if n <= 1:
            return [0.5] * n
        sorted_vals = sorted(enumerate(vals), key=lambda x: x[1])
        ranks = [0.0] * n
        for rank, (idx, _) in enumerate(sorted_vals):
            ranks[idx] = rank / (n - 1)
        return ranks

    career_ranks = _rank_norm(career_rates)
    class_ranks = _rank_norm(class_nums)

    ability_scores = [
        _ability_cfg["career_weight"] * cr + _ability_cfg["class_weight"] * cl
        for cr, cl in zip(career_ranks, class_ranks)
    ]

    strengths = []
    for i, entry in enumerate(valid_entries):
        odds = _as_float(entry.get("win_odds"))
        if odds is None or odds <= 0:
            continue
        implied_probability = 1.0 / odds
        popularity = _as_int(entry.get("popularity"))
        popularity_boost = 0.0
        if popularity:
            popularity_boost = (field_size + 1 - popularity) / (field_size * _W["ev_model"]["popularity_boost_divisor"])
        weight_change = _as_int(entry.get("weight_change"))
        weight_factor = 1.0
        if weight_change is not None:
            weight_factor = max(
                _W["ev_model"]["weight_factor_min"],
                _W["ev_model"]["weight_factor_base"] - (abs(weight_change) / _W["ev_model"]["weight_factor_scale"]),
            )
        ability_score = ability_scores[i]
        ability_factor = 1.0 + _ability_cfg["scale"] * (ability_score - 0.5)
        qual_factor = _qualitative_factor(entry, race_pace, _qual_cfg)
        gf = _gate_factor(entry, race, _W, field_size)
        pf = _pedigree_factor(entry, race, _W)
        caf = _condition_aptitude_factor(entry, race, _W)
        scf = _style_condition_factor(entry, race, _W)
        csf = _class_step_factor(entry, race, _W)
        wtf = _weight_trend_factor(entry, _W)
        obf = _owner_breeder_factor(entry, _W)
        # v8.3.0 — derived-from-existing-data factors
        dslrf = _dslr_factor(entry, race, _W)
        last3f = _last_3f_factor(entry, _W)

        cap_cfg = _W.get("new_factors_safety_cap", {})
        cap_enabled = cap_cfg.get("enabled", True)
        cap_min = float(cap_cfg.get("min", 0.85))
        cap_max = float(cap_cfg.get("max", 1.15))
        new_factors_product = gf * pf * caf * scf * csf * wtf * obf * dslrf * last3f
        if cap_enabled:
            new_factors_product = max(cap_min, min(cap_max, new_factors_product))

        strength = (
            implied_probability
            * (1.0 + popularity_boost)
            * weight_factor
            * ability_factor
            * qual_factor
            * new_factors_product
        )
        strengths.append(
            (
                entry,
                odds,
                implied_probability,
                strength,
                ability_score,
                ability_factor,
                qual_factor,
                popularity_boost,
                weight_factor,
                gf,
                pf,
                caf,
                scf,
                csf,
                wtf,
                obf,
                dslrf,
                last3f,
                new_factors_product,
            )
        )

    total_strength = sum(item[3] for item in strengths)
    if total_strength <= 0:
        return []

    candidates: list[dict[str, Any]] = []
    for (
        entry,
        odds,
        implied_probability,
        strength,
        ability_score,
        ability_factor,
        qual_factor,
        popularity_boost,
        weight_factor,
        gf,
        pf,
        caf,
        scf,
        csf,
        wtf,
        obf,
        dslrf,
        last3f,
        new_factors_product,
    ) in strengths:
        model_probability = strength / total_strength
        expected_value = model_probability * odds - 1.0
        b = odds - 1.0
        q = 1.0 - model_probability
        kelly_fraction = 0.0 if b <= 0 else max(0.0, ((b * model_probability) - q) / b)
        candidates.append(
            {
                "bet_type": "WIN",
                "number": entry.get("number"),
                "name": entry.get("name"),
                "odds": odds,
                "popularity": entry.get("popularity"),
                "implied_probability": round(implied_probability, 6),
                "model_probability": round(model_probability, 6),
                "expected_value": round(expected_value, 6),
                "edge": round(model_probability - implied_probability, 6),
                "kelly_fraction": round(kelly_fraction, 6),
                "dominant_style": entry.get("dominant_style"),
                "class_tier": entry.get("class_tier"),
                "farm_tier": entry.get("farm_tier"),
                "ability_score": round(ability_score, 4),
                "ability_factor": round(ability_factor, 4),
                "qualitative_factor": round(qual_factor, 6),
                "breakdown_factors": {
                    "popularity_boost": round(popularity_boost, 6),
                    "weight_factor": round(weight_factor, 6),
                    "ability_factor": round(ability_factor, 6),
                    "qualitative_factor": round(qual_factor, 6),
                    "gate_factor": round(gf, 6),
                    "pedigree_factor": round(pf, 6),
                    "condition_aptitude_factor": round(caf, 6),
                    "style_condition_factor": round(scf, 6),
                    "class_step_factor": round(csf, 6),
                    "weight_trend_factor": round(wtf, 6),
                    "owner_breeder_factor": round(obf, 6),
                    "dslr_factor": round(dslrf, 6),
                    "last_3f_factor": round(last3f, 6),
                    "new_factors_product": round(new_factors_product, 6),
                },
            }
        )

    # Return ALL candidates sorted by EV descending (including negative EV).
    # Positive-EV filtering is intentionally removed: JRA vig ~25% makes all EVs
    # negative pre-race; the system always outputs the best available portfolio.
    return sorted(
        candidates,
        key=lambda item: (
            item["expected_value"],
            item["model_probability"],
            -(_as_int(item.get("number")) or 0),
        ),
        reverse=True,
    )
