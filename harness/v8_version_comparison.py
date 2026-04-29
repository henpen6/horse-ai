#!/usr/bin/env python3
"""v8_version_comparison.py — backtest each engine version across 2022-2025.

Runs all 4 engine configurations on snapshots:
  v7.9 equivalent  — factors OFF, hard_skip OFF, kelly OFF
  v8.0 equivalent  — factors ON,  hard_skip OFF, kelly OFF
  v8.2/v8.4.0      — factors ON,  hard_skip ON,  kelly OFF
  v8.4.1           — factors ON,  hard_skip ON,  kelly ON

For each (version, year): n, stake, payout, profit, ROI, hit_rate.

Output: stdout table + JSON dump to apps/horse-ai/data/kelly_redux/version_comparison.json
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

REPO = pathlib.Path("/Users/masa/Dev/ai-fortress")
HORSE_AI = pathlib.Path("/Users/masa/Dev/horse-ai/apps/horse-ai")
sys.path.insert(0, str(HORSE_AI))

from src.engine import ev as _ev_module  # noqa: E402
from src.engine.future_minimal import run_future_engine  # noqa: E402
from src.engine.review import review_bets  # noqa: E402

SNAPSHOT_DIR = HORSE_AI / "data" / "snapshots"
SIM_CACHE_DIR = pathlib.Path.home() / ".openclaw" / "agents" / "horse-run-claw" / "workspace" / "sim_results_cache"
OUTPUT_PATH = HORSE_AI / "data" / "kelly_redux" / "version_comparison.json"

# Active factor blocks (production defaults; unused gate/pedigree/owner kept off)
ACTIVE_FACTOR_BLOCKS = (
    "condition_aptitude",
    "style_condition_bias",
    "class_step",
    "weight_trend",
    "new_factors_safety_cap",
)

VERSIONS = [
    ("v7.9 (no factors)",       False, False, False),
    ("v8.0 (+factors)",         True,  False, False),
    ("v8.2/v8.4.0 (+SKIP)",     True,  True,  False),
    ("v8.4.1 (+kelly)",         True,  True,  True),
]


def set_state(factors_on: bool, hard_skip_on: bool, kelly_on: bool) -> dict:
    """Toggle the 3 main switches. Returns original state for restore."""
    original = {}
    for blk in ACTIVE_FACTOR_BLOCKS:
        cfg = _ev_module._W.get(blk)
        if isinstance(cfg, dict):
            original[blk] = cfg.get("enabled", True)
            cfg["enabled"] = factors_on
    for k in ("hard_skip", "kelly_stake"):
        cfg = _ev_module._W.get(k)
        if isinstance(cfg, dict):
            original[k] = cfg.get("enabled", True)
    cfg = _ev_module._W.get("hard_skip")
    if isinstance(cfg, dict):
        cfg["enabled"] = hard_skip_on
    cfg = _ev_module._W.get("kelly_stake")
    if isinstance(cfg, dict):
        cfg["enabled"] = kelly_on
    return original


def restore_state(original: dict) -> None:
    for k, v in original.items():
        cfg = _ev_module._W.get(k)
        if isinstance(cfg, dict):
            cfg["enabled"] = v


def _build_collector_result(snapshot: dict) -> dict | None:
    cr = snapshot.get("collector_result") or {}
    if not cr:
        return None
    if not cr.get("entries"):
        cr["entries"] = snapshot.get("entries") or []
    if not cr.get("odds"):
        cr["odds"] = snapshot.get("odds") or {}
    return cr


def _review_input(actual_result: dict) -> dict:
    return {
        "finish_order": actual_result.get("finishing_order") or actual_result.get("finish_order") or [],
        "payouts": actual_result.get("payouts") or {},
    }


def run_one_set(version_label: str, factors_on: bool, hard_skip_on: bool, kelly_on: bool, snapshots: list[pathlib.Path]) -> dict:
    """Run engine on all snapshots with the given config; return per-year + total stats."""
    original = set_state(factors_on, hard_skip_on, kelly_on)
    by_year: dict[str, dict] = {}
    try:
        for sp in snapshots:
            year = sp.name[:4]
            by_year.setdefault(year, {"n": 0, "stake": 0, "payout": 0, "hits": 0, "engine_skip": 0, "hard_stop": 0})

            try:
                snapshot = json.loads(sp.read_text(encoding="utf-8"))
                cr = _build_collector_result(snapshot)
                if not cr:
                    continue
                name = sp.stem.replace("_snapshot", "")
                cache_path = SIM_CACHE_DIR / f"{name}.json"
                if not cache_path.exists():
                    continue
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
                actual_result = cache.get("actual_result") or {}
                if not actual_result.get("payouts"):
                    continue
                ri = _review_input(actual_result)
                eng = run_future_engine(collector_result=cr, budget=1200, budget_source="backtest")
            except Exception:
                continue

            if not eng.get("ok"):
                by_year[year]["hard_stop"] += 1
                continue
            pf = eng.get("portfolio_v3") or eng.get("portfolio") or {}
            bets = pf.get("bets") or []
            if not bets:
                # engine_skip path
                by_year[year]["engine_skip"] += 1
                by_year[year]["n"] += 1
                continue
            rev = review_bets(bets, ri)
            stake = pf.get("total_stake", sum(b.get("stake_yen", 0) for b in bets))
            payout = rev.get("total_payout", 0)
            hits = rev.get("hit_count", 0)
            by_year[year]["n"] += 1
            by_year[year]["stake"] += stake
            by_year[year]["payout"] += payout
            if hits > 0:
                by_year[year]["hits"] += 1
    finally:
        restore_state(original)
    return by_year


def main() -> int:
    snapshots = sorted(SNAPSHOT_DIR.glob("*_snapshot.json"))
    snapshots = [p for p in snapshots if p.name[:4] in ("2022", "2023", "2024", "2025")]
    print(f"snapshots: {len(snapshots)}", file=sys.stderr)

    results = {}
    started = time.time()
    for label, factors_on, hard_skip_on, kelly_on in VERSIONS:
        t0 = time.time()
        by_year = run_one_set(label, factors_on, hard_skip_on, kelly_on, snapshots)
        results[label] = by_year
        el = time.time() - t0
        print(f"  {label}: done in {el:.0f}s", file=sys.stderr)

    elapsed = time.time() - started
    print(f"\ntotal elapsed: {elapsed:.0f}s\n", file=sys.stderr)

    # Print table
    years = ["2022", "2023", "2024", "2025", "TOTAL"]
    print(f"{'version':<28} | {'year':>5} | {'n':>4} | {'stake':>9} | {'payout':>9} | {'profit':>10} | {'ROI':>6} | {'hit':>9} | {'eng_skip':>9}")
    print("-" * 120)
    for label, _, _, _ in VERSIONS:
        by_year = results[label]
        sums = {"n": 0, "stake": 0, "payout": 0, "hits": 0, "engine_skip": 0}
        for y in ["2022", "2023", "2024", "2025"]:
            d = by_year.get(y, {"n": 0, "stake": 0, "payout": 0, "hits": 0, "engine_skip": 0})
            n_bet = d["n"] - d["engine_skip"]
            roi = (d["payout"] / d["stake"] * 100) if d["stake"] else 0
            hit_rate = (d["hits"] / n_bet * 100) if n_bet else 0
            print(f"{label:<28} | {y:>5} | {d['n']:>4} | ¥{d['stake']:>7,} | ¥{d['payout']:>7,} | ¥{d['payout']-d['stake']:>+8,} | {roi:>5.1f}% | {d['hits']}/{n_bet} ({hit_rate:>2.0f}%) | {d['engine_skip']:>9}")
            for k in sums:
                sums[k] += d[k]
        n_bet = sums["n"] - sums["engine_skip"]
        roi = (sums["payout"] / sums["stake"] * 100) if sums["stake"] else 0
        hit_rate = (sums["hits"] / n_bet * 100) if n_bet else 0
        print(f"{label:<28} | TOTAL | {sums['n']:>4} | ¥{sums['stake']:>7,} | ¥{sums['payout']:>7,} | ¥{sums['payout']-sums['stake']:>+8,} | {roi:>5.1f}% | {sums['hits']}/{n_bet} ({hit_rate:>2.0f}%) | {sums['engine_skip']:>9}")
        print("-" * 120)

    # JSON dump
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
