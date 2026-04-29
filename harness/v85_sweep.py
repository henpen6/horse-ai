#!/usr/bin/env python3
"""v85_sweep.py — v8.5 position + numeric multi-dim optimization sweep.

Builds on v8.4.2 baseline. Tests variants combining:
  (a) NEW SKIP rules (position-style — SKIP fires before kelly)
  (b) Cell-conditional kelly cap/boost (numeric-style)
  (c) race_level / bet_type conditional kelly (position-conditional)

All applied to existing 4-year per-race feature dump (multidim_sweep.json
n=199 BET races). SIMULATED via stake/payout linear rescale; SKIP variants
are accurate, cap/boost approximated. Top candidates then warrant closed-
loop validation.

Variants:
  V9   v8.4.2 baseline (V1+V4+V6 already shipped)
  M    +SKIP DSLR 91-180 × Lv2     (cell -¥10,840 / hit 19%)
  N    +SKIP DSLR 36-63 × Lv1      (cell  -¥9,520 / hit 50%)
  P    +SKIP pop2 × edge 0.83-0.85 (extend L to next edge band)
  R    +amp DSLR 64-90 × age≤3 ×1.3 (sharper magic zone, n=16 +¥29k)
  T    +race_level Lv1 cap kelly≤1.0 (Lv1 already Floor-Hedge, don't over-bet)
  U    +bet_type differential: TRIO ×1.0 / WIDE ×1.3 (WIDE pays partial hit)
  W    +DSLR 91-180 cap kelly≤1.0 (long-rest, low signal — don't amp)
  X    +pop=1 amp ×1.15 (best subset n=43, +¥25k baseline + edge)

Combinations:
  COMBO_A  = V9 + M + R + W           (skip-and-cap conservative)
  COMBO_B  = V9 + M + P + R           (extend SKIP coverage)
  COMBO_C  = V9 + M + R + T + W       (full conservative — many caps)
  COMBO_D  = V9 + M + R + X           (skip+amp aggressive)
  COMBO_E  = V9 + M + N + P + R + W   (max SKIP)
  COMBO_F  = V9 + R + W               (numeric-only refinement)
"""
from __future__ import annotations

import json
import pathlib
import statistics

DUMP = pathlib.Path("/Users/masa/Dev/horse-ai/apps/horse-ai/data/kelly_redux/multidim_sweep.json")
OUT = pathlib.Path("/Users/masa/Dev/horse-ai/apps/horse-ai/data/kelly_redux/v85_sweep.json")


