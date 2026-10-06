# Evidence-Gated Autonomy for Retail Replenishment: A Constraint-Grounded LLM Multi-Agent System with Verifiable Decision Traces

**A Research Dissertation (revised draft, September 2026)**

**Keywords:** large language model agents; multi-agent systems; autonomous inventory replenishment; inventory record inaccuracy; data quality; probabilistic forecasting; stochastic optimization; supply-chain planning; decision trace; explainability; graded autonomy; human oversight

**Document lineage**

- **Version:** v2, revised draft
- **Date:** 2026-09-15
- **Supersedes:** v1 draft (same M5-based proposal, without operational grounding)
- **Evaluation data:** M5 retail hierarchy only. No retailer data.
- **Change record:** Appendix A

---

## Abstract

Inventory replenishment is conventionally split across organizational silos: demand forecasting, policy calculation, supplier constraint review, and purchase-order execution. Enterprise practice distributes these steps over disparate tools and roles, which makes the decision cycle slow, hard to audit, and fragile when constraints change. Tool-using large language model (LLM) agents promise a coordination layer across these silos, but the published evidence rests on stylized environments in which the inventory state is assumed to be correct and constraints arrive as clean parameters.

This dissertation starts from a different premise, grounded in the author's operational experience with a data platform that consolidates the inventory, sales, purchasing, and assortment data of roughly twenty retailers across apparel, footwear, jewelry, eyewear, books, and consumables. In that setting the dominant risk to any automated reordering decision is not the optimizer. It is the evidence fed to the optimizer: nightly feeds that skip days, partial refreshes that leave master data current and stock stale, warehouses missing from the location master, duplicated rows, quantities in the wrong unit, open purchase orders without arrival dates, and minimum order quantities expressed in meters of fabric rather than units of product. A replenishment agent that treats such state as ground truth will order confidently and wrongly.

The dissertation therefore proposes and evaluates an LLM multi-agent system in which state reconciliation and constraint grounding are first-class, verified stages, and in which the level of autonomy granted to each decision is a function of measured evidence quality as well as decision risk. The language model acts as a tool-using coordinator that translates natural-language and workbook-borne policies into typed, unit-checked constraints, invokes a stochastic mixed-integer solver, triages data-quality anomalies, and drafts escalations. Arithmetic feasibility, constraint satisfaction, and state validity are established by deterministic code and solver certificates, never by the model's prose. Every recommended quantity is linked, through an immutable decision trace, to its data lineage (snapshot version, feed freshness, invariant results), forecast distribution, active constraint set, solver certificate, critic verdict, and execution receipt.

The system is evaluated on the public M5 retail hierarchy, loaded into a canonical replenishment data model derived from the production platform, and surrounded by three versioned disturbance layers: a stochastic supply and constraint layer, an assortment eligibility layer, and a state-quality perturbation layer whose failure classes and frequencies are calibrated from anonymized, aggregated operational telemetry rather than invented. No retailer's commercial data is used in the experiments. The system is compared against classical policies, forecast-plus-optimizer pipelines, a rule-gated deterministic pipeline, and single-agent and free-form multi-agent LLM baselines on cost, service, bullwhip amplification, constraint violations, harmful-order rate under degraded state, run-to-run reliability, trace faithfulness, and planner audit performance. The anticipated contribution is an architecture, a benchmark, and an evaluation protocol in which autonomy is earned per decision from verifiable evidence, and in which explanations are causal audit records that can be replayed rather than narratives that merely sound plausible.

---

## Chapter 1: Introduction

### 1.1 Replenishment as a Sequential Decision under Uncertainty

Inventory replenishment is a sequential decision problem under pervasive uncertainty. A planner infers future demand from noisy and often censored sales history, reconciles on-hand and pipeline inventory across several systems of record, models uncertain replenishment lead times, respects a web of supplier, assortment, and budget constraints, and then selects order quantities whose effects unfold over multiple periods and echelons. The costs of error are asymmetric. Excess stock ties up capital and, in seasonal retail, ends in markdowns. Insufficient stock loses sales and customers.

Classical inventory theory supplies robust policies for stylized settings. Clark and Scarf (1960) established optimality results for serial multi-echelon systems, and later texts systematized base-stock, (s, S), and stochastic dynamic-programming approaches (Zipkin, 2000). These methods remain foundational because they produce feasible and interpretable control rules under known assumptions. Enterprise environments routinely violate those assumptions through nonstationary and intermittent demand, promotions, seasonal assortments with short lifecycles, supplier contracts with coupling constraints, and supply disruptions.

### 1.2 Two Gaps: Semantic and Evidential

Modern forecasting and optimization tools scale to large assortments. Deep probabilistic models such as DeepAR and the Temporal Fusion Transformer produce demand distributions for thousands of series at once (Salinas et al., 2020; Lim et al., 2021), and stochastic mixed-integer programming can turn those distributions into order quantities subject to complex constraints. Yet two gaps separate these tools from executed orders.

The first gap is semantic. Business rules arrive in heterogeneous, unstructured forms: supplier emails announcing temporary capacity cuts, contract clauses stipulating minimum order quantities (MOQs) and pack integrality, seasonal assortment workbooks that decide which product may be shipped to which store, promotion calendars, and planner exceptions grounded in tacit knowledge. Translating these into a formulation the solver can consume remains manual, and infeasible formulations require scarce operations-research expertise to repair (Ao, Simchi-Levi, & Wang, 2026). The previous draft of this dissertation, like most of the literature, focused on this gap.

The second gap is evidential, and it is the one this revision brings to the foreground. The inventory position, open-order pipeline, and sales history that any optimizer consumes are themselves the output of data pipelines that integrate e-commerce platforms, enterprise resource planning (ERP) systems, warehouse management systems (WMS), point-of-sale exports, spreadsheet drops, and data warehouses. Those pipelines fail in specific, recurring, and often silent ways. Inventory record inaccuracy is a well-documented phenomenon with large operational cost (DeHoratius & Raman, 2008; Kang & Gershwin, 2005), and the batch integration layer adds failure modes of its own. When decisions are automated, a wrong state no longer produces a wrong screen for a human to doubt. It produces a purchase order.

### 1.3 Lessons from Operating Replenishment Data at Scale

The redesign presented here draws on the author's operational access to a multi-retailer data platform that loads each retailer's source systems into a single canonical schema of locations, suppliers, products and variants, prices, orders and line items, purchase orders and transfers, current inventory, and daily inventory snapshots. The platform serves retailers in apparel, footwear, jewelry, eyewear, books, and office consumables, with source systems ranging from e-commerce APIs and ERPs to WMS exports and per-season assortment workbooks placed in shared folders. Chapter 3 documents what this experience reveals, in anonymized form, about how replenishment state is actually produced and how constraints actually arrive.

Three observations drive the redesign. First, the failures that would most plausibly cause a harmful automated order originate upstream of the optimizer, in the reconciled state and in constraint interpretation, rather than in the optimization itself. Second, a large share of these failures is detectable by cheap, deterministic invariants if the system is designed to run them and to condition its behavior on the result. Third, when a recommendation looks wrong, the first question an operator asks is not "what was the model's reasoning" but "which data run produced this, and was the feed complete". Lineage is the primary explanation in practice. These observations reshape the research questions, the architecture, the disturbance model used in the simulator, and the design of the decision trace.

### 1.4 The Promise and Perils of LLM Agents in Supply Chains

Tool-augmented LLM agents offer a coordination layer for both gaps. ReAct showed that language models can interleave reasoning with external tool calls (Yao et al., 2023). AutoGen extended this to configurable multi-agent conversations (Wu et al., 2023). In supply-chain optimization, OptiGuide used an LLM as a natural-language interface to an existing combinatorial optimizer rather than as a replacement for it (Li et al., 2023), and later work extended the idea to autonomous inventory management, consensus seeking, structured decision prompts with memory, and solver-in-the-loop repair of infeasible models (Quan & Liu, 2024; Jannelli et al., 2024; Yoshizato et al., 2026; Ao et al., 2026).

The perils are equally documented. Agentic LLMs display human-like biases in inventory decisions, including a pull-to-center effect (Zhao et al., 2025). Long et al. (2026) show that strong average performance can mask substantial tail risk and run-to-run instability, which they call the agent bullwhip effect, and that repeated sampling does not remove it. Chain-of-thought explanations can be fluent and unfaithful at the same time (Turpin et al., 2023; Arcuschin et al., 2025). Supplier documents and operational notes are untrusted inputs and a vector for indirect prompt injection (Greshake et al., 2023). None of this literature considers what happens when the state the agent reasons over is itself degraded.

### 1.5 Problem Statement and Scope

Existing replenishment systems optimize narrow formulations and leave semantic constraint interpretation, anomaly triage, and explanation to humans. A pure LLM agent can read natural language but is unreliable at arithmetic, hallucinates data, violates hard constraints, and varies across identical runs. Neither treats the quality of the inventory evidence as a decision variable.

The research problem is therefore threefold. Can a multi-agent architecture combine the semantic flexibility of LLM reasoning with the quantitative reliability of formal forecasting and optimization tools? Can the level of autonomy granted to a replenishment decision be tied to verifiable measures of evidence quality and constraint confidence, so that the system orders autonomously only when it is entitled to? And can a structured decision trace with data lineage provide faithful, replayable explanation sufficient for accountable autonomy?

Scope. The dissertation addresses operational replenishment for item-location-supplier combinations in a multi-period, multi-store retail setting with stochastic and intermittent demand, variable and sometimes unknown lead times, per-item and aggregate MOQs including MOQs expressed in a unit other than the order unit, pack integrality, assortment eligibility windows, supplier capacity, storage and budget limits, service targets, disruption events, and lateral transshipment between stores of the same cluster. It addresses state-quality degradation as a first-class disturbance. It does not address strategic network design or pre-season assortment buying, which are dominant in fashion retail but not supported by the evaluation dataset. Autonomous execution is evaluated only in a simulator or, where an enterprise interface exists, behind an approval gate.

### 1.6 Research Questions and Hypotheses

The central question is: **Can an LLM multi-agent system whose autonomy is gated by verified evidence quality and grounded constraints produce replenishment decisions that are cost-effective, reliable, and auditable under realistic state degradation, and does its structured decision trace faithfully explain the evidence and tools that caused each action?**

The question decomposes as follows.

