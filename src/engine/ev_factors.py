from __future__ import annotations

import json as _json
import os as _os
import pathlib as _pathlib
import re as _re
from typing import Any

_CONFIG_DIR = _pathlib.Path(__file__).parent.parent.parent / "data" / "config"
_JSON_CACHE: dict[str, dict[str, Any]] = {}


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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _load_json_config(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {}

    path = _pathlib.Path(path_value)
    if not path.is_absolute():
        path = _CONFIG_DIR / path
    cache_key = str(path)

    if cache_key not in _JSON_CACHE:
        try:
            with path.open(encoding="utf-8") as fh:
                data = _json.load(fh)
            _JSON_CACHE[cache_key] = data if isinstance(data, dict) else {}
        except (OSError, _json.JSONDecodeError):
            _JSON_CACHE[cache_key] = {}

    return _JSON_CACHE[cache_key]


def _distance_bucket_for_gate(distance: int) -> str:
    if distance < 1400:
        return "lt1400"
    if distance < 1800:
        return "m1400_1800"
    if distance < 2200:
        return "m1800_2200"
    if distance < 2800:
        return "m2200_2800"
    return "gt2800"


def _distance_bucket_for_pedigree(surface: str, distance: int | None) -> str | None:
    if surface == "ダート":
        return "dirt_any"
    if surface != "芝" or distance is None:
        return None
    if distance < 1400:
        return "turf_lt1400"
    if distance < 1800:
        return "turf_m1400_1800"
    if distance < 2200:
        return "turf_m1800_2200"
    return "turf_gt2200"


def _gate_factor(entry: dict, race: dict, _W: dict, field_size: int = 18) -> float:
    cfg = _W.get("gate_bias", {})
    if not cfg.get("enabled", True):
        return 1.0

    gate_num = _as_int(entry.get("gate_num") or entry.get("gate_number"))
    if gate_num is None or gate_num <= 0:
        return 1.0

    venue = race.get("venue")
    surface = race.get("surface")
    distance = _as_int(race.get("distance"))
    if not venue or surface not in {"芝", "ダート"} or distance is None:
        return 1.0

    disable_threshold = _as_int(cfg.get("small_field_disable_threshold"))
    if disable_threshold is not None and field_size < disable_threshold:
        return 1.0

    if gate_num <= 3:
        gate_group = "inner"
    elif gate_num >= 13:
        gate_group = "outer"
    else:
        gate_group = "middle"

    table = _load_json_config(cfg.get("table_path", "gate_bias_table.json"))
    distance_bucket = _distance_bucket_for_gate(distance)

    venue_row = table.get(str(venue))
    if isinstance(venue_row, dict):
        surface_row = venue_row.get(surface)
        if isinstance(surface_row, dict):
            bucket_row = surface_row.get(distance_bucket)
            if isinstance(bucket_row, dict):
                return float(bucket_row.get(gate_group, cfg.get("default_factor", 1.0)))

    default_row = table.get("_default", {})
    if isinstance(default_row, dict):
        return float(default_row.get(gate_group, cfg.get("default_factor", 1.0)))
    return float(cfg.get("default_factor", 1.0))


def _pedigree_factor(entry: dict, race: dict, _W: dict) -> float:
    cfg = _W.get("pedigree_factor", {})
    if not cfg.get("enabled", True):
        return 1.0

    default_factor = float(cfg.get("default_factor", 1.0))
    sire = entry.get("sire")
    if not sire:
        return default_factor

    surface = race.get("surface")
    distance = _as_int(race.get("distance"))
    key = _distance_bucket_for_pedigree(surface, distance)
    if key is None:
        return default_factor

    table = _load_json_config(cfg.get("table_path", "sire_aptitude_v1.json"))
    sire_data = table.get(str(sire))
    if not isinstance(sire_data, dict):
        return default_factor

    sire_mult = float(sire_data.get(key, default_factor))

    include_bms = cfg.get("include_dam_sire_on_dirt", True)
    dam_sire = entry.get("dam_sire")
    if include_bms and surface == "ダート" and dam_sire:
        dam_data = table.get(str(dam_sire))
        if isinstance(dam_data, dict):
            dam_mult = float(dam_data.get("dirt_any", default_factor))
            sire_mult = (sire_mult + dam_mult) / 2.0

    max_dev = float(cfg.get("max_deviation", 0.05))
    return _clamp(sire_mult, 1.0 - max_dev, 1.0 + max_dev)


def _condition_aptitude_factor(entry: dict, race: dict, _W: dict) -> float:
    cfg = _W.get("condition_aptitude", {})
    if not cfg.get("enabled", True):
        return 1.0

    today_cond = race.get("track_condition")
    if not today_cond:
        return 1.0

    past = entry.get("past_performances") or []
    if not past:
        return 1.0

    raw_finish_weights = cfg.get("finish_weights", {"1": 1.0, "2": 0.6, "3": 0.4, "4": 0.2, "5": 0.2})
    finish_weights = {}
    for key, value in raw_finish_weights.items():
        finish_position = _as_int(key)
        if finish_position is not None:
            finish_weights[finish_position] = float(value)

    matching_races = [pp for pp in past if pp.get("track_condition") == today_cond]
    if len(matching_races) < int(cfg.get("min_past_races", 3)):
        return 1.0

    def pp_weight(pp: dict) -> float:
        pos = _as_int(
            pp.get("finishing_position")
            or pp.get("finish_position")
            or pp.get("position")
        )
        if pos is None:
            return 0.0
        return finish_weights.get(pos, 0.0)

    matching_score = sum(pp_weight(pp) for pp in matching_races)
    total_score = sum(pp_weight(pp) for pp in past)
    if total_score == 0:
        return 1.0

    aptitude = matching_score / total_score
    max_dev = float(cfg.get("max_deviation", 0.10))
    normalized = _clamp((aptitude - 0.5) * 2.0, -1.0, 1.0)
    return 1.0 + (normalized * max_dev)


def _style_condition_factor(entry: dict, race: dict, _W: dict) -> float:
    cfg = _W.get("style_condition_bias", {})
    if not cfg.get("enabled", True):
        return 1.0

    track_cond = race.get("track_condition")
    style = entry.get("dominant_style")
    if not track_cond or not style:
        return 1.0

    table = cfg.get("table", {})
    cond_row = table.get(track_cond) if isinstance(table, dict) else None
    if not isinstance(cond_row, dict):
        return 1.0
    return float(cond_row.get(style, 1.0))


def _class_step_factor(entry: dict, race: dict, _W: dict) -> float:
    cfg = _W.get("class_step", {})
    if not cfg.get("enabled", True):
        return 1.0

    today_class_str = race.get("race_class") or race.get("grade")
    if not today_class_str:
        return 1.0

    tier_map = _load_json_config(cfg.get("tier_map_path", "class_tier_map.json"))
    today_tier = tier_map.get(str(today_class_str))
    if today_tier is None:
        return 1.0

    past = entry.get("past_performances") or []
    if not past:
        return 1.0

    recent_tiers = []
    for pp in past[:3]:
        cls_str = pp.get("race_class") or pp.get("grade") or pp.get("class")
        if cls_str and str(cls_str) in tier_map:
            recent_tiers.append(float(tier_map[str(cls_str)]))

    if not recent_tiers:
        return 1.0

    class_step = float(today_tier) - max(recent_tiers)
    step_scale = float(cfg.get("step_scale", 0.03))
    max_dev = float(cfg.get("max_deviation", 0.05))
    adjustment = _clamp(class_step * step_scale, -max_dev, max_dev)
    return 1.0 - adjustment


def _weight_trend_factor(entry: dict, _W: dict) -> float:
    cfg = _W.get("weight_trend", {})
    if not cfg.get("enabled", True):
        return 1.0

    current_weight = _as_float(entry.get("horse_weight"))
    if current_weight is None:
        return 1.0

    past = entry.get("past_performances") or []
    past_weights = [
        weight
        for pp in past[:3]
        if (weight := _as_float(pp.get("horse_weight"))) is not None
    ]
    if len(past_weights) < int(cfg.get("min_past_with_weight", 2)):
        return 1.0

    mean_weight = sum(past_weights) / len(past_weights)
    delta = current_weight - mean_weight

    age_int = _as_int(entry.get("age")) or 99
    past_count = len(past)
    stable_threshold = float(cfg.get("stable_threshold_kg", 4))
    if (
        cfg.get("season_adjust", True)
        and age_int <= 3
        and past_count <= int(cfg.get("season_adjust_max_past_races", 6))
    ):
        stable_threshold = float(cfg.get("season_adjust_stable_threshold_kg", 8))

    if abs(delta) <= stable_threshold:
        return 1.0 + float(cfg.get("stable_boost", 0.02))
    if delta < -float(cfg.get("drop_threshold_kg", 10)):
        return 1.0 - float(cfg.get("drop_decay", 0.05))
    if delta > float(cfg.get("gain_threshold_kg", 10)):
        return 1.0 - float(cfg.get("gain_decay", 0.03))
    return 1.0


def _dslr_factor(entry: dict, race: dict, _W: dict) -> float:
    """v8.3.0 (2026-04-28): days-since-last-race nonlinear bins.

    Empirical sweet-spot from JP racing literature (JSAI 2023, Pudaruth
    2020): horses with 14-63 days rest perform best. 連闘 (≤7 days) are
    overworked; long layoffs (>90 days) typically need a prep race.

    Default bands (configurable via weights.json):
        ≤7 days  (連闘): factor 0.95 (penalize)
        8-13 days       : factor 0.99
        14-35 days  ★   : factor 1.04 (boost — prime window)
        36-63 days  ★   : factor 1.03 (boost — fresh)
        64-120 days     : factor 1.00
        >120 days       : factor 0.97 (long layoff)
    """
    cfg = _W.get("dslr_factor", {})
    if not cfg.get("enabled", True):
        return 1.0
    past = entry.get("past_performances") or []
    if not past:
        return 1.0
    pp_date = (past[0] or {}).get("date") or ""
    race_date = race.get("date") or ""
    if not pp_date or not race_date:
        return 1.0
    try:
        from datetime import date as _d
        rd = _d.fromisoformat(race_date)
        pd = _d.fromisoformat(pp_date)
        days = (rd - pd).days
    except (TypeError, ValueError):
        return 1.0
    if days < 0:
        return 1.0
    bands = cfg.get("bands", [
        {"max": 7, "factor": 0.95},
        {"max": 13, "factor": 0.99},
        {"max": 35, "factor": 1.04},
        {"max": 63, "factor": 1.03},
        {"max": 120, "factor": 1.00},
        {"max": 9999, "factor": 0.97},
    ])
    for b in bands:
        if days <= int(b.get("max", 9999)):
            return float(b.get("factor", 1.0))
    return 1.0


def _last_3f_factor(entry: dict, _W: dict) -> float:
    """v8.3.0 (2026-04-28): 上がり3F (last 3-furlong sectional) speed factor.

    Past_performances row carries pace = "前半3F-後半3F" string. The second
    value is the 後半3F (last-3-furlong) time in seconds. Lower = better
    closing speed. Average over recent 3 past races gives a stable
    end-pace signal.

    Default bins (sec):
        avg < 33.5  (elite closer):    factor 1.05
        33.5-34.5                    :  1.03
        34.5-35.5  (average)         :  1.00
        35.5-36.5                    :  0.98
        avg ≥ 36.5  (poor closer)    :  0.95

    Note: this is an absolute-time proxy; literature recommends 上がり3F
    *rank within race*, but rank requires field-level data we don't yet
    aggregate. Absolute time is correlated and good enough as v8.3 first
    pass.
    """
    cfg = _W.get("last_3f_factor", {})
    if not cfg.get("enabled", True):
        return 1.0
    past = entry.get("past_performances") or []
    if not past:
        return 1.0
    times = []
    for pp in past[: int(cfg.get("max_past_races", 3))]:
        pace = pp.get("pace") or ""
        # "34.6-34.6" → second value
        if "-" in pace:
            try:
                _, last_3f = pace.split("-", 1)
                t = float(last_3f.strip())
                if 28.0 <= t <= 42.0:  # sanity range
                    times.append(t)
            except (ValueError, TypeError):
                continue
    min_n = int(cfg.get("min_past_races", 2))
    if len(times) < min_n:
        return 1.0
    avg = sum(times) / len(times)
    bands = cfg.get("bands", [
        {"max": 33.5, "factor": 1.05},
        {"max": 34.5, "factor": 1.03},
        {"max": 35.5, "factor": 1.00},
        {"max": 36.5, "factor": 0.98},
        {"max": 99.0, "factor": 0.95},
    ])
    for b in bands:
        if avg <= float(b.get("max", 99.0)):
            return float(b.get("factor", 1.0))
    return 1.0


def _entry_number_matches(left: Any, right: Any) -> bool:
    if left == right:
        return True
    left_int = _as_int(left)
    right_int = _as_int(right)
    return left_int is not None and right_int is not None and left_int == right_int


def _kelly_stake_multiplier(candidates: list, race: dict, _W: dict) -> tuple[float, dict]:
    """v8.4.0 Kelly fractional stake sizing.

    Multiplies base race budget by a factor derived from:
      - axis horse DSLR (days since last race)
      - top-EV edge_ratio (model_p / implied_p)

    Returns (multiplier, breakdown_dict). Multiplier is capped to
    [safety_min, safety_max] from config (default [0.5, 2.0]).

    Empirically validated (Codex Phase G-O on n=337 stakes 2023-2025):
      profit +¥72,582 vs v8.2 baseline +¥152,500
      CV mean +¥14,516 ± std ¥13,611 (statistically significant)

    Selection (axis pick) is NOT changed by this function. Only stake
    amount. Per Meehl/Kelly literature: separating WHO from HOW MUCH
    preserves engine's empirically-optimal axis selection while
    extracting Kelly-style edge from confidence-conditional sizing.

    breakdown_dict keys: dslr_multiplier, edge_ratio_multiplier,
        raw_product, capped_multiplier, axis_dslr_days,
        axis_edge_ratio.

    Disabled via _W["kelly_stake"]["enabled"] = false.
    Runtime emergency brake: HORSE_AI_KELLY_STAKE_DISABLE=1.
    """
    cfg = _W.get("kelly_stake", {})
    env_disabled = str(_os.environ.get("HORSE_AI_KELLY_STAKE_DISABLE", "")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if env_disabled or not cfg.get("enabled", True):
        return (
            1.0,
            {
                "enabled": False,
                "reason": "disabled_by_env" if env_disabled else "disabled_by_config",
            },
        )

    if not candidates:
        return (1.0, {"reason": "no_candidates"})

    axis = candidates[0] if isinstance(candidates[0], dict) else {}
    axis_number = axis.get("number")
    entries = race.get("entries") or []
    axis_entry = next(
        (entry for entry in entries if _entry_number_matches(entry.get("number"), axis_number)),
        {},
    )

    axis_dslr_days = None
    dslr_multiplier = 1.0
    past = axis_entry.get("past_performances") or []
    pp_date = (past[0] or {}).get("date") if past else None
    race_date = race.get("date")
    if pp_date and race_date:
        try:
            from datetime import date as _d

            axis_dslr_days = (_d.fromisoformat(race_date) - _d.fromisoformat(pp_date)).days
        except (TypeError, ValueError):
            axis_dslr_days = None
    if axis_dslr_days is not None and axis_dslr_days >= 0:
        for band in cfg.get(
            "dslr_bands",
            [
                {"max": 35, "multiplier": 0.667},
                {"max": 63, "multiplier": 1.0},
                {"max": 9999, "multiplier": 1.5},
            ],
        ):
            if axis_dslr_days <= int(band.get("max", 9999)):
                dslr_multiplier = float(band.get("multiplier", 1.0))
                break

    model_p = _as_float(axis.get("model_probability"))
    implied_p = _as_float(axis.get("implied_probability"))
    axis_edge_ratio = 1.0
    if model_p is not None and implied_p is not None and implied_p > 0:
        axis_edge_ratio = model_p / implied_p

    edge_ratio_multiplier = 1.0
    for band in cfg.get(
        "edge_ratio_bands",
        [
            {"min": 0.85, "multiplier": 1.4},
            {"min": 0.70, "multiplier": 1.0},
            {"min": 0.0, "multiplier": 0.8},
        ],
    ):
        if axis_edge_ratio >= float(band.get("min", 0.0)):
            edge_ratio_multiplier = float(band.get("multiplier", 1.0))
            break

    raw_product = dslr_multiplier * edge_ratio_multiplier

    # v8.4.2 V4: pop=2 cap. Empirical 4-year analysis (n=199): axis_pop=2
    # axes have ROI 110% / hit 27% — Kelly amplification (mult>1.0) loses
    # money. Cap multiplier at 1.0 (no amplification) for pop=2 axes.
    # Disable via weights.json kelly_stake.pop2_cap_enabled = false.
    pop2_capped = False
    axis_pop_v = axis.get("popularity")
    try:
        axis_pop_int = int(axis_pop_v) if axis_pop_v is not None else None
    except (TypeError, ValueError):
        axis_pop_int = None
    if cfg.get("pop2_cap_enabled", True) and axis_pop_int == 2 and raw_product > 1.0:
        raw_product = 1.0
        pop2_capped = True

    # v8.4.2 V6: DSLR 64-90 magic zone boost. Empirical 4-year (n=47):
    # DSLR 64-90 cell delta +¥53,470 (largest single Kelly contributor).
    # Multiply post-cap raw_product by configured factor (default 1.2).
    # Disable via weights.json kelly_stake.dslr_64_90_boost_enabled = false.
    dslr_boosted = False
    if (
        cfg.get("dslr_64_90_boost_enabled", True)
        and axis_dslr_days is not None
        and 64 <= axis_dslr_days <= 90
    ):
        boost = float(cfg.get("dslr_64_90_boost_factor", 1.2))
        raw_product = raw_product * boost
        dslr_boosted = True

    safety_min = float(cfg.get("safety_min", 0.5))
    safety_max = float(cfg.get("safety_max", 2.0))
    capped_multiplier = _clamp(raw_product, safety_min, safety_max)
    # M.6's low bucket (0.667 * 0.8) floors to the same ¥600 stake as 0.5.
    if safety_min < capped_multiplier < safety_min + 0.05:
        capped_multiplier = safety_min
    return (
        capped_multiplier,
        {
            "dslr_multiplier": dslr_multiplier,
            "edge_ratio_multiplier": edge_ratio_multiplier,
            "raw_product": raw_product,
            "capped_multiplier": capped_multiplier,
            "axis_dslr_days": axis_dslr_days,
            "axis_edge_ratio": axis_edge_ratio,
            "pop2_capped": pop2_capped,
            "dslr_64_90_boosted": dslr_boosted,
        },
    )


def _owner_breeder_factor(entry: dict, _W: dict) -> float:
    cfg = _W.get("owner_breeder", {})
    if not cfg.get("enabled", True):
        return 1.0

    owner_tier = entry.get("owner_tier") or "Other"
    farm_tier = entry.get("farm_tier") or "Other"
    owner_boost_map = cfg.get("owner_tier_boost", {"Tier1": 0.015, "Tier2": 0.005, "Other": 0.0})
    farm_boost_map = cfg.get("farm_tier_boost", {"Tier1": 0.015, "Tier2": 0.005, "Other": 0.0})

    owner_boost = float(owner_boost_map.get(owner_tier, 0.0))
    farm_boost = float(farm_boost_map.get(farm_tier, 0.0))
    total_boost = min(owner_boost + farm_boost, float(cfg.get("max_total_boost", 0.03)))
    return 1.0 + total_boost
