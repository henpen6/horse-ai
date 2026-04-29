# v9 Design Document — Comprehensive Engine Architecture

**Version:** v9 (planning, not yet implemented)
**Status:** DESIGN — implementation deferred per CEO directive 2026-04-30
**Author:** COO
**Last updated:** 2026-04-30 01:10 JST
**Audience:** CEO, COO, future implementers (Codex / horse-ai dev session)

---

## 0. Executive Summary

v9 is the planned **peak engine version** consolidating all empirically-validated improvements from v8.4.2 (current production) plus three structural advances:

1. **Per-segment classifier gate** with shallow tree-branch routing (depth ≤ 2, asymmetric, leaf n ≥ 20 floor)
2. **Per-leaf parameter override** for sensitive parameters only (Kelly bands + SKIP rule toggles), with inheritance and Bayesian shrinkage for small leaves
3. **Production observation framework** with 4-week rollback triggers tied to OOS performance (critical given 2026 OOS hit-rate collapse from 45% → 12.5%)

Expected lift over v8.4.2 (current production +¥285,610 / 4-year n=199 closed-loop): **modest, +¥10-30k**, dominated by per-leaf parameter optimization. Tree-branch architecture itself contributes only +¥1-3k empirically; the larger benefit is **structural readiness for future expansion (地方競馬 / 障害 / 海外, dormant signal activation)**.

**Honest caveat:** 2026 OOS data on v8.4.2 already shows generalization gap. v9 risks amplifying this if not carefully validated. Recommendation: Phase 1 of v9 (shallow tree, conservative leaves) ships only after v8.4.2 accumulates 2026 H2 OOS data confirming generalization.

---

## 1. Background and Lineage

### 1.1 Version progression (4-year backtest 2022-2025, n_BET=199)

| Version | Composition | 4-year profit | ROI | Hit |
|---|---|---|---|---|
| v7.9 | factor off / SKIP off / kelly off | +¥151,290 | 128.9% | 39% |
| v8.0 | factor wired but production-disabled (no-op) | +¥151,290 | 128.9% | 39% |
| v8.2 | + SKIP rules A/B/C/D/I/K | +¥181,170 | 175.9% | 42% |
| v8.4.1 | + Kelly fix (post-build_portfolio uniform scale) | +¥260,360 | 176.7% | 42% |
| v8.4.2 (current) | + V1 (rule_L) + V4 (pop=2 cap) + V6 (DSLR 64-90 boost) | +¥285,610 | 197.8% | 45% |
| v8.5 (deferred) | + Codex numeric all-best (DSLR/edge bands tuned) | +¥325,680 (sim) | 191.6% | 45% |
| **v9 (this doc)** | + classifier gate + per-leaf params + dormant activation | **+¥320-355k (proj)** | est 195-205% | est 45-48% |

### 1.2 Key empirical findings driving v9 design

**Finding 1: Position changes outperform numeric tuning**
- v8.4.0 → v8.4.1 transition (Kelly application point: pre-budget → post-portfolio): **+¥87,590**
- All numeric ε-scans (DSLR/last_3f magnitude tuning): noise-floor results
- Codex Random Forest stake scaler at n=199: -¥27,886 (overfit at small n)

**Finding 2: Per-grade engine optimum is different**
- G1 best version: v8.5 (+¥108k 4-year)
- G2 best version: v8.5 (+¥129k)
- G3 best version: v8.4.1 (+¥118k); v8.5 G3 microregression -¥130
- Per-grade routing harvests this divergence (estimated lift +¥1-3k / 4-year only — small but real)

**Finding 3: 2025 dominance suggests overfit risk**
- v8.4.x's +¥79k Kelly improvement: 85% from 2025 (which is in derivation window)
- 2022 Kelly regression -¥8k (out-of-sample-like behavior)
- 2026 OOS hit-rate collapsed 45% → 12.5% (n=48, partial year)

**Finding 4: factor wire-in alone is insufficient**
- v7.9 → v8.0 produced 0 profit improvement (factors dormant due to data gap or near-1.0 multiplicative output)
- Dormant factor activation requires data layer changes (netkeiba PP fields, LLM enrichment)

