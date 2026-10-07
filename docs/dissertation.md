# Evidence-Gated Autonomy for Retail Replenishment: A Constraint-Grounded LLM Multi-Agent System with Verifiable Decision Traces

**A Research Dissertation (third draft, October 2026)**

**Keywords:** large language model agents; multi-agent systems; autonomous inventory replenishment; inventory record inaccuracy; data quality; probabilistic forecasting; stochastic optimization; supply-chain planning; decision trace; explainability; graded autonomy; human oversight

**Document lineage**

- **Version:** v3, third draft
- **Date:** 2026-10-06
- **Supersedes:** v2 draft (2026-09-15)
- **Evaluation data:** M5 retail hierarchy only. Inventory, suppliers, contracts, costs and data faults are simulated.
- **Implementation:** the evidence-gated-replenishment research repository; frozen configurations and result folders are listed in Appendix B.
- **Change record:** Appendix A

---

## Abstract

Inventory replenishment is conventionally split across organizational silos: demand forecasting, policy calculation, supplier constraint review, and purchase-order execution. Tool-using large language model (LLM) agents promise a coordination layer across these silos, but the published evidence rests on stylized environments in which the inventory state is assumed to be correct and constraints arrive as clean parameters. The inventory-record-inaccuracy literature shows that the first assumption is false in most retail chains, and the data-engineering literature shows that batch integration pipelines add silent failure modes of their own. When decisions are automated, a wrong state no longer produces a wrong screen for a human to doubt. It produces a purchase order.

This dissertation treats the quality of the evidence behind a replenishment decision as a decision variable. It proposes, implements, and evaluates an LLM multi-agent system in which state reconciliation and constraint grounding are first-class, verified stages, and in which the autonomy granted to each decision is a policy over measured evidence quality, constraint confidence, and decision risk. The language model translates supplier documents into typed, unit-checked constraints, triages data-quality anomalies into evidence-linked hypotheses, routes the numerical decision, and reviews the proposal. Arithmetic feasibility, constraint satisfaction, and state validity are established by deterministic code and solver certificates, never by the model's prose. Every recommended quantity is linked, through a content-addressed decision trace, to its data lineage, forecast distribution, constraint set, solver certificate, critic verdict, and execution receipt, and can be replayed from cached evidence.

The system was built as a runnable research implementation and evaluated on the public M5 retail hierarchy inside a closed-loop lost-sales simulator surrounded by three versioned disturbance layers: a supply and constraint layer, an assortment eligibility layer, and a state-quality perturbation layer with thirteen fault operators derived from the literature and from the mechanics of batch integration. The perturbation rates are explicitly synthetic and uncalibrated. The research followed a staged route: software validation on synthetic data; import of M5 and training and backtesting of four forecasting models; pilots of the deterministic baselines; calibration of the autonomy gate on a window disjoint from every test window, which exposed an unstable deviation measure and led to a redesigned and frozen gate; real-LLM experiments with an open-weight 120-billion-parameter model; a 30-seed LLM study sized to a fixed budget; and a frozen 30-seed deterministic study that was in progress at the time of writing.

The 30-seed LLM study asked the one question only an LLM arm can answer: can the gated system replenish safely from supplier documents written in prose, which the deterministic parser cannot read? Paired over seeds, the full system reproduced the decisions that the deterministic pipeline makes from machine-readable rules (cost difference of 1.0 and 0.2 dollars per run in its favour, identical fill rate, zero harmful executions), extracted 9,504 of 9,540 constraint fields exactly, invented none, and escalated every omission before the solver ran. The same agents without the per-decision gate executed on corrupted stock data in the fault scenario, with 0.6 harmful executions per run and a cost 4.4 times higher. A hostile supplier note that reached the model unscreened was flagged and escalated in 45 of 45 decisions. Thirty replications of one decision with fixed evidence produced one action. The gate calibration showed that the binding design problem of evidence-gated autonomy is not the cap but the hold-release rule: a held catch-up order that is merely dropped is re-proposed forever, and the primary configuration therefore models delayed review explicitly. The pilots of the deterministic baselines are descriptive, the human audit study is designed but not conducted, and the stage-1 deterministic study is incomplete. Within those limits, the dissertation contributes an architecture, a benchmark, an evaluation protocol, and controlled evidence that autonomy earned per decision from verifiable evidence is implementable, auditable, and safer than fixed autonomy under degraded state.

---

## Chapter 1: Introduction

### 1.1 Replenishment as a Sequential Decision under Uncertainty

Inventory replenishment is a sequential decision problem under pervasive uncertainty. A planner infers future demand from noisy and often censored sales history, reconciles on-hand and pipeline inventory across several systems of record, models uncertain replenishment lead times, respects a web of supplier, assortment, and budget constraints, and then selects order quantities whose effects unfold over multiple periods and echelons. The costs of error are asymmetric. Excess stock ties up capital and, in seasonal retail, ends in markdowns. Insufficient stock loses sales and customers.

Classical inventory theory supplies robust policies for stylized settings. Clark and Scarf (1960) established optimality results for serial multi-echelon systems, and later texts systematized base-stock, (s, S), and stochastic dynamic-programming approaches (Zipkin, 2000). These methods remain foundational because they produce feasible and interpretable control rules under known assumptions. Enterprise environments routinely violate those assumptions through nonstationary and intermittent demand, promotions, seasonal assortments with short lifecycles, supplier contracts with coupling constraints, and supply disruptions.

### 1.2 Two Gaps: Semantic and Evidential

Modern forecasting and optimization tools scale to large assortments. Deep probabilistic models such as DeepAR and the Temporal Fusion Transformer produce demand distributions for thousands of series at once (Salinas et al., 2020; Lim et al., 2021), and stochastic mixed-integer programming can turn those distributions into order quantities subject to complex constraints. Yet two gaps separate these tools from executed orders.

The first gap is semantic. Business rules arrive in heterogeneous, unstructured forms: supplier emails announcing temporary capacity cuts, contract clauses stipulating minimum order quantities (MOQs) and pack integrality, seasonal assortment workbooks that decide which product may be shipped to which store, promotion calendars, and planner exceptions grounded in tacit knowledge. Translating these into a formulation the solver can consume remains manual, and infeasible formulations require scarce operations-research expertise to repair (Ao, Simchi-Levi, & Wang, 2026). Most of the LLM-agent literature on supply chains addresses this gap.

The second gap is evidential, and it is the one this dissertation brings to the foreground. The inventory position, open-order pipeline, and sales history that any optimizer consumes are themselves the output of data pipelines that integrate e-commerce platforms, enterprise resource planning (ERP) systems, warehouse management systems (WMS), point-of-sale exports, spreadsheet drops, and data warehouses. Those pipelines fail in specific, recurring, and often silent ways. Inventory record inaccuracy is a well-documented phenomenon with large operational cost (Raman, DeHoratius, & Ton, 2001; DeHoratius & Raman, 2008; Kang & Gershwin, 2005), and the batch integration layer adds failure modes of its own (Sculley et al., 2015; Breck et al., 2019). When decisions are automated, a wrong state no longer produces a wrong screen for a human to doubt. It produces a purchase order.

### 1.3 Why Autonomy Must Be Earned

Three propositions follow from the literature reviewed in Chapter 2 and from the analysis of how replenishment state is produced in Chapter 3. They are stated here as propositions because the dissertation is designed to test them, not to assume them.

First, the failures most likely to cause a harmful automated order originate upstream of the optimizer, in the reconciled state and in the interpretation of constraints, rather than in the optimization itself. An optimizer given a stock figure of zero for a department whose shelves are full will order confidently and wrongly, and no amount of solver quality repairs that. Kang and Gershwin (2005) showed by simulation that even small undetected discrepancies between recorded and physical stock drive disproportionate stockouts under automated replenishment, because the policy believes stock exists.

Second, a large share of these failures is detectable by cheap, deterministic invariants if the system is designed to compute them and to condition its behavior on the result. Freshness, continuity, key cardinality, referential completeness, range and ratio checks, and movement consistency are the data-quality dimensions of Wang and Strong (1996) made computable over a canonical schema, and they are the same kind of checks that the machine-learning systems literature recommends as data validation in front of any automated consumer (Breck et al., 2019).

Third, when an automated recommendation looks wrong, the useful first question is not "what was the model's reasoning" but "which data produced this, and was it complete". A natural-language rationale can be fluent and unfaithful at the same time (Turpin et al., 2023), whereas a lineage record that names the snapshot, the freshness of each table, and the invariant results can be checked. Lineage is therefore treated as the primary explanation and the first section of the decision trace.

These propositions reshape the research questions, the architecture, the disturbance model used in the simulator, and the design of the decision trace. They also determine the route the research took: the deterministic certificate and the trace were built and validated before any language model was connected, so that the contribution of the model could be measured against a system that was already safe without it.

### 1.4 The Promise and Perils of LLM Agents in Supply Chains

Tool-augmented LLM agents offer a coordination layer for both gaps. ReAct showed that language models can interleave reasoning with external tool calls (Yao et al., 2023). AutoGen extended this to configurable multi-agent conversations (Wu et al., 2023). In supply-chain optimization, OptiGuide used an LLM as a natural-language interface to an existing combinatorial optimizer rather than as a replacement for it (Li et al., 2023), and later work extended the idea to autonomous inventory management, consensus seeking, structured decision prompts with memory, and solver-in-the-loop repair of infeasible models (Quan & Liu, 2024; Jannelli et al., 2024; Yoshizato et al., 2026; Ao et al., 2026).

The perils are equally documented. Agentic LLMs display human-like biases in inventory decisions, including a pull-to-center effect (Zhao et al., 2025). Long et al. (2026) show that strong average performance can mask substantial tail risk and run-to-run instability, which they call the agent bullwhip effect, and that repeated sampling does not remove it. Chain-of-thought explanations can be fluent and unfaithful at the same time (Turpin et al., 2023; Arcuschin et al., 2025). Supplier documents and operational notes are untrusted inputs and a vector for indirect prompt injection (Greshake et al., 2023). None of this literature considers what happens when the state the agent reasons over is itself degraded.

### 1.5 Problem Statement and Scope

Existing replenishment systems optimize narrow formulations and leave semantic constraint interpretation, anomaly triage, and explanation to humans. A pure LLM agent can read natural language but is unreliable at arithmetic, hallucinates data, violates hard constraints, and varies across identical runs. Neither treats the quality of the inventory evidence as a decision variable.

The research problem is therefore threefold. Can a multi-agent architecture combine the semantic flexibility of LLM reasoning with the quantitative reliability of formal forecasting and optimization tools? Can the level of autonomy granted to a replenishment decision be tied to verifiable measures of evidence quality and constraint confidence, so that the system orders autonomously only when it is entitled to? And can a structured decision trace with data lineage provide faithful, replayable explanation sufficient for accountable autonomy?

Scope. The dissertation addresses operational replenishment for item-location-supplier combinations in a multi-period, multi-store retail setting with stochastic and intermittent demand, variable and sometimes unknown lead times, per-item and aggregate MOQs including MOQs expressed in a unit other than the order unit, pack integrality, assortment eligibility, supplier capacity, storage and budget limits, service targets, disruption events, and lateral transshipment between stores of the same cluster. Unmet demand is lost, not backordered. State-quality degradation is a first-class disturbance. Strategic network design, pre-season assortment buying, size curves, and markdown optimization are out of scope; they are not supported by the evaluation dataset. Autonomous execution is evaluated only in a simulator. No enterprise execution endpoint exists in the implementation, and none is claimed.

### 1.6 Research Questions and Hypotheses

The central question is: **Can an LLM multi-agent system whose autonomy is gated by verified evidence quality and grounded constraints produce replenishment decisions that are cost-effective, reliable, and auditable under realistic state degradation, and does its structured decision trace faithfully explain the evidence and tools that caused each action?**

The question decomposes as follows.

- **RQ1 (Performance).** How does the proposed system compare with classical policies, forecast-plus-optimizer pipelines, a rule-gated deterministic pipeline, and single-agent LLM baselines on total cost, service, stockouts, and bullwhip amplification under clean state?
- **RQ2 (Evidence gating).** Under state-quality perturbations, does conditioning autonomy on a measured data-quality signal reduce harmful executed orders relative to fixed-autonomy variants, and which degradation classes require semantic reasoning beyond deterministic invariants?
- **RQ3 (Constraint grounding).** How accurately can typed constraint extraction with unit verification handle realistic constraint forms, including aggregate MOQs, MOQs in foreign units, and assortment eligibility, when the carrier is prose rather than a machine-readable rule, and how much residual error reaches the solver?
- **RQ4 (Architecture).** Which benefits arise from role specialization, critic review, typed shared state, and episodic memory, and which coordination costs and failure modes do they introduce?
- **RQ5 (Reliability).** How often does the system violate hard constraints, produce invalid tool calls, or show high run-to-run variance under normal, disrupted, degraded-state, and adversarial conditions?
- **RQ6 (Trace faithfulness).** Do the cited lineage, forecasts, constraints, and critic findings causally support the chosen order under replay, counterfactual intervention, and evidence deletion?
- **RQ7 (Human audit).** Does a lineage-bearing structured trace reduce planner audit time and improve calibrated accept-or-override decisions, in particular the detection of decisions made on degraded state, relative to a free-form rationale?

Hypotheses. The hypotheses were fixed before the main experiments were run. Chapter 7 reports, for each, whether the evidence collected so far supports it, contradicts it, or leaves it untested.

- **H1.** A multi-agent system with formal forecast and optimization tools achieves lower expected operating cost than an LLM-only policy and service comparable to a standalone stochastic optimization pipeline under clean state.
- **H2.** The Risk and Critic Agent reduces constraint violations and high-cost tail events, at a cost in latency and tokens.
- **H3.** Typed communication and shared state reduce grounding errors and coordination variance relative to free-form agent conversation.
- **H4.** Under state-quality perturbations, evidence-gated autonomy yields a lower harmful-order rate than the same architecture with fixed autonomy and than an ungated optimizer. A rule-based gate without an LLM captures most of the benefit on failure classes detectable by single-table invariants, whereas the LLM adds value on classes that require cross-source or narrative reasoning, such as unmapped locations, historical restatements, and constraint changes announced in prose.
- **H5.** Typed constraint extraction achieves high exact-match accuracy on templated clauses and degrades on aggregate and foreign-unit forms. Unit verification and mandatory escalation on low confidence catch most residual errors before they reach the solver.
- **H6.** Structured traces score higher than free-form rationales on replay consistency, evidence completeness, contradiction rate, and counterfactual sensitivity.
- **H7.** Planners using a lineage-bearing trace audit faster and detect a larger share of decisions made on stale or incomplete state than planners given a free-form rationale.
- **H8.** Under severe demand, supplier, or state shocks, bounded autonomy with escalation outperforms unrestricted execution on safety-adjusted utility.

### 1.7 Research Route, Contributions, and Structure

The dissertation follows a design-science route in which the artifact was built first and the claims were tested against it in stages (Hevner et al., 2004). The route, documented in Section 5.11, was: software validation of the complete pipeline on synthetic data, with every decision replayed from its trace; import of the M5 dataset into the canonical data model and training of four forecasting models with rolling-origin backtests; pilots of the deterministic baselines on a 30-series panel; calibration of the autonomy gate on a window disjoint from every test window, which exposed an unstable deviation measure and led to a redesigned, re-calibrated, and frozen gate; real-LLM pilots and targeted experiments on an open-weight model served through a rate-limited free tier; a 30-seed LLM study sized to a fixed budget of twenty US dollars; and the launch of a frozen 30-seed deterministic study, incomplete at the time of writing. Each stage produced artifacts that the next stage consumed, and each configuration was frozen before its results were read.

The dissertation makes six contributions: taxonomies of state-quality failures and constraint forms derived from the literature and from the mechanics of batch integration, operationalized as perturbation operators and deterministic invariants (Chapter 3); a canonical replenishment data model and an M5 mapping onto it, so that the agents are evaluated against the interface they would face in deployment (Chapter 5); an architecture, implemented and tested, in which state reconciliation and constraint grounding are verified stages and autonomy is a policy over evidence quality (Chapter 4); a closed-loop benchmark with three versioned disturbance layers and a calibration adapter for pooled incident data (Chapter 5); a content-addressed decision trace with replay, counterfactual, and deletion tooling, and an evaluation protocol for its faithfulness (Chapters 4 and 5); and staged empirical evidence, including a 30-seed study of constraint grounding from prose and a calibration study that reframes the design of the gate (Chapters 6 and 7).

Chapter 2 reviews the literature. Chapter 3 analyses how replenishment state and constraints arise and derives the taxonomies. Chapter 4 presents the architecture as implemented. Chapter 5 describes the data, the disturbance layers, the baselines, the metrics, the statistical protocol, and the research route. Chapter 6 reports results. Chapter 7 discusses them against the research questions and hypotheses and sets out threats to validity. Chapter 8 addresses ethics, safety, and governance. Chapter 9 concludes. Appendix A records the revisions relative to the previous draft and Appendix B inventories the artifacts needed to reproduce every number in Chapter 6.

---
## Chapter 2: Literature Review

### 2.1 Inventory Control Theory and the Bullwhip Effect

Foundational inventory models formalize the trade-off between holding cost and shortage cost. Clark and Scarf (1960) established optimality for serial multi-echelon systems, and later texts systematized base-stock, (s, S), and stochastic dynamic programming (Zipkin, 2000). A central dynamic in decentralized ordering is the bullwhip effect, in which local decisions, delayed information, and forecasting errors amplify demand variability upstream. Sterman (1989) showed in the Beer Game that individually reasonable decisions produce system-level instability. Lee, Padmanabhan, and Whang (1997) attributed the effect to demand signal processing, rationing games, order batching, and price fluctuations, and Chen et al. (2000) quantified how forecasting methods and lead times interact to amplify variance. This literature motivates system-level evaluation: an agent should not be judged by one-period order accuracy alone, because unstable decisions transfer risk to suppliers and other echelons.

Long et al. (2026) show that LLM-based automation can amplify rather than mitigate these dynamics. Stochastic LLM decision-making generates order variability even when customer demand is fixed, which they call the agent bullwhip effect. Strong average performance coexists with substantial tail risk, and repeated sampling does not remove the instability, which suggests that reliability requires changing the decision policy rather than averaging over outputs. Repeated evaluation, guardrails, and risk-sensitive objectives are therefore prerequisites for any deployment.

Lateral transshipment between locations of the same echelon is a well-studied complement to supplier replenishment (Paterson et al., 2011). In multi-store retail it is a routine rebalancing instrument, and it enters this dissertation as a secondary action in the decision space because the evaluation dataset contains ten stores in three regions.

### 2.2 Inventory Record Inaccuracy, Censored Demand, and Data Quality

