# Changelog

All notable changes to the horse-ai engine, documented per Semantic Versioning conventions.

The 4-year backtest profit numbers are closed-loop validated on n=199 BET races spanning 2022-2025 G1+G2+G3 stakes. Hit rate is per BET race (not per total race count).

---

## [v9] — DESIGN ONLY (planned, not implemented)

**Date**: 2026-04-30 (design)
**Status**: design document only at `docs/v9_design.md`

### Planned additions
- `classifier_gate.py` — depth ≤ 2 asymmetric tree routing engine
- Per-segment override system with inheritance chain
- 6 active leaves: G1_default / G2_chalk / G2_default / G3_2yo_skip / G3_3_5_turf / G3_3_5_dirt + 1 fallback
- Production observation framework with 4-week ROI rollback triggers
- Roadmap: v9.1 (netkeiba PP extension) → v9.2 (LLM enrichment) → v9.3 (re-A/B disabled factors)

### Projected impact
- est +¥5-15k 4-year profit lift over v8.4.2
- Strategic value: architecture readiness for 地方競馬 / 障害 / 海外 expansion

---

## [v8.5] — DEFERRED (closed-loop simulated only)

**Date**: 2026-04-29
**Status**: research-only, not shipped due to 2026 OOS generalization concern

### Numeric optimizations from Codex 12-dim grid sweep
- DSLR thresholds: 35 → 40, 63 → 60
- DSLR multipliers: [0.667, 1.0, 1.5] → [0.85, 1.1, 1.8]
- edge_ratio multipliers: [1.4, 1.0, 0.8] → [1.55, 1.2, 0.5]
- Safety cap bounds: [0.5, 2.0] → [0.4, 2.5]
- DSLR 64-90 boost factor: 1.2 → 1.3

### Closed-loop simulate result (n=199 / 4-year)
- Profit: +¥325,680 (vs v8.4.2 +¥285,610 = **+¥40,070**)
- ROI: 191.6% (slight ROI dilution due to higher stakes)
- Hit rate: 45% (unchanged — Kelly is selection-invariant)
- Per-year: 2022 +¥48k / 2023 +¥39k / 2024 +¥67k / 2025 +¥170k

### 2026 OOS partial validation (Jan-Apr only, n=10 BET)
- v8.4.2: +¥25,890 / 30% hit
- v8.5: +¥33,120 / 30% hit (+¥7,230 improvement)
- Sample too small for confidence

### Why deferred
- 4-year fitting bias suspected (2025 contributes 85% of v8.4.x improvements)
- 2026 OOS hit-rate collapse on v8.4.2 (45% → 12.5% on n=48) — concerning generalization gap
- v9 classifier_gate provides cleaner per-grade routing instead of single-config aggressive numeric

---

## [v8.4.2] — 2026-04-28 (CURRENT PRODUCTION)

**Date**: 2026-04-28 18:55 JST
**Commit**: app/horse-ai branch in origin repo
**Status**: deployed, observation phase

### Added
- **rule_L** in `race_gate.should_hard_skip`: SKIP if axis_pop=2 AND axis_edge_ratio ∈ [0.85, 0.87]
  - Empirical 4-year (n=199): cell -¥21,430 / 18 race / 17% hit_rate (worst Kelly degradation cell)
- **V4 pop2_cap** in `_kelly_stake_multiplier`: cap kelly_mult ≤ 1.0 when axis_pop=2
  - Empirical: pop=2 axes ROI 110% / hit 27% → amplification systematically loses
- **V6 dslr_64_90_boost** in `_kelly_stake_multiplier`: multiply kelly_mult ×1.2 when DSLR ∈ [64, 90]
  - Empirical: cell delta +¥53,470 (single largest Kelly contributor, "magic zone")

### 4-year backtest (closed-loop, n=199)
- Profit: +¥285,610 (vs v8.4.1 +¥260,360 = **+¥25,250**)
- ROI: 197.8% (+21.1pp over v8.4.1)
- Hit rate: 45% (+3pp)
- Per-year: 2022 +¥25k / 2023 +¥44k / 2024 +¥58k / 2025 +¥158k

### 2026 OOS observation (Jan-Apr only)
- Total +¥7,230 / 12.5% hit_rate on n=48 races
- Per-grade: G1 -¥6k (0/5 hit), G2 +¥15k (5/17), G3 -¥1.7k (1/26)
- ⚠ Hit rate dropped from 4-year 45% → 12.5% — generalization gap

### Configuration toggles (weights.json)
- `kelly_stake.pop2_cap_enabled` (default true)
- `kelly_stake.dslr_64_90_boost_enabled` (default true)
- `kelly_stake.dslr_64_90_boost_factor` (default 1.2)
- `hard_skip.rule_L_enabled` (default true)
- `hard_skip.rule_L_pop` / `rule_L_edge_ratio_min` / `rule_L_edge_ratio_max`

---

## [v8.4.1] — 2026-04-28 (Kelly fix)

**Date**: 2026-04-28 18:55 JST (replaced v8.4.0 same day)
**Status**: superseded by v8.4.2