def apply(row: dict, mods: list[str]) -> tuple[int, int, int]:
    """Apply variant mods to a row. Each mod is a code string from variant
    table. Returns (stake, payout, hit_yn).

    SKIP mods: any matching → stake=0, payout=0
    Cap/Amp mods: rescale stake/payout proportionally
    Combinations: SKIP wins; cap/amp composed multiplicatively
    """
    pop = row.get("axis_pop")
    er = row.get("axis_edge_ratio")
    dslr = row.get("axis_DSLR")
    rl = row.get("race_level")
    age = row.get("axis_age")

    base_stake = row.get("stake_off") or 0
    base_payout = row.get("payout_off") or 0
    on_stake = row.get("stake_on") or 0
    on_payout = row.get("payout_on") or 0
    on_hit = row.get("hit_on") or 0
    cur_mult = row.get("kelly_mult") or 1.0

    # V9 already in current dump (kelly_mult includes v8.4.1 bands; v8.4.2
    # V1/V4/V6 not yet in dump because dump pre-dates v8.4.2 ship). Apply
    # V1 (rule_L SKIP) and V4/V6 to baseline if "V9" mod active.

    skip = False
    new_mult = cur_mult

    # V9 (v8.4.2 baseline) — SKIP rule_L + V4 cap pop2 + V6 boost DSLR 64-90
    if "V9" in mods:
        if pop == 2 and er is not None and 0.85 <= er <= 0.87:
            skip = True
        if pop == 2 and cur_mult > 1.0:
            new_mult = 1.0
        if dslr is not None and 64 <= dslr <= 90:
            new_mult = min(2.0, new_mult * 1.2)

    # M: SKIP DSLR 91-180 × Lv2
    if "M" in mods:
        if dslr is not None and 91 <= dslr <= 180 and rl == "Lv2":
            skip = True

    # N: SKIP DSLR 36-63 × Lv1
    if "N" in mods:
        if dslr is not None and 36 <= dslr <= 63 and rl == "Lv1":
            skip = True

    # P: SKIP pop2 × edge 0.83-0.85
    if "P" in mods:
        if pop == 2 and er is not None and 0.83 <= er < 0.85:
            skip = True

    # R: amp DSLR 64-90 × age≤3 × 1.3 (overrides V9's general 1.2 boost)
    if "R" in mods and not skip:
        try:
            ax_age = int(age) if age is not None else None
        except (TypeError, ValueError):
            ax_age = None
        if dslr is not None and 64 <= dslr <= 90 and ax_age is not None and ax_age <= 3:
            # Compose: take base mult, apply 1.3 (replaces 1.2 from V9 if V9 active)
            if "V9" in mods:
                # remove the V9 boost first (1.2) to avoid double application
                if 64 <= dslr <= 90:
                    new_mult_raw = new_mult / 1.2
                else:
                    new_mult_raw = new_mult
                new_mult = min(2.0, new_mult_raw * 1.3)
            else:
                new_mult = min(2.0, cur_mult * 1.3)

    # T: race_level Lv1 cap kelly ≤ 1.0
    if "T" in mods and not skip:
        if rl == "Lv1" and new_mult > 1.0:
            new_mult = 1.0

    # W: DSLR 91-180 cap kelly ≤ 1.0
    if "W" in mods and not skip:
        if dslr is not None and 91 <= dslr <= 180 and new_mult > 1.0:
            new_mult = 1.0

    # X: pop=1 amp × 1.15
    if "X" in mods and not skip:
        if pop == 1:
            new_mult = min(2.0, new_mult * 1.15)

    # U: bet_type differential — too granular to simulate without bet-level data
    # Skip in this sweep; would need closed-loop with build_portfolio modification

    if skip:
        return 0, 0, 0

    if abs(new_mult - cur_mult) < 1e-6:
        return on_stake, on_payout, on_hit

    if cur_mult <= 0:
        return on_stake, on_payout, on_hit
    scale = new_mult / cur_mult
    new_stake = int(round(on_stake * scale / 100.0)) * 100
    new_payout = int(round(on_payout * scale / 100.0)) * 100
    return max(100, new_stake) if on_stake > 0 else 0, max(0, new_payout), on_hit


def aggregate(rows: list[dict], mods: list[str]) -> dict:
    s = p = h = bet_n = 0
    for r in rows:
        st, py, ht = apply(r, mods)
        s += st
        p += py
        h += ht
        if st > 0:
            bet_n += 1
    return {
        "bet_n": bet_n,
        "stake": s,
        "payout": p,
        "profit": p - s,
        "roi_pct": (p / s * 100) if s else 0,
        "hits": h,
        "hit_rate": (h / bet_n * 100) if bet_n else 0,
    }


def cv_5fold(rows: list[dict], mods: list[str]) -> dict:
    rows_sorted = sorted(rows, key=lambda r: r["date"])
    n = len(rows_sorted)
    fold_size = n // 5
    deltas = []
    for i in range(5):
        start = i * fold_size
        end = (i + 1) * fold_size if i < 4 else n
        fold = rows_sorted[start:end]
        # baseline = v8.4.1 (kelly OFF — but actually we want vs v8.4.2 V9)
        s_base = sum(r["stake_off"] or 0 for r in fold)
        p_base = sum(r["payout_off"] or 0 for r in fold)
        s_v = p_v = 0
        for r in fold:
            st, py, _ = apply(r, mods)
            s_v += st
            p_v += py
        delta = (p_v - s_v) - (p_base - s_base)
        deltas.append(delta)
    return {
        "deltas": deltas,
        "mean": statistics.mean(deltas),
        "std": statistics.stdev(deltas) if len(deltas) >= 2 else 0,
        "positive_folds": sum(1 for d in deltas if d > 0),
    }