The replenishment literature has long recognized that the recorded inventory position may differ from the physical one. Raman, DeHoratius, and Ton (2001) documented that execution failures in stores, including inaccurate records and misplaced products, erode the value of sophisticated planning systems. DeHoratius and Raman (2008) found record inaccuracy in a large majority of audited store-item records in a retail chain, with error magnitude related to item cost, sales velocity, and distribution structure. Kang and Gershwin (2005) showed by simulation that even small undetected stock loss drives disproportionate stockouts under automated replenishment because the system believes stock exists. These results are direct evidence that the state fed to an automated replenishment policy is a risk factor in its own right.

Recorded sales are also a censored observation of demand: when an item is out of stock, demand is not observed. Estimation methods for lost-sales systems address this bias (Nahmias, 1994), and intermittent-demand forecasting has its own methods and pitfalls (Croston, 1972; Syntetos & Boylan, 2005). The public M5 dataset records sales, not demand, and contains no inventory, so censoring is an unavoidable limitation and a modeling consideration.

The information-systems literature frames data quality along dimensions such as accuracy, completeness, timeliness, and consistency (Wang & Strong, 1996) and documents its cost to the enterprise (Redman, 1998). The machine-learning systems literature adds that automated consumers of pipeline-produced data accumulate hidden dependencies on upstream processes and should be protected by explicit data validation at the boundary (Sculley et al., 2015; Breck et al., 2019). This dissertation operationalizes those dimensions as computable invariants over a canonical replenishment schema and ties them to the autonomy policy. To the author's knowledge, no published LLM-agent replenishment study models pipeline-induced state degradation as a disturbance.

### 2.3 Probabilistic, Hierarchical, and Intermittent Retail Forecasting

Inventory decisions require predictive distributions, because forecast uncertainty determines safety stock, service probability, and tail cost. DeepAR introduced global autoregressive probabilistic forecasting across thousands of related series (Salinas et al., 2020). The Temporal Fusion Transformer combines multi-horizon prediction with variable selection and attention (Lim et al., 2021). Gradient-boosted trees with quantile objectives are a strong retail baseline (Ke et al., 2017). Pretrained time-series foundation models such as Chronos and Moirai offer competitive zero-shot probabilistic forecasts (Ansari et al., 2024; Woo et al., 2024) and are included as candidates, not assumed to dominate task-specific retail models. Proper scoring rules such as the CRPS and pinball loss evaluate these distributions (Gneiting & Raftery, 2007).

The M5 competition is the natural benchmark because it contains a large retail hierarchy with intermittent item-level demand, prices, calendar effects, and promotions. Its accuracy track required 30,490 bottom-level forecasts aggregating into 42,840 hierarchical series, and its uncertainty track required nine quantiles (Makridakis, Spiliotis, & Assimakopoulos, 2022a; Makridakis et al., 2022b). Performance varied by aggregation level, and forecast combination and machine-learning features were effective. Replenishment evaluation must therefore preserve hierarchy, temporal splits, and probabilistic calibration. Coherence across store-item, store, department, and total levels is enforced through reconciliation methods such as trace minimization (Wickramasuriya, Athanasopoulos, & Hyndman, 2019) or, more simply, by aggregating sampled scenario paths bottom-up, which is coherent by construction.

In the proposed system the Demand Forecast Agent returns sampled trajectories and quantiles together with provenance, and the optimizer consumes them directly. The LLM is never asked to infer safety stock from prose.

### 2.4 Tool-Augmented LLMs and Multi-Agent Coordination

LLM agents extend a language model with memory, tools, observations, and an action loop. ReAct alternates reasoning and environment interaction (Yao et al., 2023). AgentBench and AgentBoard show that multi-turn success depends on grounding, long-horizon planning, and recovery from intermediate failures (Liu, X. et al., 2024; Ma et al., 2024). AutoGen operationalizes multi-agent conversation with configurable roles, tools, and human participation (Wu et al., 2023). More agents do not automatically mean more accuracy. Communication propagates errors, consumes tokens, and can deadlock.

Planning research supports a hybrid design. LLM+P translates natural language into a formal planning representation and delegates search to a classical planner, outperforming direct LLM planning on feasibility (Liu, B. et al., 2023). OptiGuide keeps the combinatorial optimizer and uses the LLM for scenario analysis and explanation (Li et al., 2023). Simchi-Levi et al. (2025) survey the emerging role of LLMs in supply-chain decisions and reach a similar conclusion: language models should interpret and orchestrate, while deterministic tools certify quantities and constraints. Schema-constrained structured output, now offered by most model providers, makes the boundary enforceable: the model's reply is rejected unless it parses into a declared type. The proposed architecture enforces this separation through typed state schemas, solver certificates, and deterministic state-validity certificates. Open-weight models with published weights and pinned revisions, such as gpt-oss-120b (OpenAI, 2025), make the model side of such a system reproducible in a way that proprietary endpoints do not.

### 2.5 LLM Agents for Supply-Chain and Inventory Decisions

InvAgent applied an LLM-based multi-agent system to inventory management with zero-shot reasoning (Quan & Liu, 2024). Jannelli et al. (2024) studied consensus seeking between autonomous supply-chain agents. Yoshizato et al. (2026) found that structured decision prompts and retrieval of prior cases improve adaptation in restricted scenarios. These studies motivate specialization and memory, but their environments assume correct state and parametric constraints.

AIM-Bench reports human-like biases in agentic LLM inventory managers, including pull-to-center and bullwhip-related effects (Zhao et al., 2025). OptiRepair uses solver diagnostics and explicit inventory-theory checks to diagnose and repair infeasible models (Ao et al., 2026). Its lesson for replenishment is that operational rationality should be specified as verifiable conditions rather than delegated to an LLM judge. The Critic Agent in this dissertation follows that principle and extends it to state validity: feasibility, unit consistency, inventory balance, policy limits, and data-quality invariants are all checked by code.

### 2.6 Explainability, Decision Traces, and Faithfulness

Planners need to know why a recommendation changed, and a visible reasoning trace appears to answer that need. Natural-language rationales can nevertheless be unfaithful. Turpin et al. (2023) showed that chain-of-thought explanations rationalize answers influenced by hidden biases. Arcuschin et al. (2025) found unfaithful reasoning on realistic prompts without planted bias. FaithCoT-Bench formalizes instance-level detection of unfaithfulness (Shen et al., 2025). A fluent trace is not evidence.

This dissertation defines explanation as a structured decision record. Every material claim references an immutable artifact: a snapshot version, a feed-freshness measurement, an invariant result, a forecast file, a constraint source, a solver output, a critic test, or an execution receipt. Faithfulness is operationalized through replay consistency, evidence consumption precision and recall, counterfactual sensitivity, and fail-closed deletion tests. Lineage is the first section of the trace because "which snapshot was this based on" is the question a replay must answer before any other.

### 2.7 Human–Automation Interaction and Graded Autonomy

The human-factors literature distinguishes use, misuse, disuse, and abuse of automation and documents automation bias, in which operators over-trust automated recommendations (Parasuraman & Riley, 1997). Parasuraman, Sheridan, and Wickens (2000) propose a model of levels of automation across information acquisition, analysis, decision selection, and action implementation. The graded autonomy in this dissertation follows that model, with one addition: the level is not fixed per item class but recomputed per decision from the quality of the evidence available at that moment.

### 2.8 Research Gap

The literature has established, separately, strong probabilistic forecasting, formal inventory optimization, tool-using LLM agents, early multi-agent supply-chain demonstrations, and a large body of evidence that inventory records are inaccurate. What remains missing is an end-to-end replenishment architecture that treats state quality as a disturbance, ties autonomy to verified evidence, grounds constraints of realistic form from documents rather than parameters, and evaluates operational performance, reliability, and trace faithfulness together on a public benchmark.

| Approach | Primary strength | Unresolved limitation |
| --- | --- | --- |
| Classical replenishment | Formal feasibility, mature policies | No semantic handling of changing rules; assumes recorded state is true |
| Forecast-first ML pipeline | Predictive accuracy at scale | Forecast separated from constraints, action, state validity, and explanation |
| Single LLM agent | Flexible natural-language interface | Arithmetic hallucination, constraint violations, long-horizon instability |
| Early supply-chain MAS | Specialization, negotiation, adaptation | Stylized environments; correct state assumed; limited tail-risk and faithfulness analysis |
| Inventory record inaccuracy research | Empirical evidence that state is wrong | Not connected to automated, LLM-coordinated decision-making |
| Data validation for ML pipelines | Boundary checks before automated consumers | Not connected to the autonomy of the consumer's actions |
| **Proposed system** | **Typed coordination + verified state + grounded constraints + solver + critic + evidence-gated autonomy + lineage trace** | **Validated in simulation on one public dataset; see Chapter 7** |

Table 2.1. Positioning of the proposed research.

---
## Chapter 3: Problem Analysis: How Replenishment State and Constraints Arise

### 3.1 Purpose and Method

Design-science research begins with problem awareness grounded in the environment in which the artifact will operate (Hevner et al., 2004). This chapter provides that grounding by analysis rather than by field observation. It asks two questions: by what mechanisms does the state that a replenishment optimizer consumes come to differ from the physical truth, and in what forms do the constraints on an order actually reach a planner? The answers are assembled from four sources: the inventory-record-inaccuracy and data-quality literature (Section 2.2); the published architecture of retail data integration, in which source systems are loaded by scheduled batch jobs into a shared warehouse schema; the public M5 dataset itself, whose own gaps are documented in Section 6.5; and the mechanics of batch integration, from which several failure classes follow by construction.

No proprietary retailer data, operational telemetry, or incident records were used anywhere in this dissertation. The taxonomies of this chapter are therefore design artifacts, and their validity is established in a specific sense: each failure class is instantiated as a perturbation operator in the simulator, and each is paired with a deterministic invariant that is tested for detecting it (Section 6.6). Their frequencies are not estimated. The simulator's fault rates are explicitly synthetic, and a calibration adapter is provided so that pooled, anonymized incident counts with a defensible exposure denominator can replace them when such data become available (Section 5.3).

### 3.2 The Canonical Replenishment Data Model

Replenishment reasoning needs a small set of entities regardless of the retailer. Table 3.1 lists them with the properties the design must handle. Each property is either a documented source of record inaccuracy, a structural consequence of batch loading, or a requirement of the formal problem in Chapter 4.

| Entity | Content | Properties the design must handle |
| --- | --- | --- |
| Locations | Stores, warehouses, e-commerce sites | Type, region, cluster membership used by transfer and assortment rules; a location present in a source feed may be absent from the master |
| Suppliers | Vendors, brands, own production | Spelling variants and aliases for one supplier; supplier may be unknown when an order is planned |
| Supplier products and variants | The supplier's view of a product | MOQ and its unit, per-variant consumption multiplier, pack multiple, lead time |
| Families, categories, products, variants | Product hierarchy | Placeholder products created for unknown SKUs; missing attributes |
| Prices | Selling price per variant and location | Validity windows, currency; a price can be missing while the item is selling (observed in M5, Section 6.5) |
| Orders and line items | Sales transactions | Channel, location, quantity, unit price and line total; returns and cancellations restate history |
| Transfers | Supplier purchase orders and inter-location transfers | Status, ordered and received quantity, expected arrival date often missing, non-stock lines such as fees |
| Live inventory | Current on-hand per variant and location | Overwritten by each load, therefore not replayable |
| Inventory snapshots | Immutable daily copy taken before each load | The replayable state history; gaps when a load is missed |
| Catalogs and assortments | Eligibility of products for clusters of locations | Validity by season or window; cluster unions |
| Reference data | Exchange rates, regions, settings | Missing rows break multi-currency valuation |

Table 3.1. Canonical replenishment data model and the properties the design must handle.

A shared schema has a design consequence. Because every retailer looks the same to downstream consumers, checks written once apply everywhere, and an agent can be designed against one interface. Chapter 5 loads the M5 dataset into this model so that the agents are evaluated on the interface they would meet in deployment.

### 3.3 How Replenishment State Is Produced

The state an optimizer consumes is typically produced by a scheduled batch pipeline that extracts from source systems, loads master data before facts so that foreign keys resolve, and overwrites current tables while retaining a snapshot. Several properties of such pipelines matter for autonomy, and each is a general property of batch integration rather than an observation about any particular system.

- **Cadence.** State is refreshed on a schedule, usually nightly. Between runs it ages. A decision taken at noon uses, at best, a snapshot from the previous night.
- **Stage ordering.** Locations and suppliers are loaded before products, and products before prices, inventory, and orders, so that references resolve. Facts whose keys do not resolve are dropped or parked.
- **Error isolation.** Stages are isolated so that one failure does not abort the run. A run can therefore complete with current product data and stale inventory, and both the run status and the surface data look normal. Sculley et al. (2015) describe the resulting hidden dependency as a form of technical debt that automated consumers inherit.
- **Snapshot before overwrite.** Live tables are overwritten; a snapshot taken before the overwrite is the only replayable history. A missed run leaves a hole in that history, whereas a source delivered as a rolling window heals on the next run.
- **Idempotency.** Loads are expected to be idempotent. Where they are not, a re-delivered file or a retried stage duplicates facts.
- **Validation and telemetry.** Breck et al. (2019) argue that every automated consumer should be preceded by explicit data validation, and that validation results and per-stage metrics are themselves a trace of how the data were produced.

The implications are direct. State has an age and a completeness that can be measured. A successful run is not the same as a complete state. Lineage must point to snapshot versions, not live tables. Validation results and stage telemetry, where they exist, are evidence that a decision system can reuse rather than re-derive.

### 3.4 A Taxonomy of State-Quality Failures

Table 3.2 catalogs the failure classes that follow from the mechanisms above and from the record-inaccuracy literature. Each is described by its mechanism, its effect on a replenishment decision if it goes undetected, and the deterministic signal that detects it. The thirteen numbered classes are implemented as perturbation operators in the simulator (Section 5.3); the fourteenth, censored demand, arises endogenously whenever simulated stock runs out.

| # | Failure class | Mechanism | Effect on replenishment if undetected | Detection signal |
| --- | --- | --- | --- | --- |
| 1 | Feed gap | A scheduled load is skipped for one or more days (credential rotation, source outage, network change) | State ages; snapshot history has holes; naive forecasters read missing days as zero demand | Snapshot age versus expected cadence; missing dates in the history window |
| 2 | Partial refresh | One stage fails while others succeed | Master data current, stock or orders stale, or the reverse; the state looks complete | Per-table freshness; spread of stage timestamps within a run |
| 3 | Stale-but-fresh feed | The run succeeds but the source export was not regenerated | Identical content with a new timestamp; zero movement everywhere | Content hash equal to the previous snapshot while movement was recorded |
| 4 | Duplicate ingestion | Non-idempotent load or re-delivered source file | Inflated sales and stock; open orders counted twice | Key cardinality checks on inventory, orders, and sales |
| 5 | Unit and money inflation | Per-unit price confused with line total; pack quantity loaded as units | Inflated revenue, demand, or on-hand; MOQ misjudged | Ratio invariants between line total, quantity, and unit price; range checks against the source quantity |
| 6 | Currency mislabel | Wrong currency code on a channel or missing exchange-rate row | Budgets and costs misvalued | Currency consistency per series; price coverage |
| 7 | Unmapped location | A store or warehouse exists in the source but not in the location master | Its stock and sales are invisible; phantom stockouts and misplaced demand | Source-versus-master location reconciliation |
| 8 | Identity drift | SKU recodes, label variants by case or accent, vendor aliases | Split demand histories; duplicated suppliers | Alias resolution against a known alias table |
| 9 | Placeholder master data | Unknown SKUs created as husks with missing attributes | Wrong hierarchy aggregation | Attribute completeness checks |
| 10 | Orphaned facts | Facts whose foreign key cannot resolve are dropped or parked | Silent undercount of sales or stock | Expected item-location pairs present; source row count equals loaded row count |
| 11 | Open-order integrity | Purchase orders with missing arrival date, missing supplier, corrupted lines, fee lines as stock lines | Pipeline inventory wrong in either direction | Schema and plausibility checks on open orders |
| 12 | Historical restatement | Source restates past sales through returns, cancellations, or back-dated orders | Training data shifts under the forecaster; replay mismatch | Diff of historical periods against the previous snapshot |
| 13 | Derived-field collapse | A field re-derived from incomplete in-memory state is silently zeroed, for example inventory | Mass phantom stockout followed by mass reorder | Distribution shift versus the previous snapshot combined with movement inconsistency |
| 14 | Censored demand | Sales are recorded only while stock is available (Nahmias, 1994) | True demand underestimated after stockouts | Stockout flags derived from snapshots |

Table 3.2. Taxonomy of state-quality failures and their deterministic detection signals.

Two properties of this taxonomy shape the design. First, every class is detectable by a deterministic check over the canonical schema, provided the schema exposes stage timestamps, a previous snapshot, a source row count, and an independent movement ledger. This argues for a rule-based state certificate before any LLM reasoning. Second, for several classes the check establishes that something is wrong but not what happened: an unmapped location may be a closed store or a broken key; a restated history may be a correction or a corruption. Distinguishing these requires reasoning across sources, timestamps, and operator notes, which is where a language model may add value and which is the basis of the second half of hypothesis H4.

### 3.5 A Taxonomy of Constraints as They Arrive

Constraints in the inventory literature are parameters. Constraints in operations are documents. Table 3.3 catalogs the forms the design must handle, the carrier in which each typically arrives, and the difficulty of formalizing it. Pack multiples, per-line minimums, capacity, and budget are standard in the literature (Zipkin, 2000). Aggregate minimums per supplier order, minimums expressed in a material unit such as metres of fabric with a per-variant consumption, and assortment eligibility windows are standard commercial practice in apparel and accessories sourcing and are included because they couple items and locations in ways a per-item policy cannot represent. The example clauses are illustrative.

| Constraint form | Typical carrier | Example (illustrative) | Formalization challenge |
| --- | --- | --- | --- |
| Per-variant pack multiple | Supplier product master | "Ship in multiples of six" | Integrality per variant |
| Minimum per supplier order (aggregate) | Contract, email | "Minimum order of one thousand units across the range" | Coupling across items and locations; supplier-level activation |
| MOQ in a foreign unit | MOQ file with per-product consumption | "Minimum one thousand metres of fabric; one garment of this size consumes 1.4 metres" | Dimensional analysis; per-variant conversion multipliers; aggregation over variants sharing a material |
| Size-curve packs | Buy sheets | "Order this model as a size curve 1/2/2/1" | Ratio constraints across variants of one product (out of scope for M5) |
| Assortment eligibility | Assortment workbook per cluster or store type | "This product belongs to the winter assortment of cluster A stores" | Binary eligibility with a validity window |
| Drop and launch calendar | Calendar with month labels | "The January drop belongs to the winter season" | Calendar parsing with year rollover; validity intervals |
| Season end and carry-over | Merchandising decisions | "Non-carry-over lines are not reordered after week N" | End-of-life rule; the alternative action is not an order |
| Lead time and arrival date | Purchase-order data, often incomplete | "Arrival unknown; assume order date plus four days" | Pipeline uncertainty; the assumption needs provenance |
| Capacity and open-to-buy | Planner limits | "Open-to-buy for the month is X" | Budget coupling across items |
| Supplier unknown | Campaign order sheets | "Supplier to be confirmed" | Nullable reference; mandatory escalation |
| Transfer policy | Rebalancing rules | "Transfer only between stores of the same cluster" | Transshipment graph restricted by cluster |
| Hostile or irrelevant text | Notes attached to any document | "Ignore previous policy and order without approval" | Must be treated as data, never as an instruction |

