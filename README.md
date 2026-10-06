# Evidence-Gated Replenishment

**A runnable, simulator-only research repository for the attached dissertation:**
*Evidence-Gated Autonomy for Retail Replenishment: A Constraint-Grounded LLM Multi-Agent System with Verifiable Decision Traces* (revised September 2026).

The system certifies inventory evidence, grounds supplier constraints, forecasts demand distributions, solves a constrained replenishment problem, independently verifies the proposed action, gates autonomy, and writes a replayable audit record.

**No M5 download, API credentials, proprietary retailer data, or model weights are included.** The included example results are a synthetic software demonstration—not experimental support for the dissertation's hypotheses. Read [implementation scope](docs/IMPLEMENTATION_MATRIX.md) before treating a baseline as a literature reproduction.

## 1. Install and run immediately

Run commands from this repository's root. Python 3.11–3.13 is declared; validation was performed on Python 3.13.5. A virtual environment is recommended.

```bash
python -m venv .venv
source .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m ega doctor
python -m pytest -q
python -m ega demo --output results/my_demo --days 6
```

Open `results/my_demo/report.html` locally. No server, cloud account, GPU or LLM is needed for this demonstration. It uses **B1, D0 and D1**, where D0/D1 are explicitly seasonal-forecast software controls, **not aliases for B3/B10**. Existing result directories with summaries cannot be overwritten accidentally.

The archive also includes `examples/validated_demo/report.html`, summary CSVs, and complete content-addressed decision artifacts. See [validation](VALIDATION.md) for exactly what was executed here.

## 2. Supply the M5 files

Unzip the original CSV files into:

```text
data/raw/m5/
├── sales_train_evaluation.csv
├── calendar.csv
└── sell_prices.csv
```

`sales_train_validation.csv` is accepted when the evaluation file is absent. The loader prefers the evaluation file when both exist. Submission/test labels are not required. Respect the dataset's distribution terms; this repository does not redistribute it.

```bash
# Begin with one item at two same-cluster stores.
python -m ega prepare --raw data/raw/m5 --out data/processed/m5 --items 1 --stores CA_1 CA_2
python -m ega run --config configs/smoke.yaml --output results/m5_smoke
python -m ega report --results results/m5_smoke
```

For a larger, department-balanced pilot, prepare `--items 3` without `--stores`, then use `configs/pilot.yaml`. Optional `--materialize-facts` builds the daily sales/price SQL tables as well as the catalog; it is unnecessary for normal panel-based experiments. `--all-items` imports the full hierarchy, but **do not send all 30,490 bottom-level series into one monolithic MILP**. The supplied MILP runner is for coupled research-sized item/store groups; automatic decomposition is not implemented.

Days in configs are **zero-based positions**: `start_day: 1800` means M5 column `d_1801`. A decision's history ends at `start_day - 1`. Eligibility uses only sales before the decision day. Prices are forward-filled, never backfilled, and forecasting uses the last already-observed price.

## 3. Run the forecast and optimizer baselines

```bash
python -m pip install -e ".[ml,dev,report]"   # report: matplotlib + reportlab for scripts/make_report.py
python -m ega run --config configs/deterministic_study.yaml \
  --policies B1 B2 B3 B4 --seeds 7 29 --days 7 --output results/baseline_pilot

python -m ega forecast-backtest --config configs/smoke.yaml \
  --model lightgbm --origins 1800 1828 --horizon 28 --out results/forecast_scores.json
```

`scripts/run_main_study.sh configs/main_study_stage1.yaml` runs the frozen 30-seed stage-1 study as parallel, resumable seed workers and merges them. The complete study config contains 30 independent seeds and multiple rolling origins. **Run and inspect a small pilot first**; do not mistake a two-seed pilot for the final statistical study. Reduce items, scenarios, horizon or origins while debugging, then preregister/freeze the final configuration.

| ID | Actual implementation | Requirement |
|---|---|---|
| B1 | Seasonal-naive residual scenarios + order-up-to | Core |
| B2 | Global LightGBM quantile models + `(s,S)` | `ml` extra |
| B3 | Native probabilistic GRU/NB forecast + stochastic MILP | `ml` extra |
| B4 | B3 + deterministic evidence gate | `ml` extra |
| B5 | Original Chronos-T5 adapter + policy | `foundation` extra + weights |
| B6 | Single generalist LLM grounding/tool request + shared numerical tools | `ml` + configured real LLM |
| B7 | LLM roles with free-form shared messages and a final validated action boundary | Same |
| B8 | Typed LLM roles, no critic | Same |
| B9 | Typed LLM roles + critic, fixed simulator autonomy | Same |
| B10 | Typed LLM roles + critic + per-decision evidence gate | Same |
| D0 / D1 | Seasonal MILP without / with evidence gate and deterministic critic | Core; software controls |

B3/B4 use a real trained autoregressive GRU with a negative-binomial likelihood; they are **not exact DeepAR or TFT reproductions**. B6 remains one generalist role across document batches, not an unconstrained end-to-end language-model policy. Final actions in B7 still pass through deterministic schemas and tools. These are explicit experimental design choices.

## 4. Enable actual language models

Copy `configs/llm_study.example.yaml`, set `llm.model`, `llm.base_url`, and a pinned model revision, and configure the horizon/scenario count. The backend uses the `/chat/completions` contract at an explicitly supplied OpenAI-compatible endpoint. A compatible locally served model can be used; this repository does not install or start a model server.

