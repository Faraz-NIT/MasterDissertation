# Experiment procedure

## Suggested order

1. Run `python -m pytest -q` and the offline synthetic demonstration.
2. Prepare three M5 items with all their stores, then run `configs/smoke.yaml`.
3. Run B1/B2/B3/B4 on one clean and one degraded scenario; inspect individual traces, fill rates, holds and true-reference comparisons.
4. Run separate rolling-origin forecast scoring before choosing a final model. Do not choose hyperparameters on the final evaluation origins.
5. Configure one real LLM and run B10 on a small public/synthetic panel. Inspect token counts, schema errors and fallback labels before comparing B6–B10.
6. Freeze a configuration and preregister primary comparisons/tolerances. The autonomy gate is frozen as of 6 Oct 2026
   (`gate-v2-spend-deviation-2026-10-06`, see `docs/GATE_CALIBRATION.md`); do not retune it on test windows. The main draft comparison is B3/B4/B9/B10; validate that the selected model/architecture implementations match the claims you intend to make.
7. Supply pooled calibration only with permission and defensible denominators. Until then, report synthetic perturbations and do not call them calibrated.
8. Run independent replications, rate/hold sensitivity, constraint carrier variants, replay and counterfactual audits.
9. Conduct a human pilot only after institutional approval; expert-review the generated reference labels and improve/match the explanation arms before a powered main study.

## Split convention

The input sales files determine the usable historical span. `start_day` is a zero-based array offset. Each origin begins `origin_stride` periods later; the final required index is checked against the available file. A validation-only M5 file is shorter than the evaluation file; decrease the final origin/end date as needed. Training stops before warm-up, and test-period observations feed forecasts without refitting weights.

## Statistical unit

At least 30 independent seeds are specified for final-study configurations, as in the proposal. Rolling origins are averaged **within seed** for paired comparisons so correlated windows are not counted as independent replications. Both Wilcoxon and paired-t results are provided; choose the inferential procedure after an appropriate distributional assessment, not whichever p-value is smallest. Holm correction is applied over generated comparison tests. Wide intervals, model changes and multiple exploration rounds remain your responsibility to report.

The summary reports descriptive replication-level tail costs and safety-adjusted utility. Detection data include class/day labels; confusion counts and confidence intervals can be computed from `detection.csv`. Full mixed-effects estimation, audit-study power analysis and all reliability metrics listed in the dissertation are not automatically fitted by this package.

## Controlled constraint corpus

`python scripts/grounding_benchmark.py --generate` creates source documents plus separate expected typed fields. Expected answers are never passed to an LLM call. Template-mode tests measure parser/validator correctness. `--prose-only` creates controlled field-complete prose without the `RULE` grammar. A deterministic parser correctly escalates these rather than pretending to understand them; add a configured LLM to evaluate extraction. This corpus is deliberately small and synthetic and must not be described as a realistic multilingual workbook benchmark.

## Repeated fixed-evidence model experiment

```
python scripts/repeat_decision.py --run-dir results/m5_smoke/D1__normal__seed7__origin0 \
  --config configs/llm_study.local.yaml --replications 30 --out results/fixed_evidence
```

Use the source run's horizon and scenario count. The script fixes the observation and forecast artifact while varying requested LLM seeds. It logs proposed quantity dispersion and distinct action hashes, and executes nothing. Some providers ignore seeds. Constant demand makes the traditional variance-ratio bullwhip denominator zero; the script reports absolute action dispersion instead of an invented finite ratio.

## Calibrate marginal rates only

The accepted input CSV has exactly `failure_class,duration_days`; it must already be pooled and anonymized. The denominator is the number of comparable monitored decision-batch days, not a count guessed from sales rows.

```
python -m ega calibrate --incidents /approved/pooled_incidents.csv \
  --exposure-days 10000 --provenance "Approved pooled telemetry extract; version X" \
  --out configs/pooled_calibration.local.json
```

Replace `10000` with the real approved denominator. Set `quality.calibrated: true` and `quality.calibration_file` in a copied config. Missing classes are not filled with fictional calibrated rates; isolated incidents remain rare-event stress scenarios. Rates are marginal, not a model of correlated outages.

## Main deterministic study, stage 1 (frozen 6 Oct 2026)

