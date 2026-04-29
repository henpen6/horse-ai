#!/usr/bin/env python3
"""v8_multidim_phase3.py — test SKIP rule + Kelly mult variants on dumped features.

Reads `apps/horse-ai/data/kelly_redux/multidim_sweep.json` (Phase 1 dump)
and applies SIMULATED variants WITHOUT re-running engine. This is a fast
sweep over candidate rules — final candidates need closed-loop validation.

Variants tested (each independent of others):

  V0:  baseline (v8.4.1 actual)
  V1:  +SKIP axis_pop=2 AND edge_ratio in [0.85, 0.87]      (cell -¥21k)
  V2:  +SKIP DSLR 91-180 AND race_level=Lv2                 (cell -¥21k)
  V3:  +SKIP race_level=Lv3 entirely                        (cell -¥10k)
  V4:  +cap kelly_mult ≤ 1.0 when axis_pop=2                (no amp)
  V5:  +cap kelly_mult ≤ 1.0 when DSLR > 90 AND Lv2         (slow amp)
  V6:  +amplify kelly_mult ×1.2 when DSLR 64-90 (magic zone)
  V7:  V1+V2+V3 combined
  V8:  V4+V5 combined (cap-based)
  V9:  V1+V4+V6 combined
  V10: ALL V1-V6 combined (aggressive)

Output:
  per-variant 4-year profit / ROI / hit_rate
  plus 5-fold chronological CV
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys

REPO = pathlib.Path("/Users/masa/Dev/ai-fortress")
DUMP_PATH = pathlib.Path("/Users/masa/Dev/horse-ai/apps/horse-ai/data/kelly_redux/multidim_sweep.json")


def load_rows() -> list[dict]:
    return json.loads(DUMP_PATH.read_text(encoding="utf-8"))


def apply_variant(row: dict, variant_id: str) -> tuple[int, int, int]:
    """Return (stake, payout, hit) under variant rule applied to this race.

    Strategy:
    - For SKIP variants: skip → stake=0, payout=0, hit=0
    - For cap/amplify variants: rescale stake & payout by new_mult / old_mult
    - For combined variants: apply SKIP first, then mult adjustments
    """
    pop = row.get("axis_pop")
    er = row.get("axis_edge_ratio")
    dslr = row.get("axis_DSLR")
    rl = row.get("race_level")
    base_stake = row.get("stake_off") or 0
    base_payout = row.get("payout_off") or 0
    base_hit = row.get("hit_off") or 0

    on_stake = row.get("stake_on") or 0
    on_payout = row.get("payout_on") or 0
    on_hit = row.get("hit_on") or 0
    cur_mult = row.get("kelly_mult") or 1.0

    skip = False
    new_mult = cur_mult

    if variant_id == "V0":
        return on_stake, on_payout, on_hit

    if variant_id in ("V1", "V7", "V9", "V10"):
        if pop == 2 and er is not None and 0.85 <= er <= 0.87:
            skip = True

    if variant_id in ("V2", "V7", "V10"):
        if dslr is not None and 91 <= dslr <= 180 and rl == "Lv2":
            skip = True

    if variant_id in ("V3", "V7", "V10"):
        if rl == "Lv3":
            skip = True

    if variant_id in ("V4", "V8", "V9", "V10"):
        if pop == 2 and cur_mult > 1.0:
            new_mult = 1.0

    if variant_id in ("V5", "V8", "V10"):
        if dslr is not None and dslr > 90 and rl == "Lv2" and cur_mult > 1.0:
            new_mult = 1.0

    if variant_id in ("V6", "V9", "V10"):
        if dslr is not None and 64 <= dslr <= 90:
            new_mult = min(2.0, cur_mult * 1.2)

    if skip:
        return 0, 0, 0

    if abs(new_mult - cur_mult) < 1e-6:
        return on_stake, on_payout, on_hit

    # Rescale stake/payout proportionally to new_mult / cur_mult
    if cur_mult <= 0:
        return on_stake, on_payout, on_hit
    scale = new_mult / cur_mult
    new_stake = int(round(on_stake * scale / 100.0)) * 100
    new_payout = int(round(on_payout * scale / 100.0)) * 100
    return max(100, new_stake) if on_stake > 0 else 0, max(0, new_payout), on_hit


def aggregate(rows: list[dict], variant_id: str) -> dict:
    s = p = 0
    n = h = bet_n = 0
    for r in rows:
        st, py, ht = apply_variant(r, variant_id)
        s += st
        p += py
        h += ht
        n += 1
        if st > 0:
            bet_n += 1
    profit = p - s
    roi = (p / s * 100) if s else 0
    hit_rate = (h / bet_n * 100) if bet_n else 0
    return {"n": n, "bet_n": bet_n, "stake": s, "payout": p, "profit": profit, "roi_pct": roi, "hits": h, "hit_rate": hit_rate}


def cv_5fold(rows: list[dict], variant_id: str) -> dict:
    rows_sorted = sorted(rows, key=lambda r: r["date"])
    n = len(rows_sorted)
    fold_size = n // 5
    deltas = []
    folds = []
    for i in range(5):
        start = i * fold_size
        end = (i + 1) * fold_size if i < 4 else n
        fold = rows_sorted[start:end]
        # baseline (V0) profit
        s_off = sum(r["stake_off"] or 0 for r in fold)
        p_off = sum(r["payout_off"] or 0 for r in fold)
        # variant profit
        s_v = p_v = 0
        for r in fold:
            st, py, _ = apply_variant(r, variant_id)
            s_v += st
            p_v += py
        delta = (p_v - s_v) - (p_off - s_off)
        deltas.append(delta)
        folds.append({"date_start": fold[0]["date"], "date_end": fold[-1]["date"], "n": len(fold), "delta": delta})
    return {
        "deltas": deltas,
        "folds": folds,
        "mean": statistics.mean(deltas),
        "std": statistics.stdev(deltas) if len(deltas) >= 2 else 0,
        "positive_folds": sum(1 for d in deltas if d > 0),
    }


def main() -> int:
    rows = load_rows()
    print(f"loaded {len(rows)} rows from {DUMP_PATH.name}\n")

    variants = ["V0","V1","V2","V3","V4","V5","V6","V7","V8","V9","V10"]
    descs = {
        "V0": "v8.4.1 baseline",
        "V1": "+SKIP pop2 × edge0.85-0.87",
        "V2": "+SKIP DSLR91-180 × Lv2",
        "V3": "+SKIP Lv3 entirely",
        "V4": "+cap kelly≤1.0 when pop=2",
        "V5": "+cap kelly≤1.0 when DSLR>90+Lv2",
        "V6": "+amp kelly×1.2 in DSLR64-90 magic",
        "V7": "V1+V2+V3 (skip combo)",
        "V8": "V4+V5 (cap combo)",
        "V9": "V1+V4+V6 (mixed best)",
        "V10": "ALL combined (aggressive)",
    }

    print(f"{'V':>3} {'desc':<40} {'BET':>4} {'stake':>9} {'payout':>9} {'profit':>10} {'ROI':>7} {'hit_rate':>8} | {'CV mean':>8} {'CV std':>8} {'pos/5':>6}")
    print("-" * 140)
    summary = {}
    for v in variants:
        agg = aggregate(rows, v)
        cv = cv_5fold(rows, v)
        summary[v] = {"agg": agg, "cv": cv}
        print(f"{v:>3} {descs[v]:<40} {agg['bet_n']:>4} ¥{agg['stake']:>7,} ¥{agg['payout']:>7,} ¥{agg['profit']:>+8,} {agg['roi_pct']:>6.1f}% {agg['hits']}/{agg['bet_n']} ({agg['hit_rate']:>2.0f}%) | ¥{cv['mean']:>+6,.0f} ¥{cv['std']:>6,.0f} {cv['positive_folds']}/5")

    # Per-year breakdown for the top variants
    print("\n=== per-year profit by variant ===")
    print(f"{'V':>3} {'2022':>9} {'2023':>9} {'2024':>9} {'2025':>9} {'TOTAL':>9}")
    for v in variants:
        per_year = {y: 0 for y in ["2022", "2023", "2024", "2025"]}
        for r in rows:
            y = r.get("year")
            if y not in per_year: continue
            st, py, _ = apply_variant(r, v)
            per_year[y] += py - st
        tot = sum(per_year.values())
        print(f"{v:>3} ¥{per_year['2022']:>+7,} ¥{per_year['2023']:>+7,} ¥{per_year['2024']:>+7,} ¥{per_year['2025']:>+7,} ¥{tot:>+7,}")

    out_path = pathlib.Path("/Users/masa/Dev/horse-ai/apps/horse-ai/data/kelly_redux/multidim_phase3.json")
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
