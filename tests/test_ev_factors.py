from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from src.engine.ev_factors import (
    _class_step_factor,
    _condition_aptitude_factor,
    _gate_factor,
    _kelly_stake_multiplier,
    _owner_breeder_factor,
    _pedigree_factor,
    _style_condition_factor,
    _weight_trend_factor,
)


def _kelly_cfg(enabled: bool = True, pop2_cap: bool = False, dslr_boost: bool = False) -> dict:
    """v8.4.2 test helper. By default V4 (pop2 cap) and V6 (DSLR 64-90 boost)
    are DISABLED so legacy v8.4.1-era tests exercise pure band logic. Tests
    for V4/V6 set the flags explicitly."""
    return {
        "kelly_stake": {
            "enabled": enabled,
            "dslr_bands": [
                {"max": 35, "multiplier": 0.667},
                {"max": 63, "multiplier": 1.0},
                {"max": 9999, "multiplier": 1.5},
            ],
            "edge_ratio_bands": [
                {"min": 0.85, "multiplier": 1.4},
                {"min": 0.70, "multiplier": 1.0},
                {"min": 0.0, "multiplier": 0.8},
            ],
            "safety_min": 0.5,
            "safety_max": 2.0,
            "pop2_cap_enabled": pop2_cap,
            "dslr_64_90_boost_enabled": dslr_boost,
            "dslr_64_90_boost_factor": 1.2,
        }
    }


def _kelly_candidate(model_p: float, implied_p: float) -> dict:
    return {
        "number": 7,
        "model_probability": model_p,
        "implied_probability": implied_p,
    }


def _kelly_race(past_date: str | None) -> dict:
    entry = {"number": 7}
    if past_date is not None:
        entry["past_performances"] = [{"date": past_date}]
    return {"date": "2026-04-28", "entries": [entry]}