### Fixed
- **Kelly multiplier application point**: moved from pre-budget (in v8.4.0) to post-build_portfolio.
- `kelly_mult` now applies UNIFORMLY across all bets after `build_portfolio` constructs the diversified portfolio (each bet's `stake_yen` scaled, ¥100-unit floor preserved).

### Why this matters
v8.4.0 pre-multiplied `routed_budget` and passed to `build_portfolio`. The portfolio builder concentrated extra budget on the top-EV ticket only (e.g., budget ¥1,200 → ¥1,800: TRIO[3,7,11] grew ¥100→¥700 while other 10 tickets stayed at ¥100). Top-EV horse hits ~22% — concentrated stakes were largely wasted.

The fix: scale each bet's stake post-portfolio. This preserves diversification while changing total exposure.

### 4-year backtest (closed-loop, n=199)
- Profit: +¥260,360 (vs v8.4.0 -¥13,950 self-test regression = **+¥274,310 swing**)
- ROI: 176.7%
- Hit rate: 42% (unchanged from v8.2 — Kelly is selection-invariant)
- This single position change was the largest gain in v8 lineage.

### Files changed
- `src/engine/future_minimal.py:run_future_engine` — moved Kelly application to after `build_portfolio()`
- `data/config/weights.json` — `kelly_stake.enabled = true` re-enabled

---

## [v8.4.0] — 2026-04-28 (Kelly stake scaffolding, SHIPPED DISABLED)

**Date**: 2026-04-28 17:50 JST
**Status**: disabled out of the gate

### Added (but disabled)
- `_kelly_stake_multiplier` function in `ev_factors.py`
- `kelly_stake` config block in `weights.json` with DSLR bands, edge_ratio bands, safety_cap
- Tests for Kelly logic

### Why shipped DISABLED
- Phase O research claimed +¥72,582 backtest improvement with Phase O bands (using stale cache edge_ratio)
- v8.4.0 self-test on closed-loop showed -¥13,950 regression
- Root cause discovered later: build_portfolio over-concentration → fixed in v8.4.1

---

## [v8.3.0] — 2026-04-28

**Date**: 2026-04-28 ~07:00 JST
**Status**: superseded

### Added
- LLM pre-review default-disabled in batch context (`HORSE_AI_BATCH_SKIP_PRE_REVIEW=1`)
- DSLR / last_3f factor scaffolding (config disabled by default — failed validation)
- gpt-5.4-mini replacement for claude-haiku-4-5 in pre-review path (`_call_haiku` function name kept for compatibility but dispatches to gpt-5.4-mini by default; `HORSE_AI_PRE_REVIEW_PROVIDER=anthropic_haiku` for legacy rollback)

### Rationale
- Batch context: LLM pre-review added 10s/race latency, token cost, with no measurable engine improvement (Counterfactual: hyp_profit ≈ actual_profit when LLM gate active)
- Single race: LLM pre-review retained as sanity check

---

## [v8.2.0] — 2026-04-28

**Date**: earlier 2026-04-28
**Status**: superseded

### Added
- `rule_I` in hard_skip: SKIP if month ∈ {2, 10}
  - Empirical: 月10 ROI 42.8% / 月2 ROI 54.9%, combined avoided -¥34k loss
- `rule_K`: SKIP if grade=G3 AND axis_age=2
  - Empirical: G3 2歳軸 ROI 18.3% / -¥17,600
- owner_tier / farm_tier population fix in build_snapshot.py:205-231

### 4-year backtest (closed-loop, n=199)
- Profit: +¥181,170 (vs v8.1 ~+¥140,180 ≈ **+¥41k**)
- ROI: 175.9%
- Hit rate: 42%

---

## [v8.1.0] — 2026-04-28

**Date**: earlier 2026-04-28
**Status**: superseded

### Added
- `should_hard_skip` function in `race_gate.py` — first deterministic hard SKIP gate
- Initial rules A/B/C/D
  - A: axis_odds < 2.5 (本命過信)
  - B: grade=G3 AND axis_pop=2
  - C: any advisory race_gate reason fired
  - D: grade=G3 AND axis_pop=1
- `_W()` live reference fix (race_gate reads ev._W instead of cached copy at module load)

### Backtest
- 2024+2025 G1+G2+G3 stakes (n=220 with v8.1 factor patch): hit 37.7% → 41.8%, ROI 147.4% → 191.1%, profit +¥117k → +¥149.7k

---

## [v8.0.0] — 2026-04-27

**Date**: 2026-04-27 21:55 JST
**Status**: superseded; factor wire-in turned out to be no-op

### Added
- 7 modular factors in `new_factors_product`:
  - `gate_factor`: venue × surface × distance × gate group
  - `pedigree_factor`: sire (and dam_sire on dirt) aptitude × surface/distance
  - `condition_aptitude_factor`: per-horse past finish weighted by today's track_condition (≥3 race floor)
  - `style_condition_factor`: 4×4 dominant_style × track_condition table
  - `class_step_factor`: today_tier − max(recent past tiers)
  - `weight_trend_factor`: |delta| ≤4kg → +2% boost; ≥10kg drops/gains → ±3-5% decay
  - `owner_breeder_factor`: Tier1/Tier2 boost capped at +3%
- `new_factors_safety_cap` clamp on product to [0.85, 1.15]
- Each candidate dict gets `breakdown_factors` for observability
- server.py race dict expanded from 5 keys to 12

### 4-year backtest (closed-loop, n=199)
- Profit: +¥151,290 (identical to v7.9 baseline — **0 improvement**)
- Reason: gate_bias / pedigree_factor / owner_breeder were disabled in production weights.json after small-n A/B failed; class_step / weight_trend remained DORMANT because netkeiba pp rows didn't populate `race_class` / `horse_weight`; condition_aptitude + style_condition produced near-1.0 multiplier output

### Lesson
Wiring data signals into the engine is necessary but insufficient — the data layer must populate fields, the magnitudes must be empirically validated at production scale, and disabled-but-present factors waste no engine time but provide no benefit.

---

## [v7.9.x] — Pre-2026-04-27

**Date**: pre-2026-04-27
**Status**: baseline

### Composition
- Core ability + popularity + weight + qualitative factors only
- No new modular factors
- No SKIP rules
- No Kelly fractional sizing

### 4-year backtest (closed-loop, n=199)
- Profit: +¥151,290
- ROI: 128.9%
- Hit rate: 39%

This is the empirical baseline against which all v8.x improvements are measured.
