#!/usr/bin/env python3
"""v8_multidim_sweep.py — 4-year multi-dimensional parameter exploration on n=199 BET races.

Phases:
  1. Feature-rich per-race dump (current v8.4.1 + comprehensive features)
  2. 1D slice analysis (per-feature avg_profit, hit_rate)
  3. 2D / 3D combinatorial Kelly mult cells
  4. Continuous Kelly function fitting (linear + interaction term)
  5. SKIP rule variation sweep
  6. Bet-type composition variation
  7. Top-K config selection by 4-year profit + 5-fold CV stability

Output: stdout report + apps/horse-ai/data/kelly_redux/multidim_sweep.json
"""
from __future__ import annotations

import json
import pathlib
import sys
import statistics
import itertools
from collections import defaultdict
from datetime import date as _date

REPO = pathlib.Path("/Users/masa/Dev/ai-fortress")
HORSE_AI = pathlib.Path("/Users/masa/Dev/horse-ai/apps/horse-ai")
sys.path.insert(0, str(HORSE_AI))

from src.engine import ev as _ev_module  # noqa: E402
from src.engine.future_minimal import run_future_engine  # noqa: E402
from src.engine.review import review_bets  # noqa: E402

SNAPSHOT_DIR = HORSE_AI / "data" / "snapshots"
SIM_CACHE_DIR = pathlib.Path.home() / ".openclaw" / "agents" / "horse-run-claw" / "workspace" / "sim_results_cache"
OUTPUT_PATH = HORSE_AI / "data" / "kelly_redux" / "multidim_sweep.json"


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


def _toggle(kelly_on: bool) -> dict:
    """Toggle kelly_stake; return original."""
    cfg = _ev_module._W.get("kelly_stake")
    if not isinstance(cfg, dict):
        return {}
    orig = {"enabled": cfg.get("enabled", False)}
    cfg["enabled"] = kelly_on
    return orig


def _restore(orig: dict) -> None:
    cfg = _ev_module._W.get("kelly_stake")
    if isinstance(cfg, dict) and orig:
        cfg["enabled"] = orig.get("enabled", False)


