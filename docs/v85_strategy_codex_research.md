# v8.5 Strategy: Precision Improvement Under ROI + Hit-Rate Joint Optimization

**Date:** 2026-04-29 JST  
**Author:** Codex consultation for COO/CEO  
**Primary local evidence:** `bin/shared/v8_version_comparison.py`, `bin/shared/v8_kelly_redux_real_run.py`, `bin/shared/v85_strategy_probe.py`  
**New artifacts:** `apps/horse-ai/data/kelly_redux/v85_strategy_rows.jsonl`, `apps/horse-ai/data/kelly_redux/v85_strategy_metrics.json`

## 1. Executive summary

The short recommendation is: **keep v8.4.1 live, do not “fix” 2022 with year-specific Kelly bands, and make v8.5 a validation/data-activation release rather than an ML-stake release.** The empirical reason is that v8.4.1 is still the strongest aggregate version by a wide margin, while the apparently attractive next moves are either dormant because data is missing or unstable under year holdout.

Top three recommendations:

| Rank | Recommendation | Quantified basis | Expected v8.5 lift | Confidence |
|---:|---|---:|---:|---|
| 1 | Continue v8.4.1 in production and observe 2026 as the first true OOS period | 4-year v8.4.1: +¥260,360, ROI 176.7%, hit 84/199 = 42.2%; +¥79,190 vs v8.2/v8.4.0 | Already banked: +¥79k/4yr vs Kelly-off; future lift unknown until 2026 | Medium-high |
| 2 | Build v8.5 around closed-loop dormant-signal activation, especially netkeiba PP gaps and disabled high-coverage factors | Current corpus: `class_step` and `weight_trend` are effectively neutral because PP `race_class` and PP `horse_weight` are 0%; `qualitative_features` is 0/7,251 entries | Research target +¥10k to +¥40k/4yr if one signal survives CV; honest floor ¥0 | Medium |
| 3 | Treat ML/RF/XGBoost as a research harness, not a ship candidate | First leave-one-year-out RF stake scaler loses -¥27,886 vs baseline; RF profit gate loses -¥150,300 | Short-term ship lift ¥0; longer-term possible after feature/backfill expansion | Medium-high negative for immediate ship |

The important nuance is that **ROI and hit_rate are not independently controllable with the current Kelly layer.** Kelly is stake-only. In the validated closed-loop A/B, axis pick changed 0/151, bet-count changed 0/151, and hit count changed 0. It improved profit by changing exposure, not by selecting more winners. Hit-rate improvement requires either better axis selection, different ticket composition, or a different SKIP gate. Those are higher-risk changes than stake sizing.

External priors support the proposed shape but not blind ML deployment. Kelly sizing is a log-growth stake allocation framework, not a selection model; the original Kelly paper frames information as useful only through correct probability estimates. Benter-style horse-racing systems historically combine a fundamental model with market-implied probabilities and a separate wagering strategy. Modern RF/XGBoost/monotonic tree methods are reasonable tools, and scikit-learn/XGBoost support monotonic constraints, but this local dataset has only 199 active-bet rows. At that size, year holdout beats random CV, and negative holdouts must be treated as real.

References used for external priors:

- Kelly (1956), *A New Interpretation of Information Rate*: https://vtda.org/pubs/BSTJ/vol35-1956/articles/bstj35-4-917.pdf
- Benter, *Computer Based Horse Race Handicapping and Wagering Systems*: https://datagolf.com/static/blogs/benter_paper.pdf
- scikit-learn `RandomForestClassifier` monotonic constraints: https://sklearn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html
- XGBoost monotonic constraints: https://xgboost.readthedocs.io/en/stable/tutorials/monotonic.html
- Horse-racing RF application, *Alternative methods of predicting competitive events*: https://www.sciencedirect.com/science/article/pii/S0169207009002143

## 2. 2022 negative regression analysis

