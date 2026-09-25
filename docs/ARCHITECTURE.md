# Architecture and extension points

```
user-provided M5 CSVs
        |
        v
canonical panel + catalog SQLite
        |
        v
closed-loop physical simulator --------> evaluator-only clean-state reference
        |
        +--> observation copy --> fault operators --> canonical Snapshot
                                                     |
                                      OBSERVE --> CERTIFY STATE
                                                     |
                                    hard fail -------+----> HOLD + urgency
                                                     |
                                 FORECAST + GROUND CONSTRAINTS
                                                     |
                                    BUILD PROBLEM / PROPOSE
                                                     |
                                    INDEPENDENT CRITIC
                                                     |
                                      AUTONOMY POLICY
                                                     |
                               SIMULATED EXECUTION / MONITOR
                                                     |
                                     content-addressed trace
```

The plus sign denotes logical independence, not concurrent execution in this version. Agents receive `Snapshot`, not `InventoryEnvironment`. Clean state, realized future demand and injected-fault labels are not passed as model inputs. Evaluator files are written after the decision.

## Typed objects

`schemas.py` contains lineage, series, inventory, purchase orders, snapshots, checks, certificates, constraints, forecasts, plans, verdicts, autonomy and receipts. Pydantic rejects unknown fields and invalid dimensions. Every numerical stage uses the same lineage tuple, including the certificate content hash. Mixing artifacts from different snapshots requires an explicit new observation/reconciliation cycle.

The code is organized into seven roles, rather than seven independent models doing arithmetic. `agents/roles.py` supplies reconciliation, demand forecast, supplier constraints, optimization, risk/critic, and execution/monitoring; `agents/orchestrator.py` supplies the orchestration/autonomy role. Deterministic tools own numerical computations. The LLM is an explicitly optional semantic backend.

## Artifacts and events

Each object is canonical JSON keyed by SHA-256. Event records carry an input reference list, an output reference, the decision identifier, and a chained event hash. Earlier proposals remain as immutable objects/events when a later hold replaces the selected action. `trace_index.json` maps decision days to final trace hashes. Execution receipts reference action hashes and idempotency keys.

`store.py` is a local research persistence layer. It is not authenticated WORM storage, a transactional ERP outbox or an identity provider. Never promote it to production merely by adding an HTTP order endpoint.

## Extending forecasting

Implement `fit(panel, train_end)` and `predict(snapshot, horizon, scenarios, seed)`. `train_end` is exclusive. Return a `Forecast` with `[scenario, series, horizon]` samples and provenance. Register the backend in `forecasting/core.py`. Add no-leakage and forecast-shape tests. Before changing B3/B4, either document the new exact model or use a new policy identifier; do not leave literature baseline names unchanged while swapping a proxy silently.

## Extending constraints

Add the parameter to the typed schema, units/ranges/source validation, numerical problem builder, optimizer, independent action checker and stress tests together. A model-extracted text field alone does not become an executable rule. Supplier documents are configured trusted sources, not proof of their contents' meaning; unfamiliar and ambiguous clauses require review. `RULE` carriers can be independently cross-checked; arbitrary prose cannot.

## Extending telemetry

Use already anonymized pooled incident counts/durations and a defensible exposure denominator. Raw retailer IDs, customer records or contracts must not enter public experiments or this repository. A richer correlated fault process needs a documented empirical co-occurrence model and its own tests. The supplied calibration adapter only estimates marginal onset intervals.

## Run outputs

- `resolved_config.json`, `environment.json`: configuration and installed versions.
- `summary.csv`, `study_summary.json`, optional `paired_comparisons.csv`: outcomes and paired comparisons.
- `POLICY__SCENARIO__seedN__originK/daily.csv`: daily actions, state quality, costs, service, harms, tokens and timing.
- `detection.csv`: class/day injection and detection flags, including false alarms.
- `run_manifest.json`: seed, reference definition, layer parameters and source provenance.
- `trace_index.json`, `artifacts/objects/`, `artifacts/audit.sqlite`: replayable evidence and chain.
- `report.html`: offline, lineage-first inspection.

Runtime `.npy` files are opened without pickle. Locally saved neural checkpoints should be treated as trusted artifacts only. No arbitrary code from supplier text or workbook cells is executed.