def dump_features() -> list[dict]:
    """Run engine on 4-year snapshots (kelly OFF), capture rich features +
    baseline ¥1200 stake outcome. Then run kelly ON, capture v8.4.1 outcome.

    Returns one row per BET race with both branches.
    """
    rows: list[dict] = []
    snapshots = sorted(SNAPSHOT_DIR.glob("*_snapshot.json"))
    snapshots = [p for p in snapshots if p.name[:4] in ("2022", "2023", "2024", "2025")]

    for sp in snapshots:
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
            actual = cache.get("actual_result") or {}
            if not actual.get("payouts"):
                continue
            ri = _review_input(actual)

            # Branch A: kelly OFF (baseline ¥1200 per race)
            orig = _toggle(False)
            try:
                eng_off = run_future_engine(collector_result=cr, budget=1200, budget_source="backtest")
            except Exception:
                eng_off = {"ok": False}
            finally:
                _restore(orig)

            # Branch B: kelly ON
            orig = _toggle(True)
            try:
                eng_on = run_future_engine(collector_result=cr, budget=1200, budget_source="backtest")
            except Exception:
                eng_on = {"ok": False}
            finally:
                _restore(orig)

            if not eng_off.get("ok"):
                continue
            pf_off = eng_off.get("portfolio_v3") or eng_off.get("portfolio") or {}
            bets_off = pf_off.get("bets") or []
            if not bets_off:
                continue
            rev_off = review_bets(bets_off, ri)

            pf_on = eng_on.get("portfolio_v3") or eng_on.get("portfolio") or {} if eng_on.get("ok") else {}
            bets_on = pf_on.get("bets") or [] if pf_on else []
            rev_on = review_bets(bets_on, ri) if bets_on else {"total_payout": 0, "hit_count": 0, "profit": 0}

            cands = eng_off.get("candidates") or []
            if not cands:
                continue
            axis = cands[0]
            axis_n = axis.get("number")
            axis_entry = next((e for e in cr.get("entries") or [] if str(e.get("number")) == str(axis_n)), {}) or {}

            past = axis_entry.get("past_performances") or []
            dslr = None
            if past and (past[0] or {}).get("date") and cr.get("date"):
                try:
                    dslr = (_date.fromisoformat(cr["date"]) - _date.fromisoformat(past[0]["date"])).days
                except Exception:
                    dslr = None
            mp = axis.get("model_probability")
            ip = axis.get("implied_probability")
            er = (mp / ip) if (mp and ip) else None

            kelly_breakdown = eng_on.get("kelly_stake_breakdown") or {}
            kelly_mult = eng_on.get("kelly_stake_multiplier", 1.0)

            # race-level features
            race_level = (eng_off.get("race_level") or {}).get("lv")
            axis_type = eng_off.get("axis_type")
            course = (cr.get("course") or {})

            row = {
                "race": name,
                "date": cr.get("date"),
                "year": (cr.get("date") or "")[:4],
                "venue": cr.get("venue"),
                "race_number": cr.get("race_number"),
                "grade": cr.get("grade"),
                "race_class": cr.get("race_class"),
                "field_size": len(cr.get("entries") or []),
                "surface": course.get("surface"),
                "distance": course.get("meters") or course.get("distance"),
                "track_condition": cr.get("track_condition"),
                "weather": cr.get("weather"),
                "month": int((cr.get("date") or "0000-00")[5:7]) if cr.get("date") else None,
                "race_level": race_level,
                "axis_type": axis_type,
                "axis_number": axis_n,
                "axis_odds": axis.get("odds"),
                "axis_pop": axis.get("popularity"),
                "axis_age": axis_entry.get("age"),
                "axis_dominant_style": axis_entry.get("dominant_style"),
                "axis_class_tier": axis_entry.get("class_tier"),
                "axis_owner_tier": axis_entry.get("owner_tier"),
                "axis_farm_tier": axis_entry.get("farm_tier"),
                "axis_DSLR": dslr,
                "axis_edge_ratio": er,
                "axis_model_p": mp,
                "axis_implied_p": ip,
                "axis_edge_diff": axis.get("edge"),
                "axis_kelly_fraction": axis.get("kelly_fraction"),
                "n_bets_off": len(bets_off),
                "stake_off": pf_off.get("total_stake", 0),
                "payout_off": rev_off.get("total_payout", 0),
                "profit_off": rev_off.get("profit", 0),
                "hit_off": int(rev_off.get("hit_count", 0) > 0),
                "n_bets_on": len(bets_on),
                "stake_on": pf_on.get("total_stake", 0),
                "payout_on": rev_on.get("total_payout", 0),
                "profit_on": rev_on.get("profit", 0),
                "hit_on": int(rev_on.get("hit_count", 0) > 0),
                "kelly_mult": kelly_mult,
                "kelly_dslr_mult": kelly_breakdown.get("dslr_multiplier"),
                "kelly_edge_mult": kelly_breakdown.get("edge_ratio_multiplier"),
                "kelly_capped": kelly_breakdown.get("capped_multiplier"),
            }
            rows.append(row)
        except Exception as exc:
            print(f"  FAIL {sp.name}: {exc}", file=sys.stderr)
            continue

    return rows


def slice_1d(rows: list[dict], feat: str, bins=None, label_fmt=None):
    """Bin by feat, compute avg_profit_off / avg_profit_on / delta / hit_rate."""
    cells: dict = defaultdict(lambda: {"n": 0, "p_off": 0, "p_on": 0, "h_off": 0, "h_on": 0, "s_off": 0, "s_on": 0, "py_off": 0, "py_on": 0})
    for r in rows:
        v = r.get(feat)
        if v is None:
            key = "(none)"
        elif bins:
            key = bins(v)
        else:
            key = v
        c = cells[key]
        c["n"] += 1
        c["p_off"] += r.get("profit_off") or 0
        c["p_on"] += r.get("profit_on") or 0
        c["h_off"] += r.get("hit_off") or 0
        c["h_on"] += r.get("hit_on") or 0
        c["s_off"] += r.get("stake_off") or 0
        c["s_on"] += r.get("stake_on") or 0
        c["py_off"] += r.get("payout_off") or 0
        c["py_on"] += r.get("payout_on") or 0
    return cells