**Finding 5: Sensitive parameters concentrated**
- Codex 12-dim grid sweep: only DSLR bands + edge bands have meaningful sensitivity (±¥9-16k each)
- Popularity divisor / weight factor / ability scale / new_factors_safety_cap bounds: ±¥0 (insensitive)
- Per-leaf optimization should restrict to sensitive parameters

---

## 2. v9 Architecture Overview

```
INPUT: collector_result (snapshot or live netkeiba/JRA)
    │
    ├ entries[] (with axis past_performances, gate, sire, age, ...)
    ├ extra_odds (馬連/ワイド/3連複/3連単)
    └ race meta (date, venue, surface, distance, weather, track_condition)
    │
    ▼
[NEW] CLASSIFIER GATE (shallow tree, depth ≤ 2, asymmetric)
    Resolves race → segment_id
    Looks up segment-specific parameter overrides
    │
    ▼
Step 1. Validation (REQUIRED_ODDS_MISSING / WAITING_ON_DATA gates)
    │
    ▼
Step 2. compute_win_ev_candidates(collector_result)
    Strength formula (segment-aware factor weights):
      strength = implied_p × (1+pop_boost)
                       × weight_f × ability_f × qual_f
                       × new_factors_product_clamped
    new_factors_product = gate × pedigree × cond × style × class_step × weight_trend × owner × dslr × last_3f
    softmax(strengths) → model_probability
    │
    ▼
Step 3. compute_race_level → Lv1/Lv2/Lv3
Step 4. classify_unknown_x (top horse)
Step 5. axis_type decision (X-High forced B; else odds≤2.5 → A else B)
Step 6. should_bet_gate (advisory)
    │
    ▼
Step 7. should_hard_skip (segment-aware rules A/B/C/D/I/K/L + per-leaf toggles)
    rule_A: axis_odds < cfg(rule_A_max_odds, segment)
    rule_B: grade=G3 AND pop=cfg(rule_B_pop, segment)
    rule_C: advisory_gate fired
    rule_D: grade=G3 AND pop=cfg(rule_D_pop, segment)
    rule_I: month ∈ cfg(rule_I_months, segment)
    rule_K: grade=G3 AND axis_age=2
    rule_L (v8.4.2): pop=2 AND edge_ratio ∈ [0.85, 0.87]
    Each rule individually toggleable per leaf
    │
    ▼
Step 8. _kelly_stake_multiplier (segment-aware bands)
    DSLR_mult (3 bands per segment)
    edge_ratio_mult (3 bands per segment)
    raw = DSLR × edge
    V4 pop=2 cap (segment-conditional toggle)
    V6 DSLR 64-90 boost (segment-conditional, factor 1.2-1.3 per segment)
    [v8.5 R] DSLR 64-90 + axis_age ≤ 3 super-boost (×1.3)
    [v8.5 X] axis_pop=1 amp ×1.15 (segment-conditional)
    Safety cap [segment.safety_min, segment.safety_max]
    │
    ▼
Step 9. build_portfolio(routed_budget, race_level, axis_type, ...)
    [UNCHANGED from v8.4.2]
    │
    ▼
Step 10. v8.4.1 Kelly post-portfolio uniform scaling [PRESERVED]
    For each bet: stake = round(stake × kelly_mult / 100) × 100, floor at 100
    Recompute portfolio.total_stake
    │
    ▼
Step 11. budget_sweep (informational)
    │
    ▼
OUTPUT: engine_result with kelly_stake_multiplier + kelly_stake_breakdown +
        classifier_gate_segment + segment_overrides_applied (for observability)
```

---

## 3. Component 1: Classifier Gate (Tree)

### 3.1 Tree shape (asymmetric, depth ≤ 2)

