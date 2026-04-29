from __future__ import annotations

import copy
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from src.engine.ev import classify_unknown_x, compute_win_ev_candidates
from src.engine import ev as ev_module
from src.engine.future_minimal import run_future_engine


def test_classify_unknown_x_class_up_signal() -> None:
    status, reasons = classify_unknown_x(
        {"past_performances": [{"class_tier": "B"}]},
        current_class_tier="A",
    )

    assert status == "X-High"
    assert "class_up" in reasons


def test_classify_unknown_x_substitute_race_signal() -> None:
    status, reasons = classify_unknown_x({}, race={"substitute_venue": True})

    assert status == "X-High"
    assert "substitute_race" in reasons


def test_classify_unknown_x_form_degradation_signal() -> None:
    status, reasons = classify_unknown_x(
        {"past_performances": [{"jra_rating": 80}, {"jra_rating": 90}]}
    )

    assert status == "X-High"
    assert "rt_drop=10.0" in reasons


def test_classify_unknown_x_style_mismatch_signal() -> None:
    entry = {"dominant_style": "差し"}
    status, reasons = classify_unknown_x(
        entry,
        dominant_style="差し",
        all_entries=[entry, {"dominant_style": "追込"}, {"dominant_style": "差し"}],
    )

    assert status == "X-High"
    assert "slow_pace_against_closer" in reasons


def test_classify_unknown_x_weight_load_delta_signal() -> None:
    status, reasons = classify_unknown_x(
        {"past_performances": [{"weight_kg": 55.0}]},
        current_weight_kg=59.0,
    )

    assert status == "X-High"
    assert "load_delta=4.0kg" in reasons


def test_classify_unknown_x_career_density_signal() -> None:
    status, reasons = classify_unknown_x({"career_density": 4.5})

    assert status == "X-Low"
    assert "density=4.5" in reasons


def test_classify_unknown_x_first_gelding_signal() -> None:
    status, reasons = classify_unknown_x(
        {"sex": "セン", "past_performances": [{"sex": "牡"}]}
    )

    assert status == "X-Low"
    assert "first_gelding_race" in reasons


def test_classify_unknown_x_disappointed_favorite_signal() -> None:
    status, reasons = classify_unknown_x(
        {"past_performances": [{"popularity": 3, "finish_position": 6}]}
    )

    assert status == "X-High"
    assert "disappointed_fav:pop3->pos6" in reasons


def test_classify_unknown_x_missing_data_is_graceful() -> None:
    assert classify_unknown_x({}) == ("X-None", [])
    assert classify_unknown_x({"past_performances": [{}]}) == ("X-None", [])


def test_compute_win_ev_candidates_includes_ability_factor() -> None:
    candidates = compute_win_ev_candidates(_collector_result())

    assert candidates
    assert all("ability_factor" in candidate for candidate in candidates)


def test_compute_win_ev_candidates_ability_factor_range() -> None:
    candidates = compute_win_ev_candidates(_collector_result())

    assert candidates
    assert all(0.92 <= candidate["ability_factor"] <= 1.08 for candidate in candidates)


def test_compute_win_ev_candidates_includes_breakdown_factors() -> None:
    candidates = compute_win_ev_candidates(_collector_result())

    expected_keys = {
        "popularity_boost",
        "weight_factor",
        "ability_factor",
        "qualitative_factor",
        "gate_factor",
        "pedigree_factor",
        "condition_aptitude_factor",
        "style_condition_factor",
        "class_step_factor",
        "weight_trend_factor",
        "owner_breeder_factor",
        "new_factors_product",
    }
    assert candidates
    assert all(expected_keys <= set(candidate["breakdown_factors"]) for candidate in candidates)


def test_run_future_engine_surfaces_kelly_stake_details(monkeypatch) -> None:
    patched_w = copy.deepcopy(ev_module._W)
    patched_w.setdefault("hard_skip", {})["enabled"] = False
    patched_w["kelly_stake"] = {
        "enabled": True,
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
    }
    monkeypatch.setattr(ev_module, "_W", patched_w)

    result = run_future_engine(
        collector_result={
            "date": "2026-04-28",
            "entries": [
                {
                    "number": 7,
                    "name": "Kelly Axis",
                    "win_odds": 2.0,
                    "popularity": 1,
                    "weight_change": 0,
                    "past_performances": [{"date": "2026-02-17"}],
                }
            ],
        },
        budget=1200,
        budget_source="test",
    )

    assert result["ok"] is True
    assert result["kelly_stake_multiplier"] == 2.0
    assert result["kelly_stake_breakdown"]["axis_dslr_days"] == 70
    assert result["portfolio"]["total_stake"] == 2400


def _collector_result() -> dict:
    return {
        "entries": [
            {
                "number": 1,
                "name": "Alpha",
                "win_odds": 2.4,
                "popularity": 1,
                "weight_change": 0,
                "career_record": {"wins": 5, "total": 10},
                "class_tier": "S",
            },
            {
                "number": 2,
                "name": "Bravo",
                "win_odds": 4.8,
                "popularity": 2,
                "weight_change": 0,
                "career_record": {"wins": 2, "total": 12},
                "class_tier": "B",
            },
            {
                "number": 3,
                "name": "Charlie",
                "win_odds": 8.0,
                "popularity": 3,
                "weight_change": 0,
                "career_record": {"wins": 1, "total": 15},
                "class_tier": "C",
            },
        ]
    }
