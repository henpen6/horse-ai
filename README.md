# horse-ai — Japanese horse racing prediction engine

> **Status:** v8.4.2 in production / v9 in design
> **Last updated:** 2026-04-30
> **Repository purpose:** development tracker, version archive, design documentation, public visibility for collaborative review

This repo is the open documentation + source code archive for an experimental Japanese horse racing prediction engine. It supports JRA (中央競馬) G1/G2/G3 stakes races with deterministic Python scoring + portfolio construction.

The system runs deployed via Discord bot (private, in a separate ops repo) but the engine itself, design docs, and backtest harnesses live here for transparency and external review by humans + LLMs.

---

## Quick architecture summary

Input (collector_result from snapshot or live) → engine → portfolio of bets

```
1. Validate odds (REQUIRED_ODDS_MISSING / WAITING_ON_DATA gates)
2. compute_win_ev_candidates → strength formula → softmax → ranked candidates
3. compute_race_level (Lv1/Lv2/Lv3) + classify_unknown_x (top horse)
4. axis_type decision (A=本命 / B=非本命)
5. should_bet_gate (advisory) + should_hard_skip (rules A/B/C/D/I/K/L)
6. _kelly_stake_multiplier (DSLR × edge_ratio × V4 pop2_cap × V6 DSLR 64-90 boost)
7. build_portfolio (Lv-routed, axis-typed bet structures)
8. Apply Kelly mult uniformly to each bet stake post-portfolio (v8.4.1 fix)
9. Output engine_result with full breakdown
```

See [`docs/v9_design.md`](docs/v9_design.md) §2 for full pipeline and `src/engine/future_minimal.py:run_future_engine` for the canonical Python entry point.

---

## Version history (4-year backtest 2022-2025, n_BET=199)

| Version | Composition | 4-year profit | ROI | Hit rate |
|---|---|---|---|---|
| v7.9 | factor off / SKIP off / Kelly off | +¥151,290 | 128.9% | 39% |
| v8.0 | factor wired but production-disabled (no-op) | +¥151,290 | 128.9% | 39% |
| v8.1 | + factor tuning + initial hard SKIP gate | +¥140,180 (early backtest) | varies | varies |
| v8.2 | + SKIP rules A/B/C/D/I/K stabilized | +¥181,170 | 175.9% | 42% |
| v8.3 | + LLM pre-review default-disabled in batch + DSLR/last_3f scaffolding | (transitional) | — | — |
| v8.4.0 | + Kelly stake scaffolding (shipped DISABLED — replication failure) | (-¥13,950 self-test regression) | — | — |
| v8.4.1 | + Kelly fix (post-build_portfolio uniform scale) | +¥260,360 | 176.7% | 42% |
| **v8.4.2 (production)** | + V1 (rule_L SKIP) + V4 (pop=2 cap) + V6 (DSLR 64-90 boost ×1.2) | **+¥285,610** | **197.8%** | **45%** |
| v8.5 (deferred) | + Codex numeric all-best (DSLR/edge bands tuned) | +¥325,680 (sim) | 191.6% | 45% |
| v9 (design only) | + classifier_gate (per-segment routing) + per-leaf overrides | est +¥320-355k | est 195-205% | est 45-48% |

Detail per version, per-grade, per-year: [`docs/v9_design.md`](docs/v9_design.md) §1.1, §13.

---

## Repository layout