```
root: branch=grade
│
├─ G1 (depth=1, leaf, n_4yr=86):
│   segment_id: "G1_default"
│   ├─ inherits default kelly bands (or v8.5 numeric)
│   └─ rule_B disabled, rule_D disabled (v8.2 SKIP rules empirically hurt G1)
│
├─ G2 (depth=2, n_4yr=86):
│   branch: axis_pop
│   ├─ axis_pop=1 → "G2_chalk" (n≈25-30)
│   │   └─ X pop=1 amp ENABLED ×1.2 (stronger than default)
│   └─ axis_pop≥2 → "G2_default" (n≈55-60)
│       └─ V4 pop=2 cap ENABLED, rule_L ENABLED
│
├─ G3 (depth=2, n_4yr=49):
│   branch: axis_age
│   ├─ axis_age=2 → "G3_2yo_skip" (n≈18, → forced SKIP via rule_K inheritance)
│   ├─ axis_age 3-5 →
│   │   branch: surface (within G3, n≈25-30)
│   │   ├─ surface=芝 → "G3_3_5_turf"
│   │   └─ surface=ダート → "G3_3_5_dirt"
│   └─ axis_age ≥6 → "G3_veteran" (n≈3-5, fallback to G3_3_5_turf)
│
└─ default (Open/未勝利/N勝C): "open_default"
   inherits global default v8.4.2 parameters
```

**Total leaves:** 6 active + 1 fallback = 7

**Leaf n minimums:**
- G1_default: n=86 ✓
- G2_chalk: n≈25-30 ✓ borderline
- G2_default: n≈55-60 ✓
- G3_2yo_skip: n≈18 (no parameter optimization needed; forced SKIP)
- G3_3_5_turf: n≈25 ✓ borderline
- G3_3_5_dirt: n≈20 ✓ borderline
- G3_veteran: n≈3-5 ✗ → must collapse to G3_3_5_turf

### 3.2 Resolve logic

```python
def resolve_segment(race, axis):
    grade = race.get("grade")
    surface = race.get("course", {}).get("surface")
    pop = axis.get("popularity")
    age = axis_entry.get("age")

    if grade == "G1":
        return "G1_default"
    elif grade == "G2":
        return "G2_chalk" if pop == 1 else "G2_default"
    elif grade == "G3":
        if age == 2:
            return "G3_2yo_skip"
        elif age and age >= 6:
            return "G3_3_5_turf"  # collapse
        else:  # age 3-5
            return "G3_3_5_dirt" if surface == "ダート" else "G3_3_5_turf"
    else:
        return "open_default"
```

### 3.3 Fallback chain

If a segment is referenced but undefined, walk up the chain:
`leaf → grade-level → default`

Example: G3_3_5_turf undefined → G3_default (synthetic) → default

### 3.4 Toggle: classifier_gate.enabled = false → revert to v8.4.2

When disabled, all races resolve to "default" segment, which mirrors v8.4.2 production config exactly. **Rollback safety guaranteed.**

---

## 4. Component 2: Per-Segment Parameter Tables

### 4.1 What may be overridden per leaf

**High-sensitivity (override-eligible):**
- `kelly_stake.dslr_bands` (thresholds + multipliers)
- `kelly_stake.edge_ratio_bands` (thresholds + multipliers)
- `kelly_stake.safety_min` / `safety_max`
- `kelly_stake.dslr_64_90_boost_factor`
- `kelly_stake.dslr_64_90_boost_factor_young` (v8.5 R)
- `kelly_stake.pop1_amp_factor` (v8.5 X)
- `kelly_stake.pop2_cap_enabled` (V4 toggle)
- `hard_skip.rule_A_enabled` ... `rule_L_enabled` (per-leaf)
- `hard_skip.rule_A_max_odds` (and other rule thresholds)

**Low-sensitivity (NEVER overridden per leaf, kept global):**
- `ev_model.popularity_boost_divisor`
- `ev_model.weight_factor_*`
- `ability.scale`
- `new_factors_safety_cap` bounds
- All disabled-but-present factors (gate_bias, pedigree, owner_breeder, dslr_factor, last_3f_factor)

**Rationale:** Codex grid sweep showed these have ±¥0 sensitivity within tested ranges. Allowing per-leaf override gives engine room to fit noise.