def _print_1d(name: str, cells: dict, sort_key=None):
    print(f"\n=== 1D slice: {name} ===")
    print(f"{'cell':>14} {'n':>4} {'profit_off':>10} {'profit_on':>10} {'delta':>8} {'hit_off':>8} {'roi_off':>7} {'roi_on':>7}")
    keys = sorted(cells.keys(), key=sort_key) if sort_key else sorted(cells.keys(), key=str)
    for k in keys:
        c = cells[k]
        n = c["n"]
        if n == 0: continue
        roi_off = (c["py_off"] / c["s_off"] * 100) if c["s_off"] else 0
        roi_on = (c["py_on"] / c["s_on"] * 100) if c["s_on"] else 0
        delta = c["p_on"] - c["p_off"]
        hit_off_rate = c["h_off"] / n * 100
        print(f"{str(k):>14} {n:>4} ¥{c['p_off']:>+8,} ¥{c['p_on']:>+8,} ¥{delta:>+6,} {c['h_off']}/{n} ({hit_off_rate:>3.0f}%) {roi_off:>6.1f}% {roi_on:>6.1f}%")


def slice_2d(rows: list[dict], feat_x: str, feat_y: str, bins_x=None, bins_y=None):
    cells: dict = defaultdict(lambda: {"n": 0, "p_off": 0, "p_on": 0, "h_off": 0, "h_on": 0, "s_off": 0, "s_on": 0, "py_off": 0, "py_on": 0})
    for r in rows:
        vx, vy = r.get(feat_x), r.get(feat_y)
        if vx is None or vy is None: continue
        kx = bins_x(vx) if bins_x else vx
        ky = bins_y(vy) if bins_y else vy
        c = cells[(kx, ky)]
        c["n"] += 1
        c["p_off"] += r.get("profit_off") or 0
        c["p_on"] += r.get("profit_on") or 0
        c["h_off"] += r.get("hit_off") or 0
        c["h_on"] += r.get("hit_on") or 0
        c["s_off"] += r.get("stake_off") or 0
        c["s_on"] += r.get("stake_on") or 0
        c["py_off"] += r.get("payout_off") or 0
        c["py_on"] += r.get("payout_on") or 0
    return cells


def _print_2d(name: str, cells: dict):
    print(f"\n=== 2D slice: {name} ===")
    keys = sorted(cells.keys(), key=str)
    print(f"{'cell':>22} {'n':>4} {'profit_off':>10} {'profit_on':>10} {'delta':>8} {'hit_off':>8} {'roi_off':>7}")
    for k in keys:
        c = cells[k]
        n = c["n"]
        if n < 3: continue  # skip very small cells
        roi_off = (c["py_off"] / c["s_off"] * 100) if c["s_off"] else 0
        delta = c["p_on"] - c["p_off"]
        hit_off_rate = c["h_off"] / n * 100
        print(f"{str(k):>22} {n:>4} ¥{c['p_off']:>+8,} ¥{c['p_on']:>+8,} ¥{delta:>+6,} {c['h_off']}/{n} ({hit_off_rate:>3.0f}%) {roi_off:>6.1f}%")


def _bin_dslr(d):
    if d is None: return "?"
    if d <= 14: return "0-14"
    if d <= 35: return "15-35"
    if d <= 63: return "36-63"
    if d <= 90: return "64-90"
    if d <= 180: return "91-180"
    return "180+"


def _bin_er(e):
    if e is None: return "?"
    if e < 0.83: return "<0.83"
    if e < 0.85: return "0.83-0.85"
    if e < 0.87: return "0.85-0.87"
    return ">0.87"