class TestKellyStakeMultiplier:
    def test_disabled_returns_neutral(self):
        multiplier, breakdown = _kelly_stake_multiplier(
            [_kelly_candidate(0.45, 0.5)],
            _kelly_race("2026-02-17"),
            _kelly_cfg(enabled=False),
        )

        assert multiplier == 1.0
        assert breakdown["enabled"] is False

    def test_long_dslr_high_edge_caps_upper(self):
        multiplier, breakdown = _kelly_stake_multiplier(
            [_kelly_candidate(0.45, 0.5)],
            _kelly_race("2026-02-17"),
            _kelly_cfg(),
        )

        assert multiplier == 2.0
        assert breakdown["axis_dslr_days"] == 70
        assert breakdown["dslr_multiplier"] == 1.5
        assert breakdown["edge_ratio_multiplier"] == 1.4
        assert abs(breakdown["raw_product"] - 2.1) < 0.001
        assert breakdown["capped_multiplier"] == 2.0

    def test_short_dslr_low_edge_caps_lower(self):
        multiplier, breakdown = _kelly_stake_multiplier(
            [_kelly_candidate(0.25, 0.5)],
            _kelly_race("2026-04-08"),
            _kelly_cfg(),
        )

        assert multiplier == 0.5
        assert breakdown["axis_dslr_days"] == 20
        assert breakdown["dslr_multiplier"] == 0.667
        assert breakdown["edge_ratio_multiplier"] == 0.8
        assert abs(breakdown["raw_product"] - 0.5336) < 0.001
        assert breakdown["capped_multiplier"] == 0.5

    def test_mid_dslr_neutral_edge_is_unchanged(self):
        multiplier, breakdown = _kelly_stake_multiplier(
            [_kelly_candidate(0.39, 0.5)],
            _kelly_race("2026-03-09"),
            _kelly_cfg(),
        )

        assert multiplier == 1.0
        assert breakdown["axis_dslr_days"] == 50
        assert breakdown["dslr_multiplier"] == 1.0
        assert breakdown["edge_ratio_multiplier"] == 1.0

    def test_missing_past_performances_defaults_dslr_neutral(self):
        multiplier, breakdown = _kelly_stake_multiplier(
            [_kelly_candidate(0.45, 0.5)],
            _kelly_race(None),
            _kelly_cfg(),
        )

        assert abs(multiplier - 1.4) < 0.001
        assert breakdown["axis_dslr_days"] is None
        assert breakdown["dslr_multiplier"] == 1.0
        assert breakdown["edge_ratio_multiplier"] == 1.4

    # v8.4.2 V4: pop=2 cap
    def test_pop2_cap_blocks_amplification(self):
        cand = _kelly_candidate(0.45, 0.5)
        cand["popularity"] = 2  # 2nd favorite
        multiplier, breakdown = _kelly_stake_multiplier(
            [cand],
            _kelly_race("2026-02-17"),  # DSLR=70, would otherwise mult 1.5×1.4=2.1
            _kelly_cfg(pop2_cap=True),
        )
        assert multiplier == 1.0  # capped down from 2.1 → 1.0
        assert breakdown["pop2_capped"] is True
        assert breakdown["raw_product"] == 1.0

    def test_pop2_cap_does_not_affect_pop1(self):
        cand = _kelly_candidate(0.45, 0.5)
        cand["popularity"] = 1  # 1st favorite
        multiplier, _ = _kelly_stake_multiplier(
            [cand],
            _kelly_race("2026-02-17"),  # DSLR=70 → 1.5
            _kelly_cfg(pop2_cap=True),
        )
        assert multiplier == 2.0  # full 2.1 capped to 2.0 by safety_max

    def test_pop2_cap_disabled_passes_through(self):
        cand = _kelly_candidate(0.45, 0.5)
        cand["popularity"] = 2
        multiplier, breakdown = _kelly_stake_multiplier(
            [cand],
            _kelly_race("2026-02-17"),
            _kelly_cfg(pop2_cap=False),
        )
        assert multiplier == 2.0  # not capped
        assert breakdown["pop2_capped"] is False

    # v8.4.2 V6: DSLR 64-90 magic zone boost
    def test_dslr_boost_in_magic_zone(self):
        # DSLR=70, edge_ratio=0.9 (>0.85) → base 1.5×1.4=2.1, boost ×1.2 → 2.52, capped 2.0
        multiplier, breakdown = _kelly_stake_multiplier(
            [_kelly_candidate(0.45, 0.5)],
            _kelly_race("2026-02-17"),
            _kelly_cfg(dslr_boost=True),
        )
        assert breakdown["dslr_64_90_boosted"] is True
        assert abs(breakdown["raw_product"] - 2.52) < 0.001
        assert multiplier == 2.0

    def test_dslr_boost_outside_zone_no_effect(self):
        # DSLR=20, mult 0.667×0.8=0.5336 → no boost
        multiplier, breakdown = _kelly_stake_multiplier(
            [_kelly_candidate(0.25, 0.5)],
            _kelly_race("2026-04-08"),
            _kelly_cfg(dslr_boost=True),
        )
        assert breakdown["dslr_64_90_boosted"] is False
        assert abs(breakdown["raw_product"] - 0.5336) < 0.001

    def test_dslr_boost_disabled_passes_through(self):
        multiplier, breakdown = _kelly_stake_multiplier(
            [_kelly_candidate(0.45, 0.5)],
            _kelly_race("2026-02-17"),
            _kelly_cfg(dslr_boost=False),
        )
        assert breakdown["dslr_64_90_boosted"] is False
        assert abs(breakdown["raw_product"] - 2.1) < 0.001

    def test_v9_combined_pop2_cap_takes_precedence_over_dslr_boost(self):
        cand = _kelly_candidate(0.45, 0.5)
        cand["popularity"] = 2
        # pop2 → cap to 1.0 first; then DSLR 70 boosts 1.0×1.2=1.2; safety cap [0.5, 2.0]
        multiplier, breakdown = _kelly_stake_multiplier(
            [cand],
            _kelly_race("2026-02-17"),
            _kelly_cfg(pop2_cap=True, dslr_boost=True),
        )
        assert breakdown["pop2_capped"] is True
        assert breakdown["dslr_64_90_boosted"] is True
        assert abs(breakdown["raw_product"] - 1.2) < 0.001
        assert multiplier == 1.2


