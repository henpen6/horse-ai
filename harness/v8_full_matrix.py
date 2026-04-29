#!/usr/bin/env python3
"""v8_full_matrix.py — version × year × grade backtest matrix.

For each (version, year, grade) tuple, compute BET count, stake, payout,
profit, ROI, hit_rate on snapshots.

Output: CSV-friendly table + JSON dump.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import copy

REPO = pathlib.Path("/Users/masa/Dev/ai-fortress")
HORSE_AI = pathlib.Path("/Users/masa/Dev/horse-ai/apps/horse-ai")
sys.path.insert(0, str(HORSE_AI))

from src.engine import ev as _ev_module  # noqa: E402
from src.engine.future_minimal import run_future_engine  # noqa: E402
from src.engine.review import review_bets  # noqa: E402

SNAPSHOT_DIR = HORSE_AI / "data" / "snapshots"
SIM_CACHE_DIR = pathlib.Path.home() / ".openclaw" / "agents" / "horse-run-claw" / "workspace" / "sim_results_cache"
OUTPUT_PATH = HORSE_AI / "data" / "kelly_redux" / "full_matrix.json"

ACTIVE_FACTORS = ("condition_aptitude", "style_condition_bias", "class_step", "weight_trend", "new_factors_safety_cap")

orig_W = copy.deepcopy(_ev_module._W)


def reset_state():
    _ev_module._W = copy.deepcopy(orig_W)


def configure(version: str):
    """Apply version-specific config to in-memory _W."""
    reset_state()
    W = _ev_module._W
    if version == "v7.9":
        for f in ACTIVE_FACTORS:
            if isinstance(W.get(f), dict):
                W[f]["enabled"] = False
        W["hard_skip"]["enabled"] = False
        W["kelly_stake"]["enabled"] = False
    elif version == "v8.0":
        for f in ACTIVE_FACTORS:
            if isinstance(W.get(f), dict):
                W[f]["enabled"] = True
        W["hard_skip"]["enabled"] = False
        W["kelly_stake"]["enabled"] = False
    elif version == "v8.2":
        # factors + SKIP, no kelly, no rule_L
        W["hard_skip"]["enabled"] = True
        W["hard_skip"]["rule_L_enabled"] = False
        W["kelly_stake"]["enabled"] = False
    elif version == "v8.4.1":
        # factors + SKIP (no L) + kelly (no V4/V6/X)
        W["hard_skip"]["enabled"] = True
        W["hard_skip"]["rule_L_enabled"] = False
        W["kelly_stake"]["enabled"] = True
        W["kelly_stake"]["pop2_cap_enabled"] = False
        W["kelly_stake"]["dslr_64_90_boost_enabled"] = False
    elif version == "v8.4.2":
        # production current
        W["hard_skip"]["enabled"] = True
        W["hard_skip"]["rule_L_enabled"] = True
        W["kelly_stake"]["enabled"] = True
        W["kelly_stake"]["pop2_cap_enabled"] = True
        W["kelly_stake"]["dslr_64_90_boost_enabled"] = True
    elif version == "v8.5":
        # v8.4.2 + Codex numeric all-best
        W["hard_skip"]["enabled"] = True
        W["hard_skip"]["rule_L_enabled"] = True
        W["kelly_stake"]["enabled"] = True
        W["kelly_stake"]["pop2_cap_enabled"] = True
        W["kelly_stake"]["dslr_64_90_boost_enabled"] = True
        W["kelly_stake"]["dslr_bands"] = [
            {"max": 40, "multiplier": 0.85},
            {"max": 60, "multiplier": 1.1},
            {"max": 9999, "multiplier": 1.8},
        ]
        W["kelly_stake"]["edge_ratio_bands"] = [
            {"min": 0.83, "multiplier": 1.55},
            {"min": 0.65, "multiplier": 1.2},
            {"min": 0.0, "multiplier": 0.5},
        ]
        W["kelly_stake"]["safety_min"] = 0.4
        W["kelly_stake"]["safety_max"] = 2.5
        W["kelly_stake"]["dslr_64_90_boost_factor"] = 1.3


def run_one_set(snapshots: list[pathlib.Path]) -> dict:
    """Run engine on each snapshot, group by (year, grade). Returns nested dict."""
    out = {}
    for sp in snapshots:
        try:
            s = json.loads(sp.read_text(encoding="utf-8"))
            cr = s.get("collector_result") or {}
            if not cr.get("entries"):
                cr["entries"] = s.get("entries") or []
            if not cr.get("odds"):
                cr["odds"] = s.get("odds") or {}
            year = sp.name[:4]
            grade = cr.get("grade") or "_OPEN_"
            if grade not in ("G1", "G2", "G3"):
                continue
            cp = SIM_CACHE_DIR / f"{sp.stem.replace('_snapshot','')}.json"
            if not cp.exists():
                continue
            cache = json.loads(cp.read_text(encoding="utf-8"))
            ar = cache.get("actual_result") or {}
            if not ar.get("payouts"):
                continue
            ri = {"finish_order": ar.get("finishing_order") or [], "payouts": ar.get("payouts") or {}}
            eng = run_future_engine(collector_result=cr, budget=1200, budget_source="backtest")
        except Exception:
            continue
        if not eng.get("ok"):
            continue
        pf = eng.get("portfolio_v3") or eng.get("portfolio") or {}
        bets = pf.get("bets") or []
        if not bets:
            continue
        rev = review_bets(bets, ri)
        st = pf.get("total_stake", sum(b.get("stake_yen", 0) for b in bets))
        py = rev.get("total_payout", 0)
        h = int(rev.get("hit_count", 0) > 0)

        key = (year, grade)
        if key not in out:
            out[key] = {"n": 0, "stake": 0, "payout": 0, "hits": 0}
        out[key]["n"] += 1
        out[key]["stake"] += st
        out[key]["payout"] += py
        out[key]["hits"] += h
    return out


def main() -> int:
    snapshots = sorted(SNAPSHOT_DIR.glob("*_snapshot.json"))
    snapshots = [p for p in snapshots if p.name[:4] in ("2022", "2023", "2024", "2025", "2026")]

    versions = ["v7.9", "v8.0", "v8.2", "v8.4.1", "v8.4.2", "v8.5"]
    years = ["2022", "2023", "2024", "2025", "2026"]
    grades = ["G1", "G2", "G3"]

    matrix = {}
    started = time.time()
    for v in versions:
        configure(v)
        t0 = time.time()
        result = run_one_set(snapshots)
        matrix[v] = {f"{y}_{g}": result.get((y, g), {"n": 0, "stake": 0, "payout": 0, "hits": 0}) for y in years for g in grades}
        print(f"  {v}: {time.time() - t0:.0f}s", file=sys.stderr)

    reset_state()
    elapsed = time.time() - started
    print(f"\ntotal {elapsed:.0f}s\n", file=sys.stderr)

    # Print per-grade table
    for grade in grades:
        print(f"\n=== {grade} per-version × per-year (profit ¥) ===")
        print(f"{'version':<10} | {'2022':>10} | {'2023':>10} | {'2024':>10} | {'2025':>10} | {'2026':>10} | {'TOTAL':>10}")
        for v in versions:
            row = []
            tot = 0
            for y in years:
                d = matrix[v].get(f"{y}_{grade}", {"stake": 0, "payout": 0})
                p = d["payout"] - d["stake"]
                tot += p
                row.append(f"¥{p:>+8,}")
            row.append(f"¥{tot:>+8,}")
            print(f"{v:<10} | {' | '.join(row)}")

    # n_BET / hit_rate / ROI grade summary 4-year
    print(f"\n=== 4-year aggregate (2022-2025) per-grade per-version ===")
    print(f"{'version':<10} {'grade':<3} | {'n_BET':>5} {'stake':>9} {'payout':>9} {'profit':>10} {'ROI':>7} {'hit':>9}")
    for v in versions:
        for grade in grades:
            n = stk = pyt = h = 0
            for y in ("2022", "2023", "2024", "2025"):
                d = matrix[v].get(f"{y}_{grade}", {"n": 0, "stake": 0, "payout": 0, "hits": 0})
                n += d["n"]
                stk += d["stake"]
                pyt += d["payout"]
                h += d["hits"]
            roi = (pyt / stk * 100) if stk else 0
            hr = (h / n * 100) if n else 0
            print(f"{v:<10} {grade:<3} | {n:>5} ¥{stk:>7,} ¥{pyt:>7,} ¥{pyt-stk:>+8,} {roi:>6.1f}% {h}/{n} ({hr:>2.0f}%)")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({k: {kk: vv for kk, vv in vs.items()} for k, vs in matrix.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