### 4.2 Override count limit per leaf

Hard rule: `override_count ≤ leaf_n / 10`

Examples:
- G1_default (n=86) → max 8-9 overrides
- G2_chalk (n=25) → max 2-3 overrides
- G3_3_5_turf (n=25) → max 2-3 overrides

### 4.3 Inheritance and resolution

```python
def resolve_param(leaf_id, param_path):
    # 1. leaf override
    if leaf_id in segments and param_path in segments[leaf_id].overrides:
        return segments[leaf_id].overrides[param_path]
    # 2. grade-level fallback
    grade_id = leaf_id.split("_")[0]
    if grade_id in segments and param_path in segments[grade_id].overrides:
        return segments[grade_id].overrides[param_path]
    # 3. default
    return DEFAULT_CONFIG[param_path]
```

### 4.4 Sample segment configs

```yaml
segments:

  default:
    # equivalent to v8.4.2 production (no overrides)

  G1_default:
    # G1 chalk-heavy markets; SKIP rules empirically counterproductive
    rule_B_enabled: false
    rule_D_enabled: false
    # Otherwise inherit default

  G2_chalk:
    # axis_pop=1 in G2 — engine sweet spot when chalk is strong
    pop1_amp_factor: 1.20
    pop1_amp_enabled: true
    # Inherit numeric bands from default

  G2_default:
    # axis_pop ≥ 2 in G2
    rule_L_enabled: true
    pop2_cap_enabled: true
    # Inherit default

  G3_2yo_skip:
    # rule_K already handles this, but explicit segment for visibility
    rule_K_enabled: true

  G3_3_5_turf:
    # G3 microregression on v8.5 numeric → use v8.4.1 風 bands
    dslr_bands:
      - {max: 35, multiplier: 0.667}
      - {max: 63, multiplier: 1.0}
      - {max: 9999, multiplier: 1.5}
    edge_ratio_bands:
      - {min: 0.85, multiplier: 1.4}
      - {min: 0.7, multiplier: 1.0}
      - {min: 0.0, multiplier: 0.8}
    dslr_64_90_boost_factor: 1.0  # G3 boost OFF

  G3_3_5_dirt:
    # G3 dirt n=20, conservative
    dslr_64_90_boost_factor: 1.0
    safety_max: 1.5

  open_default:
    # equivalent to v8.4.2 default for unrecognized grade
```

### 4.5 Closed-loop validation requirement

Before each leaf override is finalized:
1. 4-year backtest with leaf-only override (other leaves unchanged from v8.4.2)
2. Walk-forward CV: train 3 years, test 1 year, slide
3. CV mean / std > 1.0 stable; mean > +¥3k 4-year improvement vs v8.4.2

Reject leaf override that fails any of (1)(2)(3).

---

## 5. Component 3: Numeric Optimizations (v8.5 baseline)

For the **default segment** (and inherited by leaves), use Codex's 4-year grid-best:

```yaml
default:
  kelly_stake:
    dslr_bands:
      - {max: 40, multiplier: 0.85}
      - {max: 60, multiplier: 1.1}
      - {max: 9999, multiplier: 1.8}
    edge_ratio_bands:
      - {min: 0.83, multiplier: 1.55}
      - {min: 0.65, multiplier: 1.2}
      - {min: 0.0, multiplier: 0.5}
    safety_min: 0.4
    safety_max: 2.5
    pop2_cap_enabled: true
    dslr_64_90_boost_enabled: true
    dslr_64_90_boost_factor: 1.3
    dslr_64_90_boost_factor_young: 1.3  # v8.5 R
    pop1_amp_enabled: true
    pop1_amp_factor: 1.15  # v8.5 X
```

**Rationale:** v8.5 numeric was Codex grid-best. Closed-loop simulate +¥40k vs v8.4.2 baseline. 2025 overfit risk noted but 2022/2024 also positive.

---

## 6. Component 4: Stake Application (v8.4.1 Fix Preserved)

**MUST NOT modify** the v8.4.1 fix in `future_minimal.run_future_engine`:

```python
# After build_portfolio:
if kelly_stake_multiplier != 1.0 and portfolio.get("bets"):
    new_total_stake = 0
    for _bet in portfolio["bets"]:
        _scaled = int(round(_bet.get("stake_yen", 0) * kelly_stake_multiplier / 100.0)) * 100
        _scaled = max(100, _scaled)  # JRA min ¥100/ticket
        _bet["stake_yen"] = _scaled
        new_total_stake += _scaled
    portfolio["total_stake"] = new_total_stake
```

This fix is the **single biggest gain in v8 lineage** (+¥87,590 from v8.4.0). Any v9 implementation regression here = catastrophic.

---

## 7. Component 5: Refined Kelly Multipliers

Per `_kelly_stake_multiplier` in ev_factors.py:

1. Lookup segment_id via classifier_gate
2. Resolve segment-specific Kelly cfg
3. Apply DSLR band → DSLR_mult
4. Apply edge_ratio band → edge_mult
5. raw_product = DSLR_mult × edge_mult
6. **V4** if pop2_cap_enabled AND axis_pop=2 AND raw>1.0 → raw=1.0
7. **V6** if dslr_64_90_boost_enabled AND DSLR ∈ [64, 90]:
   - if axis_age ≤ 3: raw *= dslr_64_90_boost_factor_young
   - else: raw *= dslr_64_90_boost_factor
8. **X** if pop1_amp_enabled AND axis_pop=1: raw *= pop1_amp_factor
9. Safety cap: clamp(raw, [safety_min, safety_max])

Order is **critical**: V4 cap before V6/X amplification ensures pop=2 axes never reach amplification path. V6 before X means young-horse magic-zone is recognized first, then pop=1 amp on top.

---

## 8. Component 6: Hard SKIP Rules (per-leaf toggles)

All 8 rules (A/B/C/D/I/K/L + new candidates) toggleable per leaf:

| Rule | Condition | Default toggle | G1 leaf override | G3_3_5_turf override |
|---|---|---|---|---|
| A | axis_odds < 2.5 | enabled | enabled | enabled |
| B | grade=G3 + pop=2 | enabled | **disabled** | enabled |
| C | advisory gate fired | enabled | enabled | enabled |
| D | grade=G3 + pop=1 | enabled | **disabled** | enabled |
| I | month ∈ {2, 10} | enabled | enabled | enabled |
| K | grade=G3 + age=2 | enabled | enabled | enabled |
| L | pop=2 + edge ∈ [0.85, 0.87] | enabled | enabled | enabled |

**Future candidates (not yet in v9):**
- M: DSLR 36-63 + race_level=Lv1 (multidim_phase3 V9+N variant; -¥9.5k cell)
- N: DSLR 91-180 + race_level=Lv2 (multidim_phase3 V9+M variant; -¥10.8k cell, but hurts 2022)

**Decision:** Defer M/N introduction until classifier_gate stable + 2026 OOS validates.

---

## 9. Component 7: Dormant Factor Activation Roadmap

Three classes of dormant signal, **NOT in v9 initial**, scheduled for v9.1+:

### 9.1 Phase 1: netkeiba PP extension (v9.1)
**Scope:** Extend `src/collector/netkeiba/fetch_horse_history.py` and `historical_snapshot.py` to populate per-PP-row `race_class` and `horse_weight`.

**Effect:** Activates `class_step_factor` and `weight_trend_factor` (currently dormant; produce 1.0 default).

**Estimated lift:** +¥10-30k 4-year (Codex est) — but contingent on factors actually correlating with hit. Re-A/B at n=505 required.

**Effort:** 5-7 engineering days (collector + tests + closed-loop validate).

### 9.2 Phase 2: qualitative_features.\_llm_engine populate (v9.2)
**Scope:** Run gpt-5.4-mini enrichment on each entry's qualitative state (training progress, jockey conditioning, etc.) to populate `qualitative_features._llm_engine`.

**Effect:** Activates qualitative_factor in strength formula with non-default values. Currently 0% populated across 24,147 PP rows.