class TestGateFactor:
    def test_null_gate_num_returns_1(self):
        assert _gate_factor({}, {}, {"gate_bias": {"enabled": True}}, 18) == 1.0

    def test_disabled_returns_1(self):
        assert (
            _gate_factor(
                {"gate_num": 1},
                {"venue": "中山", "surface": "芝", "distance": 1200},
                {"gate_bias": {"enabled": False}},
                18,
            )
            == 1.0
        )

    def test_small_field_returns_1(self):
        cfg = {"gate_bias": {"enabled": True, "small_field_disable_threshold": 8}}
        assert _gate_factor({"gate_num": 1}, {"venue": "中山", "surface": "芝", "distance": 1200}, cfg, 6) == 1.0

    def test_inner_gate_nakayama_turf_sprint(self):
        cfg = {"gate_bias": {"enabled": True, "small_field_disable_threshold": 8}}
        result = _gate_factor({"gate_num": 2}, {"venue": "中山", "surface": "芝", "distance": 1200}, cfg, 16)
        assert abs(result - 1.06) < 0.001

    def test_middle_gate_returns_neutral(self):
        cfg = {"gate_bias": {"enabled": True, "small_field_disable_threshold": 8}}
        result = _gate_factor({"gate_num": 7}, {"venue": "中山", "surface": "芝", "distance": 1200}, cfg, 16)
        assert abs(result - 1.00) < 0.001


class TestPedigreeFactor:
    def test_missing_sire_returns_1(self):
        cfg = {"pedigree_factor": {"enabled": True, "max_deviation": 0.05, "include_dam_sire_on_dirt": True}}
        assert _pedigree_factor({}, {"surface": "芝", "distance": 1600}, cfg) == 1.0

    def test_disabled_returns_1(self):
        cfg = {"pedigree_factor": {"enabled": False}}
        assert _pedigree_factor({"sire": "ロードカナロア"}, {"surface": "芝", "distance": 1200}, cfg) == 1.0

    def test_unknown_sire_returns_1(self):
        cfg = {"pedigree_factor": {"enabled": True, "max_deviation": 0.05, "include_dam_sire_on_dirt": True}}
        result = _pedigree_factor({"sire": "Unknown Sire XYZ"}, {"surface": "芝", "distance": 1200}, cfg)
        assert result == 1.0

    def test_road_kanaloa_turf_sprint(self):
        cfg = {"pedigree_factor": {"enabled": True, "max_deviation": 0.05, "include_dam_sire_on_dirt": True}}
        result = _pedigree_factor({"sire": "ロードカナロア"}, {"surface": "芝", "distance": 1200}, cfg)
        assert abs(result - 1.05) < 0.001

    def test_dam_sire_dirt_averaging(self):
        cfg = {"pedigree_factor": {"enabled": True, "max_deviation": 0.05, "include_dam_sire_on_dirt": True}}
        entry = {"sire": "ロードカナロア", "dam_sire": "ゴールドアリュール"}
        result = _pedigree_factor(entry, {"surface": "ダート", "distance": 1700}, cfg)
        assert result >= 1.03 and result <= 1.05


class TestConditionAptitudeFactor:
    def test_missing_track_condition_returns_1(self):
        cfg = {
            "condition_aptitude": {
                "enabled": True,
                "min_past_races": 3,
                "max_deviation": 0.10,
                "finish_weights": {"1": 1.0, "2": 0.6, "3": 0.4, "4": 0.2, "5": 0.2},
            }
        }
        assert _condition_aptitude_factor({}, {}, cfg) == 1.0

    def test_disabled_returns_1(self):
        cfg = {"condition_aptitude": {"enabled": False}}
        assert _condition_aptitude_factor({}, {"track_condition": "重"}, cfg) == 1.0

    def test_insufficient_samples_returns_1(self):
        cfg = {
            "condition_aptitude": {
                "enabled": True,
                "min_past_races": 3,
                "max_deviation": 0.10,
                "finish_weights": {"1": 1.0, "2": 0.6, "3": 0.4, "4": 0.2, "5": 0.2},
            }
        }
        entry = {"past_performances": [{"track_condition": "重", "finish_position": 1}, {"track_condition": "重", "finish_position": 2}]}
        assert _condition_aptitude_factor(entry, {"track_condition": "重"}, cfg) == 1.0

    def test_strong_wet_record_boost(self):
        cfg = {
            "condition_aptitude": {
                "enabled": True,
                "min_past_races": 3,
                "max_deviation": 0.10,
                "finish_weights": {"1": 1.0, "2": 0.6, "3": 0.4, "4": 0.2, "5": 0.2},
            }
        }
        past = [{"track_condition": "重", "finish_position": 1} for _ in range(4)]
        past += [{"track_condition": "良", "finish_position": 5} for _ in range(4)]
        entry = {"past_performances": past}
        result = _condition_aptitude_factor(entry, {"track_condition": "重"}, cfg)
        assert result > 1.0