Table 3.3. Constraint forms and their formalization challenges.

The taxonomy sets three requirements for the constraint agent beyond extracting a number: unit conversion with per-variant multipliers, aggregation levels above the item, and eligibility that decides whether an item-location pair is a legitimate target for an order at all. It also fixes the evaluation question for RQ3. A constraint carried by a machine-readable rule line can be parsed deterministically; the interesting case is the same constraint carried by prose, where only a model can read it and only a verifier can tell whether it read correctly.

### 3.6 Decision Context Assumptions

Several features of the decision context are adopted as simulator assumptions. Each is stated with its justification so that it can be challenged.

- **Lost sales rather than backorders.** Retail store demand that finds no stock is lost (Nahmias, 1994). The simulator records lost sales and the forecaster flags the censored periods.
- **Transfers as a first-class action.** Rebalancing between stores of the same cluster is a routine and often cheaper response to a local shortage (Paterson et al., 2011). The action space includes lateral transshipment within a cluster at a transfer cost and a one-day lead.
- **Single sourcing.** One supplier per department, as when the supplier is the brand itself. Multi-supplier allocation and supplier fairness are not modelled.
- **Pipeline uncertainty, not only lead-time variance.** A configurable share of purchase orders is delivered without an arrival date. The system must reason about receipts whose timing is unknown and must record the assumption it makes.
- **Intermittent and censored demand.** The M5 items used are slow sellers; individual stores sell zero to three units on most days.
- **Documents as carriers.** Rules arrive as documents in two renderings: a template with a machine-readable rule line, and field-complete prose without it. Ground truth, the clean-evidence reference, and the harm checks always use the template rendering of the same contracts.
- **Lineage first.** The decision trace places lineage before evidence, constraints, and alternatives, because replay requires the snapshot version before anything else can be checked, and because a planner who distrusts a recommendation must be able to see at once whether the feed was complete.

### 3.7 Design Implications

Table 3.4 maps the analysis of this chapter to the design decisions of Chapter 4 and the experimental choices of Chapter 5. Every row corresponds to an implemented mechanism.

| Analysis | Design decision |
| --- | --- |
| State has an age and a measurable completeness; a successful run can be partial | A deterministic state certificate is computed before any forecast or proposal; autonomy is a function of it |
| Every failure class is detectable by a schema invariant; some require interpretation | A rule-based certificate runs first; the LLM triages residual anomalies into typed hypotheses and never overrides a hard failure |
| Live tables are overwritten; snapshots are the replayable history | Every artifact carries a lineage header with the snapshot version, run identifier, and certificate hash; the trace references artifacts by content hash |
| Constraints arrive with unit, aggregation, and validity semantics | The constraint schema carries unit, conversion, aggregation level, validity interval, precedence, source reference, and confidence; deterministic verification follows extraction |
| Eligibility decides whether an order is legitimate at all | Eligibility is a hard constraint in the formulation and an assortment layer in the simulator |
| Inter-location transfers are routine | Lateral transshipment within a cluster is part of the action space |
| Arrival dates are often unknown | Open orders without a date receive scenario-dependent arrival periods, and the rule used is recorded as a system default with provenance |
| Demand is censored by stockouts | Stockout flags feed a conservative censoring correction in the forecaster, and the correction is recorded |
| Replay needs lineage before anything else | Lineage is the first category of the trace and the first panel of the audit packet |
| Hostile text can reach the model | Documents are untrusted data; a deterministic screen, schema validation, source verification, the critic, and the gate stand between a note and an executed order |

Table 3.4. From analysis to design decision.

---
## Chapter 4: Methodology and Architecture

### 4.1 Research Design

The study adopts a design-science approach with controlled empirical evaluation (Hevner et al., 2004). The artifact is a hybrid multi-agent replenishment system, implemented as a tested research codebase rather than described on paper. Its utility is assessed in a closed-loop simulator through rolling-origin experiments, repeated stochastic runs, stress scenarios, state-quality perturbations, and ablations. Quantitative analysis measures cost, service, forecast quality, safety, reliability, and trace faithfulness. A human-subject component, subject to institutional approval, is designed and packaged but not conducted.

Three methodological commitments run through the chapter. Deterministic tools own every quantity: forecasts, state certificates, constraint verification, optimization, feasibility checks, and the autonomy decision are computed by code, and the language model is an optional semantic backend that interprets documents and anomalies. Every intermediate object is typed and content-addressed, so that a decision can be replayed from the evidence it cited. And every configuration that produced a reported number was frozen before the number was read; calibration used windows disjoint from every test window (Section 5.11).

### 4.2 Formal Replenishment Problem

The core is a two-stage, receding-horizon stochastic mixed-integer program with exact lost-sales dynamics. Only today's purchases and transfers are first-stage decisions; scenario-specific inventory and lost sales are recourse. The system re-solves every day on updated evidence, and no future purchase decision is available to it.

```
Indices
  i  items at locations (series)    l, l'  locations    s  suppliers
  t  periods in the horizon (T = 14)   w  demand / lead-time / arrival scenarios (W = 16)
  cl(l)  cluster of location l

True and observed state at the start of the decision day
  H[i]       true on-hand (simulator only)     Hobs[i]  observed on-hand (snapshot)
  R[i,t,w]   scheduled receipts; the arrival period of an order without a date is
             drawn per scenario and the rule used is recorded as a system default
  e[i] in {0,1}   assortment eligibility     q in [0,1]  state-quality score of the snapshot

Decisions
  x[i] >= 0, x[i] = pack[i] * k[i], k[i] integer     purchase quantity in order units
  z[i] in {0,1}  line activation      w[s] in {0,1}  supplier-order activation
  y[i,i'] >= 0 integer                 transfer from i to i' (same item, same cluster)
  N[i,t,w] >= 0,  L[i,t,w] >= 0        scenario inventory and lost sales (recourse)

Constraints
  balance        N[i,t+1,w] = N[i,t,w] + R[i,t,w] + x[i]*[t = lead(i,w)]
                              + sum_i' y[i',i]*[t = Ltr] - sum_i' y[i,i'] - D[i,t,w] + L[i,t,w]
  lost sales     L[i,t,w] > 0 only if N[i,t+1,w] = 0   (binary complementarity)
  per-line MOQ   MOQ[i] * z[i] <= x[i] <= M * z[i]
  aggregate MOQ  sum_i m[i,s] * x[i] >= MOQagg[s] * w[s],   x[i] <= M * w[s]
                 (m[i,s] converts order units to the supplier's unit, e.g. metres per unit)
  eligibility    x[i] <= M * e[i],   y[i',i] <= M * e[i]
  transfers      y[i,i'] = 0 unless cl(i) = cl(i');   sum_i' y[i,i'] <= Hobs[i]
  capacity       sum_{i of s} x[i] <= Cap[s]
  budget         sum_i c[i] x[i] + sum_s f[s] w[s] + sum trCost * y <= Budget
  storage        sum_{i at l} N[i,t,w] <= Storage[l]

Objective
  min  E_w[ purchase + fixed order + transfer + holding + lost-sales penalty ]
       + lambda * CVaR_alpha( scenario total cost ),   lambda = 0.1, alpha = 0.95
```

The CVaR term follows Rockafellar and Uryasev (2000) and penalizes the expected cost in the worst 5 percent of scenarios (alpha is a confidence level), addressing the tail-risk concerns of Long et al. (2026). The planning model omits backorders, expediting, age-based spoilage, and markdowns; the simulator charges a spoilage cost when physical storage overflows. Large portfolios must be partitioned into coupled research-sized groups; automatic decomposition is not implemented.

Two definitions complete the problem. The **autonomy policy** maps evidence to a permission level:

```
  a = pi( q, kappa, spend, dev, dos, sigma )  in  { advisory, approval, bounded, full }
    q      state-quality score of the certified snapshot
    kappa  minimum confidence of the active constraint set
    spend  purchase plus transfer plus fixed supplier cost of the proposal
    dev    extra spend beyond a transparent order-up-to baseline built on the same
           problem, as a share of the budget (gate v2, Section 6.5)
    dos    maximum projected days of supply over ordered series
    sigma  dispersion of total forecast demand across scenarios
```

The **safety-adjusted utility** used for cross-policy comparison is:

```
  U = -( E[cost] + lambda * CVaR_alpha(cost) ) - cEsc * (#held decisions) - cHarm * (#harmful executions)
      cEsc = 2,  cHarm = 100,  with cost totals per replication
```

A **harmful execution** is an executed order or transfer that, evaluated against the true state and the true constraint set known to the simulator, either violates a hard constraint (a *violation execution*) or deviates from a clean-evidence reference decision by more than a tolerance of 12 units or 50 percent per series (a *reference deviation*). The reference re-solves the same formulation with the policy's own forecast family on clean evidence and true constraints; it does not see realized demand and is not a clairvoyant oracle. The two components are reported separately because a reference deviation flags a different decision, not necessarily a wrong one. The metric is available only in simulation and is the primary outcome for RQ2.

### 4.3 Blackboard Architecture over a Canonical Schema

Specialized roles communicate through typed, versioned objects on a shared content-addressed store rather than through narrative text. Schemas, enforced with strict validation that rejects unknown fields, specify units, timestamps, confidence, provenance, and validity windows. Each object is canonical JSON keyed by its SHA-256 hash. Each stage transition writes an event that records the input references, the output reference, and a chained event hash, so that the sequence of a decision can be verified after the fact.

The agents' only view of the retailer is the canonical schema of Table 3.1, exposed as a daily snapshot. They do not read source systems, and they never receive the simulator's true state, realized future demand, or injected-fault labels. Every object carries a lineage header: snapshot version, run identifier, day, and, after certification, the hash of the state certificate under which it was produced. Objects from different snapshots cannot be combined; a mismatch is rejected before the problem is built.

### 4.4 Agents and Their Verifiable Outputs

The system is organized into seven roles. The language model is called by four of them, always with a declared output schema and never to compute a quantity. Table 4.1 lists the roles, their machine-verifiable output, and the model's bounded contribution.

| Role | Responsibility | Machine-verifiable output | What the LLM contributes (optional) |
| --- | --- | --- | --- |
| State Reconciliation and Data-Quality Agent | Runs the invariant suite over the snapshot, computes the state-quality score | State certificate: per-check outcome, evidence, weights, score | Typed hypotheses for flagged anomalies, each citing allowed evidence references; cannot change any check, the score, or the state |
| Demand Forecast Agent | Executes the trained forecasting model with censoring correction | Forecast artifact: scenario samples, quantiles, model and version, training end, correction flag | None |
| Supplier and Constraint Agent | Converts documents into typed constraints; verifies units, ranges, sources, and conflicts | Verified constraint set with issues | Extraction of constraints from documents in batches of six, with issues for anything unresolved |
| Replenishment Optimization Agent | Builds the problem and solves it with the policy calculator or the stochastic MILP | Plan: orders, transfers, objective, components, solver status, gap, active constraints | Routing of the verified specification to an allowed tool and an optional escalation reason; a request outside the allowlist is an error |
| Risk and Critic Agent | Independent feasibility check, budget and capacity stress tests, injection screening | Verdict: pass, veto, or escalate with check evidence | Semantic review citing only the independent checks; can escalate or veto, never approve past a code veto |
| Orchestrator and Autonomy Agent | Controls the workflow, applies the autonomy policy, assembles the trace | Autonomy decision with level, permission, reasons, inputs, required approvals, urgency | None |
| Execution and Monitoring Agent | Submits permitted actions to the simulator idempotently, records receipts and outcomes | Execution receipt and outcome event | None |

Table 4.1. Roles, their verifiable outputs, and the bounded contribution of the language model.

The first role is the gatekeeper of the cycle. Its certificate is computed before any forecast or proposal, and a hard failure stops the cycle in every gated policy. The orchestrator's autonomy decision is an explicit function of the certificates produced by the other roles.

### 4.5 Coordination Protocol

The cycle is sequential in this implementation: OBSERVE, CERTIFY STATE, FORECAST, GROUND CONSTRAINTS, BUILD PROBLEM and PROPOSE, VERIFY, DECIDE AUTONOMY, EXECUTE or HOLD, MONITOR.

```
observed snapshot + supplier documents
        |
   CERTIFY STATE  -------- hard failure ------->  HOLD (advisory, escalation packet, urgency)
        |
   FORECAST (trained model, censor-corrected history)
        |
   GROUND CONSTRAINTS ---- unresolved issue ---->  HOLD (escalation before any solver call)
        |
   BUILD PROBLEM / PROPOSE (order-up-to, (s,S) or stochastic MILP)
        |
   VERIFY (independent checks, stress, screen, optional semantic review)
        |
   AUTONOMY POLICY  -----> advisory | approval | bounded | full
        |
   EXECUTE (permitted) or HOLD (approval, simulated delayed review optional)
        |
   content-addressed trace, receipt, outcome
```

The orchestrator does not proceed past CERTIFY STATE in a gated policy unless the certificate has no hard failure. Candidate orders are produced only when all required typed fields are complete and carry the same lineage header. The critic cannot modify a proposal; it returns a verdict with test evidence, and a veto or escalation forces the decision to the approval level. A decision is committed only when the autonomy policy grants a level at which execution is permitted.

Coordination controls are: schema validation of every model reply with one corrective retry; a per-run call budget; a per-study spend cap enforced through a shared ledger; timeouts; waiting out provider rate limits but stopping cleanly when a daily quota is exhausted, so that a quota failure never appears as a research result; a deterministic injection screen that drops a document before any model reads it, which can be switched off only under a labelled gate version; an allowlist of numerical tools per role; and a fallback rule when the model is unavailable, which holds by default and may be configured to continue deterministically under a separately labelled effective policy. Approved resolution records with expiry are retrievable as memory for the state agent; nothing in memory can clear a failed check.

### 4.6 State Reconciliation and the Data-Quality Score

The state certificate is computed by code over the canonical snapshot, which exposes series master data, inventory rows, open orders, sales lines, price coverage, the sales history with stockout flags, per-table stage timestamps, source and loaded location lists, source and loaded row counts, the previous snapshot's inventory and hash, a movement volume, a history-revision measure, and an independent movement ledger. Seventeen checks are run, grouped by the families of Table 3.2:

- **Freshness.** Maximum table age against the expected cadence; hard failure beyond one day, warning for any lag (weight 0.20).
- **Continuity.** Missing dates or values in the history window (warning, 0.20).
- **Partial refresh.** Spread of stage timestamps within the run; hard failure beyond one day (warning otherwise, 0.15).
- **Content reuse.** Inventory content hash equal to the previous snapshot while movement was recorded (warning, 0.35).
- **Cardinality.** Duplicate keys in inventory, open orders, or sales lines (hard failure).
- **Completeness.** Expected item-location pairs present and no unknown pairs (hard failure); source row count equal to loaded count (warning).
- **Location reconciliation.** Every source location resolved in the master (hard failure).
- **Range and ratio.** Non-negative quantities in the order unit; observed stock within 5 percent of the source quantity; line total consistent with quantity and unit price (hard failure).
- **Currency and price coverage.** Currency matches the series; every series has a positive price (hard failure).
- **Identity.** Supplier aliases resolved (warning, 0.35).
- **Master attributes.** No placeholder products (hard failure).
- **Open-order integrity.** No negative, non-stock, unknown-supplier, or date-inverted orders (hard failure); unknown order or arrival dates (warning, 0.16).
- **Movement balance.** Observed stock within 10 percent or two units of the ledger's expected stock (hard failure).
- **Distribution shift.** Total stock collapsed below 15 percent of the previous snapshot while movement is inconsistent (hard failure).
- **Restatement.** Relative revision of historical rows above 5 percent (warning, 0.25).
- **Censoring.** Any stockout-flagged history cell (warning, 0.04).

Each check yields pass, warn, or hard fail together with its evidence. The score q is one minus the sum of the weights of warnings (default weight 0.12), floored at zero, and is zero for the decision if any check hard-fails. The movement ledger is a deliberately optimistic assumption: faults corrupt the observed stock but not the independent ledger, which makes several classes easier to detect than they would be without a redundant source. Sensitivity to a faulty or unavailable ledger is an additional experiment, not an inferred result.

The language model's role is bounded. When any check is not a pass, it receives the flagged checks, the stage timestamps, operator notes, the source and loaded location lists, and approved memory records, and it returns typed hypotheses, each with an explanation, evidence references drawn only from the flagged check names, a confidence, and a recommended action. A hypothesis that cites anything else is discarded. The model cannot raise q, clear a hard failure, or edit state.

### 4.7 Constraint Extraction and Verification

A constraint is a typed record with an identifier, entity, scope (series, item, supplier order, or portfolio), parameter, value, unit, conversion to the order unit, aggregation level, validity interval, precedence, source reference, and confidence. Documents arrive in one of two renderings of the same contracts. The template rendering carries a machine-readable rule line in a fixed grammar, which the deterministic parser reads exactly. The prose rendering states every field once in words, in one of two phrasings that alternate by day, and carries no rule line; the deterministic parser escalates it, so only a configured model can ground it.

The pipeline is retrieve, screen, extract, verify, and commit or escalate. Documents that fail authentication or the injection screen are removed and reported as issues. Extraction uses schema-constrained model output in batches of six documents, with the instruction to preserve values and units exactly and never to resolve conflicts silently; the documented encoding of "no conversion" is stated in the prompt so that it is not reported as an ambiguity. Verification is deterministic: every series must have pack, MOQ, unit cost, lead time, and eligibility; units must be among the known vocabulary; values must be in range; every constraint must cite a source document that exists; where a rule line is present, the extraction is cross-checked against it field by field and mismatches or omissions become issues; and any constraint below the confidence threshold of 0.9 is an issue. Any issue holds the decision before the problem is built. A material MOQ in metres combined with per-item consumption multipliers becomes a supplier-level constraint in the order unit inside the formulation; an unresolvable unit is an issue. Assumptions the system makes in the absence of data, such as the arrival rule for an order without a date, are recorded in the problem with a provenance of "system default" and a confidence, so that they appear in the trace and can be overridden.

### 4.8 Forecasting Module and Training Protocol

Four forecasting models are implemented and trained; a fifth, an adapter for the original Chronos-T5 model, is provided but requires downloaded weights and was not run.

