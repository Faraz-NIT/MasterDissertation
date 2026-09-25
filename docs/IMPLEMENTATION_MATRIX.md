# Dissertation-to-code implementation matrix

This file distinguishes a runnable research implementation from a completed empirical dissertation. The original specification is retained in `docs/dissertation_source.html`; it is not silently replaced by the implementation.

| Dissertation element | Implementation and status |
|---|---|
| Canonical M5 model | Implemented: catalog SQL entities, NumPy/memory-mapped demand/price panel, canonical typed observations and daily artifact snapshots. Runtime inventory remains in the simulator; not every artifact is mirrored into every SQL table. |
| True versus observed inventory | Implemented: physical state stays inside the simulator; faults mutate copies. The evaluator/reference uses uncorrupted state and known physical arrival dates. Agents can observe missing arrivals and recorded defaults. |
| Fourteen state-quality classes | Thirteen explicit perturbation classes; stockout censoring arises endogenously. Most state classes have dedicated checks. Missing-PO corruption requires an outstanding order. Marginal synthetic event processes, not empirical co-occurrence calibration. |
| Evidence quality scoped to each decision | Implemented at the coupled decision-batch level. A hard failure may block that entire item/store group; independent item-level gates and dynamic partitioning remain extensions. |
| LLM cannot raise quality or clear hard failure | Enforced. Triage adds evidence-linked hypotheses only. It does not autonomously repair state or reduce false-positive invariant flags. A claimed H4 improvement from semantic repair requires a separate approved-repair experiment. |
| Typed seven-role workflow | Implemented, with role-specific contracts and fixed numerical tool permissions. Forecast and constraint stages are sequential here, not concurrent. |
| Shared memory | Approved, expiring resolution records and retrieval are implemented. No learned vector-memory store, automatic incident-resolution approval, or broad episodic-memory ablation is supplied. |
| Pack, per-line/aggregate MOQ, material units | Implemented, including supplier activation and m/unit multipliers. Current material-unit vocabulary is explicit and limited; it is not a general physical-units library. |
| Supplier capacity, spend, eligibility, transfers | Implemented. Same-item, same-cluster transfers only, with delay and cost. Storage is constrained by location in each planning scenario. |
| Prose and workbook constraints | Real LLM extraction interface and field-level benchmark implemented. Deterministic `RULE` carrier cross-checks detect mismatches/omissions. XLSX reader supplies cells and rejects formulas/macros/external links. Automatic interpretation of arbitrary workbook layouts is not implemented. |
| Seasonal semantics | Eligibility/end-of-season intervention plus month-to-season rollover and cluster union helpers. No complete merchandising workbook integration or preseason buying model. |
| Size-curve packs | Not implemented in the replenishment MILP; the draft's later limitations place these outside M5-supported evaluation. |
| Forecast models | Real seasonal/SBA, LightGBM quantiles and native GRU/NB implemented and tested. Optional original Chronos-T5 adapter provided but untested against downloaded weights in the delivery environment. No TFT or Moirai implementation. |
| Hierarchical reconciliation | Coherent bottom-up scenario aggregation and all twelve M5 aggregation levels. Small-panel MinT shrinkage function provided. Default runtime does not train separate aggregate models and apply MinT to them. |
| Censoring correction | Logged past-only mean-based heuristic, not recovery of M5's unknown latent demand or a full censored likelihood estimator. |
| Stochastic optimization | Real SciPy/HiGHS MILP, first-stage purchases/transfers, scenario inventory/lost sales, expected cost and CVaR. Receding horizon, not a full multistage purchase-decision tree. |
| Infeasibility repair | Feasibility/status/gap/primal residuals recorded; infeasible/no-incumbent decisions held. No invented IIS. Automated solver-in-the-loop repair and contract-relaxation workflow remain extensions. |
| Critic | Independent action feasibility, budget/capacity stresses, injection heuristic and optional semantic review. No complete dominance proof or independent full scenario-MILP reconstruction inside the critic. |
| Autonomy | Four levels, quality/confidence/spend/deviation/stock-cover/dispersion inputs, holds, escalation urgency, separate simulated approvals. Hold budget changes urgency, not automatic release of unsafe orders. |
| Approval and execution | Simulator adapter, distinct-reviewer checks, idempotent receipt storage. No ERP integration or real identity service. Local side effects plus receipt persistence are not crash-atomic exactly-once enterprise execution. |
| B1–B10 | All policy IDs have real execution paths; B6–B10 require an actual configured LLM, and B5 requires weights. D0/D1 are explicit software controls. Baseline architectural choices are documented in README. |
| Operational metrics | Cost components, fill/service/stockouts, inventories/turns, bullwhip, harmful execution, holds, violations and LLM usage. No backorder duration, lifecycle markdown or measured CO2 model. |
| Statistical comparisons | Independent seeds, common exogenous random streams, origin-within-seed averaging, paired bootstrap, paired t/Wilcoxon results, effect sizes and Holm correction. Mixed-effects modeling and prospective power analysis are not implemented. |
| Grounding evaluation | Exact field-tuples, set match, false/omitted rules, escalation and residual eligibility metrics on controlled template/prose cases. Not a validated multilingual supplier-document corpus. |
| Trace faithfulness | Artifact hashes, input-consumption accounting, state recertification, cached-evidence numerical replay, six counterfactual factors, required-artifact deletion. Not a claim about hidden neural reasoning, and not a complete semantic context-deletion evaluation. |
| Human audit | Blinded HTML packets, three arms, counterbalancing, researcher-only labels and response scoring. No participants, ethics approval, pilot power estimates, or findings fabricated. |
| Realistic telemetry calibration | Strict input format, provenance, Wilson marginal rate intervals, duration ranges, rare-event-only handling and rate sweeps. Actual pooled telemetry and co-occurrence modeling are not supplied. |
| Full-hierarchy scalability | Memory-bounded M5 import and bounded forecast training-window sampling. Coupled MILP experiments must be partitioned manually into research-sized groups; portfolio-wide decomposition remains work. |

## Do not infer completed experiments

Passing tests means that tested code paths obey specified invariants. It does not establish H1–H8, external validity, security under all attacks, a zero harmful-order rate, model-provider determinism, or industrial readiness.