- **RQ1 (Performance).** How does the proposed system compare with classical policies, forecast-plus-optimizer pipelines, a rule-gated deterministic pipeline, and single-agent LLM baselines on total cost, service, stockouts, and bullwhip amplification under clean state?
- **RQ2 (Evidence gating).** Under realistic state-quality perturbations, does conditioning autonomy on a measured data-quality signal reduce harmful executed orders relative to fixed-autonomy variants, and which degradation classes require semantic reasoning beyond deterministic invariants?
- **RQ3 (Constraint grounding).** How accurately can typed constraint extraction with unit verification handle the constraint forms observed in practice, including aggregate MOQs, MOQs in foreign units, size-curve packs, and assortment eligibility windows, and how much residual error reaches the solver?
- **RQ4 (Architecture).** Which benefits arise from role specialization, critic review, typed shared state, and episodic memory, and which coordination costs and failure modes do they introduce?
- **RQ5 (Reliability).** How often does the system violate hard constraints, produce invalid tool calls, or show high run-to-run variance under normal, disrupted, and degraded-state conditions?
- **RQ6 (Trace faithfulness).** Do the cited lineage, forecasts, constraints, and critic findings causally support the chosen order under replay, counterfactual intervention, and evidence deletion?
- **RQ7 (Human audit).** Does a lineage-bearing structured trace reduce planner audit time and improve calibrated accept-or-override decisions, in particular the detection of decisions made on degraded state, relative to a free-form rationale?

Hypotheses.

- **H1.** A multi-agent system with formal forecast and optimization tools achieves lower expected operating cost than an LLM-only policy and service comparable to a standalone stochastic optimization pipeline under clean state.
- **H2.** The Risk and Critic Agent reduces constraint violations and high-cost tail events, at a cost in latency and tokens.
- **H3.** Typed communication and shared state reduce grounding errors and coordination variance relative to free-form agent conversation.
- **H4.** Under calibrated state-quality perturbations, evidence-gated autonomy yields a lower harmful-order rate than the same architecture with fixed autonomy and than an ungated optimizer. A rule-based gate without an LLM captures most of the benefit on failure classes detectable by single-table invariants, whereas the LLM adds value on classes that require cross-source or narrative reasoning, such as unmapped locations, historical restatements, and constraint changes announced in prose.
- **H5.** Typed constraint extraction achieves high exact-match accuracy on templated clauses and degrades on aggregate and foreign-unit forms. Unit verification and mandatory escalation on low confidence catch most residual errors before they reach the solver.
- **H6.** Structured traces score higher than free-form rationales on replay consistency, evidence completeness, contradiction rate, and counterfactual sensitivity.
- **H7.** Planners using a lineage-bearing trace audit faster and detect a larger share of decisions made on stale or incomplete state than planners given a free-form rationale.
- **H8.** Under severe demand, supplier, or state shocks, bounded autonomy with escalation outperforms unrestricted execution on safety-adjusted utility.

### 1.7 Contributions and Structure

The dissertation makes six contributions: an anonymized, practice-grounded account of how replenishment state and constraints arise in multi-retailer operations, with taxonomies of state-quality failures and constraint forms (Chapter 3); a canonical replenishment data model and an M5 mapping onto it, so that the agents are evaluated against the same interface they would face in deployment (Chapter 5); an architecture in which state reconciliation and constraint grounding are verified stages and autonomy is a policy over evidence quality (Chapter 4); a benchmark with three versioned disturbance layers, including a state-quality perturbation layer calibrated from operational telemetry (Chapter 5); an evaluation protocol for trace faithfulness that includes data lineage (Chapter 5); and controlled evidence on where LLM involvement adds value and where deterministic checks suffice (Chapter 6).

---

## Chapter 2: Literature Review

### 2.1 Inventory Control Theory and the Bullwhip Effect

Foundational inventory models formalize the trade-off between holding cost and shortage cost. Clark and Scarf (1960) established optimality for serial multi-echelon systems, and later texts systematized base-stock, (s, S), and stochastic dynamic programming (Zipkin, 2000). A central dynamic in decentralized ordering is the bullwhip effect, in which local decisions, delayed information, and forecasting errors amplify demand variability upstream. Sterman (1989) showed in the Beer Game that individually reasonable decisions produce system-level instability. Lee, Padmanabhan, and Whang (1997) attributed the effect to demand signal processing, rationing games, order batching, and price fluctuations, and Chen et al. (2000) quantified how forecasting methods and lead times interact to amplify variance. This literature motivates system-level evaluation: an agent should not be judged by one-period order accuracy alone, because unstable decisions transfer risk to suppliers and other echelons.

Long et al. (2026) show that LLM-based automation can amplify rather than mitigate these dynamics. Stochastic LLM decision-making generates order variability even when customer demand is fixed, which they call the agent bullwhip effect. Strong average performance coexists with substantial tail risk, and repeated sampling does not remove the instability, which suggests that reliability requires changing the decision policy rather than averaging over outputs. Repeated evaluation, guardrails, and risk-sensitive objectives are therefore prerequisites for any deployment.

Lateral transshipment between locations of the same echelon is a well-studied complement to supplier replenishment (Paterson et al., 2011). In multi-store retail it is a routine rebalancing instrument, and it enters this dissertation as a secondary action in the decision space because the evaluation dataset contains ten stores in three regions.

### 2.2 Inventory Record Inaccuracy, Censored Demand, and Data Quality

The replenishment literature has long recognized that the recorded inventory position may differ from the physical one. DeHoratius and Raman (2008) found record inaccuracy in a large majority of audited store-item records in a retail chain, with error magnitude related to item cost, sales velocity, and distribution structure. Kang and Gershwin (2005) showed by simulation that even small undetected stock loss drives disproportionate stockouts under automated replenishment because the system believes stock exists. These results are direct evidence that the state fed to an automated replenishment policy is a risk factor in its own right.

Recorded sales are also a censored observation of demand: when an item is out of stock, demand is not observed. Estimation methods for lost-sales systems address this bias (Nahmias, 1994), and intermittent-demand forecasting has its own methods and pitfalls (Croston, 1972; Syntetos & Boylan, 2005). The public M5 dataset records sales, not demand, and contains no inventory, so censoring is an unavoidable limitation and a modeling consideration.

The information-systems literature frames data quality along dimensions such as accuracy, completeness, timeliness, and consistency (Wang & Strong, 1996). This dissertation operationalizes those dimensions as computable invariants over a canonical replenishment schema and ties them to the autonomy policy. To the author's knowledge, no published LLM-agent replenishment study models pipeline-induced state degradation, although it is the dominant operational risk in practice (Chapter 3).

### 2.3 Probabilistic, Hierarchical, and Intermittent Retail Forecasting

Inventory decisions require predictive distributions, because forecast uncertainty determines safety stock, service probability, and tail cost. DeepAR introduced global autoregressive probabilistic forecasting across thousands of related series (Salinas et al., 2020). The Temporal Fusion Transformer combines multi-horizon prediction with variable selection and attention (Lim et al., 2021). Pretrained time-series foundation models such as Chronos and Moirai offer competitive zero-shot probabilistic forecasts (Ansari et al., 2024; Woo et al., 2024) and are included as candidates, not assumed to dominate task-specific retail models. Proper scoring rules such as the CRPS and pinball loss evaluate these distributions (Gneiting & Raftery, 2007).

The M5 competition is the natural benchmark because it contains a large retail hierarchy with intermittent item-level demand, prices, calendar effects, and promotions. Its accuracy track required 30,490 bottom-level forecasts aggregating into 42,840 hierarchical series, and its uncertainty track required nine quantiles (Makridakis, Spiliotis, & Assimakopoulos, 2022a; Makridakis et al., 2022b). Performance varied by aggregation level, and forecast combination and machine-learning features were effective. Replenishment evaluation must therefore preserve hierarchy, temporal splits, and probabilistic calibration. Coherence across store-item, store, department, and total levels is enforced through reconciliation methods such as trace minimization (Wickramasuriya, Athanasopoulos, & Hyndman, 2019).

In the proposed system the Demand Forecast Agent returns quantiles or sampled trajectories together with calibration diagnostics and provenance, and the optimizer consumes them directly. The LLM is never asked to infer safety stock from prose.

### 2.4 Tool-Augmented LLMs and Multi-Agent Coordination

LLM agents extend a language model with memory, tools, observations, and an action loop. ReAct alternates reasoning and environment interaction (Yao et al., 2023). AgentBench and AgentBoard show that multi-turn success depends on grounding, long-horizon planning, and recovery from intermediate failures (Liu, X. et al., 2024; Ma et al., 2024). AutoGen operationalizes multi-agent conversation with configurable roles, tools, and human participation (Wu et al., 2023). More agents do not automatically mean more accuracy. Communication propagates errors, consumes tokens, and can deadlock.

Planning research supports a hybrid design. LLM+P translates natural language into a formal planning representation and delegates search to a classical planner, outperforming direct LLM planning on feasibility (Liu, B. et al., 2023). OptiGuide keeps the combinatorial optimizer and uses the LLM for scenario analysis and explanation (Li et al., 2023). Simchi-Levi et al. (2025) survey the emerging role of LLMs in supply-chain decisions and reach a similar conclusion: language models should interpret and orchestrate, while deterministic tools certify quantities and constraints. The proposed architecture enforces this separation through typed state schemas, solver certificates, and, new in this revision, deterministic state-validity certificates.

### 2.5 LLM Agents for Supply-Chain and Inventory Decisions

InvAgent applied an LLM-based multi-agent system to inventory management with zero-shot reasoning (Quan & Liu, 2024). Jannelli et al. (2024) studied consensus seeking between autonomous supply-chain agents. Yoshizato et al. (2026) found that structured decision prompts and retrieval of prior cases improve adaptation in restricted scenarios. These studies motivate specialization and memory, but their environments assume correct state and parametric constraints.

AIM-Bench reports human-like biases in agentic LLM inventory managers, including pull-to-center and bullwhip-related effects (Zhao et al., 2025). OptiRepair uses solver diagnostics and explicit inventory-theory checks to diagnose and repair infeasible models (Ao et al., 2026). Its lesson for replenishment is that operational rationality should be specified as verifiable conditions rather than delegated to an LLM judge. The Critic Agent in this dissertation follows that principle and extends it to state validity: feasibility, dominance, unit consistency, inventory balance, policy limits, and data-quality invariants are all checked by code.

### 2.6 Explainability, Decision Traces, and Faithfulness