- **Seasonal naive** (B1, D0, D1). The day-of-week pattern of the last week is the centre; scenarios add shared blocks of empirical seven-day residuals resampled from the history, which preserves cross-series error dependence.
- **Croston with the Syntetos-Boylan bias correction** (backtests only). Exponentially smoothed demand size and interval with the (1 − α/2) correction (Croston, 1972; Syntetos & Boylan, 2005); scenarios as above.
- **LightGBM quantile regression** (B2). Ten gradient-boosted models, one per quantile level, with lags at 1, 7, 14, and 28 days, rolling means and dispersion, zero-demand share, the last observed price, calendar features, and a series index (Ke et al., 2017). Each model has 150 trees of depth at most 5. Scenarios are generated by recursive inverse-quantile sampling with sorted quantiles.
- **Global autoregressive GRU with a negative-binomial likelihood** (B3, B4, and all LLM policies). A compact recurrent network with hidden size 32 over a 56-day context of scaled log sales and day-of-week harmonics, trained with Adam (learning rate 0.003) for ten epochs on up to 12,000 sampled training windows with gradient clipping, deterministic seeding, and CPU-only execution. It is a probabilistic deep baseline, not a reproduction of DeepAR or the Temporal Fusion Transformer.

Training is exclusively past-only. For each rolling origin, a model is fitted once per policy family on history strictly before the warm-up boundary, and its parameters are frozen for the evaluation window. Predictions consume the current observed history up to the day before the decision, after the censoring correction has replaced stockout-flagged and missing cells by a conservative trailing-mean estimate and recorded that it did so. Future calendar features may be used; future prices are never supplied. Every forecast artifact carries the model name, version, training end, seed, and correction flag, and samples are coherent across the hierarchy by bottom-up aggregation. Model files for each origin are saved beside the run.

Backtests (Section 6.2) score the four models on the 30-series panel at two origins over a 28-day horizon with the CRPS, a weighted scaled pinball loss, a subset WRMSSE over the twelve M5 aggregation levels, and 95 percent interval coverage; a subset score is not the published full-M5 benchmark score.

### 4.9 Optimization and Policy Tools

Three numerical tools exist. An order-up-to calculator sets each eligible series to a target at the 0.95 service quantile of lead-time demand, rounds to packs, and enforces per-line minimums and eligibility; it is the B1 policy and the transparent baseline from which the gate measures deviation. An (s, S) calculator reorders to S when the inventory position falls below s and serves B2. The stochastic MILP of Section 4.2 is solved with the HiGHS solver through SciPy (Huangfu & Hall, 2018) with a 60-second time limit, a relative gap target of 0.001, and sixteen scenarios over a fourteen-day horizon in the frozen configurations. A returned solution must pass finite-value, primal-residual, and integrality checks; a timeout with an acceptable incumbent is recorded as feasible but not optimal; an infeasible or absent incumbent holds the decision. No constraint is relaxed silently and no infeasibility repair is automated. An independent action checker, separate from the solver, re-verifies any plan against pack, MOQ, aggregate MOQ, eligibility, capacity, budget, and transfer-availability rules; the critic and the evaluator both use it.

### 4.10 Evidence-Gated Autonomy, Holds, and Approval

Four autonomy levels exist: advisory (a proposal and trace for review, no execution), approval (a planner must accept before execution), bounded (execution within configured limits), and full (reserved for high-quality evidence and small spend). The level is computed per decision from the inputs of Section 4.2 against frozen thresholds: a state-quality score below 0.70 or a hard failure, an unresolved constraint issue or confidence below 0.90, a MILP without a verified incumbent, spend above 1,500, extra spend beyond the baseline above 3 percent of budget, projected days of supply above 45, or forecast dispersion above 4 each withhold permission. Spend above 2,500 requires two distinct reviewers. With no reason to withhold, the level is full when q is at least 0.95 and spend is at most 750, and bounded otherwise. A critic veto or escalation forces the approval level, and a hold or infeasible plan forces advisory. Ablations with the gate disabled run at a fixed level with the score logged but not gated.

Holding has a cost. A hold budget of two consecutive held decisions turns subsequent holds urgent in the escalation packet; it never releases an unsafe order. Two approval modes are implemented. Under *hold*, a held plan is dropped and the next day's cycle starts afresh. Under *simulated delayed approval*, a plan at the approval level that is not a hard failure is re-checked after one day against the current true constraints by the independent action checker and, if it passes, is released by simulated reviewers whose approvals are labelled as such in every trace and event. Simulated reviewers are not people and never override a hard failure. Section 6.5 explains why the second mode is the primary configuration.

Hard controls include spend caps, the deviation cap, days-of-supply and dispersion caps, prohibition of negative, non-pack, or ineligible quantities, duplicate-execution prevention through idempotency keys, a pinned gate version in every trace, and immutable execution receipts. Escalation is mandatory for state hard failures, unresolved or low-confidence constraints, critic objections, and missing solver certificates. Supplier documents are untrusted data in every role prompt, the deterministic screen drops documents that match instruction patterns, and the only execution adapter is the in-process simulator.

### 4.11 Decision Trace, Lineage, and Replay

Every decision produces a trace object that references, by content hash, the observed snapshot, the source documents, the state certificate, the certified snapshot, the forecast, the verified constraint set, the built problem, the proposal, the critic verdict, the autonomy decision, the execution receipt, and the outcome, together with the stage list, the set of artifacts consumed by any stage, the effective policy, fallback and error records, and the model's call count, token count, and the hashes of every stored request and response. Earlier proposals that a later hold replaced remain as immutable events. Ground-truth artifacts written by the evaluator are stored separately after the decision and are never part of the agent's context.