```
.
├── README.md                              # this file
├── src/
│   ├── _version.py                        # canonical version string
│   └── engine/
│       ├── ev.py                          # candidates: strength formula + softmax
│       ├── ev_factors.py                  # Kelly multiplier + 9 modular factors
│       ├── future_minimal.py              # engine entry: run_future_engine
│       ├── race_gate.py                   # SKIP rules A/B/C/D/I/K/L
│       ├── portfolio.py                   # bet construction (Lv1/Lv2/Lv3)
│       ├── budget_sweep.py                # informational stake size advisor
│       ├── review.py                      # post-race review (hits/payout)
│       ├── hard_stop.py                   # error code definitions
│       └── stake.py                       # stake normalization helpers
├── data/config/
│   └── weights.json                       # production engine config (v8.4.2)
├── tests/
│   ├── test_ev_factors.py                 # Kelly + factor unit tests (59 tests)
│   └── test_engine_phase2.py              # engine integration tests
├── docs/
│   ├── v9_design.md                       # ★ v9 comprehensive design (English, ~5,000 words)
│   ├── v841_kelly_redux_audit.md          # closed-loop validation report (v8.4.0 → v8.4.1 fix)
│   └── v85_strategy_codex_research.md     # Codex deep research v8.5 strategy report
└── harness/
    ├── v8_kelly_redux_dump.py             # fresh-engine per-race feature dump
    ├── v8_kelly_redux_real_run.py         # closed-loop A/B (kelly off vs on)
    ├── v8_version_comparison.py           # 4-year × 4-version backtest matrix
    ├── v8_multidim_sweep.py               # 1D/2D slice analysis
    ├── v8_multidim_phase3.py              # V0-V10 variant counterfactual sweep
    ├── v85_sweep.py                       # V9 + extended combos
    └── v8_full_matrix.py                  # version × year × grade matrix
```

---

## Running the engine

The engine is designed to be embedded in a Python service (HTTP server, batch backtest, etc.). It's NOT a standalone CLI. Sample call:

```python
import sys
sys.path.insert(0, ".")
from src.engine.future_minimal import run_future_engine
import json

snapshot = json.load(open("path/to/snapshot.json"))
collector_result = snapshot["collector_result"]
result = run_future_engine(
    collector_result=collector_result,
    budget=1200,
    budget_source="backtest",
)
print(result["candidates"][0])  # top axis horse
print(result["portfolio"]["bets"])  # bet plan
print(result["kelly_stake_multiplier"])  # stake adjustment
```

Snapshots are produced by separate collector scripts that scrape JRA + netkeiba (not in this repo — those touch external rate limits and are kept private).

---

## Key empirical findings driving design

1. **Position changes outperform numeric tuning** — the v8.4.0 → v8.4.1 transition (Kelly application point: pre-budget → post-portfolio) yielded **+¥87,590** (the single largest gain in v8 lineage). Numeric ε-scans on factor magnitudes consistently failed.

2. **Per-grade engine optimum is different** — G1 and G2 favor v8.5 numeric (more aggressive Kelly), G3 favors v8.4.1 風 (more conservative). Per-segment routing (v9) addresses this.

3. **Factor wire-in alone is insufficient** — v7.9 → v8.0 produced 0 profit improvement because factors were either disabled, clamped near 1.0, or dependent on data fields not populated.

4. **2025 dominance suggests overfit risk** — v8.4.x's +¥79k Kelly improvement is 85% from 2025 (which is in the derivation window). 2026 OOS data shows hit-rate collapse (45% → 12.5%), confirming generalization gap.

5. **Sensitive parameters are concentrated** — 12-dimensional grid sweep showed only DSLR bands and edge_ratio bands have meaningful sensitivity (±¥9-16k each). Most other parameters (popularity_divisor, weight_factor_*, ability_scale, new_factors_safety_cap) are flat.

6. **Random Forest / decision tree ML approaches fail at n=199** — Codex's leave-one-year-out RF stake scaler lost -¥27,886 vs baseline. Top permutation importance was a portfolio-template artifact (`bet_WIDE`), confirming the model fit noise. Tree-based ML is premature at current data scale.

---

## v9 design highlights

See [`docs/v9_design.md`](docs/v9_design.md) for the full document (~5,000 words). Key components:

1. **Classifier Gate** — depth ≤ 2 asymmetric tree routing: G1 / G2_chalk / G2_default / G3_2yo_skip / G3_3_5_turf / G3_3_5_dirt / open_default. 6 active leaves, leaf n ≥ 20 floor enforced.

