# Experiment procedure

## Suggested order

1. Run `python -m pytest -q` and the offline synthetic demonstration.
2. Prepare three M5 items with all their stores, then run `configs/smoke.yaml`.
3. Run B1/B2/B3/B4 on one clean and one degraded scenario; inspect individual traces, fill rates, holds and true-reference comparisons.
4. Run separate rolling-origin forecast scoring before choosing a final model. Do not choose hyperparameters on the final evaluation origins.
5. Configure one real LLM and run B10 on a small public/synthetic panel. Inspect token counts, schema errors and fallback labels before comparing B6–B10.
6. Freeze a configuration and preregister primary comparisons/tolerances. The main draft comparison is B3/B4/B9/B10; validate that the selected model/architecture implementations match the claims you intend to make.
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

## Known hold-budget limitation

The budget changes when a hold becomes urgent. It does not implement a real planner response-time model or automatically release orders. With `approval_mode: hold`, changing the budget can leave costs identical while changing urgency flags. Do not manufacture a claimed service effect from urgency alone. The optional simulated-reviewer mode provides a separately identified, delayed current-state check, not real planner behavior.