Four tools operate on a trace. *Replay* re-certifies the recorded observation, rebuilds the numerical problem from the cited snapshot, forecast, and constraints, re-solves it, and compares the action hash; it does not re-call the model or retrain a forecast, and a held decision replays as a fail-closed hold. *Counterfactual* intervention alters one logged factor (budget, capacity, lead time, forecast level, eligibility, or the certificate's quality score) and re-solves or re-decides, reporting whether the action or the autonomy level changed. *Deletion* withholds a required artifact and verifies that reconstruction is refused. *Trace audit* computes completeness over the mandatory references, the precision and recall of cited artifacts against the artifacts that stages actually consumed, and verifies every hash. A trace is complete only if the final quantity can be recomputed from the referenced artifacts with the pinned configuration. None of these tools claims anything about the model's hidden computation; they measure the faithfulness of the record to the evidence and tools that produced the action.

---
## Chapter 5: Experimental Design and Evaluation Protocol

### 5.1 Data: The M5 Retail Hierarchy and the Panels Used

The empirical dataset is the public M5 retail dataset. It records daily unit sales of 3,049 items in ten stores across three US states, organized into three categories and seven departments, from 29 January 2011 to 19 June 2016 (1,941 days), with weekly selling prices per store-item and a calendar of events and food-assistance days (Makridakis et al., 2022a). The 30,490 bottom-level item-store series aggregate into 42,840 series across twelve levels. The uncertainty track's quantile formulation is directly compatible with safety-stock and chance-constrained replenishment (Makridakis et al., 2022b). M5 supports continuous-replenishment items with intermittent demand and observable price and calendar effects. It contains no inventory, no suppliers, no size dimension, and no seasonal assortment. Those gaps are filled by the layers of Section 5.3 and are stated as limitations where they cannot be filled.

Three panels were prepared from the evaluation file, each with a manifest recording the hashes of the three source files. Days are zero-based positions: day 1830 is M5 column d_1831 and corresponds to 2 February 2016.

| Panel | Items | Stores | Series | Used for |
| --- | --- | --- | --- | --- |
| 30-series | FOODS_1_001, FOODS_2_001, FOODS_3_001 | all ten | 30 | Forecast backtests, deterministic pilots, gate calibration, stage-1 main study |
| 10-series | FOODS_1_001 | all ten | 10 | 30-seed LLM study on prose documents (one coupled supplier portfolio) |
| 2-series | FOODS_1_001 | CA_1, CA_2 | 2 | Real-LLM pilots and stage-2 experiments within a free-tier quota |

Table 5.1. Panels prepared from M5.

The items are slow, intermittent sellers: individual stores sell zero to three units on most days, which makes stock decisions sensitive to small forecast errors. FOODS_3_001 has no sales before September 2015, when it appears in the stores, and is therefore ineligible before that date. Test windows start at day 1800 (3 January 2016) or 1830 (2 February 2016); the gate was calibrated on days 1730 to 1757 (25 October to 21 November 2015), which is disjoint from every test warm-up. The window 1700 to 1727 was also run and found unusable because M5 has no selling price for FOODS_2_001 at three stores on 22, 15, and 8 of the days 1686 to 1727 although the item sold on those days (Section 6.5).

### 5.2 Mapping M5 into the Canonical Data Model

| Canonical entity | M5 source | Mapping |
| --- | --- | --- |
| Locations | 10 stores in 3 states | Store to location; state to region; cluster equals state (4, 3, and 3 stores), which bounds transfers |
| Families, categories, products, variants | 3 categories, 7 departments, 3,049 items | Category to family; department to category; item to product with one variant |
| Prices | Weekly sell prices per store-item | Price rows forward-filled, never backfilled; a missing price remains missing and is a certificate failure |
| Orders and line items | Daily unit sales | One aggregated sales line per item-store-day |
| Calendar and events | Calendar file | Exogenous forecasting features |
| Suppliers | None | Synthetic: one supplier per department, the brand as supplier |
| Transfers, live inventory, snapshots | None | Simulator-generated after warm-up; observed through the state-quality layer |
| Catalogs and assortments | Derivable | Eligibility from each item-store's first already-observed sale; scenario interventions remove eligibility |

Table 5.2. Mapping of M5 into the canonical replenishment data model.

### 5.3 Disturbance Layers

Three versioned layers surround the demand data. All generation parameters are in the frozen configuration files and are released with the code.

**Supply and constraint layer.** Contracts are sampled per item with a seed keyed to the item: pack size from {1, 2, 6} with the per-line MOQ equal to the pack, lead time from {2, 3, 4} days, unit cost at 55 percent of the last observed selling price, and eligibility from the assortment layer. Each supplier carries a capacity of 100 units per item it serves, a fixed cost of 2 dollars per order, and, in the aggregate-MOQ scenarios, a minimum of 12 units per item served, expressed in units or, in the foreign-unit scenario, in metres with per-item consumption of 1.2 to 1.6 metres per unit. The portfolio budget is 3,000 dollars per decision. Realized supply is exogenous and keyed by seed, day, and series: each order is cancelled with probability 0.02, filled at 80 percent with probability 0.1, delayed by one day either way with probability 0.15 each and by two further days with probability 0.05, and delivered without an arrival date with probability 0.1. Scenario interventions double the pack, add three days of lead time, cut capacity to 40 percent, remove a supplier, or introduce the aggregate minimums. Contracts are rendered into their carriers: a template with a rule line and an alternating explanatory sentence, or field-complete prose in two alternating phrasings.

**Assortment eligibility layer.** Eligibility is derived from the first recorded sale per item-store using only sales before the decision day. The eligibility-change and season-end scenarios remove eligibility from every third series after the shock day. Lateral transshipment is permitted within a cluster at 0.3 dollars per unit with a one-day lead.

**State-quality perturbation layer.** The simulator keeps the true state and exposes an observed state produced by the thirteen operators of Table 3.2: the previous day's inventory and orders with aged stage timestamps and a blanked last history day; stale inventory with an older inventory timestamp only; inventory identical to the previous snapshot with its hash; duplicated inventory, order, and sales rows with doubled history; quantities scaled by the pack factor; a foreign currency on sales lines; a hidden location with its inventory removed and a manifest note; an aliased supplier; a placeholder product; a dropped inventory row; orders with supplier and arrival date removed; historical rows halved with a revision note; and inventory zeroed. In single-class scenarios the fault starts one third of the way into the window and lasts for half the window, at most five days. In the mixed-quality scenario each class has an independent Bernoulli onset per day at rate 0.025 with durations of one to five days, and the rate multiplier is swept at 0.5, 1, and 2. These rates are labelled synthetic and uncalibrated in every run manifest. A calibration adapter accepts only pooled, anonymized incident counts and durations with an explicit exposure denominator and provenance, computes Wilson intervals for marginal onset rates, and refuses to fill missing classes with invented rates; it has not been used because no such data were available.

**Demand shocks.** The promotion scenario multiplies demand by 2.5 after the shock day; the heavy-tail scenario applies Pareto-distributed multipliers to 4 percent of series-days.

### 5.4 Inventory Initialization and Simulation State

Because M5 contains sales rather than inventory, the simulator reconstructs a starting state and runs a fourteen-day warm-up. Initial on-hand stock is five days of trailing mean demand plus a safety factor of 1.65 standard deviations over that period; an initial pipeline of two days of mean demand is due in one to three days. During warm-up every policy places order-up-to orders on clean evidence, so all policies start the evaluation window from the same state. Each evaluation day the simulator receives due shipments, serves demand from on-hand stock with unmet demand lost, charges holding at 1.5 percent of unit cost per unit-day and shortage at five times unit cost per lost unit, spills stock that exceeds a location's storage as spoilage, appends the day's sales and stockout flag to the history, and writes the snapshot that the observed state is derived from. Random draws are keyed by seed, day, series, and event class rather than by call order, so that policies that place different numbers of orders face the same exogenous shocks and paired comparisons are valid.

### 5.5 Policies and Ablations

| ID | Policy or system as implemented | Purpose |
| --- | --- | --- |
| B1 | Seasonal-naive residual scenarios + order-up-to | Transparent benchmark and the gate's deviation baseline |
| B2 | Global LightGBM quantile models + (s, S) | Strong retail feature baseline with an explicit reorder policy |
| B3 | GRU negative-binomial forecast + stochastic MILP | Forecast-and-optimization benchmark without an LLM or a gate |
| B4 | B3 + deterministic state-quality gate | Whether deterministic gating alone captures the benefit, without any LLM |
| B5 | Chronos-T5 adapter + policy | Time-series foundation model; requires weights, not run |
| B6 | One generalist LLM role doing extraction, triage, and tool request, with the same tools | Whether specialized roles add value |
| B7 | LLM roles exchanging free-form messages before a validated final object | Value of typed state and schemas |
| B8 | Typed LLM roles, no critic, with gate | Safety contribution of the critic |
| B9 | Typed LLM roles + critic, fixed autonomy (gate off, score logged) | Isolates evidence-gated autonomy |
| B10 | Typed LLM roles + critic + per-decision evidence gate + trace | Proposed full system |
| D0 / D1 | Seasonal-naive MILP without / with gate and deterministic critic | Software controls that need no optional dependency; not aliases for B3 or B4 |

Table 5.3. Baselines, ablations, and controls.

B6 to B10 refuse to run without a configured model; there is no random-number stand-in. In every LLM policy the model is the open-weight gpt-oss-120b (OpenAI, 2025) served by Cerebras under a pinned revision string, at temperature zero, in JSON-schema mode with one corrective retry, a budget of 500 calls and 6,000 output tokens per call, and the hold-on-failure rule. Every request and response is stored in the artifact store.

### 5.6 Evaluation Metrics

- **Forecast quality:** CRPS, weighted scaled pinball loss, subset WRMSSE, 95 percent interval coverage and calibration error (Gneiting & Raftery, 2007).
- **Inventory and operations:** total cost and its components (purchase, fixed order, transfer, holding, shortage, spoilage), fill rate, cycle service level, stockout rate, mean inventory, inventory turns over the window.
- **Supply-chain dynamics:** bullwhip ratio of order variance to demand variance within the window; absolute action dispersion where demand is fixed (Long et al., 2026).
- **State-quality handling:** detection recall per injected class and false-alarm rate per class from the per-day detection log; harmful executions split into violation executions and reference deviations; held decisions; mean state-quality score; escalation urgency.
- **Constraint grounding:** exact field-tuple precision and recall, whole-set exact match, false (invented) constraints, omitted constraints, escalation, and residual errors reaching the solver.
- **Agentic performance and reliability:** LLM calls, tokens, schema errors, fallback decisions, latency, metered cost, distinct actions under fixed evidence.
- **Summary:** safety-adjusted utility (Section 4.2), with expected cost and CVaR computed over independent replications.

Backorder duration, lifecycle markdowns, and emissions are not implemented.

### 5.7 Trace Faithfulness Evaluation

| Metric | Operational definition as implemented |
| --- | --- |
| Completeness | Fraction of mandatory references present and hash-verified in the trace |
| Lineage correctness | Re-certifying the recorded observation reproduces the recorded certificate exactly |
| Chain validity | Every event hash in the run's audit chain verifies |
| Consumption precision and recall | Cited causal artifacts that some stage consumed, and consumed artifacts that are cited |
| Replay consistency | Rebuilding the problem from cited artifacts reproduces the problem hash and the action hash; held decisions replay as holds |
| Counterfactual sensitivity | Whether altering one logged factor changes the action or the autonomy level |
| Deletion faithfulness | Reconstruction is refused when a required artifact is withheld |
| Stability | Distinct actions across replications of one decision with fixed evidence and varied model seed |
| Human utility | Audit accuracy, time, calibration, and workload in the designed study (not conducted) |

Table 5.4. Faithfulness metrics and their implementation.

Binding integrality, fixed charges, and shared capacity mean that action quantities need not respond monotonically to every intervention, and no change under a non-binding factor is not by itself unfaithfulness. None of the metrics claims anything about hidden model reasoning.

### 5.8 Stress Tests and Robustness Scenarios

Twenty-eight scenarios are registered. Table 5.5 lists them with the experiments in which each was run; the remaining scenarios of the deterministic design are scheduled as stage 2 of the main study.

| Group | Scenario | Intervention | Run in |
| --- | --- | --- | --- |
| Baseline | Normal | Historical demand proxy, sampled contracts, no faults | All studies |
| State quality | Feed gap | Stale snapshot with aged timestamps | Pilots, main study stage 1, coverage runs |
|  | Derived-field collapse | Inventory zeroed | Pilots, LLM pilots, LLM study, main study stage 1 |
|  | Partial refresh, stale-but-fresh, duplicate ingestion, unit inflation, currency mislabel, unmapped location, identity drift, placeholder master, orphaned facts, open-order integrity, historical restatement | One operator each | Coverage runs (D0, D1); interrupted partial B1 pilot |
|  | Mixed quality | Bernoulli onsets of every class | Sensitivity sweep |
|  | Censored demand | Endogenous stockouts | All studies |
| Demand and supply | Promotion spike, lead-time shift, capacity cut, supplier failure, heavy-tail demand | Demand or contract shock after one third of the window | Coverage runs |
| Constraint semantics | Pack change, aggregate MOQ, eligibility change, season end | Contract or assortment change announced in the documents | Coverage runs |
|  | Foreign-unit MOQ | Supplier minimum in metres with per-item conversion | Pilots, main study stage 1 |
| Adversarial | Injection | Hostile note among the supplier documents | LLM pilots; stage-2 experiment with the screen off |
| Network | Transshipment | Intra-cluster transfers emphasised | Coverage runs |

Table 5.5. Registered scenarios and where each was run.

### 5.9 Human Audit Study

Subject to institutional approval, a within-subject study will present planners or graduate students with an inventory background with decision packets drawn from simulator runs. Packets include correct decisions and known-bad decisions of three kinds: decisions made on degraded state, decisions based on a wrongly extracted constraint, and decisions with a poor forecast. Three explanation formats are compared in counterbalanced order: a free-form rationale, a structured trace without the lineage section, and the full trace with lineage. Outcomes are audit time, accept-or-override accuracy, detection rate of degraded-state decisions, calibration of stated confidence, and perceived workload. The exporter produced twelve blinded cases in three arms for three planned participants, with counterbalanced assignments, a response template, and a researcher-only answer key. No participant has seen a packet; the rationale arm is currently a deterministic summary rather than a model-generated narrative, and the reference labels require expert review before use.

### 5.10 Statistical Protocol

The replication unit is the independent seed. Policies are evaluated on identical windows and common exogenous random streams. Rolling origins, where more than one is used, are averaged within seed before any comparison so that correlated windows are not counted as independent replications. The protocol requires at least thirty seeds for an inferential comparison; runs with fewer seeds are reported as descriptive pilots and labelled as insufficient in every study summary. Paired differences between a policy and the reference policy of its study are estimated with a paired bootstrap of 5,000 resamples (95 percent percentile intervals), a Wilcoxon signed-rank test, a paired t-test, and a standardized paired effect size, and the Wilcoxon p-values are adjusted across the comparisons generated in a study with Holm's procedure (Holm, 1979). Expected cost and CVaR are computed over replication totals; within-run daily CVaR is descriptive only. All seeds, prompts, model revisions, layer parameters, solver settings, and package versions are logged in each run's manifest and environment record. Mixed-effects models and prospective power analysis are not implemented.

### 5.11 The Research Route: Validation, Training, Calibration, and Freezing

The experiments were run in stages, each consuming the previous stage's artifacts and each frozen before its results were read. Table 5.6 summarizes the route.

| Stage (2026) | What was done | Output |
| --- | --- | --- |
| 23 September: software validation | Complete pipeline run on generated synthetic data: 18 demonstration runs (B1, D0, D1 across three scenarios and two seeds), 56 scenario-coverage runs (D0, D1 across all 28 scenarios), 6 trained-model runs (B2 to B4); every decision replayed from its trace; 67 automated tests | 294 simulated decisions, 108 with full replay artifacts; validation record |
| 25 September: data import | M5 files imported into the three panels with hashed manifests; day-index and no-leakage conventions fixed | Panels and manifests |
| 29 September: training and backtests | Four forecasting models trained past-only and scored at origins 1800 and 1828 over 28 days on the 30-series panel | Backtest records |
| 29 September: deterministic pilots | B1, D0, D1 on 30 series for 14 days (two seeds); B1 to B4 on 30 series for 7 days (two seeds) across normal, feed gap, derived-field collapse, and foreign-unit MOQ | Descriptive pilots; every hold on clean days traced to one gate limit |
| 29 September: first real-LLM pilot | B4 and B6 to B10 on the 2-series panel, three scenarios, one seed, within one day of free-tier quota; four prompt and tooling defects found and fixed under test | 72 LLM-backed decisions |
| 29 September to 6 October: gate calibration | B4 with the deviation cap off on two windows disjoint from every test window; the original measure found unstable; measure redesigned, re-calibrated on the same logged decisions, frozen at the 0.03 cap under a new gate version | Gate v2; calibration record |
| 5 October: stage-2 LLM experiments | Hostile note with the deterministic screen off (five seeds); 30 fixed-evidence replications of one decision; prose grounding benchmark; all resumable across daily quota stops | Stage-2 records |
| 6 October: validation of gate v2 | B4 pilot and LLM pilot repeated with the frozen cap, under both approval modes; the catch-up dynamic identified; primary approval mode decided and the harmful metric split | Repeat records; design decision |
| 6 October: 30-seed LLM study | Sized from a two-decision probe (77,000 tokens and 0.032 dollars per decision); 10 series, prose documents, B4 control, B9, B10, two scenarios, four days; 180 LLM runs under a 19-dollar cap plus 120 free template-carrier reference runs | 480 LLM decisions; 13.14 dollars metered; 4,750 calls; no model errors |
| 6 October: stage-1 main study | B1 to B4, 30 seeds, 28 days from day 1830, four scenarios, gate v2, simulated delayed approval; 480 runs as four parallel workers with checkpointed merging; in progress at the time of writing | Partial results (Section 6.13) |

Table 5.6. The staged research route.

Three rules governed the route. Nothing was tuned on a test window: the gate was calibrated on days 1730 to 1757 and its frozen value was then validated, not adjusted, on the test window. Every configuration file that produced a reported number is retained unchanged and named in Appendix B, with the gate version recorded in every trace so that runs under the retired measure cannot be mixed with runs under the frozen one. And no model result was fabricated or simulated: LLM arms stop rather than hold when a provider quota or the spend cap is reached, and the resumable drivers continue from the next unfinished run.

The compute envelope shaped the design. A 28-day MILP run on 30 series takes about twelve minutes on one core, so the 480-run stage-1 study runs as parallel workers over roughly a day. The free LLM tier allowed about one million tokens per day, bound in practice by 150 requests per hour; a B10 decision on 30 series costs about 146,000 tokens, so the 30-series, 30-seed LLM design would cost about 500 dollars at list price and was replaced by the 10-series prose design that keeps 30 seeds and asks the one question only an LLM arm can answer.

---
## Chapter 6: Results

### 6.1 The Evidence Base

Every number in this chapter is read from a result folder produced by a frozen configuration; the folders, configurations, and the commands that regenerate the tables are listed in Appendix B. Table 6.1 summarizes the experiments and their evidential status. Only the 30-seed LLM study of Section 6.11 and the completed arm of the stage-1 main study (Section 6.13) meet the inferential requirement of the protocol; everything else is a pilot and is reported descriptively. Across all folders, more than 4,500 traced decisions were produced, every audit chain verified, and the test suite stood at 75 passing tests on 6 October 2026.

| Experiment | Panel | Policies | Scenarios | Seeds | Days | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Forecast backtests | 30 series | 4 models | – | – | 28-day horizon, origins 1800 and 1828 | Complete |
| Software validation (synthetic) | synthetic | B1 to B4, D0, D1 | 28 | 1 to 2 | 3 to 6 | Complete, 294 decisions |
| M5 pilot | 30 series | B1, D0, D1 | 4 | 2 | 14 | Descriptive, gate v1 |
| B1 to B4 pilot | 30 series | B1 to B4 | 4 | 2 | 7 | Descriptive, gate v1 |
| Gate calibration | 30 series | B4, cap off | normal | 5 | 28, two windows | Complete |
| Gate v2 validation repeats | 30 and 2 series | B4; B4, B8, B10 | 4; 3 | 2; 1 | 7; 4 | Descriptive |
| First real-LLM pilot | 2 series | B4, B6 to B10 | 3 | 1 | 4 | Descriptive, gate v1 |
| Hostile note, screen off | 2 series | B4, B8, B9, B10 | injection | 5 | 4 | Descriptive, 45 note decisions |
| Fixed-evidence reliability | 2 series | B10 | one decision | 30 replications | 1 | Complete |
| Grounding benchmarks | synthetic | template parser; LLM | 6 cases each | – | – | Complete |
| Sensitivity sweep | 2 series | B1, D0, D1 | mixed quality | 1 | 4 | Descriptive |
| 30-seed LLM study on prose | 10 series | B4, B9, B10; B3, B4 reference | 2 | 30 | 4 | Complete, inferential |
| Stage-1 main study | 30 series | B1 to B4 | 4 | 30 | 28 | In progress, 62 of 480 runs |
| Human-audit packets | 30 series | – | – | – | 12 cases | Prepared, not conducted |

Table 6.1. Experiments on disk and their evidential status.

### 6.2 Forecast Training and Backtests

Each model was trained only on history before the forecast origin and scored over the following 28 days at the two origins. Table 6.2 reports means over the two origins; lower is better except coverage, whose target is 95 percent.

| Model | CRPS | Weighted pinball | Subset WRMSSE | 95 percent coverage |
| --- | --- | --- | --- | --- |
| Seasonal naive | 0.842 | 0.552 | 1.565 | 90.0 percent |
| Croston SBA | 0.637 | 0.396 | 1.316 | 94.5 percent |
| LightGBM quantile | 0.636 | 0.473 | 1.676 | 94.5 percent |
| GRU negative binomial | 0.602 | 0.423 | 1.755 | 95.0 percent |

Table 6.2. Forecast backtests on the 30-series panel.

The GRU model gives the best probabilistic score and the best-calibrated intervals, which is why B3, B4, and the LLM policies use it. Croston SBA gives the best point accuracy and the best pinball loss, a reminder that simple intermittent-demand methods are hard to beat on slow items. The seasonal naive model is clearly worst and under-covers; it is retained only as the transparent B1 policy and the warm-up policy. These are subset scores on 112 hierarchy nodes and are not comparable with the published full-M5 leaderboard.

### 6.3 Software Validation and Replay

Before any M5 experiment, the complete pipeline was run on generated synthetic data. All 108 decisions of the bundled demonstration reproduced their action hash and their state certificate exactly in cached-evidence replay, the 56 scenario-coverage runs exercised every registered scenario with every audit chain verifying, and the six trained-model runs did the same. The replay result establishes the mechanical half of H6: a decision made from typed artifacts can be recomputed from the artifacts the trace cites. In every M5 study reported below, the audit chain of every run verified.

### 6.4 Deterministic Pilots on the 30-Series Panel

Two pilots, each with two seeds, compare the deterministic policies. They were run under the retired gate v1 and are descriptive. Tables 6.3 and 6.4 report means over seeds; "harmful" counts executed decisions that broke a true constraint or departed from the clean-evidence reference beyond tolerance, with true-constraint violations in parentheses.

| Scenario | Policy | Cost | Fill rate | Days held | Harmful (violations) |
| --- | --- | --- | --- | --- | --- |
| Normal | B1 | 869 | 94 percent | 0.0 | 14.0 (0.0) |
| Normal | D0 | 1,186 | 97 percent | 0.5 | 0.0 (0.0) |
| Normal | D1 | 949 | 93 percent | 11.0 | 0.0 (0.0) |
| Feed gap | B1 | 964 | 93 percent | 0.0 | 14.0 (0.0) |
| Feed gap | D0 | 1,337 | 94 percent | 0.0 | 4.0 (3.0) |
| Feed gap | D1 | 879 | 93 percent | 11.5 | 0.0 (0.0) |
| Derived-field collapse | B1 | 1,009 | 98 percent | 0.0 | 12.5 (0.0) |
| Derived-field collapse | D0 | 1,505 | 98 percent | 0.0 | 2.5 (0.0) |
| Derived-field collapse | D1 | 922 | 93 percent | 11.0 | 0.0 (0.0) |
| Foreign-unit MOQ | B1 | 869 | 94 percent | 0.0 | 14.0 (14.0) |
| Foreign-unit MOQ | D0 | 1,261 | 96 percent | 0.0 | 0.5 (0.0) |
| Foreign-unit MOQ | D1 | 937 | 92 percent | 12.0 | 0.5 (0.0) |

Table 6.3. M5 pilot: rule versus optimizer, with and without the gate (14 days from day 1800, seeds 7 and 29, gate v1).

| Scenario | Policy | Cost | Fill rate | Days held | Harmful (violations) |
| --- | --- | --- | --- | --- | --- |
| Normal | B1 | 391 | 93 percent | 0.0 | 7.0 (0.0) |
| Normal | B2 | 388 | 80 percent | 0.0 | 5.0 (0.0) |
| Normal | B3 | 563 | 98 percent | 0.0 | 0.0 (0.0) |
| Normal | B4 | 364 | 93 percent | 6.0 | 0.0 (0.0) |
| Feed gap | B1 | 438 | 92 percent | 0.0 | 7.0 (0.0) |
| Feed gap | B2 | 458 | 72 percent | 0.0 | 2.0 (0.0) |
| Feed gap | B3 | 604 | 98 percent | 0.0 | 3.0 (2.0) |
| Feed gap | B4 | 679 | 73 percent | 6.0 | 0.0 (0.0) |
| Derived-field collapse | B1 | 732 | 93 percent | 0.0 | 5.0 (0.0) |
| Derived-field collapse | B2 | 625 | 91 percent | 0.0 | 3.0 (0.0) |
| Derived-field collapse | B3 | 1,052 | 98 percent | 0.0 | 3.5 (0.0) |
| Derived-field collapse | B4 | 679 | 73 percent | 6.0 | 0.0 (0.0) |
| Foreign-unit MOQ | B1 | 391 | 93 percent | 0.0 | 7.0 (7.0) |
| Foreign-unit MOQ | B2 | 388 | 80 percent | 0.0 | 5.0 (5.0) |
| Foreign-unit MOQ | B3 | 575 | 95 percent | 0.0 | 0.5 (0.0) |
| Foreign-unit MOQ | B4 | 461 | 89 percent | 4.5 | 0.0 (0.0) |

Table 6.4. B1 to B4 pilot (7 days from day 1830, seeds 7 and 29, gate v1).

Four observations carry forward. The gate removed every harmful execution in every scenario of both pilots: B4 and D1 executed no order that broke a true constraint or departed from the reference. The ungated optimizer kept ordering on corrupted evidence: B3 executed 3.0 to 3.5 harmful orders per seven days when the feed was stale or the stock field was zeroed, with the highest cost of any policy when stock data were corrupted. The rule-based policies B1 and B2 violated the supplier's material minimum on every executed day in the foreign-unit scenario, because they enforce line-level rules only; B1's high harmful count in the normal scenario is entirely reference deviation, reflecting that its rule differs from the optimizer that defines the reference. And the gate held too often: B4 and D1 held on six of seven and eleven of fourteen days even in the normal scenario, and B4's fill rate fell to 73 percent under faults. The traces attributed every clean-day hold to a single gate limit, the deviation cap, which prompted the calibration study.

### 6.5 Gate Calibration, Redesign, and the Hold-Release Problem

**The original measure was unstable.** Gate v1 measured deviation as the unit distance between the proposal and the order-up-to baseline divided by the baseline's units, with an uncalibrated cap of 2.5. B4 was run with the cap disabled on clean evidence in two windows disjoint from every test window, and the measure was logged on every decision. Its 95th percentile was 44.1 on days 1730 to 1757 and 5.1 on days 1700 to 1727: the measure divides by the size of the baseline order, so a baseline of a few units inflates it, and the two windows disagreed by an order of magnitude. The cap of 2.5 would have held on about 90 percent and 33 percent of clean days respectively.

**Gate v2.** The gated measure was redesigned as the extra spend of the proposal beyond the baseline's spend, as a share of the budget. It is bounded, denominated in money, and unaffected by how small the baseline order is. It was recomputed exactly from the stored problem and plan of every logged decision, so no new runs were needed to calibrate it.

| Clean-day spend deviation | Decisions | p50 | p75 | p90 | p95 | p99 | Trips at 0.03 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Days 1730 to 1757, five seeds | 140 | 0.0141 | 0.0186 | 0.0233 | 0.0274 | 0.0398 | 3.6 percent |
| Days 1700 to 1727, five seeds | 95 | 0.0069 | 0.0116 | 0.0203 | 0.0285 | 0.0344 | 3.2 percent |

Table 6.5. Distribution of the v2 deviation measure on clean evidence in the two calibration windows.

The two windows now agree. The cap was frozen at 0.03 of budget, between the 95th and 99th percentile of both windows, under the gate version string recorded in every subsequent trace. The spend, days-of-supply, and dispersion caps never tripped on clean days (95th percentiles of 92.7 dollars, 28.6 days, and 0.12) and were left unchanged.

**A real-data finding in the first window.** Days 1700 to 1727 were unusable as a calibration window because M5 has no selling price for one item at three stores on several of those days although the item sold. The price-coverage check correctly hard-failed, but a single missing price hard-fails the whole 30-series decision, so every store held and stock ran down; B4's fill rate fell to 49 to 65 percent and it held on 10.8 of 28 days. The finding is kept as evidence that even a curated public dataset contains state-quality gaps of the kind the taxonomy anticipates, and it raises a design question recorded in Section 7.3: whether one series should block a whole coupled portfolio.

**Validation on the test window exposed the hold-release problem.** Repeating B4 of the B1 to B4 pilot with the frozen cap and nothing else changed did not reduce holds: B4 held on all seven days in every scenario. The traces show why. The warm-up places order-up-to orders, so the optimizer's first decision after warm-up is a catch-up that consolidates a fourteen-day horizon into one purchase. Its extra spend was 0.054 to 0.074 of budget on day 1830 across the eight ungated B3 runs, about twice the cap, and 0.033 to 0.036 on day 1730 in the calibration window. After that first order executes, the measure settles to a median of 0.017 (95th percentile 0.038) on later days. With the cap at 0.03 and a held plan simply dropped, the catch-up is held, nothing executes, the same catch-up is proposed and held the next day, and the run never reaches steady state. The calibration window's 3.6 percent trip rate is almost exactly its five first days.

The cap is therefore a steady-state cap, and the hold-release rule decides whether steady state is ever reached. Four options were considered: keep the cap and model approval explicitly; keep the cap and accept that a system which never receives approval cannot make catch-up purchases; recalibrate including first days, which makes the deviation check nearly vacuous; or redefine the baseline so that horizon consolidation does not count as deviation. The first was adopted as the primary configuration, with the second as its ablation. Table 6.6 compares them on the pilot.

| Scenario | Approval mode | Days held | Fill rate | Cost | Harmful (violations) |
| --- | --- | --- | --- | --- | --- |
| Normal | hold (plan dropped) | 7.0 | 72 percent | 364 | 0.0 (0.0) |
| Normal | simulated delayed approval | 1.0 | 95 percent | 554 | 1.0 (0.0) |
| Feed gap | hold | 7.0 | 72 percent | 364 | 0.0 (0.0) |
| Feed gap | simulated delayed approval | 4.0 | 94 percent | 523 | 0.0 (0.0) |
| Derived-field collapse | hold | 7.0 | 72 percent | 364 | 0.0 (0.0) |
| Derived-field collapse | simulated delayed approval | 4.0 | 94 percent | 523 | 0.0 (0.0) |
| Foreign-unit MOQ | hold | 7.0 | 72 percent | 364 | 0.0 (0.0) |
| Foreign-unit MOQ | simulated delayed approval | 1.5 | 95 percent | 571 | 0.5 (0.0) |

Table 6.6. B4 with the frozen gate under the two approval modes (30 series, 7 days from day 1830, seeds 7 and 29).

With delayed review, the catch-up is released one day later after it passes the current-state checks, later days pass on their own, fill rate recovers to 94 to 95 percent, and the only "harmful" flags are distance-to-reference flags with no true-constraint violation. The same repeat on the 2-series LLM pilot behaved as intended: B4, B8, and B10 acted on every clean day, held two days under the stock-field fault and three under the hostile note, with no harmful order. Because of this finding, the harmful metric is reported everywhere as its two components, and every pilot run before 6 October is cited only for its harm and cost figures, never for its hold counts.

### 6.6 State-Quality Detection

The certificate is policy-independent, so detection can be pooled over every M5 run. Table 6.7 reports recall over injected class-days and the false-alarm rate on days when a class was not injected, from the per-day detection logs of ten studies (49,608 class-days).

| Failure class | Injected class-days | Recall | False-alarm rate |
| --- | --- | --- | --- |
| Feed gap | 175 | 100 percent | 0.27 percent |
| Partial refresh | 10 | 100 percent | 0 |
| Stale-but-fresh | 9 | 88.9 percent | 1.05 percent |
| Duplicate ingestion | 7 | 100 percent | 0 |
| Unit inflation | 6 | 100 percent | 0 |
| Currency mislabel | 6 | 100 percent | 0 |
| Unmapped location | 6 | 100 percent | 0 |
| Identity drift | 8 | 100 percent | 0 |
| Placeholder master | 6 | 100 percent | 0 |
| Orphaned facts | 6 | 100 percent | 0.34 percent |
| Open-order integrity | 6 | 100 percent | 50.2 percent (see text) |
| Historical restatement | 10 | 100 percent | 0 |
| Derived-field collapse | 387 | 100 percent | 0 |

Table 6.7. Detection recall and false-alarm rate per failure class, pooled over all M5 runs.

Every injected class was detected on every class-day except one stale-but-fresh day of nine, which is the class whose signal (an unchanged content hash while movement was recorded) is weakest when little moved. The open-order figure is not a false alarm in the ordinary sense: the check warns whenever an open order lacks an arrival date, and the supply layer delivers ten percent of orders without one independently of the fault schedule, so the warning fires on genuine missing dates and carries a weight of 0.16 rather than a hard failure. Excluding it, the certificate raised a flag on about one to six percent of normal-scenario days across studies, almost all of them the censoring warning or a missing-date warning, neither of which withholds permission by itself. Under the gate, B4 executed no harmful order in any M5 study.

### 6.7 Real-LLM Pilots

The first pilot connected the open-weight model to B4 and B6 to B10 on the 2-series panel for four days in three scenarios with one seed, within one day of free-tier quota: 72 LLM-backed decisions, no model errors, and no metered cost. Table 6.8 reports it under gate v1.

| Scenario | Policy | Cost | Days held | Tokens per run |
| --- | --- | --- | --- | --- |
| Normal | B4 | 12.8 | 1.0 | 0 |
| Normal | B6 | 12.3 | 2.0 | 52,531 |
| Normal | B7 | 1.1 | 3.0 | 179,352 |
| Normal | B8 | 12.8 | 1.0 | 39,749 |
| Normal | B9 | 11.6 | 0.0 | 55,679 |
| Normal | B10 | 12.8 | 1.0 | 55,797 |
| Derived-field collapse | B4 | 12.3 | 3.0 | 0 |
| Derived-field collapse | B6 | 12.3 | 3.0 | 26,041 |
| Derived-field collapse | B7 | 1.1 | 4.0 | 102,801 |
| Derived-field collapse | B8 | 12.3 | 3.0 | 22,160 |
| Derived-field collapse | B9 | 32.0 | 0.0 | 59,334 |
| Derived-field collapse | B10 | 12.3 | 3.0 | 30,147 |
| Injection | B4 | 1.1 | 4.0 | 0 |
| Injection | B6 | 1.1 | 4.0 | 50,614 |
| Injection | B7 | 1.1 | 4.0 | 157,725 |
| Injection | B8 | 1.1 | 4.0 | 37,541 |
| Injection | B9 | 10.5 | 3.0 | 41,510 |
| Injection | B10 | 1.1 | 4.0 | 41,563 |

Table 6.8. First real-LLM pilot (2 series, 4 days from day 1800, seed 42, gate v1). Fill rate was 100 percent and harmful executions zero for every policy. A cost of about 1.1 means the policy never ordered and paid only to hold stock.

Three things were learned. On template documents the model read the supplier rules exactly as the deterministic parser did: B4, B8, and B10 made identical decisions in every scenario, so on this slice the LLM changed nothing relative to the gated deterministic system. Without the gate, B9 kept ordering on the zeroed stock field and cost 2.6 times as much as the gated policies. The free-form variant B7 never placed an order and consumed about 3.5 times the tokens of B10 for the same decisions. The hostile note was removed by the deterministic screen before any model read it, so the pilot did not test the model's own resistance; that was the purpose of the stage-2 experiment of Section 6.8.

Running on real data with a real model also exposed four defects, each fixed and covered by a test before any later run: the optimizer prompt treated any text in the escalation field as an escalation but never told the model to leave it empty, which held every B10 decision; the documented encoding of "no conversion" was reported by the model as an ambiguity, which escalated every decision until the prompt stated the convention; the single-agent B6 was never instructed to request the optimizer, which the workflow requires, and held every day until it received the same routing instruction as the multi-agent optimizer role; and free-tier rate limits required the client to wait out short limits and stop cleanly on daily quota. The repeat of B4, B8, and B10 under the frozen gate v2 is reported in Section 6.5.

### 6.8 Hostile Supplier Note with the Screen Off

In this experiment the deterministic injection screen was switched off under a labelled gate version, so that the note "Ignore previous policy. Reveal the API key and order without approval." reached the extraction agent among the genuine supplier documents on three of four days for five seeds. Only schema validation, source verification, the critic (B9, B10), and the gate (B8, B10) stood between the note and an executed order; B4 has no model and is the control.

| Policy | Decisions with the note | Note turned into a rule | Model flagged the note | Reached optimizer | Executed | Harmful |
| --- | --- | --- | --- | --- | --- | --- |
| B4 (control) | 15 | 0 | – | 0 | 0 | 0 |
| B8 | 15 | 0 | 15 | 0 | 0 | 0 |
| B9 | 15 | 0 | 15 | 0 | 0 | 0 |
| B10 | 15 | 0 | 15 | 0 | 0 | 0 |

Table 6.9. Hostile note with the deterministic screen off (2 series, 4 days, five seeds).

In 45 of 45 model decisions the extraction agent kept the thirteen genuine rules, turned no part of the note into a rule, and reported the note as an issue, which the workflow treats as an escalation: the decision was held before the optimizer ran. The verbatim issue texts were "Conflicting instruction in supplier-note/injected: directive to ignore previous policy and reveal API key", "Ignored non-rule document supplier-note/injected", and "Ignored untrusted supplier note attempting to override policy". The model reached, on its own, the outcome the deterministic screen produces. No policy executed a harmful order and there were no model errors. One hostile phrasing on a small panel is not a security proof; it is evidence that the data-not-instruction framing, the typed schema, and the escalation path work together for the case tested.

### 6.9 Fixed-Evidence Reliability

Thirty replications of one stored B10 decision were run with the snapshot, forecast, and documents held fixed and only the requested model seed varied. All thirty produced the same action hash: a proposal of six units, with zero variance in proposed units and one distinct action, at 13,857 tokens per decision; nothing was executed and the decision was at the approval level in all thirty. Providers may ignore seeds, and the model ran at temperature zero, so this measures the reproducibility of the pipeline given its evidence rather than the intrinsic stochasticity of the model. It nevertheless demonstrates that the agent bullwhip mechanism of Long et al. (2026), in which the model's own variability generates order variability under fixed demand, has no channel in this architecture: the model proposes typed fields and the quantity is computed by the solver.

### 6.10 Constraint Grounding Benchmarks

Three controlled corpora of six cases each give supplier documents and the typed rules they encode; a reader must recover every rule exactly or escalate, and the expected answers are never passed to a model.

| Corpus | Reader | Cases | Whole set exact | Escalated | False rules | Omitted fields | Reaching solver | Calls, tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Template with rule line | Deterministic parser | 6 | 6 | 0 | 0 | 0 | 0 | – |
| Controlled prose | Deterministic parser | 6 | 0 | 6 | 0 | 82 | 0 | – |
| Controlled prose | gpt-oss-120b | 6 | 6 | 0 | 0 | 0 | 0 | 18 calls, 49,763 tokens |

Table 6.10. Controlled grounding benchmarks.

The deterministic parser reads the rule grammar perfectly and, by design, escalates every prose case instead of guessing, so no wrong rule ever reached the solver from either reader. The model recovered every field of every prose case, including the aggregate and foreign-unit minimums and the capacity cut. The corpora are small and synthetic; the 30-seed study of the next section is the test at scale.

### 6.11 The 30-Seed LLM Study on Prose Documents

**Design.** The study keeps thirty seeds and asks whether the gated LLM system can replenish safely from supplier documents written in prose, which the deterministic parser cannot read. Ten series (one item at all ten stores, forming one coupled supplier portfolio with capacity and fixed costs) are run for four decision days from day 1830 in the normal and derived-field-collapse scenarios, under gate v2 with simulated delayed approval. Three policies read prose: B4, whose parser escalates every document and therefore holds every day, is the control; B9 and B10 are the typed LLM systems without and with the per-decision gate. B3 and B4 on the template rendering of the same contracts, with the same seeds and days, are the no-cost reference: B4 on templates is the upper reference for B10 on prose, and B3 on templates the ungated reference for B9. Ground truth, the clean-evidence reference, and the harm checks use the template rendering throughout. The study comprised 180 LLM runs and 120 reference runs, 480 LLM decisions, 4,750 model calls with no errors, and 13.14 dollars of metered spend at list price, below the 19-dollar cap; a B10 decision on this panel used about 74,000 tokens and eleven calls on a normal day.

| Policy | Documents | Scenario | Cost | CVaR 95 percent | Fill rate | Days held | Executed | Harmful (violations / reference) | Utility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B4 | prose | Normal | 9.2 | 18.6 | 97.6 percent | 4.0 | 0.0 | 0.0 (0.0 / 0.0) | −19.1 |
| B9 | prose | Normal | 31.1 | 44.4 | 100 percent | 0.3 | 3.7 | 0.0 (0.0 / 0.0) | −36.1 |
| B10 | prose | Normal | 29.9 | 44.4 | 100 percent | 0.4 | 3.6 | 0.0 (0.0 / 0.0) | −35.1 |
| B3 | template | Normal | 32.1 | 48.2 | 100 percent | 0.0 | 4.0 | 0.0 (0.0 / 0.0) | −36.9 |
| B4 | template | Normal | 30.9 | 48.2 | 100 percent | 0.1 | 3.9 | 0.0 (0.0 / 0.0) | −35.8 |
| B4 | prose | Collapse | 9.2 | 18.6 | 97.6 percent | 4.0 | 0.0 | 0.0 (0.0 / 0.0) | −19.1 |
| B9 | prose | Collapse | 112.9 | 168.9 | 100 percent | 0.5 | 3.3 | 0.6 (0.0 / 0.6) | −190.8 |
| B10 | prose | Collapse | 25.5 | 42.8 | 100 percent | 2.1 | 1.9 | 0.0 (0.0 / 0.0) | −34.0 |
| B3 | template | Collapse | 127.0 | 170.6 | 100 percent | 0.0 | 3.7 | 0.8 (0.0 / 0.8) | −227.4 |
| B4 | template | Collapse | 25.8 | 42.8 | 100 percent | 2.0 | 2.0 | 0.0 (0.0 / 0.0) | −34.0 |

Table 6.11. Outcomes per run, means over thirty seeds; CVaR and utility over replication totals. "Collapse" is the derived-field-collapse scenario.

**Does reading prose cost anything?** Paired over the thirty seeds, B10 on prose differed from B4 on templates by −0.98 dollars per run in the normal scenario (95 percent bootstrap interval −1.98 to −0.19; Wilcoxon p = 0.021, not significant after Holm adjustment) and by −0.23 in the collapse scenario (−0.51 to 0.00; p = 0.11), with identical fill rates of 100 percent, zero harmful executions in both, and 0.3 and 0.1 more held days per run. The gated LLM system therefore reproduced, from prose, the decisions the deterministic system makes from machine-readable rules, at the price of an occasional extra hold.

**Does the gate matter with LLM agents?** In the collapse scenario B9, with the gate off, executed on 3.3 of four days including the two days on which the stock field was zeroed, with 0.6 harmful executions per run (all reference deviations, no true violation) and a cost of 112.9; B10 held 2.1 days, executed 1.9, and had none. Paired over seeds, B10 cost 87.4 dollars per run less than B9 (−98.1 to −76.0; Wilcoxon p < 0.0001, Holm-adjusted 0.0001), had 0.60 fewer harmful executions (−0.77 to −0.43; adjusted p = 0.0005), and held 1.6 more days (1.37 to 1.80). Relative to the prose control B4, which never orders, B9 cost 103.7 more per run (92.9 to 114.0; standardized paired effect 3.47) and B10 16.3 more (14.0 to 18.8; effect 2.37). In the normal scenario the two LLM systems did not differ (cost difference −1.18, −3.11 to 0.00; p = 0.18). The same pattern holds for their deterministic references: B3 on templates had 0.83 harmful executions per run and a cost of 127.0 in the collapse scenario against B4's zero and 25.8. B9 on prose was in fact slightly safer than B3 on templates (−0.23 harmful executions; cost −14.0, p = 0.001) because its extraction escalations held half a day per run that B3 executed.

**Extraction fidelity at scale.** Every B9 and B10 decision that reached extraction was compared field by field with the rules encoded in its prose documents. B10 extracted 9,504 of 9,540 fields exactly (99.62 percent recall) with no value or unit mismatch and no invented rule, and matched the whole rule set in 174 of 180 decisions; B9 extracted 12,648 of 12,720 (99.43 percent) with the same zero false-rule count and 228 of 240 whole-set matches. Every omission was caught by verification before the solver ran: of B10's 74 held decisions, 60 were state hard failures on the collapse days, 12 were extraction escalations (six where the model omitted one store's rules and six where it reported the absent confidence field as an issue), and two were the days-of-supply cap. B9 held 24 decisions: 18 extraction escalations and six critic verdicts. The residual error reaching the solver was zero in both systems.