**Estimated lift:** +¥20-50k 4-year (highly speculative; LLM signal quality unknown).

**Risk:** Token cost ~10× current; latency +30-60s per race. Sample-test on 40-60 race batch first.

### 9.3 Phase 3: Re-A/B disabled factors at n=505 (v9.3)
**Scope:** Re-test `gate_bias`, `pedigree_factor`, `owner_breeder` at full 4-year n=505. Original A/B failed at n=32-50 (pre-v8 era).

**Effect:** Each factor either passes A/B at n=505 (and is re-enabled) or stays disabled.

**Estimated lift:** unknown; could be ±¥10k.

**Risk:** Low; toggle-based, A/B mechanically determined.

---

## 10. Component 8: Production Observation Framework

### 10.1 Daily metrics

Log per race (in `engine_details`):
- segment_id (which classifier leaf fired)
- kelly_mult final value
- kelly_breakdown (V4 capped, V6 boosted, X amped, etc.)
- skip_rule fired (if any)
- baseline_stake (¥1200) and final_stake delta

### 10.2 Weekly aggregates

Compute every Monday for prior week:
- Per-segment race count, profit, ROI, hit_rate
- Per-rule SKIP fire count
- Kelly multiplier distribution (mean, median, % at safety_max, % at safety_min)

### 10.3 Rollback triggers

**4-week trailing:**
- ROI < (production baseline ROI − 10pp) for 4 consecutive weeks: **ALERT**
- ROI < (baseline − 20pp) for 4 weeks: **AUTOMATIC ROLLBACK to v8.4.2**

**Per-segment:**
- Any segment with hit_rate < 25% over 4 weeks (n≥10): disable that segment, fall back to default

### 10.4 Manual override

CEO can trigger `classifier_gate.enabled = false` at any time → instant rollback to v8.4.2 behavior.

---

## 11. File-by-File Implementation Plan (Future)

### 11.1 New files

- `apps/horse-ai/src/engine/classifier_gate.py` — segment resolution + fallback chain
- `apps/horse-ai/data/config/segments.json` — segment override definitions
- `apps/horse-ai/tests/test_classifier_gate.py` — unit tests

### 11.2 Modified files

- `apps/horse-ai/src/engine/ev_factors.py` — `_kelly_stake_multiplier` reads segment cfg
- `apps/horse-ai/src/engine/race_gate.py` — `should_hard_skip` reads segment cfg
- `apps/horse-ai/src/engine/future_minimal.py` — calls classifier_gate before kelly
- `apps/horse-ai/data/config/weights.json` — add `classifier_gate` block, `default` segment with v8.5 numeric

### 11.3 Backward compatibility

- All existing config keys preserved
- `classifier_gate.enabled = false` (default in initial ship) → exact v8.4.2 behavior
- Per-leaf override system fully optional; missing overrides inherit cleanly

### 11.4 Testing requirements

- 59 existing unit tests must pass
- New tests:
  - Tree resolution for each leaf
  - Fallback chain when segment missing
  - Per-leaf parameter override correctly applied
  - Toggle off equals v8.4.2 behavior (regression test)
  - Bug audit: 10 invariants from v8.4.1/v8.4.2 must hold per leaf
- Closed-loop A/B: each segment vs default must show stable improvement before activation
- Walk-forward CV: 3-fold leave-year-out for each segment override

---

## 12. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Per-leaf overfit (small n) | High | Medium | leaf n ≥ 20 floor + override count ≤ n/10 + Bayesian shrinkage to parent |
| 2026 OOS amplifies hit_rate gap | Medium | High | classifier_gate.enabled=false rollback; 4-week ROI trigger |
| 2025 train-overlap bias | High | Medium | Walk-forward CV per segment; reject overrides failing CV |
| Implementation regression on Kelly fix | Low | Catastrophic | Preserve v8.4.1 fix block as-is; regression test |
| Segment fallback chain bug | Low | Medium | Unit test each chain; default fallback to v8.4.2 |
| Disabled factors re-enabled too eagerly | Medium | Medium | Phase v9.1/v9.2/v9.3 separately; A/B per factor |
| Configuration sprawl | Medium | Low | Inheritance + minimal override norm; per-leaf override count limit |

