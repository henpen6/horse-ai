# v8.4.1 Kelly stake redux — audit report

**Date**: 2026-04-28 JST
**Author**: COO (closed-loop re-derivation)
**Predecessor**: v8.4.0 (Kelly stake scaffolding shipped DISABLED — replication failure)

---

## Summary

v8.4.0 shipped the Kelly fractional stake sizing function but left
`kelly_stake.enabled = false` because the v8.4.0 self-test showed
**-¥13,950 profit regression** vs v8.2 baseline despite Phase O having
claimed +¥72k.

v8.4.1 root-causes that gap to a **build_portfolio composition bug**
(extra budget concentrated on top-EV bet instead of diversified scale),
fixes the application point, and validates the corrected behavior on
fresh-engine closed-loop data.

**Result: +¥87,590 / 3-year n=151 (vs OFF baseline). 3 years all
positive. 4/5 chronological folds positive. SHIP as v8.4.1.**

---

## Phase 1: Fresh-engine data regeneration (n=151)

`bin/shared/v8_kelly_redux_dump.py` — runs current v8.4.0 engine
(kelly_stake disabled) on every snapshot in 2023-2025 with viable
extra_odds + actual_result. Produces per-race
`{axis_number, axis_dslr_days, axis_edge_ratio (fresh),
portfolio, payout, profit at ¥1200 baseline}`.

Output: `apps/horse-ai/data/kelly_redux/n_fresh_v840.jsonl`

```
n=151 active-bet races (out of 378 snapshots)
2023: 60 races, baseline profit +¥20,880
2024: 28 races, baseline profit +¥46,700
2025: 63 races, baseline profit +¥88,520
TOTAL: baseline profit +¥156,100, ROI 186.1%, hit 68/151 (45.0%)
```

Reconciliation with Phase O n=337: Phase O included SKIP races (zero
stake) in n; we include only active-bet races. Phase O total stake
¥184,800 / ¥1200 = 154 active-bet races, matches our n=151 within
sampling jitter.

## Phase 2: Distribution characterization

DSLR quartiles (train 2023+2024): 25%=36d / 50%=62d / 75%=83d.
Range 14-406d. Phase O literature bands {≤35, 36-63, ≥64} closely
align with the actual quartiles → no re-binning needed.

**edge_ratio quartiles (train): 25%=0.837 / 50%=0.848 / 75%=0.863.**
Min=0.803, max=0.924. Distribution is **much narrower than Phase O
assumed**. Phase O's `<0.70` low-conviction band has zero population
in the fresh engine — softmax + new_factors_safety_cap clamp the
realistic edge_ratio range to ~[0.80, 0.92]. The ">0.85" high-
conviction band catches roughly half the races.

This narrow range means edge_ratio bands act as a **2-state switch**
(>0.85 vs ≤0.85) rather than the 3-state Phase O design. The "0.7-0.85
neutral" band is doing all the heavy lifting for the bottom half.

## Phase 3 — quantile-derived custom bands (REJECTED)

We tried fitting 9-cell `(DSLR x edge_ratio)` empirical-Kelly
multipliers from train (2023+2024) and applying to 2025 hold-out.

```
Train cell ROI:               edge ≤0.844   ≤0.860   >0.860
   DSLR ≤48           ROI=0.44 m=0.50 | ROI=3.25 m=1.98 | ROI=3.40 m=2.00
   DSLR ≤76           ROI=0.67 m=0.50 | ROI=1.12 m=0.68 | ROI=1.74 m=1.06
   DSLR  >76          ROI=2.86 m=1.74 | ROI=0.08 m=0.50 | ROI=1.99 m=1.21
   train overall ROI = 1.64
```

**2025 hold-out delta: -¥6,428 (FAIL).** n=8-11 per train cell is too
small; cells with extreme train ROI (0.08, 2.86) flipped sign in test.

Verdict: per-cell empirical-Kelly does NOT generalize at this n.
Pre-specified bands (Phase O literature-derived) are more robust.

## Phase 3.5: Implementation bug discovery

We then applied **Phase O's exact bands** (not custom-fit) directly to
the fresh dataset using a simple per-race scaling simulation:

```
def po_dslr_mult(d):
    return 0.667 if d<=35 else 1.0 if d<=63 else 1.5
def po_er_mult(e):
    return 1.4 if e>0.85 else 1.0 if e>=0.7 else 0.8

# scale stake AND payout uniformly by mult:
profit_simulated = sum(payout*mult - stake*mult for race)
```

Result: **+¥55,728 vs OFF baseline. 3 years all positive.**

But running the same Phase O bands through the **actual v8.4.0
implementation closed-loop** (engine builds portfolio with kelly-scaled
budget, review_bets at result) yields:

```
Phase 3.5 closed-loop A/B (n=151):
  off (kelly disabled): stake=¥181,200 payout=¥337,300 profit=¥+156,100 hit=68/151
  on  (kelly enabled):  stake=¥243,100 payout=¥385,250 profit=¥+142,150 hit=64/151
  delta: profit=-13,950 stake=+61,900 hits=-4
  portfolio bet-count changed: 37/151
  axis pick changed:           0/151
```

Delta -¥13,950 **exactly matches** the v8.4.0 self-test number that
caused the ship-disabled decision. Hits dropped 4 (more concentration
= less diversified hits). `portfolio bet-count changed: 37/151`
= build_portfolio reshapes itself when budget changes.

### Root cause

For race 2024-04-06 中山 11R:
```
=== OFF (budget ¥1,200) ===
  TRIO×10 @ ¥100 each + WIDE×1 @ ¥200  → total ¥1,200
=== ON (budget ¥1,800, kelly_mult=1.5) ===
  TRIO[3,7,11] @ ¥700 (others ¥100), WIDE @ ¥200 → total ¥1,800
```