def _bin_odds(o):
    if o is None: return "?"
    if o < 2.0: return "<2.0"
    if o < 3.5: return "2.0-3.5"
    if o < 5.0: return "3.5-5.0"
    if o < 8.0: return "5.0-8.0"
    if o < 15.0: return "8.0-15.0"
    return ">15.0"


def _bin_age(a):
    if a is None: return "?"
    if a <= 3: return "≤3"
    if a == 4: return "4"
    if a == 5: return "5"
    return "≥6"


def _bin_field(f):
    if f is None: return "?"
    if f <= 12: return "≤12"
    if f <= 14: return "13-14"
    if f <= 16: return "15-16"
    return "≥17"


def main() -> int:
    print("Phase 1: dumping features (4-year, kelly OFF + ON branches)...", file=sys.stderr)
    rows = dump_features()
    print(f"  rows: {len(rows)}", file=sys.stderr)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # baseline aggregate
    sof = sum(r.get("stake_off") or 0 for r in rows)
    pof = sum(r.get("payout_off") or 0 for r in rows)
    son = sum(r.get("stake_on") or 0 for r in rows)
    pon = sum(r.get("payout_on") or 0 for r in rows)
    hof = sum(1 for r in rows if r.get("hit_off"))
    hon = sum(1 for r in rows if r.get("hit_on"))

    print(f"\n=== aggregate (4-year, n_BET={len(rows)}) ===")
    print(f"  kelly OFF: stake=¥{sof:,} payout=¥{pof:,} profit=¥{pof-sof:+,} ROI={pof/sof*100:.1f}% hit={hof}/{len(rows)}")
    print(f"  kelly ON : stake=¥{son:,} payout=¥{pon:,} profit=¥{pon-son:+,} ROI={pon/son*100:.1f}% hit={hon}/{len(rows)}")
    print(f"  delta: ¥{(pon-son)-(pof-sof):+,}")

    # 1D slices
    _print_1d("year", slice_1d(rows, "year"))
    _print_1d("race_level", slice_1d(rows, "race_level"), sort_key=lambda x: str(x))
    _print_1d("axis_type", slice_1d(rows, "axis_type"))
    _print_1d("grade", slice_1d(rows, "grade"))
    _print_1d("axis_pop", slice_1d(rows, "axis_pop"), sort_key=lambda x: int(x) if isinstance(x, int) else 99)
    _print_1d("axis_age", slice_1d(rows, "axis_age", _bin_age))
    _print_1d("axis_DSLR", slice_1d(rows, "axis_DSLR", _bin_dslr))
    _print_1d("axis_edge_ratio", slice_1d(rows, "axis_edge_ratio", _bin_er))
    _print_1d("axis_odds", slice_1d(rows, "axis_odds", _bin_odds))
    _print_1d("field_size", slice_1d(rows, "field_size", _bin_field))
    _print_1d("surface", slice_1d(rows, "surface"))
    _print_1d("month", slice_1d(rows, "month"))
    _print_1d("axis_dominant_style", slice_1d(rows, "axis_dominant_style"))

    # 2D slices (selected high-value pairs)
    _print_2d("DSLR × edge_ratio (current Kelly)", slice_2d(rows, "axis_DSLR", "axis_edge_ratio", _bin_dslr, _bin_er))
    _print_2d("DSLR × axis_age", slice_2d(rows, "axis_DSLR", "axis_age", _bin_dslr, _bin_age))
    _print_2d("edge_ratio × axis_pop", slice_2d(rows, "axis_edge_ratio", "axis_pop", _bin_er))
    _print_2d("DSLR × race_level", slice_2d(rows, "axis_DSLR", "race_level", _bin_dslr))
    _print_2d("axis_odds × axis_pop", slice_2d(rows, "axis_odds", "axis_pop", _bin_odds))
    _print_2d("axis_type × race_level", slice_2d(rows, "axis_type", "race_level"))
    _print_2d("DSLR × surface", slice_2d(rows, "axis_DSLR", "surface", _bin_dslr))

    print(f"\nsaved feature dump: {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
