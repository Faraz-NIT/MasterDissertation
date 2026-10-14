# Selective delegation experiment with LangGraph

This supplement compares a fixed three-role LLM workflow with a selectively delegated
workflow and the same numerical planner supplied with structured information.
All three execute through a compiled LangGraph `StateGraph`; forecasts, planner,
initial-stock rules, demand and supplier opportunities are shared within matched cases.

The graph has explicit nodes for supplier intake, supplier-model extraction, source
verification, LLM coordination or declared-policy routing, constrained planning,
action validation, LLM review and release. Conditional edges skip the supplier model
for complete declared tables, replace routine priority selection with explicit rules,
and invoke LLM review only when the selective workflow's checks fail. Failed checks
still hold the action. Review requests are recorded; no human response is simulated.

`architecture.py` defines intake, policy and release rules; `graph.py` implements the
actual orchestration. `run.py` prepares fixed inputs, develops, freezes and executes.
`analyze.py` checks every decision, model call and graph path and calculates the
registered measures. `independent_ledger.py` replays FIFO and supplier deliveries
without using the evaluated inventory simulator.

The native local-model API remains the same as the earlier experiment, with unchanged
model digest, prompts, examples and generation settings. LangGraph coordinates those
calls; it does not train the model or change its weights. External tracing is disabled.
Every call's full request and response and each decision's graph-node trace are recorded.

## Reproduction

Install `requirements.txt` in a Python environment and provide the completed earlier
study's prepared inputs under `study_results/ollama_clean_study_20261009/data`.
Run the pinned local model from that study. In a fresh output directory:

```bash
python -m pytest -q tests/test_selective_architecture.py tests/test_ollama_clean_study.py
python scripts/architecture_study/run.py prepare
python scripts/architecture_study/run.py develop
python scripts/architecture_study/check_development.py
```

The freeze step also requires the documented numerical and live LangGraph integration
receipts. The published output includes those original checks and excluded development
runs. The evaluation commands are:

```bash
python scripts/architecture_study/run.py freeze
python scripts/architecture_study/run.py run
python scripts/architecture_study/analyze.py
```

Preparation and execution refuse to overwrite an existing study. The main grid has
30 series per dataset, two seven-day windows, three scenarios, 30 fresh simulation
seeds and three workflows: 1,080 policy runs. The historical windows were previously
studied; this is a diagnostic-driven architecture experiment, not an unseen-data
confirmation or an estimate of retailer-wide effects. The structured comparator
receives already prepared data; staff effort and realised financial return are not measured.