The 2022 regression is real, but the evidence says it is **variance inside a positive aggregate stake-sizing rule**, not an infrastructure bug and not a reason to disable v8.4.1.

Re-run of `bin/shared/v8_version_comparison.py`:

| Version | Stake | Payout | Profit | ROI | Hit |
|---|---:|---:|---:|---:|---:|
| v7.9 no factors | ¥523,200 | ¥674,490 | +¥151,290 | 128.9% | 168/436 = 38.5% |
| v8.0 factors | ¥523,200 | ¥674,490 | +¥151,290 | 128.9% | 168/436 = 38.5% |
| v8.2/v8.4.0 SKIP | ¥238,800 | ¥419,970 | +¥181,170 | 175.9% | 84/199 = 42.2% |
| v8.4.1 Kelly | ¥339,400 | ¥599,760 | +¥260,360 | 176.7% | 84/199 = 42.2% |

Per-year Kelly delta:

| Year | Active bets | Kelly OFF profit | Kelly ON profit | Delta | Hit change |
|---:|---:|---:|---:|---:|---:|
| 2022 | 48 | +¥25,070 | +¥16,670 | -¥8,400 | 0 |
| 2023 | 60 | +¥20,880 | +¥32,500 | +¥11,620 | 0 |
| 2024 | 28 | +¥46,700 | +¥55,650 | +¥8,950 | 0 |
| 2025 | 63 | +¥88,520 | +¥155,540 | +¥67,020 | 0 |
| Total | 199 | +¥181,170 | +¥260,360 | +¥79,190 | 0 |

The 2022 loss is not evenly distributed. It is dominated by one short-rest/moderate-edge bucket that v8.4.1 deliberately downweights:

| 2022 Kelly cell | n | OFF profit | ON profit | Delta | Hit |
|---|---:|---:|---:|---:|---:|
| `<=35d / edge 0.70-0.85 / mult 0.667` | 2 | +¥19,560 | +¥9,080 | -¥10,480 | 1/2 |
| `64+d / edge 0.70-0.85 / mult 1.5` | 11 | -¥1,360 | -¥3,840 | -¥2,480 | 3/11 |
| `64+d / edge >=0.85 / mult 2.0` | 9 | +¥3,090 | +¥6,180 | +¥3,090 | 4/9 |
| `36-63d / edge >=0.85 / mult 1.4` | 10 | +¥11,650 | +¥13,120 | +¥1,470 | 4/10 |

Interpretation: 2022 was hurt mainly because a profitable short-rest cell was downweighted. That is exactly the kind of finite-sample path dependence a stake-sizing layer can produce. It does not contradict the 4-year result unless the short-rest/moderate-edge cell is consistently profitable out-of-sample. Across all active rows, that same cell has n=22, OFF ROI 170.9%, but Kelly ON ROI 145.2% because the multiplier suppresses payout and stake together with JRA unit rounding. This is a candidate for future smoothing, but not enough to overwrite the whole rule.

Decision matrix:

| Option | Result | 2022 effect | Aggregate effect | Recommendation |
|---|---|---:|---:|---|
| A1 Accept OOS noise | 3/4 years positive, total +¥79,190 vs OFF | Keeps -¥8,400 | Keeps +¥79,190 | **Accept** |
| A2 Per-year recalibration | Non-actionable for future years; leave-one-year-out shrinkage did not fix 2022 reliably | Prior_n=10: -¥12,070 vs OFF; prior_n=40: -¥6,323 vs OFF | Loses most of 2023-2025 Kelly gain | Reject |
| A3 Continuous Kelly multiplier | Best in-sample grid only +¥32,298 vs OFF | Not proven better in 2022 | Far below current +¥79,190 | Reject for v8.5 |
| A4 Bayesian shrinkage by cell | In-sample +¥12,291 to +¥30,851 vs OFF depending prior | Partial improvement only at heavy shrinkage | Far below current +¥79,190 | Reject as replacement |
| A5 Walk-forward validation | Correct standard for future proposals | Shows 2022 is one negative fold | Needed for v8.5 gates | Adopt methodology |