---

## 13. Per-Version Comparison (anchor table)

4-year backtest profit per grade (closed-loop, n=199 BET races):

| Version | G1 (n=51-86) | G2 (n=73-133) | G3 (n=49-201) | TOTAL | ROI | Hit |
|---|---|---|---|---|---|---|
| v7.9 | +¥106,670 | +¥48,330 | -¥510 | +¥154,490 | 128.9% | 39% |
| v8.0 | (no-op vs v7.9) | +¥154,490 | 128.9% | 39% |
| v8.2 | +¥84,680 | +¥60,950 | +¥34,800 | +¥180,430 | 175.9% | 42% |
| v8.4.1 | +¥96,090 | +¥75,370 | +¥83,590 | +¥255,050 | 176.7% | 42% |
| v8.4.2 (production) | +¥97,010 | +¥99,500 | +¥82,690 | +¥279,200 | 197.8% | 45% |
| v8.5 (deferred) | +¥110,580 | +¥137,760 | +¥73,730 | +¥322,070 | 191.6% | 45% |
| **v9 (this design, projected)** | +¥110-115k | +¥137-142k | +¥80-85k | **+¥327-342k** | est 195-205% | est 45-48% |

v9 projection assumes:
- G1 inherits v8.5 numeric (no further gain)
- G2 splits chalk vs default → small additional lift
- G3 reverts to v8.4.1 風 numeric → gains ~¥7k vs v8.5 (recovers G3 microregression)
- Net: v9 ≈ v8.5 + ¥5-15k (modest, dominated by G3 recovery)

---

## 14. Open Questions for CEO

1. **Ship sequencing**: Phase 1 of v9 (classifier_gate + per-leaf overrides) before or after 2026 H2 OOS data accumulates on v8.4.2?
2. **Default numeric base**: should v9 default segment be v8.4.2 (conservative) or v8.5 (aggressive)? Affects baseline for all leaves.
3. **G3_veteran fallback**: collapse to G3_3_5_turf, or define explicitly? Current proposal collapses (n too small).
4. **rule_B/D disable on G1**: closed-loop validate on 4-year first (estimated +¥3-5k); or accept on v8.2 historical observation?
5. **2026 OOS rollback threshold**: -10% ROI trigger appropriate? Or stricter (-5%)?
6. **Codex re-engagement**: should Codex audit this v9 design before implementation? (current Codex deep-research subprocess returned partial findings; v9 design here goes beyond what Codex covered)
7. **Position changes from Codex Phase G-O TASK A**: A6 (race_level pre-candidates) was positive — incorporate into v9 or defer?
8. **Architecture readiness vs immediate gain**: per-leaf gain is small (~+¥5-15k); is the architectural readiness for 地方競馬 / 障害 sufficient justification, or wait?

---

## 15. Summary

v9 = v8.4.2 + classifier_gate (depth ≤ 2 asymmetric) + per-leaf parameter override (sensitive params only) + v8.5 numeric default + production observation framework.

**Empirical lift over v8.4.2 (4-year backtest):** modest +¥5-15k from per-leaf optimization, dominated by G3 numeric reversion.

**Strategic value:** architecture readiness for future expansion (地方競馬, 障害, 海外, dormant factor activation), explicit per-grade tuning, cleaner SKIP rule semantics, rollback safety.

**Recommended ship cadence:**
- v9 Phase 1 (architecture + G1/G2/G3 leaves): ship after 2026 H2 OOS validates v8.4.2 generalization
- v9.1 (netkeiba PP extension): independent, earliest data-layer gain
- v9.2 (LLM enrichment): high-cost, controlled rollout
- v9.3 (re-A/B disabled factors): mechanical, low-risk

**Implementation gate:** ship Phase 1 only after closed-loop validation per segment + walk-forward CV mean/std > 1.0 + CEO approval + clean 2026 H2 OOS data on v8.4.2.

— COO 2026-04-30 01:10 JST