`configs/main_study_stage1.yaml`: B1–B4, 30 seeds, one origin, 28 decision days from day 1830, scenarios normal,
feed_gap, derived_field_collapse and foreign_unit_moq, gate v2, simulated delayed approval. 480 runs; a 28-day MILP run
takes about 12 minutes on one core, so the study is run as parallel seed workers:

```
scripts/run_main_study.sh configs/main_study_stage1.yaml      # WORKERS=4 by default, niced, resumable
```

Each worker is an ordinary `ega run --resume` on a seed subset; rerunning the script resumes whatever was interrupted
and finally merges the workers into `results/main_study_stage1` (`scripts/merge_studies.py`, hard links) and renders the
report. The statistical unit is the seed; one origin means no within-seed origin averaging. Stage 2 is the remaining
13 scenarios of `configs/deterministic_study.yaml` with identical settings. "Harmful" executions are reported with
their split into true-constraint violations and distance-to-reference flags.

## Shortened LLM study on a USD 20 budget (frozen 6 Oct 2026)

A 30-series, 30-seed LLM study costs about USD 500 at list price (146k tokens per B10 decision), so the LLM arms are
run on a design that keeps 30 seeds and asks the one question only an LLM arm can answer: can the gated LLM system
replenish safely from **prose** supplier documents that the deterministic parser cannot read?

`configs/llm_prose_study.cerebras.yaml`: 10 series (FOODS_1_001 at all ten stores, one coupled supplier portfolio),
`document_carrier: prose` (field-complete prose, no RULE line; ground truth and oracle still use the template
rendering of the same contracts), B4 (control: holds every day on prose), B9 and B10 (LLM systems without and with
the gate), 30 seeds, 4 decision days from day 1830, normal and derived_field_collapse, gate v2, simulated approval.
`configs/llm_prose_study_reference.yaml` runs B3 and B4 on the template carrier for the same seeds and days at no
cost: B4 there is the upper reference for B10-on-prose, B3 the no-gate reference for B9.

Sized by the probe `results/llm_prose_probe` (6 Oct 2026): a B10 decision on this panel costs 77k tokens, 11.5 calls
and USD 0.032 at list price; the 480 LLM decisions come to about USD 17, hard-capped at USD 19 by `llm.max_cost_usd`
(the ledger `results/llm_spend_prose.json` is shared by parallel workers under a file lock). On the free tier the
daily token quota allows about 13 decisions per day; with paid credit the study takes a few hours:

```
set -a; . ./.env; set +a
WORKERS=3 PY=.venv/bin/python scripts/run_main_study.sh configs/llm_prose_study.cerebras.yaml
PY=.venv/bin/python scripts/run_main_study.sh configs/llm_prose_study_reference.yaml
```

Both resume after a quota stop or a cap stop with the same command.

## Stage 2 on the Cerebras free tier

The first LLM pilot (`configs/llm_study.cerebras.yaml`: 2 series, 1 seed, 4 days, B4 and B6–B10) used about 950k
tokens, which is one day of the free tier for `gpt-oss-120b` (1M tokens/day; in practice the binding limits are
150 requests/hour and 5 requests/minute, so a run sleeps for up to an hour whenever the hourly request budget is
spent, which is why step 1 below takes about 40 minutes and the whole driver several hours). The
30-series, 30-seed design is not reachable on that quota; it needs paid credit. `scripts/run_llm_cerebras.sh` runs
the experiments that are reachable, each resumable, and rebuilds the PDF report:

1. `configs/llm_injection_unscreened.cerebras.yaml`: the injection scenario with `gate.injection_screen: false`, so the
   hostile note reaches the model instead of being dropped by the regex screen. B4 is the no-LLM control. The gate
   version string labels every trace of this run; never mix it with screened runs in one comparison.
2. `scripts/repeat_decision.py` on a stored B10 decision, 30 replications, only the requested LLM seed varies.
3. `scripts/grounding_benchmark.py` on the controlled prose corpus, where the deterministic parser can only escalate.

Export `EGA_LLM_API_KEY` in the shell first; a remote endpoint without a key stops before any run is written.

## Known hold-budget limitation

The budget changes when a hold becomes urgent. It does not implement a real planner response-time model or automatically release orders. With `approval_mode: hold`, changing the budget can leave costs identical while changing urgency flags. Do not manufacture a claimed service effect from urgency alone. The optional simulated-reviewer mode provides a separately identified, delayed current-state check, not real planner behavior.
