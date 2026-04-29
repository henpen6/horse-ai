#!/usr/bin/env python3
"""v8_kelly_redux_real_run.py — closed-loop A/B with kelly_stake ON vs OFF.

Phase 3.5 of v8.4.1 redux. For each snapshot in 2023-2025:
  - Run engine A: kelly_stake disabled (current production state)
  - Run engine B: kelly_stake enabled with Phase O bands
Captures full portfolio + review for both branches so we can detect
portfolio-composition shifts caused by budget changes.

In-memory mutation of _ev_module._W; weights.json on disk untouched.

Output: apps/horse-ai/data/kelly_redux/n_real_ab_v840.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from datetime import date as _date

REPO = pathlib.Path("/Users/masa/Dev/ai-fortress")
HORSE_AI = pathlib.Path("/Users/masa/Dev/horse-ai/apps/horse-ai")
sys.path.insert(0, str(HORSE_AI))

from src.engine import ev as _ev_module  # noqa: E402
from src.engine.future_minimal import run_future_engine  # noqa: E402
from src.engine.review import review_bets  # noqa: E402

SNAPSHOT_DIR = HORSE_AI / "data" / "snapshots"
SIM_CACHE_DIR = pathlib.Path.home() / ".openclaw" / "agents" / "horse-run-claw" / "workspace" / "sim_results_cache"
OUTPUT_DIR = HORSE_AI / "data" / "kelly_redux"
OUTPUT_PATH = OUTPUT_DIR / "n_real_ab_v840.jsonl"


def _build_collector_result(snapshot: dict) -> dict | None:
    cr = snapshot.get("collector_result") or {}
    if not cr:
        return None
    if not cr.get("entries"):
        cr["entries"] = snapshot.get("entries") or []
    if not cr.get("odds"):
        cr["odds"] = snapshot.get("odds") or {}
    return cr


def _build_review_input(actual_result: dict) -> dict:
    return {
        "finish_order": actual_result.get("finishing_order") or actual_result.get("finish_order") or [],
        "payouts": actual_result.get("payouts") or {},
    }


def _set_kelly_state(enabled: bool) -> dict:
    """Toggle kelly_stake.enabled in in-memory _W. Phase O bands already
    in weights.json (just disabled). Return original config for restore."""
    cfg = _ev_module._W.get("kelly_stake")
    if not isinstance(cfg, dict):
        return {}
    original = {"enabled": cfg.get("enabled", False)}
    cfg["enabled"] = enabled
    return original


def _restore_kelly(original: dict) -> None:
    cfg = _ev_module._W.get("kelly_stake")
    if isinstance(cfg, dict) and original:
        cfg["enabled"] = original.get("enabled", False)


def _run_one_branch(cr: dict, kelly_enabled: bool, review_input: dict) -> dict | None:
    original = _set_kelly_state(kelly_enabled)
    try:
        eng = run_future_engine(collector_result=cr, budget=1200, budget_source="backtest")
    except Exception:
        eng = {"ok": False}
    finally:
        _restore_kelly(original)

    if not eng.get("ok"):
        return None

    pf = eng.get("portfolio_v3") or eng.get("portfolio") or {}
    bets = pf.get("bets") or []
    if not bets:
        return None

    rev = review_bets(bets, review_input)
    stake = pf.get("total_stake", sum(b.get("stake_yen", 0) for b in bets))
    payout = rev.get("total_payout", 0)
    profit = rev.get("profit", payout - stake)
    hits = rev.get("hit_count", 0)

    candidates = eng.get("candidates") or []
    axis = candidates[0] if candidates else {}

    return {
        "stake": stake,
        "payout": payout,
        "profit": profit,
        "hits": hits,
        "n_bets": len(bets),
        "axis_number": axis.get("number"),
        "axis_model_p": axis.get("model_probability"),
        "axis_implied_p": axis.get("implied_probability"),
        "kelly_mult": eng.get("kelly_stake_multiplier"),
        "kelly_breakdown": eng.get("kelly_stake_breakdown"),
    }


def _process_one(snapshot_path: pathlib.Path) -> dict | None:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    cr = _build_collector_result(snapshot)
    if not cr:
        return None

    name = snapshot_path.stem.replace("_snapshot", "")
    cache_path = SIM_CACHE_DIR / f"{name}.json"
    if not cache_path.exists():
        return None
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    actual_result = cache.get("actual_result") or {}
    if not actual_result.get("payouts"):
        return None
    review_input = _build_review_input(actual_result)

    a = _run_one_branch(cr, kelly_enabled=False, review_input=review_input)
    if a is None:
        return None
    b = _run_one_branch(cr, kelly_enabled=True, review_input=review_input)
    if b is None:
        return None

    return {
        "race": name,
        "date": cr.get("date"),
        "off": a,
        "on": b,
        "delta_profit": b["profit"] - a["profit"],
        "delta_stake": b["stake"] - a["stake"],
        "delta_n_bets": b["n_bets"] - a["n_bets"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--year", type=str, default=None)
    parser.add_argument("--filter", default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    snapshots = sorted(SNAPSHOT_DIR.glob("*_snapshot.json"))
    snapshots = [p for p in snapshots if p.name[:4] in ("2023", "2024", "2025")]
    if args.year:
        snapshots = [p for p in snapshots if p.name.startswith(args.year)]
    if args.filter:
        snapshots = [p for p in snapshots if args.filter in p.name]
    if args.limit:
        snapshots = snapshots[: args.limit]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    started = time.time()
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        for i, sp in enumerate(snapshots, 1):
            try:
                row = _process_one(sp)
            except Exception as exc:
                if args.verbose:
                    print(f"FAIL {sp.name}: {exc}", file=sys.stderr)
                continue
            if not row:
                continue
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if args.verbose or i % 50 == 0:
                el = time.time() - started
                print(f"[{i}/{len(snapshots)}] {sp.name}: off=¥{row['off']['profit']:+,} on=¥{row['on']['profit']:+,} ({el:.0f}s)", file=sys.stderr)

    n = len(rows)
    if not n:
        print("no rows", file=sys.stderr)
        return 1
    off_profit = sum(r["off"]["profit"] for r in rows)
    on_profit = sum(r["on"]["profit"] for r in rows)
    off_stake = sum(r["off"]["stake"] for r in rows)
    on_stake = sum(r["on"]["stake"] for r in rows)
    off_payout = sum(r["off"]["payout"] for r in rows)
    on_payout = sum(r["on"]["payout"] for r in rows)
    off_hits = sum(1 for r in rows if r["off"]["hits"] > 0)
    on_hits = sum(1 for r in rows if r["on"]["hits"] > 0)

    portfolio_changed = sum(1 for r in rows if r["off"]["n_bets"] != r["on"]["n_bets"])
    axis_changed = sum(1 for r in rows if r["off"]["axis_number"] != r["on"]["axis_number"])

    print(f"\n=== Phase 3.5 closed-loop A/B (n={n}) ===", file=sys.stderr)
    print(f"  off (kelly disabled): stake=¥{off_stake:,} payout=¥{off_payout:,} profit=¥{off_profit:+,} hit={off_hits}/{n}", file=sys.stderr)
    print(f"  on  (kelly enabled):  stake=¥{on_stake:,} payout=¥{on_payout:,} profit=¥{on_profit:+,} hit={on_hits}/{n}", file=sys.stderr)
    print(f"  delta: profit={on_profit - off_profit:+,} stake={on_stake - off_stake:+,} hits={on_hits - off_hits:+}", file=sys.stderr)
    print(f"  portfolio bet-count changed: {portfolio_changed}/{n}", file=sys.stderr)
    print(f"  axis pick changed:           {axis_changed}/{n}", file=sys.stderr)

    # Per-year
    for yr in ("2023", "2024", "2025"):
        sub = [r for r in rows if r["date"].startswith(yr)]
        if not sub: continue
        yof = sum(r["off"]["profit"] for r in sub)
        yon = sum(r["on"]["profit"] for r in sub)
        print(f"  {yr}: n={len(sub)} off=¥{yof:+,} on=¥{yon:+,} delta=¥{yon-yof:+,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