2. **Per-Segment Parameter Tables** — only sensitive parameters (Kelly bands + SKIP rule toggles) override per leaf. Override count ≤ leaf_n / 10 to prevent overfitting. Inheritance: leaf → grade → default fallback chain.

3. **Numeric Default = v8.5 Codex grid-best** — DSLR bands (40, 60), DSLR mults (0.85, 1.1, 1.8), edge mults (1.55, 1.2, 0.5), safety cap [0.4, 2.5].

4. **G3 reverts to v8.4.1 風 numeric** — G3 microregression on v8.5 (-¥130) recovered by per-leaf override.

5. **rule_B/D disabled on G1** — empirically validated (v8.2 SKIP rules cost G1 -¥20k vs v7.9). Per-leaf toggle in v9.

6. **Kelly fix preserved** — v8.4.1 post-build_portfolio uniform scaling MUST NOT regress. Single biggest gain in v8 lineage.

7. **Production observation framework** — daily metrics, weekly aggregates, 4-week ROI rollback triggers. `classifier_gate.enabled = false` → instant rollback to v8.4.2.

8. **Dormant signal activation roadmap** — v9.1 (netkeiba PP extension for race_class / horse_weight per row), v9.2 (LLM enrichment for qualitative_features), v9.3 (re-A/B disabled factors at n=505).

---

## Disabled / dormant signals (engineering backlog)

The engine has 9 modular factors in `new_factors_product`. Currently only 2 (`condition_aptitude` + `style_condition`) produce non-trivial output:

| Factor | Status | Reason |
|---|---|---|
| gate_bias | disabled | A/B at n=32-50 failed; not yet re-tested at n=505 |
| pedigree_factor (sire/damsire) | disabled | A/B at n=32-50 failed |
| condition_aptitude | enabled, active | track_condition × past_finish weighting |
| style_condition_bias | enabled, active | dominant_style × track_condition lookup |
| class_step | enabled but DORMANT | netkeiba PP rows lack `race_class` field |
| weight_trend | enabled but DORMANT | netkeiba PP rows lack `horse_weight` field |
| owner_breeder | disabled | A/B at n=32-50 failed |
| dslr_factor | disabled | v8.3 scaffolding failed |
| last_3f_factor | disabled | v8.3 scaffolding failed |

Plus `qualitative_features._llm_engine` is 0% populated across 24,147 PP rows — LLM enrichment never wired.

This disabled-signal backlog is the v9.1+ activation target.

---

## Backtest harnesses (reproducibility)

All harnesses in `harness/` use deterministic in-process engine toggling (`_ev_module._W` mutation pattern) so that (a) production weights.json is never modified, (b) engine runs fresh per-race (no stale-cache contamination), (c) any version A/B can be reproduced from snapshots.

To run any harness, you'd need:
- The 505 snapshot files (private, derived from netkeiba scrapes — not redistributed)
- The actual_result cache files (private, derived from JRA result pages)

The harnesses themselves are open here for methodology transparency.

---

## License

MIT (this repo, code + docs)

The data this engine operates on (JRA odds, netkeiba past performances, race results) is owned by the respective publishers. This engine does not include or redistribute that data.

---

## Disclaimer

- This is a **research project**, not financial advice.
- Past backtest results are not predictive of future performance.
- Japanese parimutuel betting is a regulated activity (only JRA/NRA channels are legal); use this code only for educational research within applicable law.
- The owner accepts no liability for losses or misuse.

---

## Contributing / Contact

Pull requests welcome for documentation improvements. Code changes will be reviewed against the closed-loop validation methodology in `docs/v9_design.md` §11.

For substantive design discussion, open an issue with the relevant version label (v9-design, v9.1-roadmap, etc.).

---

— horse-ai dev / 2026-04-30
