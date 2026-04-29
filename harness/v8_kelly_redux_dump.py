#!/usr/bin/env python3
"""v8_kelly_redux_dump.py — fresh-engine per-race feature/result dump for Kelly redux.

Phase 1 of v8.4.1 closed-loop Kelly redux. Runs the v8.4.0 engine
(kelly_stake disabled per current weights.json) on each snapshot in
apps/horse-ai/data/snapshots/ for years 2023-2025 and dumps:

  - axis horse number, model_p, implied_p, edge_ratio (fresh engine)
  - axis DSLR (race date - past_performances[0].date in days)
  - portfolio bets at baseline budget=¥1200
  - review_bets profit/payout/hits against actual_result.payouts

Output: apps/horse-ai/data/kelly_redux/n_fresh_v840.jsonl

LLM pre-review is NOT invoked. Cache is only used for actual_result. The
engine itself runs fresh on the snapshot's collector_result.

Usage:
  python3 bin/shared/v8_kelly_redux_dump.py [--limit N] [--year YEAR] [--verbose]
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
OUTPUT_PATH = OUTPUT_DIR / "n_fresh_v840.jsonl"


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


def _compute_axis_dslr(axis_number, entries: list, race_date: str) -> int | None:
    if axis_number is None or not race_date:
        return None
    for entry in entries:
        if str(entry.get("number")) != str(axis_number):
            continue
        past = entry.get("past_performances") or []
        if not past:
            return None
        pp_date = (past[0] or {}).get("date")
        if not pp_date:
            return None
        try:
            return (_date.fromisoformat(race_date) - _date.fromisoformat(pp_date)).days
        except (TypeError, ValueError):
            return None
    return None


def _safe_div(a, b):
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return None
    return a / b if b else None


def _process_one(snapshot_path: pathlib.Path, verbose: bool = False) -> dict | None:
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

    # Fresh engine run with current v8.4.0 weights (kelly_stake disabled).
    try:
        eng = run_future_engine(collector_result=cr, budget=1200, budget_source="backtest")
    except Exception as exc:
        if verbose:
            print(f"  ENGINE ERR {name}: {exc}", file=sys.stderr)
        return None
    if not eng.get("ok"):
        if verbose:
            print(f"  engine not ok {name}: skip={eng.get('skip_reason') or eng.get('hard_stop_reason')}", file=sys.stderr)
        return None

    pf = eng.get("portfolio_v3") or eng.get("portfolio") or {}
    bets = pf.get("bets") or []
    if not bets:
        return None  # no portfolio = nothing to evaluate

    candidates = eng.get("candidates") or []
    if not candidates:
        return None
    axis = candidates[0]
    axis_number = axis.get("number")
    model_p = axis.get("model_probability")
    implied_p = axis.get("implied_probability")
    edge_ratio = _safe_div(model_p, implied_p)

    axis_dslr = _compute_axis_dslr(axis_number, cr.get("entries") or [], cr.get("date"))

    rev = review_bets(bets, review_input)
    stake = pf.get("total_stake", sum(b.get("stake_yen", 0) for b in bets))
    payout = rev.get("total_payout", 0)
    profit = rev.get("profit", payout - stake)
    hits = rev.get("hit_count", 0)

    return {
        "race": name,
        "date": cr.get("date"),
        "venue": cr.get("venue"),
        "race_number": cr.get("race_number"),
        "axis_number": axis_number,
        "axis_model_p": model_p,
        "axis_implied_p": implied_p,
        "axis_edge_ratio": edge_ratio,
        "axis_dslr_days": axis_dslr,
        "n_bets": len(bets),
        "stake_yen": stake,
        "payout_yen": payout,
        "profit_yen": profit,
        "hits": hits,
        "winner": (actual_result.get("finishing_order") or [{}])[0].get("number") if actual_result.get("finishing_order") else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--year", type=str, default=None, help="filter by year prefix, e.g. 2024")
    parser.add_argument("--filter", default=None, help="substring filter")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    snapshots = sorted(SNAPSHOT_DIR.glob("*_snapshot.json"))
    # Restrict to 2023-2025 by default
    snapshots = [p for p in snapshots if p.name[:4] in ("2023", "2024", "2025")]
    if args.year:
        snapshots = [p for p in snapshots if p.name.startswith(args.year)]
    if args.filter:
        snapshots = [p for p in snapshots if args.filter in p.name]
    if args.limit:
        snapshots = snapshots[: args.limit]

    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    skipped = 0
    started = time.time()
    with out_path.open("w", encoding="utf-8") as fh:
        for i, sp in enumerate(snapshots, 1):
            try:
                row = _process_one(sp, verbose=args.verbose)
            except Exception as exc:
                if args.verbose:
                    print(f"FAIL {sp.name}: {exc}", file=sys.stderr)
                skipped += 1
                continue
            if not row:
                skipped += 1
                continue
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if args.verbose or i % 25 == 0:
                el = time.time() - started
                er = row['axis_edge_ratio']
                er_s = f"{er:.3f}" if er is not None else "nan"
                print(
                    f"[{i}/{len(snapshots)}] {sp.name}: dslr={row['axis_dslr_days']} "
                    f"edge_ratio={er_s} profit=¥{row['profit_yen']:+,} ({el:.0f}s)",
                    file=sys.stderr,
                )

    elapsed = time.time() - started
    n = len(rows)
    print(f"\n=== Phase 1 dump complete ===", file=sys.stderr)
    print(f"  output: {out_path}", file=sys.stderr)
    print(f"  rows:    {n} (skipped {skipped})", file=sys.stderr)
    print(f"  elapsed: {elapsed:.0f}s", file=sys.stderr)
    if n:
        agg_stake = sum(r["stake_yen"] for r in rows)
        agg_payout = sum(r["payout_yen"] for r in rows)
        agg_profit = agg_payout - agg_stake
        agg_hits = sum(1 for r in rows if r["hits"] > 0)
        print(
            f"  baseline (v8.4.0 kelly OFF, ¥1200/race): "
            f"stake=¥{agg_stake:,} payout=¥{agg_payout:,} profit=¥{agg_profit:+,} "
            f"hit={agg_hits}/{n} ({agg_hits / n * 100:.1f}%) ROI={agg_payout / agg_stake * 100:.1f}%",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