class TestStyleConditionFactor:
    def test_missing_condition_returns_1(self):
        cfg = {"style_condition_bias": {"enabled": True, "table": {}}}
        assert _style_condition_factor({}, {}, cfg) == 1.0

    def test_disabled_returns_1(self):
        cfg = {"style_condition_bias": {"enabled": False}}
        assert _style_condition_factor({"dominant_style": "逃げ"}, {"track_condition": "不良"}, cfg) == 1.0

    def test_furyo_nige(self):
        table = {"良": {"逃げ": 1.00}, "稍重": {"逃げ": 1.02}, "重": {"逃げ": 1.04}, "不良": {"逃げ": 1.06}}
        cfg = {"style_condition_bias": {"enabled": True, "table": table}}
        result = _style_condition_factor({"dominant_style": "逃げ"}, {"track_condition": "不良"}, cfg)
        assert abs(result - 1.06) < 0.001

    def test_furyo_oikomi(self):
        table = {"良": {"追込": 1.00}, "稍重": {"追込": 0.98}, "重": {"追込": 0.95}, "不良": {"追込": 0.92}}
        cfg = {"style_condition_bias": {"enabled": True, "table": table}}
        result = _style_condition_factor({"dominant_style": "追込"}, {"track_condition": "不良"}, cfg)
        assert abs(result - 0.92) < 0.001

    def test_ryo_neutral(self):
        table = {"良": {"逃げ": 1.00, "追込": 1.00}}
        cfg = {"style_condition_bias": {"enabled": True, "table": table}}
        assert _style_condition_factor({"dominant_style": "追込"}, {"track_condition": "良"}, cfg) == 1.0


class TestClassStepFactor:
    def test_missing_race_class_returns_1(self):
        cfg = {"class_step": {"enabled": True, "step_scale": 0.03, "max_deviation": 0.05}}
        assert _class_step_factor({}, {}, cfg) == 1.0

    def test_disabled_returns_1(self):
        cfg = {"class_step": {"enabled": False}}
        assert _class_step_factor({}, {"race_class": "G1"}, cfg) == 1.0

    def test_large_step_up_penalty(self):
        cfg = {"class_step": {"enabled": True, "step_scale": 0.03, "max_deviation": 0.05}}
        past = [{"race_class": "未勝利"}, {"race_class": "未勝利"}, {"race_class": "未勝利"}]
        entry = {"past_performances": past}
        result = _class_step_factor(entry, {"race_class": "オープン"}, cfg)
        assert abs(result - 0.95) < 0.001

    def test_step_down_boost(self):
        cfg = {"class_step": {"enabled": True, "step_scale": 0.03, "max_deviation": 0.05}}
        past = [{"race_class": "G1"} for _ in range(3)]
        entry = {"past_performances": past}
        result = _class_step_factor(entry, {"race_class": "オープン"}, cfg)
        assert result > 1.0 and result <= 1.05