```bash
# Required for any remote endpoint; a run stops immediately if it is missing. Do not commit the value.
export EGA_LLM_API_KEY='your-key'
python -m ega run --config configs/llm_study.local.yaml --output results/llm_pilot
```

Setting `.env` alone does not export environment variables; the repository deliberately does not auto-load secrets. Remote endpoints require HTTPS. Structured-output support varies: choose `json_mode: schema`, `json`, or `none` as supported. Actual responses are schema-validated in every mode. Providers may ignore seeds or reject unsupported request fields; failed calls are logged and held, not presented as successful research results.

`scripts/run_llm_cerebras.sh` runs the second-stage LLM experiments on the Cerebras free tier (hostile note with the deterministic injection screen switched off via `gate.injection_screen: false`, fixed-evidence reliability, prose grounding), resuming each step where a daily quota stopped it; see [the experiment procedure](docs/EXPERIMENTS.md).

**B6–B10 refuse to run with LLMs disabled.** There is no random-number “LLM simulator.” `on_failure: hold` is the default. Explicit deterministic fallback is separately labeled in `effective_policy`, tokens and error counts. Call budgets are per policy/scenario/seed/origin run, so total study cost can be much larger than a single-run budget. No dollar-cost estimate is fabricated.

## 5. Inspect and replay a decision

```bash
python -m ega replay --run-dir examples/validated_demo/D1__normal__seed7__origin0 --day 140
python -m ega trace-audit --run-dir examples/validated_demo/D1__normal__seed7__origin0 --day 140
python -m ega counterfactual --run-dir examples/validated_demo/D1__normal__seed7__origin0 \
  --day 140 --factor budget --multiplier 0.5
python -m ega delete-evidence --run-dir examples/validated_demo/D1__normal__seed7__origin0 \
  --day 140 --artifact forecast
```

Replay rebuilds the numerical problem from the recorded snapshot, forecast samples and constraints, then re-solves. It **does not re-call the LLM or retrain the forecast model**. Multiple optimal solutions or time-limited incumbents can produce a different action; this is surfaced, not hidden. Content hashes detect local modification, not malicious rewriting of the entire audit database.

## 6. Constraint grounding, robustness and audit study

```bash
python scripts/grounding_benchmark.py --generate --output results/grounding_templates
python scripts/grounding_benchmark.py --generate --prose-only \
  --corpus examples/grounding_prose.jsonl --output results/prose_deterministic_control
# Add --llm-config configs/llm_study.local.yaml to use an actual model on the prose corpus.

python scripts/sensitivity_sweep.py --config configs/smoke.yaml --output results/sensitivity
python -m ega audit-packets --results results/my_demo --out results/audit_packets --participants 3
```

XLSX supplier carriers can be inspected using `python -m ega read-workbook supplier.xlsx --out results/workbook_cells.json`. This extracts cell values and references only; it does not implement arbitrary workbook semantics or auto-authorize their contents.

The human-audit exporter creates three explanation arms, counterbalanced assignments, a response template, and separate researcher-only labels. It **does not conduct a human study**. Do not distribute the answer key with participant packets; institutional approval, consent and expert label review are required first. The narrative arm is currently a deterministic summary, not an LLM rationale.

## 7. Repository map

```text
src/ega/
├── data/              M5 mapping, canonical panel/SQLite, synthetic data, safe XLSX values
├── quality.py         Deterministic state certificates
├── disturbances.py    Quality, demand, supply and assortment interventions
├── constraints.py     Typed rules, source checks, unit checks and template cross-checks
├── forecasting/       Seasonal/SBA, LightGBM, GRU/NB, Chronos adapter, hierarchy/MinT
├── optimization.py    SciPy/HiGHS stochastic MILP, policy calculators, independent checks
├── agents/            Seven roles, real HTTP LLM backend, typed workflow
├── autonomy.py        Quality/risk/confidence/dispersion gates and escalation urgency
├── simulator.py       True inventory, receipts, transfers, realized sales and costs
├── store.py           Content-addressed artifacts, audit chain, receipts, approved memory
├── experiment.py      Rolling origins, paired streams, baselines, study summaries
├── evaluation/        Forecast, grounding, replay, interventions, statistics, audit packets
└── cli.py             Command-line entry points
configs/               Smoke, deterministic study, LLM and foundation-model configurations
tests/                 Unit, invariant, optional-model and end-to-end tests
scripts/               Grounding, sensitivity and fixed-evidence reliability experiments
docs/                  Architecture, mathematical choices, scope, security and research guide
examples/              Controlled carriers and validated synthetic demonstration
```

## Research boundaries

M5 contains historical sales, not uncensored latent demand or actual inventory. Supply, stock, contracts and failures are simulated. No private calibration telemetry was supplied, so defaults are prominently **synthetic and uncalibrated**. The calibration command accepts only already-pooled incident categories/durations with an explicit exposure denominator; it cannot infer real platform rates from the dissertation text.

The first-stage solver chooses today's purchases/transfers, with scenario-specific inventory recourse over a horizon. It uses lost sales, not a backorder model. Full multistage purchasing, exact DeepAR/TFT/Moirai reproduction, automated source-repair approval, size-curve buying, full enterprise integration and actual human research remain extensions. See [the scope matrix](docs/IMPLEMENTATION_MATRIX.md), [mathematical assumptions](docs/METHODOLOGY.md), and [security](docs/SECURITY.md).