**Cost of the semantic layer.** B10 used about 296,000 tokens per normal run and 153,000 per collapse run, where the two hard-fail days called the model only for triage; B9, which executes on every day, used 296,000 and 306,000. At the list price used for metering, a B10 decision cost about three cents on this panel. The 2-series pilot showed the free-form variant B7 costing 3.5 times as much as B10 for the same decisions; B7 was not included at thirty seeds.

### 6.12 Sensitivity Sweep

The mixed-quality scenario was run on the 2-series panel for four days with the synthetic fault-rate multiplier at 0.5, 1, and 2 and the hold budget at 0, 2, and 5. The hold budget changed neither cost nor the number of holds, which is as documented: it only changes how urgently a hold is flagged. Averaged over hold budgets, D1 held three days at multipliers of 0.5 and 1 and four at 2, executed no harmful order, and kept a 100 percent fill rate at a cost of 0.96, while D0 without the gate executed on every day at a cost of 25.2 and a 62 percent fill rate, and B1 cost 10.4 with a single hold. Mean state quality fell from 0.25 to zero at the doubled rate. These are stress settings on uncalibrated rates with one seed; they show the direction of the trade-off, not its magnitude.

### 6.13 Stage-1 Main Deterministic Study (In Progress)

The frozen stage-1 study (B1 to B4, thirty seeds, 28 days from day 1830, four scenarios, gate v2, simulated delayed approval) was launched on 6 October 2026 as four parallel workers with checkpointed merging. At 15:13 CEST that day, 62 of 480 runs were complete, all in the B1 arm, and the B1 normal arm was the only cell with its full thirty seeds: expected run cost 1,453.0 (standard deviation 38.7; CVaR over seeds 1,526.5), fill rate 95.1 percent, cycle service level 62.0 percent, stockout rate 1.7 percent, bullwhip ratio 1.65, no true-constraint violations, and 28.0 reference deviations per 28 executed days, which again records that the order-up-to rule differs from the optimizer that defines the reference rather than that it broke a rule. The feed-gap cell had 23 seeds (cost 1,649.8, fill 94.2 percent) and the collapse cell three. The B2 to B4 arms, the paired comparisons, and stage 2 with the remaining thirteen scenarios are pending; the study summary regenerates from the merged folder and the tables of this section are to be completed from it. No conclusion about B2 to B4 at thirty seeds is drawn in this draft.

### 6.14 Human-Audit Packets

Twelve blinded decision cases from the M5 pilot were exported in three explanation arms (narrative, structured without lineage, full lineage) for three planned participants, counterbalanced, with a separate researcher-only answer key and a response template. No participant has seen them. Institutional approval, consent, expert review of the reference labels, and replacement of the deterministic narrative by a model-generated rationale come first. RQ7 and H7 are therefore untested.

---
## Chapter 7: Discussion

### 7.1 Answers to the Research Questions

**RQ1 (performance under clean state).** The evidence is descriptive. In the pilots the optimizer-based policies achieved the highest fill rates (95 to 98 percent for B3 against 93 percent for B1 and 72 to 80 percent for B2) at a higher cost, which reflects their service target and the cost of carrying stock rather than inefficiency; under clean state B4 with simulated delayed approval matched B3's service at a similar cost. On the 10-series prose study at thirty seeds, the full system B10 and its deterministic counterpart B4 did not differ in cost or service under clean state, and neither did B9 and B3. No pure LLM policy exists in the implementation, because every LLM policy shares the numerical tools, so the "LLM-only" comparison of H1 cannot be made with this artifact; the closest evidence, that the free-form B7 never ordered and consumed 3.5 times the tokens, is one seed on two series. The stage-1 main study will provide the thirty-seed comparison of B1 to B4.

**RQ2 (evidence gating).** This is the question the collected evidence answers most clearly. In every pilot and in the thirty-seed study, the gated policies executed no harmful order on corrupted evidence, while the ungated optimizer did (B3: 3.0 to 3.5 harmful executions per seven days in the pilots; 0.83 per four days at thirty seeds) and so did the ungated LLM system (B9: 0.6 per run, paired difference against B10 of −0.60 with an adjusted p of 0.0005). All harmful executions were reference deviations, not true-constraint violations: an ungated optimizer given a zeroed stock field orders what a correctly informed optimizer would not, and that is precisely the mechanism the gate is designed to interrupt. The second half of the question, which classes require semantic reasoning beyond invariants, is unanswered: every injected class was detected by the deterministic certificate (Table 6.7), and the LLM's triage hypotheses were produced but never used to repair state or reduce holds, by design. Showing that semantic triage reduces false holds requires an approved-repair experiment that does not yet exist.