def main():
    rows = json.loads(DUMP.read_text(encoding="utf-8"))
    print(f"loaded {len(rows)} rows\n")

    variants = {
        "v8.4.1 baseline (kelly-OFF stake)": [],
        "v8.4.1 ON (kelly-ON, no V9)": [],  # special — uses on_stake / on_payout directly
        "V9 (v8.4.2 baseline)": ["V9"],
        "V9 + M": ["V9", "M"],
        "V9 + N": ["V9", "N"],
        "V9 + P": ["V9", "P"],
        "V9 + R": ["V9", "R"],
        "V9 + T": ["V9", "T"],
        "V9 + W": ["V9", "W"],
        "V9 + X": ["V9", "X"],
        "COMBO_A: V9+M+R+W": ["V9", "M", "R", "W"],
        "COMBO_B: V9+M+P+R": ["V9", "M", "P", "R"],
        "COMBO_C: V9+M+R+T+W": ["V9", "M", "R", "T", "W"],
        "COMBO_D: V9+M+R+X": ["V9", "M", "R", "X"],
        "COMBO_E: V9+M+N+P+R+W": ["V9", "M", "N", "P", "R", "W"],
        "COMBO_F: V9+R+W": ["V9", "R", "W"],
        "COMBO_G: V9+N+X": ["V9", "N", "X"],
        "COMBO_H: V9+N+R+X": ["V9", "N", "R", "X"],
        "COMBO_I: V9+N+R": ["V9", "N", "R"],
        "COMBO_J: V9+N+R+X+W": ["V9", "N", "R", "X", "W"],
    }

    results = {}
    print(f"{'variant':<40} {'BET':>4} {'stake':>9} {'payout':>9} {'profit':>10} {'ROI':>7} {'hit':>9} | {'CV mean':>9} {'CV std':>9} {'pos/5':>6}")
    print("-" * 145)
    for name, mods in variants.items():
        if name == "v8.4.1 baseline (kelly-OFF stake)":
            agg = {"bet_n": 199, "stake": 0, "payout": 0, "profit": 0, "roi_pct": 0, "hits": 0, "hit_rate": 0}
            stk = sum(r["stake_off"] or 0 for r in rows)
            pyt = sum(r["payout_off"] or 0 for r in rows)
            hits = sum(1 for r in rows if r.get("hit_off"))
            agg = {"bet_n": 199, "stake": stk, "payout": pyt, "profit": pyt - stk, "roi_pct": pyt / stk * 100 if stk else 0, "hits": hits, "hit_rate": hits / 199 * 100}
            cv = {"mean": 0, "std": 0, "positive_folds": 0}
        elif name == "v8.4.1 ON (kelly-ON, no V9)":
            stk = sum(r["stake_on"] or 0 for r in rows)
            pyt = sum(r["payout_on"] or 0 for r in rows)
            hits = sum(1 for r in rows if r.get("hit_on"))
            agg = {"bet_n": 199, "stake": stk, "payout": pyt, "profit": pyt - stk, "roi_pct": pyt / stk * 100 if stk else 0, "hits": hits, "hit_rate": hits / 199 * 100}
            cv = {"mean": 0, "std": 0, "positive_folds": 0}
        else:
            agg = aggregate(rows, mods)
            cv = cv_5fold(rows, mods)
        results[name] = {"agg": agg, "cv": cv, "mods": mods}
        cv_str = f"¥{cv['mean']:>+7,.0f} ¥{cv['std']:>7,.0f} {cv['positive_folds']}/5" if cv['std'] else "       -        -    -"
        print(f"{name:<40} {agg['bet_n']:>4} ¥{agg['stake']:>7,} ¥{agg['payout']:>7,} ¥{agg['profit']:>+8,} {agg['roi_pct']:>6.1f}% {agg['hits']}/{agg['bet_n']} ({agg['hit_rate']:>2.0f}%) | {cv_str}")

    # Per-year for top 5 variants
    print("\n=== per-year profit ===")
    print(f"{'variant':<40} {'2022':>9} {'2023':>9} {'2024':>9} {'2025':>9} {'TOTAL':>9}")
    sorted_variants = sorted(results.items(), key=lambda kv: kv[1]["agg"]["profit"], reverse=True)
    for name, data in sorted_variants[:8]:
        per_year = {y: 0 for y in ["2022", "2023", "2024", "2025"]}
        for r in rows:
            y = r.get("year")
            if y not in per_year: continue
            if name == "v8.4.1 baseline (kelly-OFF stake)":
                d = (r.get("payout_off") or 0) - (r.get("stake_off") or 0)
            elif name == "v8.4.1 ON (kelly-ON, no V9)":
                d = (r.get("payout_on") or 0) - (r.get("stake_on") or 0)
            else:
                st, py, _ = apply(r, data["mods"])
                d = py - st
            per_year[y] += d
        tot = sum(per_year.values())
        print(f"{name:<40} ¥{per_year['2022']:>+7,} ¥{per_year['2023']:>+7,} ¥{per_year['2024']:>+7,} ¥{per_year['2025']:>+7,} ¥{tot:>+7,}")

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {OUT}")


if __name__ == "__main__":
    main()