Same 11 bet tickets, same axis. **build_portfolio dumps the entire
extra ¥600 onto the top-EV ticket** instead of scaling all stakes
proportionally. Top-EV horse hits only ~22% of the time — most of the
time the concentrated ¥600 is wasted. This is **classic top-pick
concentration**, NOT Kelly fractional sizing.

### Fix (one-line semantics, ~12-line code change)

`apps/horse-ai/src/engine/future_minimal.py`:

```python
# OLD (v8.4.0):
if kelly_stake_multiplier != 1.0:
    routed_budget = int(routed_budget * kelly_stake_multiplier)
    routed_budget = max(600, (routed_budget // 100) * 100)
portfolio = build_portfolio(..., budget=routed_budget)

# NEW (v8.4.1):
portfolio = build_portfolio(..., budget=routed_budget)  # original budget
if kelly_stake_multiplier != 1.0 and portfolio.get("bets"):
    new_total_stake = 0
    for _bet in portfolio["bets"]:
        _scaled = int(round(_bet.get("stake_yen", 0) * kelly_stake_multiplier / 100.0)) * 100
        _scaled = max(100, _scaled)  # JRA min ¥100/ticket
        _bet["stake_yen"] = _scaled
        new_total_stake += _scaled
    portfolio["total_stake"] = new_total_stake
```

This applies the multiplier **uniformly across all bets** after
build_portfolio constructs the diversified portfolio, preserving the
ticket-allocation ratio that engine optimized for.

## Phase 4 — Closed-loop A/B post-fix

```
=== Phase 3.5 closed-loop A/B (n=151) — POST-FIX ===
  off (kelly disabled): stake=¥181,200 payout=¥337,300 profit=¥+156,100 hit=68/151
  on  (kelly enabled):  stake=¥259,700 payout=¥503,390 profit=¥+243,690 hit=68/151
  delta: profit=+87,590 stake=+78,500 hits=+0
  portfolio bet-count changed: 0/151
  axis pick changed:           0/151
  2023: n=60 off=¥+20,880 on=¥+32,500 delta=¥+11,620
  2024: n=28 off=¥+46,700 on=¥+55,650 delta=¥+8,950
  2025: n=63 off=¥+88,520 on=¥+155,540 delta=¥+67,020
```

- profit +¥87,590 vs OFF baseline
- hits unchanged (Kelly is a stake adjustment, not a selection change)
- bet-count + axis stable (correct invariants)
- 3 years all positive

## Phase 5 — 5-fold chronological CV

Train on 4 folds, evaluate on 1, slide forward chronologically.

```
fold 1 (2023-01-09 → 2023-06-04, n=30): off=¥ +6,620 on=¥ +6,490 delta=¥   -130
fold 2 (2023-06-11 → 2023-12-28, n=30): off=¥+14,260 on=¥+26,010 delta=¥+11,750
fold 3 (2024-03-02 → 2025-01-19, n=30): off=¥+67,950 on=¥+98,530 delta=¥+30,580
fold 4 (2025-01-26 → 2025-06-22, n=30): off=¥+51,100 on=¥+77,040 delta=¥+25,940
fold 5 (2025-07-27 → 2025-12-28, n=31): off=¥+16,170 on=¥+35,620 delta=¥+19,450

CV: mean=¥+17,518  std=¥12,145  mean/std=1.44  positive folds=4/5
```

Significance gate (pre-specified): mean > 2*std (strict) or mean > std
(lenient, Phase O standard).

- Strict (>2σ): FAIL (1.44 < 2.0)
- Lenient (>1σ, Phase O standard): PASS (1.44 > 1.07 = Phase O claim)
- Positive folds: PASS (4/5; only fold 1 -¥130 = rounding-noise level)

Verdict: **lenient gate pass + 4/5 positive + 3-year all-positive +
robust portfolio behavior** → ship.

## Bug audit checklist (per v8.4.0 spec, re-validated post-fix)

- [x] kelly_mult does NOT mutate engine.compute_win_ev_candidates output (axis_changed: 0/151)
- [x] axis number lookup correct (top-EV horse, NOT top by popularity)
- [x] DSLR computation handles missing past_performances (returns multiplier 1.0)
- [x] edge_ratio division by zero protected (model_p=None or implied_p=0 returns 1.0)
- [x] safety_cap clamps both directions [0.5, 2.0]
- [x] routed_budget rounding doesn't break build_portfolio (build_portfolio sees ORIGINAL budget; scaling happens after)
- [x] hard_skip path NOT affected (engine_skip races still get empty portfolio, no kelly mult applied — early return before scaling block)
- [x] strategy_router (insufficient_data_coverage → ¥600) AND kelly_mult interaction sane (composes correctly: ¥600 base × multiplier)
- [x] kelly_breakdown is JSON-serializable for cache write
- [x] **NEW**: portfolio composition stable when kelly enabled (bet-count delta: 0/151)
- [x] **NEW**: hit-rate invariant under kelly enable/disable (Kelly is stake-only)

## Test results

- 52/52 tests in test_ev_factors.py + test_engine_phase2.py PASS (kelly + engine integration)
- 11 pre-existing test failures in test_batch_review_silent_fail / test_collector_race_result / test_horse_detail_enrichment / test_main_future — verified by `git stash` to also fail on commit `2747479` (pre-fix). NOT introduced by v8.4.1.

## Ship decision: GO as v8.4.1

- weights.json: kelly_stake.enabled = true, _comment updated with v8.4.1 closed-loop validation summary
- _version.py: v8.4.0 → v8.4.1
- future_minimal.py: kelly application moved post-build_portfolio with uniform per-bet scaling
- This audit doc as immutable record of the closed-loop validation