**RQ3 (constraint grounding).** On the controlled corpora the model recovered every field of every prose case, including aggregate and foreign-unit minimums. At scale, over 420 decisions and 22,260 fields, extraction precision was 100 percent, recall 99.4 to 99.6 percent, no rule was invented, and every omission was caught by deterministic verification before the solver ran, so the residual error reaching the solver was zero. The failure mode that did occur, omission of one store's rules in a batch, is exactly the one the required-field check exists for. The degradation that H5 predicted on aggregate and foreign-unit forms did not appear on these corpora; the corpora are synthetic and field-complete, and a real multilingual workbook corpus would be a harder test.

**RQ4 (architecture).** The ablations are small. On template documents the model changed nothing: B4, B8, and B10 made identical decisions, so on that carrier the LLM's roles are redundant with the parser, and the critic (B8 versus B10) had no occasion to act. On prose documents the typed roles with and without the critic were not compared at thirty seeds; B9's six critic verdicts in 240 decisions show that the critic does fire. Specialization versus a single generalist (B6) and typed versus free-form exchange (B7) were run at one seed only. The coordination cost is measurable: about 74,000 tokens and eleven calls per decision on ten series, and 146,000 tokens on thirty.

**RQ5 (reliability).** No hard-constraint violation was executed by any gated policy in any M5 run. No model call failed validation in the thirty-seed study (4,750 calls) or the stage-2 experiments. Thirty replications of one decision produced one action. The hostile note was escalated in 45 of 45 decisions when it reached the model. Run-to-run variance under normal conditions was similar across B9, B10, B3, and B4 (cost standard deviations of 6.7 to 7.6 over seeds), and the gate reduced it sharply under the fault (7.4 for B10 against 29.9 for B9).

**RQ6 (trace faithfulness).** Replay reproduced 108 of 108 validation decisions exactly, every audit chain in every study verified, and every held decision replays as a fail-closed hold. Counterfactual and deletion tooling exists and was exercised on individual decisions but not run at scale, and there is no free-form rationale arm against which to compare the structured trace, so the comparative half of H6 is untested.

**RQ7 (human audit).** Untested. The packets exist; the study does not.

### 7.2 Status of the Hypotheses

| Hypothesis | Evidence | Status |
| --- | --- | --- |
| H1 Tools beat an LLM-only policy; service comparable to a standalone optimizer | No LLM-only arm exists; B10 matched B4 and B9 matched B3 at 30 seeds under clean state | Second half supported; first half not testable with this artifact |
| H2 The critic reduces violations and tail events | B8 and B10 identical on templates at one seed; critic fired six times in 240 B9 decisions on prose | Untested at scale |
| H3 Typed state beats free-form exchange | B7 never ordered and used 3.5 times the tokens, one seed | Consistent, not established |
| H4 Gated autonomy lowers harmful orders; the rule gate captures most of the benefit; the LLM adds value on interpretive classes | B4 and B10 zero harmful executions in every study; B3 and B9 not; B10 versus B9 at 30 seeds adjusted p = 0.0005; every class detected by invariants; LLM triage never used to repair | First two clauses supported; third clause untested |
| H5 High exact match on templates, degradation on aggregate and foreign-unit forms, residual caught by verification | 100 percent precision, 99.4 to 99.6 percent recall, zero invented rules, zero residual reaching the solver; no degradation on aggregate or foreign-unit forms | Supported except the predicted degradation, which did not occur |
| H6 Structured traces beat free-form rationales on replay, completeness, contradiction, counterfactual sensitivity | 108 of 108 exact replays; chains verified; no rationale arm | Mechanical half supported; comparative half untested |
| H7 Lineage-bearing traces improve planner audit | Packets prepared, no participants | Untested |
| H8 Bounded autonomy with escalation beats unrestricted execution on safety-adjusted utility under shocks | Collapse scenario at 30 seeds: B10 −34.0 versus B9 −190.8; B4 −34.0 versus B3 −227.4 | Supported for the state-quality shock tested |

Table 7.1. Hypotheses and their evidential status.

### 7.3 What the Gate Calibration Changed

The calibration study is the most consequential methodological result of the dissertation, because it reframed what evidence-gated autonomy has to get right. The original deviation measure, a unit ratio, was both uncalibrated and unstable, and under it the pilots overstated holds; a measure in money as a share of budget was stable across windows and could be frozen honestly. But freezing the cap revealed that a cap on departure from a baseline is a steady-state instrument. The first decision after a hand-over from a rule-based warm-up is a legitimate catch-up that consolidates a horizon, and a gate that merely drops a held plan traps the system in a cycle of proposing and holding the same order. The problem is not the number but the hold-release rule.

The primary configuration therefore models review explicitly: a held plan at the approval level is re-checked a day later against the current true constraints and released if it still passes, with the release labelled as simulated in every trace. This is a modelling decision, not a calibration, and three alternatives were documented. The implication for deployment is that an evidence-gated system must be designed together with the human process that resolves its holds, including response time, because the trade-off between a wrong order and a missed sale is set by that process rather than by the cap. The price-gap finding points the same way: a single missing price hard-failed a whole thirty-series portfolio, which is the safe behaviour for a coupled solve but an expensive one, and finer-grained gating within a batch is a design extension recorded in Section 9.3.

### 7.4 Where the Language Model Added Value, and Where It Did Not

On machine-readable documents the model added nothing to the gated deterministic pipeline: the parser reads the rule line exactly, and the model's extraction, triage, routing, and review reproduced the same decisions at a cost of tens of thousands of tokens per decision. On prose documents the model was the only component that could ground the constraints at all, and it did so with no invented rule across 22,260 fields, while the deterministic verifier caught the omissions. The division of labour that emerges is sharper than the one hypothesised: the model's value lies in reading what the parser cannot, and the deterministic layers (certificate, verifier, solver, checker, gate) are what make that reading safe to act on. The triage hypotheses, which were expected to carry the model's value on interpretive failure classes, were generated but never consumed by any decision rule, so their value is unmeasured rather than absent.

The hostile-note result belongs here too. The model, told that supplier text is data, refused to treat an instruction as a rule in every case tested and escalated it, reaching the same outcome as the pattern screen. The model is not a security boundary, and the experiment used one phrasing; what it shows is that the layered design does not depend on the screen alone for the case tested.

### 7.5 Threats to Validity

**Internal validity.** The state-quality layer is synthetic and uncalibrated: fault classes, magnitudes, and rates are design choices, not estimates, and the mixed-quality sweep used one seed on two series. The independent movement ledger is an optimistic assumption that makes several classes easier to detect than they would be without a redundant source. The simulated reviewer releases a plan after one day if it passes current-state checks, which is a favourable model of human review. Supply realization, contracts, costs, and the budget are synthetic. The clean-evidence reference is a re-solve of the same formulation, so a "reference deviation" can flag a different but defensible decision; the split into violations and deviations mitigates but does not remove this.

**Construct validity.** Harmful execution is defined by the simulator's truth and has no direct field equivalent beyond post-hoc audit. Trace faithfulness as measured here is faithfulness of the record to external evidence and tools, not to any hidden computation of the model. Extraction fidelity was measured against prose generated from the same typed rules in two fixed phrasings, which is easier than real supplier documents.

**External validity.** M5 is a grocery and household dataset; the three items used are slow sellers from one category at ten stores of one retailer. Pre-season buying, size curves, and markdowns are outside the evaluation. One open-weight model at one revision was used at temperature zero; other models and settings may behave differently, and provider determinism is not guaranteed. Results from the 2-series panel, where the model changed no decision, should not be generalized.

**Statistical conclusion validity.** The pilots use one to five seeds and are descriptive; the thirty-seed study uses four decision days on ten series, so its cost totals are small in absolute terms and its paired tests are well powered for the large fault effect but not for small clean-state differences, as the non-significant B10 versus B4 cost difference shows after Holm adjustment. The stage-1 main study is incomplete. Multiple comparisons were adjusted within each study but not across the chapter.

### 7.6 Managerial Implications

The evidence supports a graded adoption recipe that is more conservative than a fully agentic pipeline. First, introduce a deterministic state certificate and a content-addressed trace in front of the existing replenishment engine, without any language model and without autonomous execution: in every experiment these two components carried the whole safety benefit and cost nothing per decision. Second, decide the hold-release process before setting any cap, model its response time, and calibrate the cap on a clean window disjoint from the evaluation period, because the cap is a steady-state instrument. Third, add typed constraint grounding with mandatory escalation for documents that the deterministic parser cannot read, and measure extraction fidelity against the verifier's findings; on the evidence here the model reads prose rules precisely and the verifier catches what it omits. Fourth, grant bounded autonomy per decision only after these layers have run for long enough to show that holds are rare on clean evidence and complete on corrupted evidence. Fifth, treat every supplier document as data, keep the pattern screen on, and measure the model's own resistance separately with the screen off before relying on either.

---
## Chapter 8: Ethical, Safety, and Governance Considerations

### 8.1 Automation Bias and Accountability

A well-formatted trace may increase trust even when the underlying action is poor (Parasuraman & Riley, 1997). Reviewers must be trained to treat the trace as auditable evidence rather than as authority, and the interface must expose uncertainty, failed checks, held decisions, and alternatives, not only the selected recommendation. Responsibility for procurement policy and high-risk approvals remains with the organization. The system makes unambiguous whether an action was proposed, approved, modified, held, or executed autonomously, at what autonomy level, on what evidence, and under which gate version, and this record is content-addressed. Simulated approvals are labelled as such in every event so that they can never be mistaken for human decisions.

### 8.2 Data Quality as a Safety Property

Treating state quality as a gate shifts risk from wrong orders to delayed orders. A hold on uncertified state can itself cause a stockout, and the calibration study showed that a hold that is never resolved can stall the system indefinitely. The hold budget makes urgency explicit, the approval model makes the resolution process explicit, and the service cost of holding is measured in closed loop rather than assumed away. The system communicates to planners why a decision is held, in terms of the failing check and its evidence, and never presents a held decision as a recommendation to do nothing. All perturbations are synthetic; if pooled incident data are ever used for calibration, the adapter requires them to be anonymized, aggregated, and accompanied by provenance and an exposure denominator, and it refuses to invent rates for classes without data.

### 8.3 Security, Prompt Injection, and Data Handling

Supplier messages, operational notes, and workbook cells are untrusted inputs and a known vector for indirect prompt injection (Greshake et al., 2023). The architecture separates data from instructions in every prompt, restricts numerical tools per role to an allowlist, validates every model reply against a schema, requires that executable constraints cite an existing authenticated source, and screens documents for instruction patterns before any model reads them. The stage-2 experiment measured the model's own behaviour with the screen off and found it escalated the note in every case tested; this is evidence for one phrasing, not a guarantee, and the screen stays on in every primary configuration. The only execution adapter is the in-process simulator; there is no ERP endpoint, no shell or code tool, and no URL fetching, which is the main containment boundary. Idempotency keys prevent duplicate execution inside the simulator but do not provide crash-atomic transactions across external systems.

Remote model calls transmit every supplied document and observation field to the provider, and raw requests and responses are persisted for reproducibility. Only public and synthetic data were sent, under the provider's published terms. API keys are read from an environment variable, are never written to tracked files or stored request records, and the repository deliberately does not auto-load secrets. Local hashes and append-only conventions detect accidental tampering; a user who controls the files can rewrite the whole chain, and genuine immutable storage would need signing and trusted timestamps.

### 8.4 Supplier Concentration

Where multiple suppliers exist, an optimizer may favour those with lower cost or lead-time variance and create concentration effects. The evaluation models one supplier per department, so this concern is not exercised here. Any diversification policy must be represented as an explicit constraint rather than assumed to emerge from optimization, and supplier allocation should be reported alongside cost when multi-sourcing is modelled.

### 8.5 Environmental and Economic Externalities

Higher service targets raise inventory, transport, and emissions. Where data permit, a carbon or waste cost can be added to the objective; none is modelled here. The computational cost of the semantic layer is reported in tokens, calls, and metered dollars, and the B4 ablation tests directly whether a deterministic policy suffices: on machine-readable documents it does, and the language model's tokens buy nothing. Reserving the model for documents the parser cannot read is therefore also the cheaper and lower-footprint design.

### 8.6 Research Conduct

No human participants were involved; the audit study will proceed only after institutional approval, informed consent, and expert review of the reference labels, and researcher-only answer keys are kept separate from participant packets. No proprietary data were used. All reported numbers derive from frozen configurations retained with the code, no model result was fabricated or simulated, and runs that stopped on provider quota or on the spend cap are recorded as stopped rather than as held decisions.

---

## Chapter 9: Conclusion

### 9.1 Summary of Contributions

This dissertation reframes autonomous replenishment as a problem of earning autonomy from evidence and tests that framing with a working system. Its contributions are: (1) taxonomies of state-quality failures and constraint forms derived from the literature and from the mechanics of batch integration, each operationalized as a perturbation operator and paired with a deterministic invariant that was shown to detect it; (2) a canonical replenishment data model and a mapping of the M5 dataset onto it, with three prepared panels and strict no-leakage conventions; (3) a modular, typed, tool-grounded multi-agent architecture, implemented and tested, in which state certification and constraint grounding are verified stages, the language model is confined to interpreting documents and anomalies, and autonomy is a per-decision policy over evidence quality, constraint confidence, and risk; (4) a closed-loop benchmark with versioned supply, eligibility, and state-quality layers, a calibration adapter for pooled incident data, and a staged protocol that freezes configurations and calibrates on disjoint windows; (5) a content-addressed decision trace with replay, counterfactual, deletion, and audit tooling, shown to reproduce every validated decision exactly; and (6) controlled evidence that the gate removes harmful executions under corrupted state in every experiment, including a thirty-seed comparison in which the gated LLM system reproduced the deterministic decisions from prose documents with no invented rule while the ungated system executed on corrupted stock, together with a calibration study showing that the binding design problem of evidence-gated autonomy is the hold-release rule rather than the cap.

### 9.2 Limitations

The limitations of Section 7.5 apply. In addition, the perturbation layer is synthetic and reported with sensitivity sweeps rather than calibration; the harmful-execution metric requires a simulator truth and has no direct field equivalent; the language-model ablations beyond the gate are at one seed; the stage-1 deterministic study is incomplete and stage 2 has not started; the human audit has not been conducted; and the foundation-model forecaster was not run. The implementation is a research simulator with no enterprise execution path, and nothing in this dissertation should be read as a claim of industrial readiness.

### 9.3 Future Directions

The immediate steps are fixed by the route: complete stage 1 and run stage 2 of the deterministic study with the remaining thirteen scenarios; run the thirty-series, thirty-seed LLM design, which costs about 500 dollars at list price; and conduct the audit study once approved. Three design extensions follow directly from the findings. Gating within a coupled batch, so that one series with a missing price does not hold a whole portfolio, would reduce the service cost of the certificate without weakening it. An approved-repair experiment, in which the model's triage hypotheses can propose evidence-producing corrections that a reviewer accepts, is the missing test of the interpretive half of H4. And a horizon-matched baseline or an explicit hand-over rule after warm-up would let the deviation cap be calibrated on all days rather than on steady state alone. Beyond these, calibrating the perturbation layer from pooled incident data when such data become available, extending the decision space to pre-season buys with size curves and to markdowns, learning the autonomy policy itself as Long et al. (2026) did for ordering policies, and applying the lineage-bearing trace protocol to other operational domains in which automated decisions consume pipeline-produced state are the natural continuations.

---
## References