The subtle point: A2/A4 look “more statistical,” but at n=199 they reduce exactly the profitable exposure that made v8.4.1 valuable. The right answer is not to fit the past harder. The right answer is to shadow-log 2026 Kelly OFF vs ON and learn whether 2025 was derivation overlap or genuine regime fit.

## 3. Multi-dim parameter exploration

### 3.1 Dataset and objective

`v85_strategy_probe.py` created a per-race matrix from 2022-2025:

| Surface | Count |
|---|---:|
| Snapshots in corpus | 505 |
| Payout-backed rows | 448 |
| Engine-evaluable rows | 436 |
| v8.2/v8.4.0 active bet rows | 199 |
| Active rows by year | 2022=48, 2023=60, 2024=28, 2025=63 |

The joint objective should be explicit:

```python
score = profit_yen - lambda_miss * max(0, target_hit_rate - hit_rate)
```

or, more transparently, produce a Pareto table:

| Candidate | Profit | ROI | Hit rate | Active bets |
|---|---:|---:|---:|---:|
| v8.4.1 current | +¥260,360 | 176.7% | 42.2% | 199 |
| Higher-hit gate variant | lower expected profit until proven | target 140-170% | 45-50% | lower/higher depends |

Do not hide the tradeoff. A hit-rate increase bought by removing high-variance profitable bets may feel better but reduce the bankroll objective.

### 3.2 First RF prototype: negative

I tested a simple leave-one-year-out RandomForest prototype on the 199 active rows. Features included axis DSLR, edge ratio, odds, popularity, age, style, grade, race level, field size, surface, distance, post hour, month, owner/farm/class tiers, and current portfolio bet-type counts. This is deliberately close to Topic B1/B2, but it is a prototype, not a production model.

| Holdout | Base profit | RF stake-only profit | Delta | RF gate profit | Gate hit | Base hit |
|---:|---:|---:|---:|---:|---:|---:|
| 2022 | +¥25,070 | +¥14,066 | -¥11,004 | -¥5,840 | 38.1% | 33.3% |
| 2023 | +¥20,880 | +¥27,190 | +¥6,310 | +¥19,990 | 43.6% | 40.0% |
| 2024 | +¥46,700 | +¥37,183 | -¥9,517 | +¥7,650 | 30.8% | 39.3% |
| 2025 | +¥88,520 | +¥74,845 | -¥13,675 | +¥9,070 | 46.7% | 52.4% |
| Total | +¥181,170 | +¥153,284 | -¥27,886 | +¥30,870 | 41.7% | 42.2% |

Classifier AUC was only moderate: 2022=0.56, 2023=0.69, 2024=0.65, 2025=0.59. The 2025 permutation importance list was unstable and led with `bet_WIDE`, then venue/style indicators. That is not a durable signal hierarchy; it is a warning that the model is reading portfolio templates and year-specific payout clusters.

Recommendation for B1/B2: keep the harness, but do not ship an ML multiplier in v8.5 unless a walk-forward model beats v8.4.1 net profit and does not reduce hit rate. The current evidence is negative.

### 3.3 Monotonic constraints

Monotonic constraints are attractive because they encode priors:

- Higher edge ratio should not reduce predicted hit probability.
- Extremely low DSLR or high rust should not increase predicted hit probability without evidence.
- Stronger market rank should generally increase predicted hit probability.

Both scikit-learn and XGBoost support monotonic constraints for eligible tree models. Locally, however, the raw cell evidence is not cleanly monotone:

| Cell | n | OFF ROI | Hit |
|---|---:|---:|---:|
| `<=35d / edge 0.70-0.85` | 22 | 170.9% | 40.9% |
| `<=35d / edge >=0.85` | 22 | 283.1% | 59.1% |
| `36-63d / edge 0.70-0.85` | 35 | 114.3% | 34.3% |
| `36-63d / edge >=0.85` | 29 | 156.5% | 51.7% |
| `64+d / edge 0.70-0.85` | 46 | 212.2% | 39.1% |
| `64+d / edge >=0.85` | 44 | 152.5% | 38.6% |

Edge is helpful in the short and mid DSLR cells, but not in the long-rest cell. DSLR is not monotone either. Therefore B3 should be tested as a regularizer after data expansion, not asserted now.

### 3.4 Bet-type composition

The current portfolio lifts hit rate above axis-win rate by using exotics plus WIDE coverage. Axis win rate in the current corpus is 28.4% on all engine rows and 27.1% on active rows; active portfolio hit rate is 42.2%.

Portfolio composition:

| Bet-type set | n | Profit | ROI | Hit |
|---|---:|---:|---:|---:|
| TRIO+WIDE | 121 | +¥100,680 | 169.3% | 35.5% |
| QUINELLA+WIDE | 34 | +¥9,120 | 122.4% | 50.0% |
| EXACTA+QUINELLA+WIDE | 17 | +¥2,430 | 111.9% | 58.8% |
| EXACTA+WIDE | 16 | +¥49,840 | 359.6% | 68.8% |
| QUINELLA | 10 | +¥20,300 | 269.2% | 30.0% |

This is the most promising hit-rate lever, but the sample sizes are tiny outside TRIO+WIDE. A v8.5 portfolio tuner should search ticket mix with constraints:

- Preserve total stake at ¥1,200 before Kelly.
- Evaluate hit-rate and profit Pareto frontier, not only ROI.
- Require year holdout. `EXACTA+WIDE` is too attractive in-sample to trust without fold stability.

### 3.5 Stage gate optimizer

The SKIP gate is still load-bearing. Counterfactual betting of all 237 skipped races would have produced -¥29,880, ROI 89.5%, hit 35.4%. That validates the existence of the gate.

But rule-level evidence is mixed:

| Skip reason | Counterfactual n | Profit if bet | ROI | Hit |
|---|---:|---:|---:|---:|
| Rule D G3 pop1 | 82 | -¥36,970 | 62.4% | 30.5% |
| Rule K G3 age2 | 23 | -¥21,410 | 22.4% | 17.4% |
| Rule I month02 | 38 | -¥16,390 | 64.1% | 26.3% |
| Rule I month10 | 40 | -¥14,990 | 68.8% | 37.5% |
| Rule A axis odds <2.5 | 50 | -¥8,700 | 85.5% | 42.0% |
| Rule B G3 pop2 | 46 | +¥8,030 | 114.5% | 34.8% |
| Rule C advisory fired | 47 | +¥11,200 | 119.9% | 40.4% |

An exploratory relax set using only positive exclusive clusters produced +¥43,920 in-sample, but it was negative in 2025 (-¥6,060). That makes F4 a good v8.5 research candidate, not an immediate patch.

## 4. Dormant factor activation plan

The biggest v8.5 opportunity is not adding new math. It is making sure existing intended features actually carry data.

Corpus scan:

| Field class | Coverage |
|---|---:|
| Race-level `race_class` | 485/505 snapshots = 96.0% |
| Current `horse_weight` | 7,235/7,251 entries = 99.8% |
| Current `gate_number`, owner/farm/class tier | 6,772/7,251 entries = 93.4% |
| Sire/damsire | 6,286/7,251 entries = 86.7% |
| Past-performance `date` | 24,147/24,147 PP rows = 100% |
| Past-performance `track_condition` | 23,887/24,147 = 98.9% |
| Past-performance `pace` | 23,101/24,147 = 95.7% |
| Past-performance `race_class` | 0 observed |
| Past-performance `horse_weight` | 0 observed |
| `qualitative_features` | 0/7,251 entries |

### C1. netkeiba PP extension