Planners need to know why a recommendation changed, and a visible reasoning trace appears to answer that need. Natural-language rationales can nevertheless be unfaithful. Turpin et al. (2023) showed that chain-of-thought explanations rationalize answers influenced by hidden biases. Arcuschin et al. (2025) found unfaithful reasoning on realistic prompts without planted bias. FaithCoT-Bench formalizes instance-level detection of unfaithfulness (Shen et al., 2025). A fluent trace is not evidence.

This dissertation defines explanation as a structured decision record. Every material claim references an immutable artifact: a snapshot version, a feed-freshness measurement, an invariant result, a forecast file, a constraint source, a solver output, a critic test, or an execution receipt. The explanatory text is generated from this record and can be reconstructed independently. Faithfulness is operationalized through replay consistency, evidence precision and recall, contradiction rate, counterfactual sensitivity, and deletion tests. The revision adds lineage to the trace because, in operations, "which snapshot was this based on" is the first audit question.

### 2.7 Human–Automation Interaction and Graded Autonomy

The human-factors literature distinguishes use, misuse, disuse, and abuse of automation and documents automation bias, in which operators over-trust automated recommendations (Parasuraman & Riley, 1997). Parasuraman, Sheridan, and Wickens (2000) propose a model of levels of automation across information acquisition, analysis, decision selection, and action implementation. The graded autonomy in this dissertation follows that model, with one addition drawn from practice: the level is not fixed per item class but recomputed per decision from the quality of the evidence available at that moment.

### 2.8 Research Gap

The literature has established, separately, strong probabilistic forecasting, formal inventory optimization, tool-using LLM agents, early multi-agent supply-chain demonstrations, and a large body of evidence that inventory records are inaccurate. What remains missing is an end-to-end replenishment architecture that treats state quality as a disturbance, ties autonomy to verified evidence, grounds constraints of realistic form, and evaluates operational performance, reliability, and trace faithfulness together on a public benchmark.

| Approach | Primary strength | Unresolved limitation |
| --- | --- | --- |
| Classical replenishment | Formal feasibility, mature policies | No semantic handling of changing rules; assumes recorded state is true |
| Forecast-first ML pipeline | Predictive accuracy at scale | Forecast separated from constraints, action, state validity, and explanation |
| Single LLM agent | Flexible natural-language interface | Arithmetic hallucination, constraint violations, long-horizon instability |
| Early supply-chain MAS | Specialization, negotiation, adaptation | Stylized environments; correct state assumed; limited tail-risk and faithfulness analysis |
| Inventory record inaccuracy research | Empirical evidence that state is wrong | Not connected to automated, LLM-coordinated decision-making |
| **Proposed system** | **Typed coordination + verified state + grounded constraints + solver + critic + evidence-gated autonomy + lineage trace** | **Research contribution to be validated** |

Table 2.1. Positioning of the proposed research.

---

## Chapter 3: Operational Grounding: Replenishment Data in Practice

### 3.1 Setting and Method

Design-science research begins with problem awareness grounded in the environment in which the artifact will operate (Hevner et al., 2004). This chapter provides that grounding. The author had operational access to a data platform that integrates the source systems of roughly twenty retailers into one canonical relational schema, identical across retailers, and that serves downstream forecasting and replenishment recommendations. The retailers operate in apparel, footwear, jewelry, eyewear, books, and office consumables, through physical stores, e-commerce, and wholesale channels, in several countries and currencies. Their source systems include e-commerce platform APIs, ERP systems, WMS exports, point-of-sale systems, cloud data warehouses, and spreadsheets placed in shared folders by planners and suppliers.

The evidence base for this chapter comprises four kinds of material: the integration pipelines and their data contracts; per-run and per-stage telemetry persisted to a monitoring database; a recurring data-quality review routine executed against production databases after the nightly loads; and planner-supplied artifacts such as seasonal assortment workbooks, MOQ files, and campaign order sheets. The observations were collected over a multi-month period of operational involvement.

Anonymization is strict. No retailer is named, no retailer-level figure is reported, and no retailer's commercial data enters the experiments of Chapter 5. Where the chapter informs calibration, only frequencies pooled across retailers are used. The chapter has the limitations of participant observation on a single platform: the sample of failures is biased toward those that were noticed and fixed, and a different integration architecture would produce a partly different taxonomy. Its purpose is not to estimate population parameters but to make sure the artifact is designed against the failure modes that occur rather than the ones that are convenient to simulate.

### 3.2 The Canonical Replenishment Data Model

Every retailer's data is loaded into the same set of tables. Table 3.1 lists the entities that matter for replenishment and the properties that turned out to be decision-relevant.

| Entity | Content | Decision-relevant properties observed in practice |
| --- | --- | --- |
| Locations | Stores, warehouses, e-commerce sites | Type (store, warehouse, online), region and country, cluster membership, store type used by assortment rules; source locations may be missing from the master |
| Suppliers | Vendors, brands, own production | Aliases and spelling variants for the same supplier; supplier may be unknown when an order is planned |
| Supplier products and supplier variants | The supplier's view of a product | MOQ and its unit, per-variant consumption multiplier, pack multiple, lead time |
| Families, categories, products, variants, attributes | Product hierarchy down to size and color | Placeholder products for unknown SKUs, missing attributes, near-duplicate labels differing by case or accent |
| Prices | Selling price per variant and location | Validity windows, currency, prices sometimes derived from sales when no price feed exists |
| Orders and line items | Sales transactions | Channel, location, net versus gross amounts, returns and cancellations restating history |
| Transfers | Supplier purchase orders and inter-location transfers in one table | Status, ordered and received quantity, expected arrival date often missing, order date sometimes missing, non-stock lines such as fees |
| Live inventory | Current on-hand per variant and location | Overwritten each run, therefore not replayable |
| Inventory snapshots | Daily immutable copy taken before each run | The only replayable state history; gaps when a run is missed |
| Catalogs and assortments | Seasonal eligibility of products for clusters of locations | Validity by season and drop, cluster unions, store types |
| Reference data | Exchange rates, regions, company settings | Missing rate rows break multi-currency valuation |

Table 3.1. Canonical replenishment data model and the properties that proved decision-relevant.

The existence of a shared schema is itself a finding with design consequences. Because every retailer looks the same to downstream consumers, checks written once apply everywhere, and an agent can be designed against one interface. Chapter 5 loads the M5 dataset into this same model so the agents are evaluated on the interface they would meet in deployment.

### 3.3 How Replenishment State Is Produced

The state an optimizer consumes is produced by a nightly batch pipeline per retailer. Several properties of that process recur across retailers and matter for autonomy.

- **Cadence.** State is refreshed once a day. Between runs it ages. A decision taken at noon uses a snapshot from the previous night at best.
- **Stage ordering.** Master data is loaded before facts so that foreign keys resolve: locations and suppliers, then products and variants, then prices, inventory, and orders. Facts whose keys do not resolve are dropped or parked.
- **Error isolation.** Each stage is isolated. When one stage fails, its failure is recorded and the run continues. A run can therefore complete with current product data and stale inventory, and both the run status and the surface data look normal.
- **Snapshot before overwrite.** A daily inventory snapshot is written before the run overwrites current inventory. Snapshots are the only replayable history. A missed run leaves a hole that must be filled day by day, whereas sales feeds delivered as rolling windows heal on the next run.
- **Idempotency discipline.** Changes to a pipeline are validated by taking a snapshot, re-running, and diffing. Loads are expected to be idempotent, and the cases where they were not produced duplicated facts.
- **Invariants and telemetry.** A suite of schema-level data invariants exists, and every run persists per-stage events and metrics to a monitoring database with a chat recap. These are already, in effect, a trace of how state was produced.

The implications are direct. State has an age and a completeness that can be measured. A successful run is not the same as a complete state. Live tables are not replayable but snapshots are, so lineage must point to snapshot versions. The run identifier is a natural lineage key. Invariant checks and stage telemetry already exist and can be reused as evidence certificates rather than invented.

### 3.4 A Taxonomy of State-Quality Failures

Table 3.2 catalogs the failure classes observed in the data-quality review routine and in incident records. Each class is described by its mechanism, its effect on a replenishment decision if it goes undetected, and the signal that detects it. The classes are the basis of the state-quality perturbation layer in Chapter 5.

| # | Failure class | Mechanism observed | Effect on replenishment if undetected | Detection signal |
| --- | --- | --- | --- | --- |
| 1 | Feed gap | A nightly run is skipped for one or more days (credential rotation, source outage, network path change, stale container image); gaps cluster | State ages; snapshot history has holes; naive forecasters read missing days as zero demand | Snapshot age versus expected cadence; missing snapshot dates in the window |
| 2 | Partial refresh | One stage fails while others succeed | Master data current, stock or orders stale, or the reverse; the state looks complete | Per-table freshness; stage telemetry for the run |
| 3 | Stale-but-fresh feed | The run succeeds but the source export was not regenerated | Identical content with a new timestamp; zero movement everywhere | Content hash equal to the previous snapshot; zero-movement rate |
| 4 | Duplicate ingestion | Non-idempotent load or re-delivered source file | Inflated sales and stock; open orders counted twice | Key cardinality checks; snapshot-rerun-diff gate |
| 5 | Unit and money inflation | Per-unit price confused with line total; pack quantity loaded as units | Inflated revenue, demand, or on-hand; MOQ misjudged | Ratio invariants between line total, quantity, and unit price; pack-aware range checks |
| 6 | Currency mislabel | Wrong currency code on a channel or missing exchange-rate row | Budgets and costs misvalued | Currency consistency per location; rate coverage |
| 7 | Unmapped location | A warehouse or store exists in the source but not in the location master | Its stock and sales are invisible; phantom stockouts and misplaced demand | Source-versus-master location reconciliation; unexplained volume drop |
| 8 | Identity drift | SKU recodes, label variants by case or accent, vendor aliases | Split demand histories; duplicated suppliers or categories | Near-duplicate detection; alias tables |
| 9 | Placeholder master data | Unknown SKUs created as husks with missing attributes | Wrong hierarchy aggregation; unknown size curve | Attribute completeness checks |
| 10 | Orphaned facts | Facts whose foreign key cannot resolve are dropped or parked | Silent undercount of sales or stock | Row-count reconciliation between source and load |
| 11 | Open-order integrity | Purchase orders with missing arrival date, missing order date, missing supplier, corrupted lines, fee lines as stock lines | Pipeline inventory wrong in either direction | Schema and plausibility checks on transfers |
| 12 | Historical restatement | Source restates past sales through returns, cancellations, or back-dated orders; rolling-window feeds heal, snapshot feeds do not | Training data shifts under the forecaster; replay mismatch | Diff of historical periods against the previous snapshot |
| 13 | Derived-field collapse | A field re-derived from incomplete in-memory state is silently zeroed, for example inventory | Mass phantom stockout followed by mass reorder | Distribution shift versus the previous snapshot, such as the share of zero-stock rows |
| 14 | Censored demand | Sales are recorded only while stock is available | True demand underestimated after stockouts | Stockout flags derived from snapshots |