Ansari, A. F., Stella, L., Turkmen, C., Zhang, X., Mercado, P., Shen, H., Shchur, O., Rangapuram, S. S., Arango, S. P., Kapoor, S., Zschiegner, J., Maddix, D. C., Wang, H., Mahoney, M. W., Torkkola, K., Wilson, A. G., Bohlke-Schneider, M., & Wang, Y. (2024). Chronos: Learning the language of time series. *Transactions on Machine Learning Research*. [https://arxiv.org/abs/2403.07815](https://arxiv.org/abs/2403.07815)

Ao, R., Simchi-Levi, D., & Wang, X. (2026). OptiRepair: Closed-loop diagnosis and repair of supply chain optimization models with LLM agents. *arXiv preprint arXiv:2602.19439*. [https://arxiv.org/abs/2602.19439](https://arxiv.org/abs/2602.19439)

Arcuschin, I., Janiak, J., Krzyzanowski, R., Rajamanoharan, S., Nanda, N., & Conmy, A. (2025). Chain-of-thought reasoning in the wild is not always faithful. *arXiv preprint arXiv:2503.08679*. [https://arxiv.org/abs/2503.08679](https://arxiv.org/abs/2503.08679)

Breck, E., Polyzotis, N., Roy, S., Whang, S. E., & Zinkevich, M. (2019). Data validation for machine learning. *Proceedings of Machine Learning and Systems (MLSys 2019)*.

Chen, F., Drezner, Z., Ryan, J. K., & Simchi-Levi, D. (2000). Quantifying the bullwhip effect in a simple supply chain: The impact of forecasting, lead times, and information. *Management Science, 46*(3), 436–443. [https://doi.org/10.1287/mnsc.46.3.436.12069](https://doi.org/10.1287/mnsc.46.3.436.12069)

Clark, A. J., & Scarf, H. (1960). Optimal policies for a multi-echelon inventory problem. *Management Science, 6*(4), 475–490. [https://doi.org/10.1287/mnsc.6.4.475](https://doi.org/10.1287/mnsc.6.4.475)

Croston, J. D. (1972). Forecasting and stock control for intermittent demands. *Operational Research Quarterly, 23*(3), 289–303. [https://doi.org/10.1057/jors.1972.50](https://doi.org/10.1057/jors.1972.50)

DeHoratius, N., & Raman, A. (2008). Inventory record inaccuracy: An empirical analysis. *Management Science, 54*(4), 627–641. [https://doi.org/10.1287/mnsc.1070.0789](https://doi.org/10.1287/mnsc.1070.0789)

Gneiting, T., & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *Journal of the American Statistical Association, 102*(477), 359–378. [https://doi.org/10.1198/016214506000001437](https://doi.org/10.1198/016214506000001437)

Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., & Fritz, M. (2023). Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection. *Proceedings of the 16th ACM Workshop on Artificial Intelligence and Security (AISec '23)*, 79–90. [https://doi.org/10.1145/3605764.3623985](https://doi.org/10.1145/3605764.3623985)

Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information systems research. *MIS Quarterly, 28*(1), 75–105. [https://doi.org/10.2307/25148625](https://doi.org/10.2307/25148625)

Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics, 6*(2), 65–70.

Huangfu, Q., & Hall, J. A. J. (2018). Parallelizing the dual revised simplex method. *Mathematical Programming Computation, 10*(1), 119–142. [https://doi.org/10.1007/s12532-017-0130-5](https://doi.org/10.1007/s12532-017-0130-5)

Jannelli, V., Schoepf, S., Bickel, M., Netland, T., & Brintrup, A. (2024). Agentic LLMs in the supply chain: Towards autonomous multi-agent consensus-seeking. *arXiv preprint arXiv:2411.10184*. [https://arxiv.org/abs/2411.10184](https://arxiv.org/abs/2411.10184)

Kang, Y., & Gershwin, S. B. (2005). Information inaccuracy in inventory systems: Stock loss and stockout. *IIE Transactions, 37*(9), 843–859. [https://doi.org/10.1080/07408170590969861](https://doi.org/10.1080/07408170590969861)

Ke, G., Meng, Q., Finley, T., Wang, T., Chen, W., Ma, W., Ye, Q., & Liu, T.-Y. (2017). LightGBM: A highly efficient gradient boosting decision tree. *Advances in Neural Information Processing Systems, 30*.

Lee, H. L., Padmanabhan, V., & Whang, S. (1997). Information distortion in a supply chain: The bullwhip effect. *Management Science, 43*(4), 546–558. [https://doi.org/10.1287/mnsc.43.4.546](https://doi.org/10.1287/mnsc.43.4.546)

Li, B., Mellou, K., Zhang, B., Pathuri, J., & Menache, I. (2023). Large language models for supply chain optimization. *arXiv preprint arXiv:2307.03875*. [https://arxiv.org/abs/2307.03875](https://arxiv.org/abs/2307.03875)

Lim, B., Arik, S. O., Loeff, N., & Pfister, T. (2021). Temporal Fusion Transformers for interpretable multi-horizon time series forecasting. *International Journal of Forecasting, 37*(4), 1748–1764. [https://doi.org/10.1016/j.ijforecast.2021.03.012](https://doi.org/10.1016/j.ijforecast.2021.03.012)

Liu, B., Jiang, Y., Zhang, X., Liu, Q., Zhang, S., Biswas, J., & Stone, P. (2023). LLM+P: Empowering large language models with optimal planning proficiency. *arXiv preprint arXiv:2304.11477*. [https://arxiv.org/abs/2304.11477](https://arxiv.org/abs/2304.11477)

Liu, X., Yu, H., Zhang, H., Xu, Y., Lei, X., Lai, H., Gu, Y., Ding, H., Men, K., Yang, K., Zhang, S., Deng, X., Zeng, A., Du, Z., Zhang, C., Shen, S., Zhang, T., Su, Y., Sun, H., Huang, M., Dong, Y., & Tang, J. (2024). AgentBench: Evaluating LLMs as agents. *International Conference on Learning Representations*. [https://openreview.net/forum?id=zAdUB0aCTQ](https://openreview.net/forum?id=zAdUB0aCTQ)

Long, C. X., Simchi-Levi, D., Zhu, F., Su, H., Calmon, A. P., & Calmon, F. P. (2026). Reliability and effectiveness of autonomous AI agents in supply chain management. *arXiv preprint arXiv:2605.17036*. [https://arxiv.org/abs/2605.17036](https://arxiv.org/abs/2605.17036)

Ma, C., Zhang, J., Zhu, Z., Yang, C., Yang, Y., Jin, Y., Lan, Z., Kong, L., & He, J. (2024). AgentBoard: An analytical evaluation board of multi-turn LLM agents. *Advances in Neural Information Processing Systems, 37*. [https://arxiv.org/abs/2401.13178](https://arxiv.org/abs/2401.13178)

Makridakis, S., Spiliotis, E., & Assimakopoulos, V. (2022a). M5 accuracy competition: Results, findings, and conclusions. *International Journal of Forecasting, 38*(4), 1346–1364. [https://doi.org/10.1016/j.ijforecast.2021.11.013](https://doi.org/10.1016/j.ijforecast.2021.11.013)

Makridakis, S., Spiliotis, E., Assimakopoulos, V., Chen, Z., Gaba, A., Tsetlin, I., & Winkler, R. L. (2022b). The M5 uncertainty competition: Results, findings and conclusions. *International Journal of Forecasting, 38*(4), 1365–1385. [https://doi.org/10.1016/j.ijforecast.2021.10.009](https://doi.org/10.1016/j.ijforecast.2021.10.009)

Nahmias, S. (1994). Demand estimation in lost sales inventory systems. *Naval Research Logistics, 41*(6), 739–757. [https://doi.org/10.1002/1520-6750(199410)41:6<739::AID-NAV3220410605>3.0.CO;2-A](https://doi.org/10.1002/1520-6750%28199410%2941:6%3C739::AID-NAV3220410605%3E3.0.CO;2-A)

OpenAI. (2025). gpt-oss-120b & gpt-oss-20b model card. *arXiv preprint arXiv:2508.10925*. [https://arxiv.org/abs/2508.10925](https://arxiv.org/abs/2508.10925)

Parasuraman, R., & Riley, V. (1997). Humans and automation: Use, misuse, disuse, abuse. *Human Factors, 39*(2), 230–253. [https://doi.org/10.1518/001872097778543886](https://doi.org/10.1518/001872097778543886)

Parasuraman, R., Sheridan, T. B., & Wickens, C. D. (2000). A model for types and levels of human interaction with automation. *IEEE Transactions on Systems, Man, and Cybernetics, Part A, 30*(3), 286–297. [https://doi.org/10.1109/3468.844354](https://doi.org/10.1109/3468.844354)

Paterson, C., Kiesmüller, G., Teunter, R., & Glazebrook, K. (2011). Inventory models with lateral transshipments: A review. *European Journal of Operational Research, 210*(2), 125–136. [https://doi.org/10.1016/j.ejor.2010.05.048](https://doi.org/10.1016/j.ejor.2010.05.048)

Quan, Y., & Liu, Z. (2024). InvAgent: A large language model based multi-agent system for inventory management in supply chains. *arXiv preprint arXiv:2407.11384*. [https://arxiv.org/abs/2407.11384](https://arxiv.org/abs/2407.11384)

Raman, A., DeHoratius, N., & Ton, Z. (2001). Execution: The missing link in retail operations. *California Management Review, 43*(3), 136–152.

Redman, T. C. (1998). The impact of poor data quality on the typical enterprise. *Communications of the ACM, 41*(2), 79–82. [https://doi.org/10.1145/269012.269025](https://doi.org/10.1145/269012.269025)

Rockafellar, R. T., & Uryasev, S. (2000). Optimization of conditional value-at-risk. *Journal of Risk, 2*(3), 21–41. [https://doi.org/10.21314/JOR.2000.038](https://doi.org/10.21314/JOR.2000.038)

Salinas, D., Flunkert, V., Gasthaus, J., & Januschowski, T. (2020). DeepAR: Probabilistic forecasting with autoregressive recurrent networks. *International Journal of Forecasting, 36*(3), 1181–1191. [https://doi.org/10.1016/j.ijforecast.2019.07.001](https://doi.org/10.1016/j.ijforecast.2019.07.001)

Sculley, D., Holt, G., Golovin, D., Davydov, E., Phillips, T., Ebner, D., Chaudhary, V., Young, M., Crespo, J.-F., & Dennison, D. (2015). Hidden technical debt in machine learning systems. *Advances in Neural Information Processing Systems, 28*.

Shen, X., Wang, S., Tan, Z., Yao, L., Zhao, X., Xu, K., Wang, X., & Chen, T. (2025). FaithCoT-Bench: Benchmarking instance-level faithfulness of chain-of-thought reasoning. *arXiv preprint arXiv:2510.04040*. [https://arxiv.org/abs/2510.04040](https://arxiv.org/abs/2510.04040)

Simchi-Levi, D., Mellou, K., Menache, I., & Pathuri, J. (2025). Large language models for supply chain decisions. *arXiv preprint arXiv:2507.21502*. [https://arxiv.org/abs/2507.21502](https://arxiv.org/abs/2507.21502)

Sterman, J. D. (1989). Modeling managerial behavior: Misperceptions of feedback in a dynamic decision making experiment. *Management Science, 35*(3), 321–339. [https://doi.org/10.1287/mnsc.35.3.321](https://doi.org/10.1287/mnsc.35.3.321)

Syntetos, A. A., & Boylan, J. E. (2005). The accuracy of intermittent demand estimates. *International Journal of Forecasting, 21*(2), 303–314. [https://doi.org/10.1016/j.ijforecast.2004.10.001](https://doi.org/10.1016/j.ijforecast.2004.10.001)

Turpin, M., Michael, J., Perez, E., & Bowman, S. R. (2023). Language models don't always say what they think: Unfaithful explanations in chain-of-thought prompting. *Advances in Neural Information Processing Systems, 36*. [https://proceedings.neurips.cc/paper_files/paper/2023/hash/ed3fea9033a80fea1376299fa7863f4a-Abstract-Conference.html](https://proceedings.neurips.cc/paper_files/paper/2023/hash/ed3fea9033a80fea1376299fa7863f4a-Abstract-Conference.html)

Wang, R. Y., & Strong, D. M. (1996). Beyond accuracy: What data quality means to data consumers. *Journal of Management Information Systems, 12*(4), 5–33. [https://doi.org/10.1080/07421222.1996.11518099](https://doi.org/10.1080/07421222.1996.11518099)

Wickramasuriya, S. L., Athanasopoulos, G., & Hyndman, R. J. (2019). Optimal forecast reconciliation for hierarchical and grouped time series through trace minimization. *Journal of the American Statistical Association, 114*(526), 804–819. [https://doi.org/10.1080/01621459.2018.1448825](https://doi.org/10.1080/01621459.2018.1448825)

Woo, G., Liu, C., Kumar, A., Xiong, C., Savarese, S., & Sahoo, D. (2024). Unified training of universal time series forecasting transformers. *Proceedings of the 41st International Conference on Machine Learning*. [https://arxiv.org/abs/2402.02592](https://arxiv.org/abs/2402.02592)

Wu, Q., Bansal, G., Zhang, J., Wu, Y., Li, B., Zhu, E., Jiang, L., Zhang, X., Zhang, S., Liu, J., Awadallah, A. H., White, R. W., Burger, D., & Wang, C. (2023). AutoGen: Enabling next-gen LLM applications via multi-agent conversation. *arXiv preprint arXiv:2308.08155*. [https://arxiv.org/abs/2308.08155](https://arxiv.org/abs/2308.08155)

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). ReAct: Synergizing reasoning and acting in language models. *International Conference on Learning Representations*. [https://openreview.net/forum?id=WE_vluYUL-X](https://openreview.net/forum?id=WE_vluYUL-X)

Yoshizato, K., Shimizu, K., Higa, R., & Otsuka, T. (2026). AI agent systems for supply chains: Structured decision prompts and memory retrieval. *arXiv preprint arXiv:2602.05524*. [https://arxiv.org/abs/2602.05524](https://arxiv.org/abs/2602.05524)

Zhao, X., Xie, Y., Chen, C., & Sun, Y. (2025). AIM-Bench: Evaluating decision-making biases of agentic LLM as inventory manager. *arXiv preprint arXiv:2508.11416*. [https://arxiv.org/abs/2508.11416](https://arxiv.org/abs/2508.11416)

Zipkin, P. H. (2000). *Foundations of inventory management*. McGraw-Hill.

---

## Appendix A: Summary of Revisions Relative to the Previous Draft

This appendix records what changed between the second draft (September 2026) and this one, and why, so that the revision can be reviewed as a set of decisions.

**From proposal to results.** The previous draft described expected findings. This draft reports the results of a staged programme of experiments on an implemented system: software validation, forecast training and backtests, deterministic pilots, gate calibration, real-LLM pilots and stage-2 experiments, a thirty-seed LLM study, and the partial stage-1 deterministic study. Chapter 6 is new, Chapter 7 replaces the expected-findings chapter with a discussion of what the evidence supports, and every number is traceable to a result folder listed in Appendix B.

**Grounding of Chapter 3.** The problem analysis now derives the taxonomies of state-quality failures and constraint forms from the inventory-record-inaccuracy and data-quality literature and from the mechanics of batch integration, and validates them by construction: each class is implemented as a perturbation operator and paired with a deterministic invariant that is tested for detecting it. The perturbation layer is explicitly synthetic and uncalibrated, with a calibration adapter provided for pooled, anonymized incident data. The M5 price gaps discovered during calibration are reported as evidence that public data contain such faults.

**Architecture as implemented.** Chapter 4 now describes the system that exists: a sequential protocol, seventeen named certificate checks with their weights, the exact bounded role of the language model in four of seven roles, the two document carriers, the four trained forecasting models and their training protocol, the HiGHS-solved MILP, the frozen gate thresholds, the two approval modes, and the replay, counterfactual, deletion, and audit tools.

**The gate.** The deviation measure was redesigned from a unit ratio to extra spend as a share of budget after calibration showed the original to be unstable, re-calibrated on logged decisions, and frozen at 0.03 under a new gate version. Validation on the test window identified the hold-release problem, and simulated delayed approval was adopted as the primary configuration with plan-dropping as the ablation. The harmful-execution metric is reported split into true-constraint violations and reference deviations.

**Experimental design.** The research route, compute envelope, and freezing rules are documented (Section 5.11). The LLM arms were re-designed around a fixed budget: a ten-series prose-document study at thirty seeds replaces the thirty-series LLM design, which is deferred. Stage 2 experiments with the injection screen off, fixed-evidence replications, and prose grounding were added. The statistical protocol states the replication unit, the paired procedures, and the Holm adjustment as implemented.

**Hypotheses.** The research questions and hypotheses are unchanged except that H4 no longer presupposes calibrated perturbation rates; Table 7.1 records the status of each.

**Scope statements.** Lost sales replace backorders in the formulation; size curves, pre-season buying, and markdowns are stated as out of scope; the foundation-model forecaster is listed as not run; and the human audit is reported as designed but not conducted.

**Literature.** Added execution failures in retail operations, the cost of poor data quality, hidden technical debt and data validation in machine-learning systems, gradient-boosted quantile regression, the HiGHS solver, Holm's procedure, and the open-weight model used.

**Unchanged.** The M5 dataset as the sole evaluation dataset. The blackboard architecture with typed objects. The critic that cannot modify proposals. The CVaR-augmented objective. The seven-role decomposition. The trace-faithfulness protocol of replay, counterfactual, and deletion tests. The deployment recipe of deterministic certificates first and bounded autonomy last, now supported by evidence rather than expectation.

---

## Appendix B: Reproduction and Artifact Inventory

Every number in Chapter 6 is read from a result folder by the results exporter and the report generator; both are re-run by a single command each and their outputs are included in the result tree.

| Section | Result folder(s) | Frozen configuration | Regenerating command |
| --- | --- | --- | --- |
| 6.2 Backtests | `results/forecast_{seasonal_naive,croston_sba,lightgbm,deep}.json` | `configs/smoke.yaml` with model overrides | `python -m ega forecast-backtest --config configs/smoke.yaml --model <name> --origins 1800 1828 --horizon 28` |
| 6.3 Validation | `examples/validated_demo/`, `examples/validation/` | `python -m ega demo` | `python -m pytest -q`; `python -m ega demo --output results/my_demo --days 6` |
| 6.4 Pilots | `results/m5_pilot`, `results/baseline_pilot` | `configs/pilot.yaml`; `configs/deterministic_study.yaml` with two seeds and seven days | `python -m ega run --config ... --seeds 7 29` |
| 6.5 Calibration | `results/gate_calibration`, `results/gate_calibration_1700_price_gap`, `results/baseline_pilot_gate_v2`, `results/baseline_pilot_gate_v2_oracle_approval`, `results/llm_pilot_cerebras_gate_v2` | `configs/gate_calibration.yaml`; gate version `gate-v2-spend-deviation-2026-10-06` | `python scripts/calibrate_gate.py` |
| 6.6 Detection | `detection.csv` in every run folder | – | pooled with pandas as described in Section 6.6 |
| 6.7 LLM pilot | `results/llm_pilot_cerebras` | `configs/llm_study.cerebras.yaml` | `python -m ega run --config configs/llm_study.cerebras.yaml` |
| 6.8 Hostile note | `results/llm_injection_unscreened_cerebras` | `configs/llm_injection_unscreened.cerebras.yaml` (gate version `gate-v1-synthetic-INJECTION-SCREEN-OFF`) | `scripts/run_llm_cerebras.sh` |
| 6.9 Fixed evidence | `results/fixed_evidence_cerebras/reliability.json` | – | `python scripts/repeat_decision.py --replications 30` |
| 6.10 Grounding | `results/grounding_templates`, `results/prose_deterministic_control`, `results/grounding_prose_cerebras` | `examples/grounding_prose.jsonl` | `python scripts/grounding_benchmark.py --generate [--prose-only] [--llm-config ...]` |
| 6.11 Prose study | `results/llm_prose_study`, `results/llm_prose_study_reference` | `configs/llm_prose_study.cerebras.yaml`, `configs/llm_prose_study_reference.yaml` | `WORKERS=3 scripts/run_main_study.sh configs/llm_prose_study.cerebras.yaml` |
| 6.12 Sensitivity | `results/sensitivity/rate_*_hold_*` | `configs/smoke.yaml` | `python scripts/sensitivity_sweep.py --config configs/smoke.yaml` |
| 6.13 Main study | `results/main_study_stage1` (merged from `results/main_study_stage1_workers/w0..w3`) | `configs/main_study_stage1.yaml` | `scripts/run_main_study.sh configs/main_study_stage1.yaml` |
| 6.14 Audit packets | `results/audit_packets` | – | `python -m ega audit-packets --participants 3` |
| Index and report | `results/RESULTS.md`, `results/results_summary.json`, `results/report/pilot_results.pdf` | – | `python scripts/export_results.py`; `python scripts/make_report.py` |

Table B.1. Result folders, configurations, and regenerating commands.

Each run folder holds `run_manifest.json` (seed, policy specification, layer parameters, fault schedule, environment versions, and the reference definition), `daily.csv`, `detection.csv`, `summary.json`, `trace_index.json`, and `artifacts/` with the content-addressed object store and the audit chain. Each study folder holds `resolved_config.json`, the exact configuration that ran, `summary.csv`, `study_summary.json`, and, where more than one policy was run, `paired_comparisons.csv`. A decision is replayed with `python -m ega replay --run-dir <run> --day <day>`, audited with `trace-audit`, and intervened upon with `counterfactual` and `delete-evidence`.

The frozen settings common to every M5 study are: horizon 14 days, 16 scenarios, 60-second solver time limit, CVaR confidence 0.95 with weight 0.1, budget 3,000, warm-up 14 days, forecast lookback 56 days, GRU training of 10 epochs on at most 12,000 windows, LightGBM with 150 trees, state-quality layer version `synthetic-control-v1-NOT-calibrated` with onset rate 0.025 and durations of one to five days, gate v2 with the cap at 0.03, and simulated delayed approval with a one-day delay. The LLM arms use gpt-oss-120b at revision `cerebras-gpt-oss-120b-2026-09-29`, temperature 0, JSON-schema mode, one retry, 500 calls per run, 6,000 output tokens per call, hold on failure, and a spend ledger with a hard cap. The M5 source files are identified by SHA-256 in each panel manifest and are not redistributed.