`src/collector/netkeiba/fetch_horse_history.py` currently parses date, popularity, corner positions, field size, finish, venue, distance, track condition, and pace. It does not parse past race class or body weight. `weight_trend` needs past `horse_weight`; `class_step` needs PP `race_class`/`grade`/`class`. Therefore both factors can be enabled in config and still be behaviorally neutral.

Implementation scope:

1. Extend `_parse_history_row()` to parse available netkeiba columns for race name/class, horse body weight, and possibly carried weight.
2. Normalize `damsire` into `dam_sire` or update `_pedigree_factor()` to read both keys. Current snapshots have `damsire`, while the factor reads `dam_sire` for the dirt dam-sire branch.
3. Add parser tests with fixed HTML fixtures. Do not depend on live netkeiba in tests.
4. Backfill a 2022-2025 sample, then run closed-loop A/B with only one factor family active at a time.

Effort estimate: 3-5 engineering days for parser + tests + sample backfill, plus 1-2 days for closed-loop A/B. Expected lift is uncertain: +¥0 floor, +¥10k to +¥25k/4yr plausible if used as stake/gate signal, higher only if CV proves it.

### C2. gate_bias / pedigree / owner_breeder

These are disabled, but data coverage is now high enough to re-test:

- `gate_number`: 93.4%
- sire/damsire: 86.7%
- owner/farm/class tiers: 93.4%

Prior micro-optimization showed tempting but unstable pockets: gate_bias isolation had a best in-sample +¥41,300, owner_breeder tiny-epsilon isolation +¥20,280, and gate_bias+pedigree +¥41,660. Those were not v8.4.1 closed-loop with Kelly and year holdout, so they are not ship evidence. They are good candidates for `v85_strategy_probe.py` extension.

### C3. LLM qualitative features

`qualitative_features` is completely off in the 2022-2025 snapshots. The EV engine has a qualitative multiplier path, but no populated data. This is the only dormant area that could plausibly improve hit rate rather than just stake sizing, because it can affect axis probability/ranking.

Recommendation: run a small backfill experiment first:

| Step | Size | Acceptance gate |
|---|---:|---|
| Sample G1/G2/G3 across all years | 40-60 races | extraction success >95%, deterministic cache reuse |
| Closed-loop A/B qualitative ON/OFF | same sample | axis changes must improve profit or hit without one-race artifact |
| Full backfill | 448 payout-backed rows | chronological CV positive before config enable |

LLM enrichment should not be enabled live by default until cache behavior and cost are known.

## 5. 2026 production observation framework

2026 is the clean test because it was not part of the Kelly derivation period. The observation plan should shadow Kelly OFF for every production race without changing live output.

Baseline Kelly multiplier distribution from the 199 active historical rows:

| Multiplier | n | Share |
|---:|---:|---:|
| 0.667 | 22 | 11.1% |
| 0.934 | 22 | 11.1% |
| 1.0 | 35 | 17.6% |
| 1.4 | 30 | 15.1% |
| 1.5 | 46 | 23.1% |
| 2.0 | 44 | 22.1% |

Weekly dashboard metrics:

| Metric | Definition | Trigger |
|---|---|---|
| Kelly mult drift | Weekly multiplier distribution vs baseline | Investigate if any bucket differs by >20pp after n>=20 |
| Shadow ROI delta | `profit(Kelly ON) - profit(Kelly OFF)` from same engine snapshot | Alert if 4-week delta ROI < -10% |
| Hit invariant | ON hit count must equal OFF hit count for stake-only Kelly | Any mismatch is a bug |
| Portfolio invariant | ON bet-count and axis must equal OFF for stake-only Kelly | Any mismatch is a bug |
| Year concentration | Profit contribution by month/grade | Investigate if one payout cluster explains all gain |

Rollback rule: do not roll back on a single bad week. Roll back to v8.4.0/Kelly-OFF only if 4-week shadow delta is below -10% return ROI, or if the stake-only invariants fail.