class TestWeightTrendFactor:
    def test_missing_current_weight_returns_1(self):
        cfg = {
            "weight_trend": {
                "enabled": True,
                "min_past_with_weight": 2,
                "stable_threshold_kg": 4,
                "drop_threshold_kg": 10,
                "gain_threshold_kg": 10,
                "stable_boost": 0.02,
                "drop_decay": 0.05,
                "gain_decay": 0.03,
                "season_adjust": False,
            }
        }
        assert _weight_trend_factor({}, cfg) == 1.0

    def test_disabled_returns_1(self):
        cfg = {"weight_trend": {"enabled": False}}
        assert _weight_trend_factor({"horse_weight": 480}, cfg) == 1.0

    def test_stable_weight_boost(self):
        cfg = {
            "weight_trend": {
                "enabled": True,
                "min_past_with_weight": 2,
                "stable_threshold_kg": 4,
                "drop_threshold_kg": 10,
                "gain_threshold_kg": 10,
                "stable_boost": 0.02,
                "drop_decay": 0.05,
                "gain_decay": 0.03,
                "season_adjust": False,
            }
        }
        entry = {"horse_weight": 482, "past_performances": [{"horse_weight": 480}, {"horse_weight": 480}]}
        result = _weight_trend_factor(entry, cfg)
        assert abs(result - 1.02) < 0.001

    def test_heavy_drop_decay(self):
        cfg = {
            "weight_trend": {
                "enabled": True,
                "min_past_with_weight": 2,
                "stable_threshold_kg": 4,
                "drop_threshold_kg": 10,
                "gain_threshold_kg": 10,
                "stable_boost": 0.02,
                "drop_decay": 0.05,
                "gain_decay": 0.03,
                "season_adjust": False,
            }
        }
        entry = {"horse_weight": 460, "past_performances": [{"horse_weight": 480}, {"horse_weight": 480}]}
        result = _weight_trend_factor(entry, cfg)
        assert abs(result - 0.95) < 0.001

    def test_season_adjust_young_horse(self):
        cfg = {
            "weight_trend": {
                "enabled": True,
                "min_past_with_weight": 2,
                "stable_threshold_kg": 4,
                "drop_threshold_kg": 10,
                "gain_threshold_kg": 10,
                "stable_boost": 0.02,
                "drop_decay": 0.05,
                "gain_decay": 0.03,
                "season_adjust": True,
                "season_adjust_stable_threshold_kg": 8,
                "season_adjust_max_past_races": 6,
            }
        }
        past = [{"horse_weight": 476}, {"horse_weight": 476}, {"horse_weight": 476}, {"horse_weight": 476}]
        entry = {"horse_weight": 470, "age": 3, "past_performances": past}
        result = _weight_trend_factor(entry, cfg)
        assert abs(result - 1.02) < 0.001


class TestOwnerBreederFactor:
    def test_all_null_returns_1(self):
        cfg = {
            "owner_breeder": {
                "enabled": True,
                "owner_tier_boost": {"Tier1": 0.015, "Tier2": 0.005, "Other": 0.0},
                "farm_tier_boost": {"Tier1": 0.015, "Tier2": 0.005, "Other": 0.0},
                "max_total_boost": 0.03,
            }
        }
        assert _owner_breeder_factor({}, cfg) == 1.0

    def test_disabled_returns_1(self):
        cfg = {"owner_breeder": {"enabled": False}}
        assert _owner_breeder_factor({"owner_tier": "Tier1", "farm_tier": "Tier1"}, cfg) == 1.0

    def test_both_tier1_capped(self):
        cfg = {
            "owner_breeder": {
                "enabled": True,
                "owner_tier_boost": {"Tier1": 0.015, "Tier2": 0.005, "Other": 0.0},
                "farm_tier_boost": {"Tier1": 0.015, "Tier2": 0.005, "Other": 0.0},
                "max_total_boost": 0.03,
            }
        }
        result = _owner_breeder_factor({"owner_tier": "Tier1", "farm_tier": "Tier1"}, cfg)
        assert abs(result - 1.03) < 0.001

    def test_tier2_owner_only(self):
        cfg = {
            "owner_breeder": {
                "enabled": True,
                "owner_tier_boost": {"Tier1": 0.015, "Tier2": 0.005, "Other": 0.0},
                "farm_tier_boost": {"Tier1": 0.015, "Tier2": 0.005, "Other": 0.0},
                "max_total_boost": 0.03,
            }
        }
        result = _owner_breeder_factor({"owner_tier": "Tier2", "farm_tier": "Other"}, cfg)
        assert abs(result - 1.005) < 0.001


class TestSafetyCap:
    def test_product_capped_at_max(self):
        product = 1.08**7
        capped = max(0.85, min(1.15, product))
        assert abs(capped - 1.15) < 0.001

    def test_product_capped_at_min(self):
        product = 0.92**7
        capped = max(0.85, min(1.15, product))
        assert abs(capped - 0.85) < 0.001
