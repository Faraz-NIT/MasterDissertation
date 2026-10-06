# Mathematical and experimental choices

## Data boundary

`Panel` owns historical M5 sales, prices and calendar features. The simulator treats historical sales as an exogenous demand proxy; it cannot reconstruct demand that M5 never recorded. At decision day t, `Snapshot.history_days` is strictly less than t. Eligibility is based on the first already-observed sale, never the first future sale. Known future calendar features may be used; future realized sell prices are not supplied to a forecaster.

Forecast models fit only before the warm-up boundary. During the evaluation window their parameters are frozen, but predictions consume the current observed sales history. The final split/origins are explicit configuration, not an automatically optimized train/test split.

Inventory is initialized from trailing mean/dispersion plus seeded pipeline orders. All policies receive the same warm-up policy. During the policy evaluation they develop different endogenous inventories and observed sales histories. Random draws are keyed by seed, day, series and event class rather than by a policy-dependent call count. Thus comparable exogenous shocks do not drift when policies place different numbers of orders.

## State certificate

Every observation exposes a canonical catalog, stock, purchase orders, historical sales, prices, stage timestamps, source/load manifests and an independent movement ledger. Warn weights reduce q from one; any hard failure sets q to zero. The movement ledger is intentionally a **strong, clean redundant-source assumption**: faults corrupt the observed stock without corrupting the independent ledger. This makes some anomalies easier to detect than in real operations. Sensitivity to faulty/unavailable redundant sources is an additional experiment, not an inferred result.

The certificate covers the decision batch. It does not grant per-item autonomy within a failed coupled batch. A successful pipeline timestamp does not erase source completeness or content-reuse failures. A model can append a hypothesis with allowed evidence references, but has no capability to mutate stock or the numeric certificate.

## Optimization

The MILP includes integer pack multipliers, line activation, supplier-order activation, today's purchases, integer same-cluster transfers, and scenario-specific nonnegative inventory and lost-sales variables. Binary complementarity prevents reporting lost sales while holding available stock. The inventory balance is enforced at each horizon period, including current pipeline receipts, purchase arrival scenarios, outgoing transfers and delayed incoming transfers.

Supplier aggregate minimums are either unit-valued or material-valued. A material MOQ uses a per-item m/unit multiplier inside the supplier sum, not independent item-wise rounding. Budget includes purchases, fixed supplier charges and transfer costs. Storage is location-specific per scenario-period. Planning only orders today; tomorrow the system re-solves with updated evidence. There are no secretly available future purchase decisions.

The objective is:

```
E[procurement + supplier fixed charges + transfers + holding + lost-sales penalty]
+ lambda * CVaR_alpha(scenario total cost)
```

**CVaR convention:** this code uses alpha as a confidence level; `alpha = 0.95` means the worst 5% tail. The draft's phrase “worst alpha fraction” is therefore interpreted explicitly as tail mass `1 - alpha`, not followed literally. Empirical CVaR uses fractional scenario mass when necessary.

`scipy.optimize.milp` supplies the HiGHS MIP status, gap and bound. A returned vector must also pass finite-value, primal-residual and integrality checks. A timeout with an acceptable incumbent is recorded as feasible but not optimal. No infeasible solution is relabeled feasible; no contract is silently relaxed. An IIS/repair engine is not implemented.

The planning model omits expedite, backorders, age-based spoilage and markdowns. Physical storage overflow can incur a simulator spoilage cost. Supply can cancel, partially fill or delay orders after commitment; this is distinct from a proposed-order feasibility violation. Partial fulfillment is not constrained to be a full pack, because the pack rule applies to the committed purchase request, not necessarily to a disrupted shipment.

## Policies and ablations

B1/B2 enforce line-level pack, minimum and eligibility rules but do not optimize all portfolio couplings. Any aggregate/budget violations are measured rather than silently repaired. B3/B4 share the native deep model and numerical optimizer. B6–B10 share those tools; B6 uses a generalist extraction/tool-request role, B7 shares free-form role messages, B8 removes the critic, B9 removes evidence-dependent autonomy, and B10 includes it.

B9 can optimize against a wrong state even if the critic finds the plan internally consistent. Recognized deterministic source-template mismatches still cause escalation in all variants. A critic-veto cannot become a model-approved pass. The two demonstration policies use the seasonal model so the offline run needs no optional ML dependency.

The LLM triage path only changes descriptive hypotheses and possible vetoes/escalations; it does not clear failed invariants. Demonstrating lower false holds from semantic state repair requires an additional approved, evidence-producing reconciliation procedure. This restriction must be reflected when interpreting B4 versus B10.

## Autonomy and holds

The gate considers q, minimum extraction confidence, procurement/transfer spend, extra spend beyond a deterministic order-up-to baseline as a share of budget, resulting stock cover and forecast dispersion. Missing/hard-failed evidence is advisory/hold. Riskier otherwise valid recommendations require approval, including two distinct reviewer labels above the configured high-spend threshold.

The optional `approval_mode: oracle` means **simulated reviewers**, not real people. After a delay, current true constraints are rechecked. The source-data hard failure is never overridden. The hold budget only escalates urgency; it is not permission to auto-approve stale evidence. Holding's actual service/cost impact is measured through closed-loop lost sales and costs, but an independently identified causal hold-cost decomposition is not computed.

## Clean-state reference and harmful execution

The simulator's reference optimizer uses the policy's forecast family on clean evidence and the true current constraints/arrival dates. It does not see future realized demand and is not a globally optimal dynamic-programming oracle. A positive executed order/transfer is marked harmful if it violates a true hard constraint or differs from that reference beyond configurable absolute/relative quantity tolerances. A nonexistent reference incumbent is marked unavailable, not a zero-order oracle.

Harmful-execution rate divides by nonzero executed decisions. A policy that holds everything can appear safe on this metric; cost, service, held decisions and escalation penalties must be reported alongside it. Within-run daily CVaR is descriptive. The study summary separately computes mean and CVaR over independent replication totals; do not interchange the two.

## Forecast and trace metrics

WRMSSE uses the twelve aggregation levels, trailing training revenue weights, and scales after leading-zero trimming. Constant-scale nodes are excluded without renormalization and their missing weight is reported. A subset score is not the published full-M5 benchmark score. Hierarchical uncertainty scores in the backtest aggregate sample paths first, then take quantiles; summing marginal quantiles would generally be invalid.

MinT shrinkage is available only as a small-panel utility. Clipping negative reconciled bottom values and reaggregating preserves coherence, but is not an exact constrained nonnegative-MinT optimizer.

Counterfactuals alter one logged numerical factor. Binding integrality, fixed charges and shared capacity mean that action quantities need not be monotonically responsive to every intervention. No action change under a nonbinding constraint is not by itself unfaithfulness. Required-artifact deletion tests fail-closed reconstructability, not whether a particular prose token causally influenced a model.

Replay is cached-evidence tool replay. It rebuilds from saved observation/forecast/constraint artifacts; it does not require the original CSVs, live provider or model download. Forecast re-training and LLM re-generation are distinct experiments. Provider seeds and revision names must not be treated as guarantees of identical outputs.