## 6. v8.5 candidate roadmap

| Rank | Candidate | Effort | Empirical basis | Expected lift | Risk | Decision |
|---:|---|---:|---|---:|---|---|
| 1 | Closed-loop dormant factor activation and netkeiba PP extension | 1 week | Multiple intended factors are neutral due missing PP fields; data coverage otherwise high | +¥10k to +¥40k/4yr if CV passes | Medium | Do first |
| 2 | SKIP rule per-grade/per-reason tuning | 2-3 days | Current gate avoids -¥29,880 overall, but B/C clusters are positive in-sample | +¥5k to +¥15k if 2025 issue resolved | Medium-high | Research |
| 3 | Portfolio composition tuner | 3-5 days | Hit-rate lever; `EXACTA+WIDE` small-n ROI/hit strong | +2-5pp hit possible; profit unknown | High | Prototype only |
| 4 | ML-based Kelly multiplier | 3 days prototype, more for robust | First RF stake-only loses -¥27,886 | ¥0 near-term | High | Do not ship v8.5 |
| 5 | Axis-pick formula refinement | 1-2 weeks | Axis win only 27.1% active; hit ceiling lives here | Potentially high | Very high | After feature backfill |
| 6 | Per-year band recalibration | 1 day | LOYO shrinkage fails; future year unknown | ¥0 | Medium | Reject |
| 7 | Multi-axis portfolio | Weeks | Could lift hit by covering top2 axis | +3-8pp hit possible; ROI likely lower | Very high | Later |

The roadmap deliberately ranks data activation above model complexity. With n=199 active races, complex learners can easily find payout artifacts. Better features and closed-loop validation are more valuable than a larger model.

## 7. Closed-loop validation as standard

Phase O failed because it used stale cached engine outputs. v8.5 should make closed-loop validation non-optional.

Standard protocol:

```python
# Pseudocode for every proposal
snapshot = load_snapshot(path)
collector_result = build_collector_result(snapshot)
actual = load_actual_result_only(sim_cache_path)

with in_memory_weights(candidate_config):
    branch_b = run_future_engine(collector_result=collector_result, budget=1200, budget_source="backtest")

with in_memory_weights(control_config):
    branch_a = run_future_engine(collector_result=collector_result, budget=1200, budget_source="backtest")

review_a = review_bets(branch_a["portfolio"]["bets"], actual)
review_b = review_bets(branch_b["portfolio"]["bets"], actual)
```

Rules:

1. Cache may provide actual results and payouts only. It must not provide candidates, edge_ratio, portfolio, or stake values.
2. Every proposal reports denominators separately: snapshots, payout-backed rows, engine-evaluable rows, active bet rows.
3. Stake-only proposals must prove `axis_changed=0`, `bet_count_changed=0`, and `hit_changed=0`.
4. Selection proposals must show top-pick changes, active-bet changes, and hard-skip changes.
5. Validation must include chronological splits: leave-one-year-out and walk-forward. Random CV is not acceptable for ship.
6. A proposal needs aggregate profit lift, no catastrophic year, and a plausible causal explanation. One payout cluster is not enough.

`bin/shared/v85_strategy_probe.py` is the first v8.5 harness implementing this pattern over 2022-2025 with Kelly ON/OFF and no-SKIP counterfactuals.

## 8. Open questions for CEO/COO

1. What is the explicit v8.5 objective function: maximize absolute profit, maximize ROI, or require hit_rate >=45% even if profit falls?
2. Is 2026 production shadow logging of Kelly OFF authorized in the live server path, provided it does not change output?
3. Is LLM qualitative backfill budget approved for a 40-60 race sample?
4. Should v8.5 optimize only active bet rows (n=199) or include the no-SKIP counterfactual surface (n=436) for gate redesign?
5. Are we comfortable with a v8.5 release whose main deliverable is validation/data plumbing rather than an immediately enabled new factor?