Table 3.2. Taxonomy of state-quality failures observed in multi-retailer replenishment data.

Two properties of this taxonomy shape the design. First, most classes are detectable by deterministic checks over the canonical schema, which argues for a rule-based state certificate before any LLM reasoning. Second, several classes (7, 8, 12, and often 2) require reasoning across sources or across time to distinguish a data fault from a real event, for example a real store closure from an unmapped store, or a real demand collapse from a frozen feed. This is where a language model that can read stage telemetry, source manifests, and operator notes may add value, and it is the basis of hypothesis H4.

### 3.5 A Taxonomy of Constraints as They Arrive

Constraints in the literature are parameters. Constraints in practice are documents. Table 3.3 catalogs the forms observed, the carrier in which they arrive, and the difficulty of formalizing them.

| Constraint form | Typical carrier | Example (paraphrased) | Formalization challenge |
| --- | --- | --- | --- |
| Per-variant pack multiple | Supplier product master | "Ship in multiples of six" | Integrality per variant |
| Minimum per supplier order (aggregate) | Contract, email | "Minimum order of one thousand units across the range" | Coupling across items and locations; supplier-level activation |
| MOQ in a foreign unit | MOQ file with per-product consumption | "Minimum one thousand meters of fabric; one garment of this size consumes 1.4 meters" | Dimensional analysis; per-variant conversion multipliers; aggregation over variants sharing a material |
| Size-curve packs | Buy sheets | "Order this model as a size curve 1/2/2/1" | Ratio constraints across variants of one product |
| Assortment eligibility | Seasonal implantation workbook per cluster or store type | "This product belongs to the winter assortment of cluster A stores" | Binary eligibility with a validity window; union semantics for an all-stores cluster |
| Drop and launch calendar | Implantation calendar with month labels | "The January drop belongs to the winter season that started the previous autumn" | Calendar parsing with year rollover; validity intervals |
| Season end and carry-over | Merchandising decisions | "Non-carry-over lines are not reordered after week N; mark down instead" | End-of-life rule; the alternative action is not an order |
| Lead time and arrival date | Purchase-order data, often incomplete | "Arrival unknown; assume order date plus four days" | Pipeline uncertainty; the assumption needs provenance |
| Capacity and open-to-buy | Planner limits | "Open-to-buy for the month is X" | Budget coupling across items |
| Supplier unknown | Campaign order sheets | "Supplier to be confirmed" | Nullable reference; mandatory escalation |
| Channel rules | Operating procedures | "The online warehouse also serves store returns" | Location-type rules affecting available stock |
| Transfer policy | Rebalancing files | "Transfer only between stores of the same cluster" | Transshipment graph restricted by cluster |

Table 3.3. Constraint forms observed in practice and their formalization challenges.

The constraint agent of the previous draft handled prose clauses about capacity and pack size. The taxonomy shows three additional requirements: unit conversion with per-variant multipliers, aggregation levels above the item, and eligibility windows that decide whether an item-location pair is even a legitimate target for an order. Workbooks, not prose, are the dominant carrier, and their semantics (season labels, month-to-season mapping, cluster unions) are conventions that must be extracted and verified, not assumed.

### 3.6 Decision Context Specifics

Several features of the decision context were consistent across retailers and are absent from stylized benchmarks.

- **Seasonality of the assortment, not only of demand.** Fashion and accessories retailers decide most volume in pre-season buys. In-season replenishment applies to a subset of carry-over lines. Items leave the assortment at season end and are marked down rather than reordered. The evaluation dataset used in this dissertation supports continuous replenishment items, so pre-season buying is out of scope and is stated as such.
- **Transfers as a first-class action.** Supplier purchase orders and inter-location transfers share one table and one reconciliation process. Rebalancing stock between stores of a cluster is routine and is frequently the cheaper response to a local shortage. The action space of the system therefore includes lateral transshipment.
- **Single sourcing dominates.** The supplier is often the brand or the retailer's own production. Multi-supplier allocation and supplier fairness, prominent in the previous draft, are secondary in this setting and are treated briefly.
- **Pipeline uncertainty, not only lead-time variance.** Open purchase orders frequently lack an arrival date. The system must reason about receipts whose timing is unknown and must record the assumption it makes.
- **Intermittent and censored demand at the variant level.** Size-level demand is sparse and is censored by stockouts. Prices are sometimes derived from sales, and multi-currency valuation depends on reference data that can be missing.
- **Planner artifacts are spreadsheets.** Rules, MOQ files, campaign orders, and assortments arrive as workbooks, sometimes in more than one natural language, and are loaded through one-shot procedures. An escalation packet that a planner can act on should look like the artifacts they already use.
- **Lineage is the first audit question.** When a recommendation looks wrong, operators check which run produced the underlying figures and whether the feed was complete before questioning the model. An LLM assistant already operated over the same schema is traced per session for the same reason. This ordering of audit questions motivates lineage as the first section of the decision trace.

### 3.7 Design Implications

Table 3.4 maps the observations of this chapter to the design decisions of Chapter 4 and the experimental choices of Chapter 5.

| Observation | Design decision |
| --- | --- |
| State has an age and a measurable completeness; a successful run can be partial | A deterministic state certificate is computed before any forecast or proposal; autonomy is a function of it |
| Most failure classes are detectable by schema invariants; some require cross-source reasoning | A rule-based certificate runs first; the LLM triages residual anomalies into typed hypotheses and never overrides a hard failure |
| Live tables are overwritten; snapshots are the replayable history | The trace references snapshot versions and run identifiers, never live tables |
| Constraints arrive as workbooks with unit, aggregation, and calendar semantics | Constraint schema carries unit, conversion, aggregation level, validity interval, and source reference; deterministic unit verification follows extraction |
| Eligibility decides whether an order is legitimate at all | Eligibility is a hard constraint in the formulation and an assortment layer in the simulator |
| Inter-location transfers are routine | Lateral transshipment within a cluster is part of the action space |
| Arrival dates are often unknown | Open orders carry scenario-dependent arrival periods and the assumption is recorded |
| Demand is censored by stockouts | Stockout flags from snapshots feed a censoring correction in the forecaster |
| Operators ask for lineage first | Lineage is the first category of the trace and the first panel of the audit interface |
| Pipelines already emit per-stage telemetry and invariant results | The system reuses them as evidence rather than re-deriving them |

Table 3.4. From observation to design decision.

---

## Chapter 4: Methodology and Architecture

### 4.1 Research Design

The study adopts a design-science approach with controlled empirical evaluation (Hevner et al., 2004). The artifact is a hybrid multi-agent replenishment system. Its utility is assessed in a closed-loop simulator through rolling-origin experiments, repeated stochastic runs, stress scenarios, state-quality perturbations, and ablations. Quantitative analysis measures cost, service, forecast quality, safety, reliability, and trace faithfulness. A human-subject or expert-review component, subject to institutional approval, compares audit performance across explanation formats. Development, tuning, and final evaluation scenarios are separated to limit overfitting to the benchmark.

### 4.2 Formal Replenishment Problem

The core is a stochastic mixed-integer program, extended relative to the previous draft with observed-versus-true state, eligibility, aggregate and foreign-unit MOQs, lateral transshipment, and uncertain arrivals.

```
Indices
  i  items          l, l'  locations          s  suppliers
  t  periods        w      demand / lead-time / arrival scenarios
  c  clusters of locations; cl(l) is the cluster of l

True and observed state at the start of period t
  H[i,l,t]      true on-hand           Hobs[i,l,t]  observed on-hand (from the snapshot)
  B[i,l,t]      backorders             O[i,l,s,t]   outstanding orders
  IP[i,l,t]  =  H + O - B              (the system decides on Hobs; evaluation uses H)
  e[i,l,t] in {0,1}   eligibility of item i at location l in period t (assortment)
  q[t] in [0,1]       state-quality score of the snapshot used for the decision

Decisions
  x[i,l,s,t] >= 0   order quantity in order units
  k[i,l,s,t]  integer   pack multiplier         x = pack[i,s] * k
  z[i,l,s,t] in {0,1}   item-line activation
  wA[s,t]    in {0,1}   supplier-order activation
  y[i,l,l',t] >= 0  lateral transshipment from l to l'

Constraints
  balance      N[i,l,t+1,w] = N[i,l,t,w] + A[i,l,t,w]
                              + sum_l' y[i,l',l,t-Ltr] - sum_l' y[i,l,l',t] - D[i,l,t,w]
  per-item MOQ MOQ[i,s] * z <= x <= M * z
  aggregate MOQ in the supplier's unit
               sum_{i,l} m[i,s] * x[i,l,s,t] >= MOQagg[s] * wA[s,t],     x <= M * wA[s,t]
               (m[i,s] converts order units to the supplier's unit, e.g. meters per garment)
  eligibility  x[i,l,s,t] <= M * e[i,l,t]         y[i,l,l',t] <= M * e[i,l',t]
  transfers    y[i,l,l',t] = 0 unless cl(l) = cl(l');    sum_l' y[i,l,l',t] <= Hobs[i,l,t]
  capacity     sum_{i,l} x[i,l,s,t] <= Cap[s,t]
  budget       sum_{i,l,s} unitCost[i,s,t] * x[i,l,s,t] + sum trCost * y <= Budget[t]
  arrivals     A[i,l,t,w] includes scheduled receipts whose arrival period is scenario-
               dependent when the purchase order carries no arrival date

Objective
  min  E_w[ purchase + fixed order + transshipment + holding + shortage + expedite + spoilage ]
       + lambda * CVaR_alpha( total cost )
```

The CVaR term follows Rockafellar and Uryasev (2000) and penalizes the expected cost in the worst alpha fraction of scenarios, addressing the tail-risk concerns of Long et al. (2026). The formulation is modular. Large experiments may use decomposition, scenario reduction, or a base-stock approximation, and the Orchestrator may invoke a simpler policy calculator for low-risk, uncoupled items and the full solver for coupled or high-value decisions.

Two definitions complete the problem. The **autonomy policy** maps evidence to a permission level:

```
  a[t] = pi( q[t], r[t], kappa[t], sigma[t] )  in  { advisory, approval, bounded, full }
    q      state-quality score of the decision's evidence
    r      decision risk (spend, deviation from the deterministic baseline, days of supply)
    kappa  confidence of the active constraint set
    sigma  forecast dispersion relative to history
```

The **safety-adjusted utility** used for cross-policy comparison is:

```
  U = -( E[cost] + lambda * CVaR_alpha )  -  cEsc * (#escalations)  -  cHarm * (#harmful executions)
```

A **harmful execution** is an executed order or transfer that, evaluated against the true state and true constraint set known to the simulator, violates a hard constraint or deviates from the oracle decision by more than a tolerance. This metric is available only in simulation and is the primary outcome for RQ2.

### 4.3 Blackboard Architecture over a Canonical Schema

Specialized agents communicate through typed, versioned JSON objects on a shared state store rather than through narrative text. Schemas specify units, timestamps, confidence, provenance, and validity windows. Each state transition receives a decision identifier and a hash. Natural-language messages may accompany the objects for negotiation and explanation, but downstream tools consume only typed fields.

Two changes distinguish this revision. First, the agents' only view of the retailer is the canonical schema of Table 3.1. They do not read source systems. This mirrors deployment, makes invariant checks portable, and lets the M5 evaluation exercise the same interface. Second, every object carries a lineage header: snapshot version, run identifier, and the state certificate under which it was produced. An object produced under one snapshot cannot be combined with an object produced under another without an explicit reconciliation step.

### 4.4 Agents and Their Verifiable Outputs

| Agent | Responsibility | Required machine-verifiable output |
| --- | --- | --- |
| State Reconciliation and Data-Quality Agent | Loads the decision's evidence from the snapshot, runs the invariant suite, computes the state-quality score, triages anomalies into typed hypotheses with evidence, reconciles sources where several exist | State certificate: per-table freshness, continuity, invariant results, score, unresolved discrepancies, hypotheses |
| Demand Forecast Agent | Selects and executes forecasting models, applies censoring correction, reconciles the hierarchy | Forecast artifact: quantiles or scenarios, calibration diagnostics, model and version, feature window, stockout-adjusted flags |
| Supplier and Constraint Agent | Retrieves contracts, workbooks, and events; converts them into typed constraints; verifies units and ranges | Constraint set: entity, scope, parameter, value, unit, conversion, aggregation level, validity interval, precedence, source reference, confidence |
| Replenishment Optimization Agent | Builds candidate plans with a policy calculator or the stochastic MILP, including transshipment | Feasible candidates, objective breakdown, active constraints, solver status and gap, solver certificate |
| Risk and Critic Agent | Runs independent checks: feasibility, dominance, unit consistency, inventory balance, policy limits, stress tests, injection screening | Pass, veto, or escalate with identified failure conditions and test evidence |
| Orchestrator and Autonomy Agent | Controls the workflow, resolves conflicts, evaluates the autonomy policy, assembles the trace or the escalation packet | Committed decision with autonomy level, or escalation packet |
| Execution and Monitoring Agent | Submits approved orders and transfers idempotently, monitors confirmations, receipts, and exceptions, attaches outcomes to the decision identifier | Execution receipt and post-decision outcome events |

Table 4.1. Specialized agents and their outputs.

Compared with the previous draft, the first agent is promoted from a reconciliation step to the gatekeeper of the cycle, and the Orchestrator's autonomy decision is made explicit as a policy over the certificates produced by the other agents.

### 4.5 Coordination Protocol

The cycle is: OBSERVE, CERTIFY STATE, then FORECAST and GROUND CONSTRAINTS in parallel, then PROPOSE, VERIFY, COMMIT, EXECUTE, MONITOR.

The Orchestrator does not proceed past CERTIFY STATE unless the certificate has no hard failures, or an approved exception is present. Candidate orders are produced only when all required typed fields are complete and carry the same lineage header. The Critic cannot modify a proposal. It returns structured objections and test evidence, the Optimization Agent may revise, and the Critic re-runs. A decision is committed when all hard checks pass and the autonomy policy grants a level at which execution is permitted. Otherwise an escalation packet is generated for a planner.

Coordination controls include schema validation, unit normalization, idempotency keys, timeouts, retry budgets, stale-state detection through the lineage header, maximum dialogue turns, and deterministic tool execution wherever possible. Each agent has an allowlist of tools and write permissions. If the LLM is unavailable, the system degrades to the deterministic baseline policy under the same state certificate, so that operational continuity does not depend on the model.

### 4.6 State Reconciliation and the Data-Quality Score

The state certificate is computed by code over the canonical schema, scoped to the evidence a specific decision uses (the item-location's inventory rows, its open orders, its sales history, the prices and eligibility that apply). Invariant families follow Table 3.2:

- **Freshness.** Age of each table's snapshot relative to the expected cadence.
- **Continuity.** Missing snapshot dates in the history window.
- **Completeness.** Expected item-location pairs present; source locations reconciled against the master.
- **Cardinality.** No duplicate keys in facts or open orders.
- **Range and ratio.** Non-negative stock and quantities; line total consistent with quantity and unit price; pack-aware plausibility.
- **Cross-source consistency.** Agreement between systems of record where more than one reports on-hand.
- **Movement consistency.** Stock at t approximately equals stock at t-1 plus receipts minus sales, within an adjustment tolerance.
- **Partial refresh.** Per-table freshness agrees within a run.
- **Restatement.** Historical periods unchanged since the previous snapshot beyond a tolerance.
- **Distribution shift.** Share of zero-stock rows and total on-hand within bounds of the previous snapshot.
- **Censoring.** Stockout flags derived for the forecaster.

Each check yields pass, warn, or hard fail, plus evidence. The score q aggregates warns with weights; any hard fail sets q to zero for the decision. The LLM's role is bounded. It receives flagged anomalies together with stage telemetry, source manifests, and any operator notes, and it proposes a typed hypothesis for each (for example "location L is present in the source manifest but absent from the master" versus "location L closed"), citing the evidence. Hypotheses feed the escalation packet and, where an approved resolution exists in memory, a proposed correction. The model cannot raise q, clear a hard fail, or edit state.

### 4.7 Constraint Extraction and Verification

Constraints arrive as structured fields, prose clauses, or workbook cells. The Supplier and Constraint Agent maps each to a schema with entity, scope (variant, product, supplier order, cluster), parameter, value, unit, conversion to the order unit, aggregation level, effective interval, source reference, precedence, and confidence.

The pipeline is retrieve, extract, normalize, validate, cross-check, and commit or escalate. Extraction uses structured LLM output constrained by the schema. Normalization is deterministic dimensional analysis: an MOQ in meters combined with a per-variant consumption in meters per unit yields an order-unit constraint at the aggregation level stated by the source, and an unresolvable unit is a hard failure. Validation checks ranges and feasibility of each constraint on its own. Cross-checking compares the extraction against a library of contract templates and adversarially varied wordings. Workbook semantics (season labels, month-to-season rollover, cluster unions, store types) are extracted as explicit typed conventions and verified against the location master and the calendar. Unknown or conflicting constraints, and any extraction below a confidence threshold, trigger escalation and are never resolved silently. Assumptions the system makes in the absence of data, such as a default arrival offset for an order without an arrival date, are themselves recorded as constraints with a provenance of "system default", so they appear in the trace and can be overridden.

### 4.8 Forecasting Module

Models are trained and compared with rolling-origin validation. Candidates include seasonal naive, Croston-style intermittent-demand methods and their bias corrections (Croston, 1972; Syntetos & Boylan, 2005), LightGBM quantile regression with lags and price and calendar features, DeepAR, the Temporal Fusion Transformer, and pretrained Chronos or Moirai models. Selection may be global, cluster-specific, or ensemble-based. Where the state certificate marks periods as stockouts, the forecaster applies a censoring correction in the spirit of lost-sales estimation (Nahmias, 1994), and records that it did. The Forecast Agent returns at minimum the median, service-relevant upper quantiles, scenario samples, calibration coverage, and a data-quality status inherited from the certificate. Item-store forecasts are reconciled to higher levels by trace minimization (Wickramasuriya et al., 2019).

### 4.9 Optimization and Policy Tools

The Optimization Agent chooses between a fast policy function and the mathematical program according to item criticality and constraint coupling. A base-stock calculator suffices for uncoupled, eligible items with per-item constraints. Aggregate MOQs, shared capacity, budgets, foreign-unit conversions, and transshipment couple items and locations and require the MILP. The LLM supplies a validated problem specification and interprets the solver output. It cannot alter the objective value or declare feasibility without a solver certificate. When the model is infeasible, the workflow retrieves an irreducible infeasible subsystem or equivalent diagnostic and asks the agent to propose a correction that is re-solved, following the solver-in-the-loop principle (Ao et al., 2026). Proposed corrections that relax a constraint sourced from a contract are escalated rather than applied.

### 4.10 Evidence-Gated Autonomy and Safety Controls

The architecture operates under four autonomy levels: advisory (proposal and trace for review), approval (a planner accepts or edits before execution), bounded-autonomous (execution within configured limits), and full (simulator or tightly controlled sandbox only). The previous draft assigned levels by item class. This revision computes the level per decision from the autonomy policy of Section 4.2. A high-value order on a fresh, complete snapshot with high-confidence constraints may execute autonomously within bounds. The same order on a snapshot with a continuity gap, or with a constraint extracted at low confidence, is downgraded to approval or advisory, and a hard state failure produces a hold with an escalation packet rather than any order.

Holding has a cost. A hold is bounded by a configurable budget of periods and by the projected service impact, after which the system escalates with urgency rather than continuing to hold. The evaluation compares hold budgets because the trade-off between a wrong order and a missed sale is empirical.

Hard controls include spend caps, maximum percentage change from the deterministic baseline, maximum days of supply, prohibition of negative, non-pack, or ineligible quantities, duplicate-order prevention through idempotency keys, policy version pinning, two-person approval for high-risk actions, cancellation and rollback procedures, and immutable execution receipts. Escalation is mandatory for new or unknown suppliers, conflicting or low-confidence constraints, state hard failures, unresolved cross-source discrepancies, high-value orders, extreme forecast shifts, and unavailable verification tools. Supplier documents and workbook cells are treated as untrusted data; the Critic screens them for instructions, and executable constraint changes require an authenticated source.

### 4.11 Native Structured Decision Trace with Lineage

Every proposed or executed order creates a structured trace. The trace is a causal audit object whose fields can be checked against external artifacts, not a dump of hidden chain-of-thought. A human-readable explanation is generated only after the record is complete. Fields span seven categories:

1. **Identity and timing:** decision identifier, item-location-supplier, timestamp, policy version, autonomy level granted and the policy inputs that produced it.
2. **Lineage:** snapshot version and date, run identifier, per-table freshness, continuity, invariant results, state-quality score, anomalies and their typed hypotheses, censoring flags.
3. **Evidence:** source record identifiers or hashes, reconciliation results, forecast model and version, quantiles or scenarios, data-quality status.
4. **Constraints:** normalized values, units and conversions, aggregation level, source clauses or cells, validity intervals, precedence, confidence, whether each constraint was active at the optimum, and system defaults used in place of missing data.
5. **Alternatives:** candidate quantities including transfers, expected cost and service, solver status and gap, reasons for rejection.
6. **Verification:** critic tests, stress scenarios, detected risks, vetoes, revisions, injection screening, residual uncertainty.
7. **Commit and execution:** selected action, approval or override, idempotency key, ERP or supplier response, later outcome events.

A trace is complete only if the final quantity can be recomputed from the referenced snapshot, constraint set, and tools with pinned versions. Outcome events attach to the same decision identifier and are retrievable by the memory component for analogous cases, including approved resolutions of state anomalies.

---

## Chapter 5: Experimental Design and Evaluation Protocol

### 5.1 Data: The M5 Retail Hierarchy

The empirical dataset is the public M5 retail dataset. It records daily unit sales of 3,049 items in ten stores across three US states, organized into three categories and seven departments, from 29 January 2011 to 19 June 2016 (1,941 days), with weekly selling prices per store-item and a calendar of events and food-assistance days (Makridakis et al., 2022a). The 30,490 bottom-level item-store series aggregate into 42,840 series across twelve levels. The uncertainty track's quantile formulation is directly compatible with safety-stock and chance-constrained replenishment (Makridakis et al., 2022b). A rolling-origin split preserves temporal order and prevents leakage.

M5 supports continuous-replenishment items with intermittent demand and observable price and calendar effects. It contains no inventory, no suppliers, no size dimension, and no seasonal assortment. Those gaps are filled by the layers of Section 5.3 and are stated as limitations where they cannot be filled.

### 5.2 Mapping M5 into the Canonical Data Model

The dataset is loaded into the canonical schema of Table 3.1 so that the agents see the interface they would meet in deployment.

| Canonical entity | M5 source | Mapping |
| --- | --- | --- |
| Locations | 10 stores in 3 states | Store to location of type store; state to region; cluster equals state (4, 3, and 3 stores) |
| Families, categories, products, variants | 3 categories, 7 departments, 3,049 items | Category to family; department to category; item to product with one variant |
| Prices | Weekly sell prices per store-item | Price rows with validity windows and a single currency |
| Orders and line items | Daily unit sales | One aggregated line per item-store-day; channel store |
| Calendar and events | Calendar file | Exogenous forecasting features |
| Suppliers, supplier products | None | Synthetic: one supplier per department (brand-as-supplier), contracts sampled from the supply layer |
| Transfers | None | Simulator-generated purchase orders and inter-store transfers |
| Live inventory, inventory snapshots | None | Simulator-generated after warm-up; observed through the state-quality layer |
| Catalogs and assortments | Derivable | Eligibility from each item-store's first recorded sale, plus optional synthetic seasonal rotation delivered as workbooks |

Table 5.1. Mapping of M5 into the canonical replenishment data model.

### 5.3 Disturbance Layers

Three versioned layers surround the demand data. All generation parameters are versioned and released with the code so that experiments are reproducible and sensitivity analyses can vary realism.

**Supply and constraint layer.** Supplier assignments are created at department level. Lead times follow discrete distributions with seasonality and disruption regimes. Per-item MOQs and pack sizes are sampled from category-specific ranges. A subset of suppliers carries an aggregate MOQ per supplier order, and a subset of departments carries a foreign-unit MOQ over a shared material with per-item consumption multipliers, mirroring Table 3.3. Supplier capacities and budgets are calibrated to produce both slack and binding cases. Partial fills, cancellations, late deliveries, and temporary outages are simulated, and a configurable share of purchase orders is delivered without an arrival date. Constraints are rendered into their realistic carriers: prose clauses generated from templates with adversarial wording variants, and workbook files with the season, drop, and cluster conventions of Section 3.5, so that the constraint agent is tested on documents rather than parameters.

**Assortment eligibility layer.** Many M5 series begin with a long run of zeros before the first sale, which is read as the item not yet being carried at that store. Eligibility is therefore derived from the first recorded sale per item-store. An optional seasonal rotation assigns a fraction of items to seasons with drop calendars per cluster and an end-of-season rule for non-carry-over items, delivered as implantation workbooks. Lateral transshipment is permitted within a cluster with a transfer cost and a short lead time (Paterson et al., 2011).

**State-quality perturbation layer.** The simulator keeps the true state and exposes to the system an observed state produced by perturbation operators implementing the classes of Table 3.2: dropped snapshot days, frozen feeds, selectively stale tables, duplicated rows, quantities scaled by a pack factor, mislabeled currency, a hidden location, aliased suppliers, placeholder items, dropped orphan facts, corrupted or missing purchase-order fields, restated history, a zeroed inventory field, and censoring that arises naturally from stockouts. Each operator has an onset process, a duration distribution, and a magnitude.

**Calibration protocol.** Class frequencies, durations, and co-occurrence are calibrated from the monitoring telemetry and incident records described in Chapter 3, pooled across retailers so that no retailer is identifiable, and published as ranges rather than point values. Classes observed only as isolated incidents are treated as rare-event scenarios rather than rates. Every experiment is repeated at half, once, and twice the calibrated rates and under a purely synthetic configuration, so that conclusions do not hinge on one platform's history.

### 5.4 Inventory Initialization and Simulation State

Because M5 contains sales rather than inventory, the simulator reconstructs feasible starting states with a warm-up period. Initial on-hand stock is based on forecasted lead-time demand plus a service-level safety factor, and open orders are seeded from historical demand and supplier lead times. Each step updates sales, lost sales or backorders, receipts, transfers, true on-hand, inventory position, storage utilization, budget consumption, and outstanding orders, then writes the daily snapshot that the observed state is derived from. The same exogenous random streams are used across policies to support paired comparisons.

### 5.5 Baseline Policies and Ablations

| ID | Policy or system | Purpose |
| --- | --- | --- |
| B1 | Seasonal naive + order-up-to | Transparent benchmark; safety stock from historical error |
| B2 | LightGBM quantile + (s, S) | Strong retail feature baseline with an explicit reorder policy |
| B3 | Probabilistic deep model + stochastic MILP | Forecast-and-optimization benchmark without an LLM |
| B4 | B3 + rule-based state-quality gate | Tests whether deterministic gating alone captures the benefit of evidence gating, without any LLM |
| B5 | Time-series foundation model + policy | Tests zero-shot or lightly adapted Chronos and Moirai forecasts |
| B6 | Single LLM agent + the same tools | Controls for whether specialized agents add value |
| B7 | Multi-agent, free-form messages | Tests the value of typed state and schemas |
| B8 | Typed multi-agent without critic | Measures the safety contribution of adversarial verification |
| B9 | Typed multi-agent + critic, fixed autonomy | Isolates the contribution of evidence-gated autonomy |
| B10 | Proposed full system | Typed MAS + critic + evidence-gated autonomy + lineage trace + bounded execution |

Table 5.2. Baselines and ablations.

B4 and B9 are new. B4 asks whether the LLM is necessary at all for state gating; B9 asks whether gating adds anything once a critic is present. Together with B10 they address hypothesis H4 directly.

### 5.6 Evaluation Metrics

Evaluation spans six groups.

- **Forecast quality:** WRMSSE, weighted scaled pinball loss, CRPS, interval coverage, calibration error (Gneiting & Raftery, 2007).
- **Inventory and operations:** expected total cost and its components (holding, shortage, purchase, transfer), fill rate, cycle service level, stockout rate, backorder duration, inventory turns, days of supply, spoilage.
- **Supply-chain dynamics:** bullwhip ratio and upstream order amplification, including under the agent bullwhip protocol of Long et al. (2026) with demand held fixed.
- **State-quality handling:** detection precision and recall per failure class against injected perturbations, time to detect, harmful-execution rate, autonomy calibration (the relationship between granted autonomy and realized decision error), escalation precision (share of escalations the oracle would also have flagged), hold cost.
- **Constraint grounding:** exact-match accuracy on typed fields including unit and aggregation level, false-constraint rate, share of residual errors reaching the solver, escalation rate on low confidence.
- **Agentic performance and reliability:** task success rate, valid tool-call rate, schema errors, hallucinated fields, constraint violations, dialogue turns, latency, tokens, escalation rate, mean and tail cost, 95th and 99th percentile regret, run-to-run variance, sensitivity to prompt paraphrase.

Safety-adjusted utility (Section 4.2) is the summary outcome for cross-policy comparison under shocks.

### 5.7 Trace Faithfulness Evaluation

| Metric | Operational definition |
| --- | --- |
| Completeness | Fraction of mandatory lineage, evidence, and decision fields present and valid |
| Lineage correctness | Whether the referenced snapshot version, run identifier, and invariant results match the simulator's log for that decision |
| Evidence precision | Fraction of cited evidence actually consumed by a tool or decision rule |
| Evidence recall | Fraction of materially used evidence represented in the trace |
| Contradiction rate | Inconsistencies between narrative claims and logged numerical artifacts |
| Replay consistency | Whether replaying the recorded snapshot, constraint set, model, and solver reproduces the action |
| Counterfactual sensitivity | Whether changing a cited decisive factor changes the decision in the predicted direction |
| Deletion faithfulness | Decision change after removing or masking a claimed important factor |
| Stability | Trace and action similarity across semantically equivalent prompts and random seeds |
| Human utility | Audit accuracy, time, calibrated trust, and quality of overrides |

Table 5.3. Metrics for the native decision trace.

Counterfactual tests change one factor at a time: supplier capacity, lead time, forecast upper quantile, budget, service target, eligibility, and, new in this revision, the state-quality score and individual invariant results. The trace should identify the factor if it is decisive, and the action should move consistently with inventory theory. For deletion tests, an evidence item is removed from the agent context and the system re-run; a rationale that claims a factor is decisive but yields the same action without it is marked potentially unfaithful. Replay uses pinned model versions and deterministic seeds to distinguish trace incompleteness from stochastic variance.

### 5.8 Stress Tests and Robustness Scenarios

| Group | Scenario | Intervention | Primary test |
| --- | --- | --- | --- |
| Demand and supply | Normal | Historical-style demand, calibrated lead times | Baseline efficiency and service |
|  | Promotion spike | Abrupt demand increase with a known or unknown promotion flag | Forecast adaptation and exception reasoning |
|  | Lead-time shift | Supplier delay distribution changes mid-run | Pipeline awareness and safety-stock response |
|  | Capacity cut | Temporary 30 to 60 percent supplier capacity reduction | Constraint compliance and allocation |
|  | Supplier failure | One supplier unavailable for several periods | Transshipment, escalation |
|  | Heavy-tail demand | Rare extreme demand events | CVaR behavior and tail reliability |
| Constraint semantics | MOQ or pack change | Contract rule changed in prose | Extraction and version validity |
|  | Aggregate MOQ | Supplier-order minimum introduced by email | Coupled formulation; batching across items |
|  | Foreign-unit MOQ | Material minimum in meters with per-item consumption | Unit conversion and verification |
|  | Eligibility change | New drop workbook adds and removes item-cluster pairs | Eligibility as a hard constraint |
|  | Season end | Non-carry-over items leave the assortment | Refusal to reorder; alternative action |
| State quality | Feed gap | Snapshot missing for 1 to 5 consecutive days | Freshness and continuity gating |
|  | Partial refresh | Inventory stale, orders and products current | Per-table freshness; harmful-order avoidance |
|  | Stale-but-fresh | Feed frozen with new timestamps | Content-hash detection |
|  | Duplicate ingestion | Sales and open orders doubled for a window | Cardinality checks |
|  | Unit inflation | Quantities loaded in packs as units | Ratio invariants; MOQ misjudgment avoided |
|  | Unmapped location | One store's stock and sales hidden | Cross-source reasoning versus real closure |
|  | Derived-field collapse | Inventory zeroed for a department | Distribution-shift detection; mass-reorder avoidance |
|  | Historical restatement | Past sales revised downward | Forecast stability; replay consistency |
|  | Open-order integrity | Arrival dates and suppliers missing on open orders | Recorded assumptions; escalation |
| Adversarial | Injected instruction | Supplier note or workbook cell asks the agent to ignore policy | Tool permissions and injection resistance |
| Network | Transshipment enabled | Intra-cluster transfers allowed | Cost of rebalancing versus ordering |

Table 5.4. Robustness and safety scenarios.

### 5.9 Human Audit Study

Subject to institutional approval, a within-subject study presents planners or graduate students with an inventory background with decision packets drawn from simulator runs. Packets include correct decisions and known-bad decisions of three kinds: decisions made on degraded state, decisions based on a wrongly extracted constraint, and decisions with a poor forecast. Three explanation formats are compared in counterbalanced order: a free-form rationale, a structured trace without the lineage section, and the full trace with lineage. Outcomes are audit time, accept-or-override accuracy, detection rate of degraded-state decisions, calibration of stated confidence against correctness, and perceived workload. The lineage-less arm isolates the contribution of lineage from that of structure. Sample size is set from a pilot.

### 5.10 Statistical Analysis

Policies are evaluated on identical rolling windows and random streams. Each stochastic scenario uses at least 30 independent replications, with more added if confidence intervals remain wide. Paired bootstrap confidence intervals compare cost, service, and harmful-execution outcomes. Wilcoxon signed-rank tests or paired t-tests are chosen after inspecting paired differences, and effect sizes accompany p-values. Mixed-effects models estimate policy effects while accounting for item, store, category, scenario, and failure-class heterogeneity. Detection metrics are reported with confidence intervals per failure class. Tail outcomes use quantile estimates and CVaR. Multiple comparisons across ablations are controlled. All seeds, prompts, model versions, layer parameters, and environment versions are logged.

---

## Chapter 6: Expected Findings and Implications

### 6.1 Operational Performance under Clean State

Under clean state, the full system is expected to outperform single-agent LLM baselines on cost and service because quantitative decisions are anchored in deterministic solvers, and to approximate the stochastic MILP baseline (B3) on average cost because both rely on the same formulation (H1). Relying on stable probabilistic forecasts and enforcing policy limits through the Critic is expected to reduce run-to-run instability and upstream order amplification relative to LLM-only policies, addressing the agent bullwhip effect (Long et al., 2026). The system is not expected to beat a well-calibrated optimizer on clean data. Its case rests on what happens when data and constraints are not clean.

### 6.2 Where Failures Originate: Evidence Gating versus Critic Review

The comparison among B3, B4, B9, and B10 under the state-quality layer is the central experiment of the revision. Consistent with Chapter 3, the expectation is that harmful executions under calibrated perturbations arise predominantly from degraded state and misread constraints rather than from optimizer error, so that B3 and B9 show similar harmful-execution rates while B4 and B10 show substantially lower ones (H4). The Critic, which checks the proposal against the state it was given, is expected to catch few of these cases, because a proposal can be internally consistent with a wrong snapshot.

The B4 versus B10 comparison is expected to be nuanced. On classes detectable by single-table invariants (feed gap, duplicate ingestion, unit inflation, derived-field collapse), the rule gate is expected to capture most of the benefit. On classes requiring cross-source or narrative reasoning (unmapped location versus real closure, restatement, constraint change announced in prose), the LLM-triaged hypotheses are expected to reduce both missed detections and false escalations. If this pattern holds, the managerial implication is that deterministic gating should be adopted first and that LLM involvement should be reserved for the residual, which is a more conservative and more defensible deployment recipe than a fully agentic pipeline.

### 6.3 Constraint Grounding

Typed extraction with structured output is expected to reach high exact-match accuracy on templated clauses and to degrade on aggregate and foreign-unit forms and on workbook conventions with calendar rollover (H5). Deterministic unit verification is expected to convert most residual extraction errors into escalations rather than solver inputs. The foreign-unit MOQ scenario is expected to be the most discriminating: a system that ignores conversion will either under-order below the material minimum or over-order by the conversion factor, and both are visible as harmful executions.

### 6.4 Specialization, Typed State, and Coordination Cost

Ablations against a single tool-using LLM (B6) and a free-form multi-agent system (B7) are expected to show that the separation of concerns, in which one agent certifies state, another grounds constraints, a third formulates the program, and a fourth critiques, prevents the model from silently reconciling contradictions to reach a plausible answer. Typed, schema-validated objects with lineage headers are expected to reduce grounding errors, invalid tool calls, and token consumption relative to free-form conversation (H3). Coordination costs (latency, escalation volume) are expected to rise with the number of certificates, and the hold budget experiments are expected to show a real trade-off between avoided harmful orders and missed sales that must be set by policy rather than assumed away.

### 6.5 Trace Faithfulness and Human Audit

The structured trace is expected to achieve near-perfect replay consistency because it records the exact snapshot, constraint set, and solver inputs. Counterfactual and deletion tests are expected to show high causal sensitivity, including for state-quality factors: lowering the score of a snapshot cited as adequate should downgrade the autonomy level in the replay (H6). In the audit study, structure alone is expected to improve accept-or-override accuracy on constraint and forecast errors, while lineage is expected to account for most of the improvement in detecting decisions made on degraded state, because that is the information a planner needs to see and a free-form rationale rarely contains (H7).

### 6.6 Transferability and Managerial Implications

Because the agents operate only on the canonical schema, results are expected to transfer to any retailer loaded into the same model, which is the deployment path in practice. The dissertation expects to offer a graded adoption recipe: deterministic state certificates and lineage traces first, because they carry most of the safety benefit and require no language model; typed constraint grounding second, with mandatory escalation below a confidence threshold; LLM triage and bounded autonomy last, and only for item classes where observed reliability supports it.

---

## Chapter 7: Ethical, Safety, and Governance Considerations

### 7.1 Automation Bias and Accountability

A well-formatted trace may increase trust even when the underlying action is poor (Parasuraman & Riley, 1997). Reviewers must be trained to treat the trace as auditable evidence rather than as authority, and the interface must expose uncertainty, failed checks, held decisions, and alternatives, not only the selected recommendation. Responsibility for procurement policy and high-risk approvals remains with the organization. The system must make unambiguous whether an action was proposed, approved, modified, held, or executed autonomously, and at what autonomy level and on what evidence, and this record must be immutable.

### 7.2 Data Quality as a Safety Property

Treating state quality as a gate shifts risk from wrong orders to delayed orders. A hold on uncertified state can itself cause a stockout, and the hold budget makes this trade-off explicit and configurable rather than hidden. The system must communicate to planners why a decision is held, in terms of the failing check and its evidence, and must never present a held decision as a recommendation to do nothing. The calibration of the perturbation layer uses pooled, anonymized telemetry only, and no retailer's commercial data is used or reported.

### 7.3 Security and Prompt Injection

Supplier messages, operational notes, and workbook cells are untrusted inputs and a known vector for indirect prompt injection (Greshake et al., 2023). The architecture separates data from instructions, restricts tool permissions per agent, validates schemas, and requires authenticated sources for executable constraint changes. The Critic explicitly screens inputs that ask the model to ignore policy, reveal data, or call unauthorized tools. Execution endpoints use idempotency keys and least privilege to prevent duplicate or unauthorized orders.

### 7.4 Supplier Concentration

Where multiple suppliers exist, an optimizer may favor those with lower cost or lead-time variance and create concentration effects. Because single sourcing dominates in the setting studied, this concern is secondary here, but supplier allocation and concentration are reported alongside cost, and diversification policies must be represented as explicit constraints rather than assumed to emerge from optimization.

### 7.5 Environmental and Economic Externalities

Higher service targets may raise inventory, transport, and emissions. Where data permit, a carbon or waste cost can be added to the objective. The computational cost of LLM calls is reported through tokens, latency, and model size, and the B4 ablation tests directly whether a deterministic policy suffices for routine items.

### 7.6 Limitations

External validity is the primary limitation. The supplier and constraint layers are semi-synthetic, the taxonomy of Chapter 3 comes from a single platform with a specific integration architecture, and M5 is a grocery and household dataset whereas much of the motivating experience comes from seasonal fashion and accessories. Pre-season buying, size curves, and markdowns are out of scope. Public sales data record observed rather than true demand. LLM behavior changes across versions, and proprietary models limit reproducibility. A structured trace verifies external evidence and tool use but cannot prove correspondence with latent neural computation. Human audit findings from a small sample may not generalize to professional planners under time pressure.

---

## Chapter 8: Conclusion

### 8.1 Summary of Contributions

This dissertation reframes autonomous replenishment as a problem of earning autonomy from evidence. Its contributions are: (1) a practice-grounded, anonymized account of how replenishment state and constraints are actually produced across many retailers, with taxonomies of state-quality failures and constraint forms; (2) a canonical replenishment data model and a mapping of the M5 dataset onto it, so that agents are evaluated on a deployment-realistic interface; (3) a modular, typed, tool-grounded multi-agent architecture in which state certification and constraint grounding are verified stages and autonomy is a per-decision policy over evidence quality, decision risk, constraint confidence, and forecast dispersion; (4) a closed-loop benchmark with versioned supply, eligibility, and state-quality layers, the last calibrated from operational telemetry; (5) a decision trace with data lineage and an evaluation protocol for its faithfulness; and (6) controlled evidence on where deterministic checks suffice and where language-model reasoning adds value, translated into a graded adoption recipe.

### 8.2 Limitations

The limitations of Section 7.6 apply. In addition, the calibration of the perturbation layer reflects one platform's history and is therefore reported as ranges with sensitivity sweeps, and the harmful-execution metric requires a simulator oracle and has no direct field equivalent beyond post-hoc audit.

### 8.3 Future Directions

The most valuable next step is a live, approval-gated deployment on the platform that motivated the design, in which the state certificate and lineage trace are introduced first, without any autonomous execution, and planner interaction data is used to calibrate autonomy thresholds against observed decision quality. Extending the decision space to pre-season buys with size curves and to markdown decisions would cover the dominant volume in fashion retail. Learning the autonomy policy itself, for example with the GRPO-based post-training that Long et al. (2026) used to reduce agent bullwhip, is a promising direction, as are data-quality-aware forecasting models that consume the state certificate directly, multi-enterprise negotiation, and the application of the lineage-bearing trace protocol to other operational domains in which automated decisions consume pipeline-produced state.

---

## References

Ansari, A. F., Stella, L., Turkmen, C., Zhang, X., Mercado, P., Shen, H., Shchur, O., Rangapuram, S. S., Arango, S. P., Kapoor, S., Zschiegner, J., Maddix, D. C., Wang, H., Mahoney, M. W., Torkkola, K., Wilson, A. G., Bohlke-Schneider, M., & Wang, Y. (2024). Chronos: Learning the language of time series. *Transactions on Machine Learning Research*. [https://arxiv.org/abs/2403.07815](https://arxiv.org/abs/2403.07815)

Ao, R., Simchi-Levi, D., & Wang, X. (2026). OptiRepair: Closed-loop diagnosis and repair of supply chain optimization models with LLM agents. *arXiv preprint arXiv:2602.19439*. [https://arxiv.org/abs/2602.19439](https://arxiv.org/abs/2602.19439)

Arcuschin, I., Janiak, J., Krzyzanowski, R., Rajamanoharan, S., Nanda, N., & Conmy, A. (2025). Chain-of-thought reasoning in the wild is not always faithful. *arXiv preprint arXiv:2503.08679*. [https://arxiv.org/abs/2503.08679](https://arxiv.org/abs/2503.08679)

Chen, F., Drezner, Z., Ryan, J. K., & Simchi-Levi, D. (2000). Quantifying the bullwhip effect in a simple supply chain: The impact of forecasting, lead times, and information. *Management Science, 46*(3), 436–443. [https://doi.org/10.1287/mnsc.46.3.436.12069](https://doi.org/10.1287/mnsc.46.3.436.12069)

Clark, A. J., & Scarf, H. (1960). Optimal policies for a multi-echelon inventory problem. *Management Science, 6*(4), 475–490. [https://doi.org/10.1287/mnsc.6.4.475](https://doi.org/10.1287/mnsc.6.4.475)

Croston, J. D. (1972). Forecasting and stock control for intermittent demands. *Operational Research Quarterly, 23*(3), 289–303. [https://doi.org/10.1057/jors.1972.50](https://doi.org/10.1057/jors.1972.50)

DeHoratius, N., & Raman, A. (2008). Inventory record inaccuracy: An empirical analysis. *Management Science, 54*(4), 627–641. [https://doi.org/10.1287/mnsc.1070.0789](https://doi.org/10.1287/mnsc.1070.0789)

Gneiting, T., & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *Journal of the American Statistical Association, 102*(477), 359–378. [https://doi.org/10.1198/016214506000001437](https://doi.org/10.1198/016214506000001437)

Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., & Fritz, M. (2023). Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection. *Proceedings of the 16th ACM Workshop on Artificial Intelligence and Security (AISec '23)*, 79–90. [https://doi.org/10.1145/3605764.3623985](https://doi.org/10.1145/3605764.3623985)

Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information systems research. *MIS Quarterly, 28*(1), 75–105. [https://doi.org/10.2307/25148625](https://doi.org/10.2307/25148625)

Jannelli, V., Schoepf, S., Bickel, M., Netland, T., & Brintrup, A. (2024). Agentic LLMs in the supply chain: Towards autonomous multi-agent consensus-seeking. *arXiv preprint arXiv:2411.10184*. [https://arxiv.org/abs/2411.10184](https://arxiv.org/abs/2411.10184)

Kang, Y., & Gershwin, S. B. (2005). Information inaccuracy in inventory systems: Stock loss and stockout. *IIE Transactions, 37*(9), 843–859. [https://doi.org/10.1080/07408170590969861](https://doi.org/10.1080/07408170590969861)

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

Parasuraman, R., & Riley, V. (1997). Humans and automation: Use, misuse, disuse, abuse. *Human Factors, 39*(2), 230–253. [https://doi.org/10.1518/001872097778543886](https://doi.org/10.1518/001872097778543886)

Parasuraman, R., Sheridan, T. B., & Wickens, C. D. (2000). A model for types and levels of human interaction with automation. *IEEE Transactions on Systems, Man, and Cybernetics, Part A, 30*(3), 286–297. [https://doi.org/10.1109/3468.844354](https://doi.org/10.1109/3468.844354)

Paterson, C., Kiesmüller, G., Teunter, R., & Glazebrook, K. (2011). Inventory models with lateral transshipments: A review. *European Journal of Operational Research, 210*(2), 125–136. [https://doi.org/10.1016/j.ejor.2010.05.048](https://doi.org/10.1016/j.ejor.2010.05.048)

Quan, Y., & Liu, Z. (2024). InvAgent: A large language model based multi-agent system for inventory management in supply chains. *arXiv preprint arXiv:2407.11384*. [https://arxiv.org/abs/2407.11384](https://arxiv.org/abs/2407.11384)

Rockafellar, R. T., & Uryasev, S. (2000). Optimization of conditional value-at-risk. *Journal of Risk, 2*(3), 21–41. [https://doi.org/10.21314/JOR.2000.038](https://doi.org/10.21314/JOR.2000.038)

Salinas, D., Flunkert, V., Gasthaus, J., & Januschowski, T. (2020). DeepAR: Probabilistic forecasting with autoregressive recurrent networks. *International Journal of Forecasting, 36*(3), 1181–1191. [https://doi.org/10.1016/j.ijforecast.2019.07.001](https://doi.org/10.1016/j.ijforecast.2019.07.001)

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

This appendix records what changed between the previous draft and this one, and why, so that the revision can be reviewed as a set of decisions.

**Thesis and title.** The previous draft argued that an LLM should coordinate while tools compute and a trace explains. This draft keeps that position and adds a stronger claim: autonomy must be earned per decision from verifiable evidence quality, because in practice the dominant risk to an automated order is degraded state and misread constraints rather than the optimizer. The title was changed to name that claim.

**New Chapter 3.** An anonymized, practice-grounded chapter describes how replenishment state is produced by nightly batch integration across many retailers, and catalogs fourteen state-quality failure classes and twelve constraint forms as they arrive. No retailer is named and no commercial data is used.

**Research questions and hypotheses.** RQ2 (evidence gating), RQ3 (constraint grounding of realistic forms), and RQ7 (audit detection of degraded-state decisions) are new or sharpened. H4, H5, and H7 are new. H1, H2, H3, H6, and H8 carry over.

**Formal model.** Added observed versus true state, assortment eligibility, aggregate MOQs and MOQs in a foreign unit with per-item conversion, lateral transshipment within a cluster, scenario-dependent arrivals for orders without an arrival date, an explicit autonomy policy over evidence, a safety-adjusted utility, and the definition of a harmful execution.

**Architecture.** The Inventory State Agent becomes the State Reconciliation and Data-Quality Agent and gates the cycle with a deterministic state certificate. The Orchestrator's autonomy decision is an explicit policy. The protocol adds a CERTIFY STATE step. Every typed object carries a lineage header. Constraint schemas carry unit, conversion, aggregation level, and confidence. System defaults used in place of missing data are recorded as constraints with provenance. A bounded hold action with an explicit hold budget replaces silent continuation on uncertified state.

**Decision trace.** Lineage (snapshot version, run identifier, freshness, invariant results, quality score, anomaly hypotheses) becomes the second category of the trace and the first panel of the audit interface, because it is the first question operators ask.

**Experimental design.** M5 is loaded into the canonical data model. Three versioned disturbance layers replace the single semi-synthetic supplier layer, and the state-quality layer is calibrated from pooled telemetry with sensitivity sweeps and a purely synthetic control. Baselines B4 (rule-gated deterministic pipeline) and B9 (fixed-autonomy multi-agent system) are added. Metrics add state-quality detection, harmful-execution rate, autonomy calibration, escalation precision, hold cost, and constraint-grounding accuracy. Scenarios add constraint-semantics, state-quality, and transshipment groups. The audit study adds a lineage-less arm.

**Literature.** Added inventory record inaccuracy, censored demand and intermittent forecasting, data-quality dimensions, lateral transshipment, human-automation interaction, indirect prompt injection, and design-science method. Citations switched to author-year style with an alphabetical reference list.

**De-emphasized.** Multi-supplier allocation and supplier fairness, which are secondary where the supplier is the brand. Free-form agent negotiation, retained only as an ablation baseline. Item-class-based autonomy levels, replaced by per-decision evidence gating.

**Unchanged.** The M5 dataset as the sole evaluation dataset. The blackboard architecture with typed JSON objects. The Critic that cannot modify proposals. The CVaR-augmented objective. The trace-faithfulness protocol of replay, counterfactual, and deletion tests. The seven-agent decomposition, now with revised responsibilities.
