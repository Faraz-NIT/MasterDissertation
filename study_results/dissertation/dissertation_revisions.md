@@ paragraph 1
A Research Dissertation — completed simulation studies integrated, October 2026

@@ paragraph 4
Design science with completed controlled simulations and software audits; human-audit evaluation proposed as future work

@@ replace 12
Retail replenishment depends on more than an accurate demand forecast. Inventory records, incoming orders and supplier terms must also be reliable enough to support an executable decision. This dissertation examines how large language model (LLM) agents can assist that process while remaining subject to explicit operational controls. It develops a hybrid architecture in which language models interpret bounded document evidence and request tools, while deterministic components certify the state, generate forecasts, optimize quantities and decide whether execution is permitted.

The design is informed by retail standards and the literature on inventory, data quality and automation. Two completed computational studies used thirty selected M5 item-store series with simulated inventory, suppliers and disturbances. The first comprised 360 numerical runs across thirty simulation seeds, eight two-day prose feasibility runs and four structured-rule controls. The second evaluated four matched parser/LLM and recovery/no-recovery configurations over fourteen days, two seeds and four scenarios, producing 32 runs and 448 decision traces.

The numerical study showed the importance of evidence controls: under a missing-feed disturbance, the ungated optimizer recorded 63 hard-constraint violations, compared with none for its gated counterpart. The initial local LLM configuration failed to produce an executable replenishment decision because its constraint extraction was incomplete or dimensionally incorrect. After the extraction task was narrowed and independently checked, the second study recorded 186 nonzero replenishment actions across the model-enabled arms and no committed-plan hard violations. Verified recovery of corrupted derived inventory reduced mean simulated cost from USD 894.30 to USD 796.51 and raised fill rate from 89% to 96%.

These findings support a practical role for LLM agents within a governed replenishment workflow. They do not establish an additional economic advantage from the language model: the strongest parser achieved the same operational results, and only ten of twenty model recovery choices followed the instruction. The contribution is a demonstrated way to combine bounded language interpretation with verifiable decisions, together with a managerial framework for deciding where such assistance is worth its cost. Short horizons, synthetic supplier documents and two seeds in the second study limit generalization; field return on investment and human-audit benefits remain untested.

@@ front
# Executive Summary

For a retail manager, the attraction of an LLM agent is its ability to work with the information that sits around an optimization model: a supplier note, a changed limit, an exception in an inventory feed or an explanation requested by a planner. The experiments examined whether that assistance could be incorporated without weakening the controls over purchase and transfer decisions. The results show that it can, provided the language model has a narrow task and its output remains subject to independent checks.

The clearest operating improvement came from restoring usable evidence. In the fourteen-day pilot, a simulated integration error caused a derived stock field to collapse even though the underlying source and movement records remained available. Verified recovery reduced average portfolio cost by USD 97.79, or 10.93%, and improved fill rate by seven percentage points. The recovery tool also refused to repair stale-feed cases where current evidence was absent. This distinction matters commercially: recovering a demonstrably wrong calculation is different from inventing missing stock information.

The LLM-assisted system maintained the same cost and service outcomes as a capable deterministic parser. Its bounded extraction calls returned all 76 submitted numeric terms correctly, and the two model-enabled configurations executed 186 nonzero replenishment actions without a recorded hard violation. However, the model selected recovery incorrectly in ten stale-feed cases. Independent eligibility checks blocked those requests. Managers should therefore view the successful execution boundary as a property of the whole control system, rather than as evidence that the model itself is consistently reliable.

The adoption case is strongest where business information is genuinely difficult to express through maintained rules: changing supplier language, exceptions that span several documents, and the preparation of evidence for review. Those broader advantages were not measured here. On the controlled documents used in this study, a parser was equally effective and required no language-model calls. A sensible business decision would retain that parser for routine clauses, use the LLM selectively for a demonstrated information gap, and compare its additional benefit with inference, review and monitoring costs.

This dissertation consequently recommends a staged approach. Establish source lineage and state checks first; formalize the main constraints second; introduce trace-based review third; and pilot LLM assistance with approval before considering bounded execution. Success should be judged on service, total operating cost, time to resolve exceptions and harmful execution, alongside model accuracy. A convincing explanation is useful only when the underlying decision can be checked.

@@ append 34
The completed empirical work is narrower than this overall problem statement. It covers three FOODS items across ten stores, a numerical benchmark and a subsequent controlled agent pilot. The full multi-origin, severity and human-review programme remains a research agenda. Chapter 5 states which comparisons were actually completed, and Chapter 6 separates observed findings from propositions that still require testing.

@@ append 37
The research questions and hypotheses are retained from the revised design so that the reader can judge the original intentions against the completed evidence. They were not rewritten to make the observed results appear successful. The studies below provide descriptive evidence for parts of this agenda; they do not amount to a confirmatory test of all eight hypotheses. Section 6.7 records the evidential status of each question and hypothesis.

@@ replace 56
The dissertation makes six connected contributions. It develops a compact, literature-informed replenishment schema; makes evidence quality part of the permission to act; implements a hybrid interpretation-and-tool workflow; creates transparent M5-based simulation conditions; evaluates recorded decisions through integrity checks and selected replays; and translates the findings into a staged adoption framework. The empirical contribution includes both a failed first LLM configuration and a revised configuration that supported actual replenishment. Retaining the failure is important because it shows why the controls and the narrower task were necessary.

The business contribution is therefore a conditional adoption argument. LLM agents can be useful participants in replenishment when their role matches an information problem and their output can be verified. The numerical benefit observed here came from evidence recovery, which was available equally to the parser and LLM configurations. Demonstrating a workable language interface and demonstrating that this interface creates additional commercial value are separate steps.

The original eight-chapter structure is retained. Chapters 2 and 3 establish the literature and operating context; Chapter 4 explains the architecture and the implemented pilot; Chapter 5 reports the executed design; Chapter 6 presents results and managerial implications; Chapter 7 addresses governance and limitations; and Chapter 8 draws the conclusion. The appendices contain the full run tables, every graph from the two final study reports, and the reproducibility record.

@@ paragraph 120
These observations are important for the business-school framing of the study. The aim is to understand how an organization can combine formal decision support with human judgment while retaining control over the evidence behind a decision. The completed experiments assess operating outcomes, exception handling and software auditability. Audit time, reviewer workload and calibrated human trust remain proposed evaluation outcomes rather than reported findings.

@@ replace 127
The study adopted a design-science approach because the research problem concerned both a managerial need and an artifact intended to address it (Hevner et al., 2004). The artifact combined data-quality checks, probabilistic forecasting, formal optimization, bounded language interpretation and an explicit autonomy policy. Its evaluation proceeded in two stages: an initial numerical and live-model feasibility study, followed by a revised agent pilot responding to the first stage's grounding failures.

The initial study established a useful distinction. Strong replenishment tools could operate on structured rules, but the small local language model could not reliably complete the larger extraction task from prose. The revised design therefore assigned fewer decisions to the language model. It retained deterministic interpretation where the document grammar was known, asked the model for a small number of quoted numeric terms, and used independently checked tools to bind those terms to business metadata.

The second stage used a matched four-configuration design: parser without recovery, parser with recovery, LLM without recovery, and LLM with recovery. This made it possible to separate the effect of inventory recovery from the effect of adding a language model. All configurations received the same observable source evidence and the same trained forecaster, optimizer and deterministic critic. The model did not receive clean evaluator state or future sales.

Development and evaluation were separated within each stage, with model settings, prompts, input versions and solver parameters recorded before the relevant evaluation. The revised pilot was nevertheless an adaptive engineering study informed by the initial failure. It was not an independent preregistered confirmation of the dissertation hypotheses. The planned human-audit component was not conducted.

@@ paragraph 137
The wider design also specifies safety-adjusted utility so that a policy is not rewarded merely for avoiding every difficult decision. The reported implementation supplies a descriptive utility proxy combining operating cost, a run-level tail-cost diagnostic and configured penalties for escalation and harmful execution. It is useful for comparing the registered simulator policies, but its penalty weights were not estimated from a retailer's actual review workload or losses.

@@ paragraph 139
The simulator distinguishes two kinds of undesirable outcome. A hard violation means that a committed action breaks a true constraint used by the post-decision evaluator. A clean-reference deviation means that the action differs materially from a numerical reference decision; such a difference is not, by itself, proof of business harm. The stored harmful-execution proxy can include these deviations. Chapter 6 therefore reports hard violations, holds and reference deviations separately rather than treating them as interchangeable measures.

@@ paragraph 148
These roles describe responsibilities, not a requirement to run seven separate language models. In the evaluated V2 pilot, state certification, forecasting, optimization, critic review, autonomy decisions and execution records were deterministic. The LLM performed compact supplier/portfolio term extraction and, in the recovery configuration, requested a recovery tool. Actionable memory and an LLM critic were disabled. Consequently, the study demonstrates a controlled hybrid workflow; it does not isolate the effect of seven conversational agents.

@@ paragraph 152
The architecture can support a separately labelled deterministic fallback when policy permits. The completed LLM studies used a hold-on-failure boundary and did not substitute a hidden parser for a rejected model term. This distinction is essential for interpretation: a held model decision remains a held decision, and a deterministic control is not counted as an LLM success.

@@ append 153
The revised pilot added a recovery route before a suspect state could proceed. Recovery was allowed only for a derived-inventory collapse accompanied by a movement inconsistency, with a complete and current source inventory observation that agreed with the recorded movement ledger. The tool restored permitted derived quantities, retained the original observation and issued a new state certificate. It did not infer missing sales or use the simulator's hidden true state.

A stale or incomplete feed failed those preconditions. The right response was to hold, because agreement with old information cannot establish the current stock position. Both parser and LLM configurations had access to the same recovery evidence. This prevented an information advantage from being mistaken for a language-model advantage.

@@ replace 166
The full design represents a constraint through its entity, scope, parameter, value, unit, conversion, aggregation, validity, source and precedence. The first live-model study asked the model to extract this larger tuple from controlled prose. It revealed dimensional errors and missing terms, so no model-grounded proposal reached the optimizer.

The V2 pilot used a more limited division of labour. A capable parser handled the 155 supported routine clauses. The model was used for supplier capacity and portfolio budget terms, returning only a source reference, numeric value, unit and a short verbatim value quote. Where a capacity term changed, the new source version required a fresh interpretation rather than reuse of an obsolete cache entry.

Independent validation checked the numeric value, unit and quoted source span before tools attached the entity, scope, validity and other structural fields. Those fields were tool-derived metadata, not fields the language model had independently understood. Wrong or omitted numeric terms were not silently replaced. A bounded correction attempt was permitted, although none was required in the completed V2 extraction calls.

Verified results were cached against the document version, model and context. A cache hit was reuse of an earlier interpretation, not a new model trial. This reduced repeated inference while retaining evidence of what had originally been submitted and returned. The method is appropriate for the disclosed document grammars; it cannot be assumed to work unchanged on natural supplier contracts.

@@ replace 170
The executed numerical benchmark used three distinct forecast/policy combinations: seasonal-naive demand scenarios for B1, global LightGBM quantiles for B2, and a native recurrent probabilistic model for B3 and B4. The recurrent model used a gated recurrent unit with a negative-binomial demand likelihood. It was not a reproduction of published DeepAR or Temporal Fusion Transformer results.

Separate descriptive backtests covered seasonal naive, Croston-SBA, LightGBM and the native recurrent model. The preferred pre-study holdout origins were 1760 and 1788; later origins 1800 and 1828 were retained as overlapping descriptive evidence. Scores were calculated for the selected thirty-series panel and its 112 aggregate nodes, not for the full M5 competition hierarchy.

The V2 comparisons shared one saved recurrent model. It used a 56-day lookback, a hidden dimension of 32, ten training epochs and at most 12,000 training windows. It supplied demand scenarios to the same optimizer in all four configurations. This kept forecasting differences from being attributed to the LLM.

Chronos, Moirai and the Temporal Fusion Transformer remain relevant literature and proposed extensions. They were not executed as replenishment baselines in these completed studies. Hierarchical scenario aggregation was used for the backtest scores; no comparative MinT reconciliation experiment was completed. The LLM did not generate the numerical forecasts.

@@ append 174
The registered solver used a seven-day planning horizon, four sampled scenarios, a five-second time limit and a relative mixed-integer gap of 0.001. The portfolio budget was USD 3,000; risk weight was 0.1 with a 0.95 tail-risk level. Orders were bounded at 1,000 units per item-location line, and eligible transfers were enabled. Supplier capacity was also subject to the active source-derived constraints, including the capacity-cut scenario.

Purchasing, fixed order, transfer, holding, shortage and spoilage costs were included within the decision window. Purchases were charged when ordered, and remaining stock received no terminal salvage credit. The short-window total is therefore a simulated operating-cost measure, not a retailer profit or return-on-investment calculation.

@@ paragraph 180
A hold can prevent a bad order and still carry a service cost. The implementation recorded a hold budget and escalation penalties; the completed V2 study used approval mode hold, without a live human approver. A decision requiring approval consequently remained held. The experiment did not vary review staffing, approval delay or hold budgets to estimate an optimal escalation service level.

@@ paragraph 181
The evaluated controls included typed inputs, source references, unit checks, pack and eligibility checks, spend limits, deterministic critic review, state-version checks and idempotent simulator receipts. These were local simulation controls. Authenticated supplier integration, operational least-privilege enforcement and externally immutable audit storage remain deployment requirements; local hashes and chains should not be described as providing those guarantees.

@@ append 182
For the revised pilot, the exact model request was stored before the HTTP call and paired with its later response or error. The record therefore included unsuccessful attempts and semantic validation, as well as accepted results. Imported cached calls were distinguished from fresh physical calls. Authorization headers were excluded from the evidence export.

The independent audit checked content hashes, event-chain ordering, request/response pairing and the recorded context for explicitly forbidden evaluator fields. These checks support the integrity of the observed workflow. They do not prove that a model's internal explanation is faithful, nor do they protect against an actor who could rewrite the complete local store.

@@ append 194
The completed experiments selected FOODS_1_001, FOODS_2_001 and FOODS_3_001 across all ten stores, producing thirty bottom-level series. This was a deliberate small portfolio, not a random or department-balanced sample of M5. Historical sales were used as a demand proxy; the analysis does not claim to observe demand that was lost before the original sales were recorded.

The numerical decisions covered 2–8 February 2016. The two-day feasibility and structured-rule comparisons covered 2–3 February 2016. Their registered training cutoff was 18 January 2016. The V2 decisions covered 1–14 March 2016, with training ending on 15 February 2016 and a fourteen-day warm-up. These are historical data dates. Cloud execution and document preparation took place in October 2026.

@@ paragraph 197
Each completed stage used a single decision origin, with training data ending before its warm-up and evaluation period. Multiple origins were used only in the separate forecasting backtests. Policy comparisons used matched seeds and exogenous opportunity streams; the V2 implementation removed the policy label from the unknown-arrival opportunity key so that equivalent business opportunities were sampled consistently across the compared configurations.

@@ replace 202
The simulation added supplier/constraint, assortment and state-quality layers because those operational facts were absent from M5. Supplier rules and wholesale economics were generated by the research environment. They were exposed as structured rules or controlled prose with disclosed rendering grammars. These documents represent an extraction test, not a validated sample of commercial contracts.

Three scenarios were executed in the initial numerical study: normal operation, derived-field collapse and feed gap. The prose feasibility comparisons used normal operation and derived-field collapse. The V2 pilot added a fourth scenario, supplier capacity cut, registered before evaluation outcomes were observed.

Derived-field collapse set a calculated inventory quantity to an implausible value while leaving an observed source quantity and movement evidence available in V2. Feed gap made relevant evidence insufficiently current. Capacity cut changed a supplier limit while leaving the need for formal feasibility checks intact. The V2 evidence-recovery tool could repair the first condition, but could not legitimately repair the missing-feed condition.

The wider taxonomy in Chapter 3 remains the motivation for future robustness tests. Low, medium and high severity bands, the complete fault taxonomy, prompt-injection resilience and assortment rotation were not all evaluated in these bounded studies. The disturbance configuration was explicitly synthetic and not calibrated to proprietary incident frequencies.

@@ paragraph 210
Initialization was part of the simulation rather than a reconstruction of the original stores' stock. The V2 warm-up lasted fourteen days. Sensitivity to alternative starting stocks and warm-up lengths was not measured in the completed pilot. This is especially important for the original two-day cases: initial inventory could satisfy demand even when the policy placed no replenishment orders.

@@ append 211
The executed comparisons were a subset of Table 5.2. B1–B4 supplied the thirty-seed numerical benchmark. B9 and B10 supplied the first live-model feasibility comparison. The revised pilot compared B10 with a strengthened B4 parser control, each with and without the same recovery tool. That strengthened parser could interpret the disclosed prose grammar; it was not the more limited original parser that failed the first prose cases.

The revised labels retain their policy lineage, but the actual V2 configuration matters more than the label: all four arms used the same deterministic critic, and the LLM critic and actionable memory were disabled. B5–B8, an unconstrained LLM-only ordering policy, critic removal, memory ablation and the complete multi-origin matrix were not executed. Appendix B records every completed run without combining different decision horizons or carriers.

[[TABLE:study_scope]]

@@ append 215
The implemented outcome records included cost, fill rate, stockout frequency, cycle service, mean inventory, window inventory turns, bullwhip, holds, executed actions, hard violations, clean-reference deviations, model calls, tokens and latency. Forecast backtests recorded WRMSSE, weighted scaled pinball loss, CRPS and 95% interval coverage. Appendix B reports the run-level operational values and the complete backtest scores.

Fill rate is the proportion of demand units served; stockout frequency is a share of item-store-day observations; cycle service is a run-specific cycle measure. They should not be substituted for one another. Inventory turns refer to the short simulated window and are not annualized. Bullwhip and daily tail-cost diagnostics are descriptive at these horizons.

Human review time, trust calibration, measured workforce savings, full failure-detection precision/recall and organizational return on investment were not collected. Safety-adjusted utility remains sensitive to the configured simulator penalties. The main conclusions consequently use interpretable operating and safety measures rather than that proxy alone.

@@ replace 225
The planned trace measures in Table 5.3 define a broader evaluation agenda. The completed evidence covers local integrity, selected reconstruction, structural artifact dependence and numerical sensitivity. It does not cover all those measures or a controlled comparison with free-form rationales.

[[TABLE:trace_framework]]

Five V2 decisions were replayed from copied stores using recorded model output and the frozen numerical tools. The selection included three executed cases and two held cases, spanning normal operation, recoverable collapse and stale feeds. Recorded state/certificate and action hashes matched in all five. The original stores remained unchanged.

For the three executed cases, removing the saved forecast blocked reconstruction in all three. This establishes dependence on a required software artifact; it is not a semantic deletion test of the model's document understanding. Separately, reducing budget and supplier capacity to 1% of their recorded levels changed the selected action without introducing a new violation. No language model was recalled and no forecast was retrained for these checks.

@@ append 230
The executed stress coverage was normal operation, derived-field collapse, feed gap and, in V2, capacity cut. The other groups in Table 5.4 remain proposed tests. In particular, zero committed violations in the current pilot is not evidence of robustness against an unseen prompt injection, new unit convention, prolonged disruption or natural contract ambiguity.

@@ replace 234
The human-audit study was not conducted. No participants were recruited and no measurements of review time, trust, workload or detection accuracy were collected. This limitation applies to RQ7 and H7, regardless of how complete the software audit records are.

The proposed extension retains a within-subject comparison of a free-form explanation, a structured trace without lineage, and a full trace with lineage, subject to institutional approval. Planners or suitably trained participants would review both sound decisions and known failures, with formats presented in counterbalanced order. Review time, accept-or-override accuracy and confidence would then establish whether the trace helps people rather than merely storing more information.

For managers, the distinction is material. A technically reproducible decision record is useful preparation for audit, but it does not demonstrate that a planner can use that record quickly or correctly under operational pressure.

@@ replace 238
The analysis is descriptive and preserves the study boundaries. The numerical benchmark contains thirty independent simulation seeds for each policy/scenario cell. Its first eight seeds were extended by twenty-two disjoint seeds after the base results had completed; configuration and trained-model equivalence were checked before the analytical union was used. This was an exploratory increase in replication, not a confirmatory registration.

The V2 pilot contains two matched seeds for each configuration/scenario cell at one origin. Days within a run, stores sharing constraints, repeated documents and cache hits are not independent replications. Reported contrasts are differences in matched means, with percentages calculated against the reference mean. No p-values, power calculations, non-inferiority tests or confirmatory significance claims are supplied.

The earlier two-day prose cases and later fourteen-day hybrid cases differ in information, extraction target, forecast window and configuration. They are reported as a development progression, not as a causal estimate of one prompt change. Neither the initial thirty-series numerical study nor the later agent pilot represents the complete rolling-origin and severity design.

The original proposal's bootstrap, mixed-effects and participant analyses remain possible extensions. Applying them to the present two-seed agent pilot would not resolve its small sample or its controlled document distribution. The emphasis here is on transparent effect magnitude, correct attribution and the evidence still needed for a commercial claim.

@@ heading 242
Chapter 6: Experimental Findings and Managerial Implications

@@ replace 243
The clean-state comparison establishes what the language model should preserve before any additional benefit is claimed. In the seven-day numerical study, the recurrent forecast plus optimizer (B3) achieved mean cost of USD 375.36 and a 93.95% fill rate. The seasonal-naive order-up-to baseline (B1) recorded USD 399.85 and 92.05%. The gated optimizer (B4) remained close to B3, at USD 374.00 and 93.94%. These values describe the selected portfolio and short simulation window; they are not general estimates of forecasting-model superiority.

The LightGBM plus (s, S) configuration (B2) recorded similar clean-state cost to B1, but a lower 80.97% fill rate. A forecasting method and an inventory policy must therefore be judged together. A technically modern model can still produce an unattractive service trade-off under its particular policy and settings. The separate forecasting backtests did not identify one model that dominated every score, and they should not be treated as a ranking of end-to-end replenishment systems.

[[TABLE:v1_means]]

[[FIGURE:v1_numeric_cost]]

In the fourteen-day V2 pilot, every parser/LLM matched pair produced exactly the same cost and fill outcome, at both recovery settings and in all four scenarios. Under normal operation, each configuration averaged USD 796.51 and a 96.00% fill rate. This supports the feasibility of inserting a bounded language interpretation step while preserving the numerical workflow. It does not establish statistical equivalence across a wider population or an economic premium for the LLM.

[[TABLE:v2_means]]

[[FIGURE:v2_normal_cost]]

The two studies should not be compared through their absolute totals. They use different historical windows, horizons, initialization and information arrangements. The higher total cost in a fourteen-day study is not evidence of deterioration relative to a seven-day study. The informative comparisons are those within each matched design.

@@ replace 246
The numerical study demonstrates that checking a proposal against its inputs is insufficient when the inputs themselves are unreliable. In the feed-gap scenario, B3 recorded 63 hard-constraint violations and no holds. Adding the deterministic evidence gate in B4 reduced the recorded hard violations to zero and produced 90 held decisions across the thirty seven-day runs. Fill rates were 90.29% for B3 and 90.55% for B4. This is a useful safety result within the configured disturbance, without requiring a language model.

[[FIGURE:v1_numeric_safety]]

The derived-field-collapse scenario exposed the cost of holding without recovery. In the initial numerical comparison, B4 averaged USD 369.42 and 90.50% fill, while B3 averaged USD 497.05 and 93.71% fill. The lower spend was accompanied by reduced service and delayed ordering. It should not be interpreted as an unqualified business improvement.

V2 supplied a more constructive response when the evidence was sufficient. Both recovery configurations repaired ten collapse decisions, changing 279 derived quantity fields per configuration, and issued new certificates before ordering. Their collapse-scenario mean cost fell from USD 894.30 without recovery to USD 796.51 with recovery. Fill rose from 89% to 96%, mean aggregate on-hand inventory increased from 184.54 to 207.54 units, and stockout frequency fell from 5.83% to 2.14% of item-store-day observations. The number of held decisions fell from eleven to one across the two runs in each configuration.

[[TABLE:recovery_contrast]]

[[FIGURE:v2_collapse_cost]]

The cost breakdown explains why the recovery was commercially useful in the simulator. Recovery increased purchasing, order, transfer and holding expenditure, but reduced the shortage penalty by USD 195.99 on average. The net reduction was USD 97.79. The benefit was better availability at a lower combined operating cost, rather than a simple reduction in purchases or stock. The shortage valuation is a registered simulation assumption, so a retailer would have to reassess the balance using its own margin and service economics.

[[TABLE:cost_components]]

A recorded decision illustrates how the boundary worked. On 5 March 2016, in seed 13 of the LLM recovery configuration, the derived stock field for FOODS_1_001 at CA_1 showed zero. The current observed source and movement ledger both indicated eleven units. The model requested recovery, and the independent tool restored the field to eleven, checked the other portfolio records and issued a new certificate. Twenty-eight derived quantities changed in that decision. The model did not invent those quantities; it initiated a verified step before numerical planning. In the stale-feed cases, the same request was refused because current evidence was missing.

The operating mechanism is clear: valid information allowed replenishment to resume before the missing stock translated into further lost sales. The same results appeared in the parser and LLM configurations because the recovery evidence and deterministic tool were shared. The observed 10.93% cost reduction belongs to that recovery mechanism. It cannot be assigned to the presence of the language model.

Recovery did not improve the feed-gap results. Both configurations continued to average USD 894.30 and 89% fill because current evidence was absent. That boundary is commercially important. A system that fills a missing stock field with a plausible number may appear responsive but can create a larger purchasing error. In the tested workflow, the tool required source-and-ledger agreement and refused to turn stale information into a current fact.

Under capacity cut, all configurations averaged USD 805.07 and 95.78% fill, with no committed hard violation. The capacity source was reinterpreted when its version changed and the optimizer respected the active rule. This provides a bounded example of maintaining an executable constraint through a supply change, rather than evidence of handling every supplier disruption.

[[FIGURE:v2_capacity_cost]]

@@ replace 249
The first live-model study is central to the dissertation's interpretation. Four B9/B10 runs generated thirty recorded calls and 112,739 tokens, yet all eight model decision days were held. No model-grounded replenishment proposal reached the optimizer. The controlled prose task was too demanding for the selected small local model and serving profile.

Post-decision assessment found 88 exact eleven-field tuples among 95 returned tuples and 112 submitted source rules: 92.63% precision and 78.57% recall. Seven returned tuples had wrong units, and twenty-four submitted tuples were omitted. On each of seven extraction days, only sixteen of the 157 available documents were submitted before early termination. The eighth day was stopped by the state gate. Conditional accuracy therefore concealed a much larger coverage gap.

[[TABLE:grounding_summary]]

[[FIGURE:v1_grounding_quality]]

The two-day prose parser controls also held their decisions because the original deterministic parser did not support that prose representation. The separately added structured-rule controls did execute. This comparison showed that inability to interpret the chosen carrier, rather than inability to compute a replenishment plan, was blocking the process.

The V2 design responded by making the model's job smaller and more testable. Across 48 fresh extraction calls, it returned all 76 submitted capacity and budget numeric terms with the correct source value, unit and quote. No extraction correction was needed in the completed evaluation. The other routine clauses and structural metadata were supplied by trusted parsing and binding tools.

Across all four configurations, the independent source audit found complete active-rule sets on 388 grounding-eligible decision days, each with 157 source rules. There were no false or omitted active rules in those eligible sets. Sixty decision days were stopped by state-quality checks before grounding. The full pipeline coverage is therefore conditional on state eligibility, and is not a claim that the LLM interpreted every rule on all 448 days.

The narrower task should not be described as an improvement from 78.57% to 100% on the same extraction benchmark. The target changed from a full business tuple to a bounded numeric term, the carrier and verification changed, and metadata responsibility moved to tools. The positive conclusion is that a deliberately limited language task can be integrated successfully into a controlled replenishment pipeline.

Tool selection remained a separate weakness. The model followed the recovery instruction in ten of twenty fresh choices and requested recovery incorrectly in all ten stale-feed cases. The independent tool refused those requests and the gate held the decisions. The result suggests a practical next design change: establish tool eligibility deterministically before offering a choice to the model. That change is a recommendation, not an intervention evaluated in the frozen pilot.

@@ replace 252
The revised pilot supports separation of responsibilities, but it does not prove that a larger conversational team improves inventory performance. State reconciliation, numerical forecasting, optimization, critic checks and execution were deterministic. The model was responsible for the compact extraction step and the recovery request. No role-removal, free-form communication or actionable-memory comparison was completed.

The business value of this separation is that each responsibility can be inspected and replaced independently. A supplier term can be checked against its quote without asking the model to certify its own interpretation. A purchase quantity can be recomputed without relying on the model's arithmetic. A manager can also retain a parser for stable documents and introduce language assistance only where that parser becomes costly to maintain.

[[TABLE:agent_runtime]]

The model-enabled configurations recorded 68 fresh calls and 69,073 tokens: 48 extraction calls and twenty recovery selections. The recovery configuration used more calls and tokens than its no-recovery counterpart. The exercise from request to completion lasted approximately 59.6 minutes on the retained CPU instance, including development and evaluation; it was not a deployment throughput benchmark.

[[FIGURE:v2_collapse_latency]]

Caching helped the workflow avoid interpreting the same unchanged evidence repeatedly. It also makes naive accuracy denominators misleading: a thousand reused documents do not represent a thousand new language-model judgements. The report therefore separates fresh calls, reused evidence and decision-day coverage.

The endpoint incurred no paid API charge because the model ran locally. Hosting, electricity, engineering effort, review and monitoring were not priced. A claim that the system was free, cheaper overall or more productive for planners would consequently go beyond the evidence. The operational comparison with the parser, which required no language-model calls, is a useful reminder that complexity must earn its place.

@@ replace 255
The software audit provides a stronger basis for review than a narrative alone. It checked 130,430 original content-addressed objects and 130,542 chained events across the 32 V2 runs. All discovered object hashes, chains, configured run identities and request/response associations passed the recorded checks. The audit found no explicitly forbidden evaluator fields in the captured model requests. It does not rule out every possible leakage channel or provide external authentication.

Five selected decisions were replayed from copied evidence stores. All reproduced their recorded state/certificate and action hashes. Three were executed decisions and two were held decisions. Removing the saved forecast blocked reconstruction in the three executed cases; changing budget or capacity to 1% changed the selected order without a new constraint violation.

These findings establish trace usefulness at the software boundary. They show that the observed inputs and tools can reproduce selected recorded decisions. They do not reveal hidden model reasoning, establish semantic dependence on every quoted document, or demonstrate superiority over a free-form explanation in a randomized comparison.

[[TABLE:replay_summary]]

No human-audit result is reported. A manager may reasonably see these records as useful audit infrastructure, but faster review, better trust calibration and lower workload remain hypotheses. Those benefits should be tested with representative planners and realistic time pressure before becoming part of a financial business case.

@@ replace 258
The results support an adoption sequence in which reliable evidence precedes greater autonomy. The initial study showed that an agent can produce a plausible-looking extraction and still fail to support an order. The later study showed that a narrowly tasked model can participate in actual replenishment when independent tools establish the decision boundary. The useful managerial question is where that participation solves an information problem that existing rules do not solve economically.

Three aspects make LLM agents promising for replenishment. They can provide an interface to supplier language that is inconvenient to encode manually; they can organize a bounded request for specialist tools; and they can help present the recorded evidence to a planner. The pilot directly demonstrated only the first aspect for a small controlled numeric task and the ability to request a recovery tool. It did not measure manual encoding savings, broad exception resolution or the quality of a planner-facing explanation.

The observed operating results nevertheless provide a sound basis for a cautious positive case. The model-enabled workflow executed 186 nonzero replenishment actions and retained the parser's cost and service outcomes. Its residual selection errors were contained by independently applied conditions. This is a workable pattern for adding semantic assistance without delegating unchecked purchasing authority.

[[FIGURE:v2_execution_safety]]

The parser's identical performance also defines where an LLM is unnecessary. If supplier documents follow a stable disclosed grammar, a deterministic parser is easier to cost, quicker to inspect and capable of the same results in this study. Language assistance should be directed towards heterogeneous documents or changing conventions, then evaluated against that strong control. A weaker parser would exaggerate the apparent value of the model.

[[TABLE:managerial_value]]

A business pilot should begin in advisory or approval mode. Planning should own service and exception priorities; procurement should own supplier interpretation; the data team should own source quality; finance should approve economic assumptions; and a named operational owner should decide the permitted automation level. A supplier-language model should not acquire purchase-order authority merely because an extraction is fluent.

The dashboard should report total operating cost, fill, stockout frequency, overdue holds, exception resolution time and harmful execution alongside extraction precision, coverage, call volume and latency. Promotion to bounded execution should require agreed performance margins and review of failure cases over several demand regimes. The current pilot supplies no calibrated universal threshold for that promotion.

The financial test is incremental: compare the additional contribution from LLM assistance with inference, integration, maintenance, verification and review costs. Recovery benefits that an existing rules engine can obtain should not be counted again as an LLM benefit. This discipline produces a more credible case for adoption because the organization can retain the useful controls even if the model fails to justify its operating expense.

@@ append 258
## 6.7 Answers to the Research Questions and Status of the Hypotheses

The evidence supports the central question in a limited but practical sense. A bounded LLM-assisted system can participate in useful replenishment while authority remains tied to verified evidence. The observed advantage is the controlled workflow and recoverability of the decision, not a demonstrated improvement over the strongest parser. Table 6.8 separates those findings from the parts of the original research agenda that remain open.

[[TABLE:research_questions]]

[[TABLE:hypotheses]]

The first failed model configuration and the later successful hybrid configuration should both inform the conclusion. Excluding the failure would overstate readiness; excluding the later executed decisions would understate what the revised design achieved. Taken together, they suggest that reducing the model's responsibility, checking it independently and preserving source evidence are more useful design choices than adding untested agent roles.

@@ append 263
The stale-feed selections provide a concrete example of why accountability must sit outside the model. Ten tool requests were inconsistent with the instruction, yet none was allowed to become a repair or an executed order. A commercial rollout should preserve that independent permission boundary and name the owner of any policy override. A manager should be able to see that a recommendation was refused without having to infer the refusal from a long conversation log.

@@ paragraph 267
Evidence gating shifts risk from acting on bad information to delaying an action. In the V2 collapse scenario, holding without recovery reduced fill to 89%, while verified recovery restored it to 96%. A hold was therefore a temporary control, not an adequate replenishment strategy by itself. The implemented penalty and hold budget do not establish an optimal human escalation process; a retailer would also need an owner, deadline and service target for resolving the exception.

@@ paragraph 270
Supplier documents, spreadsheets and operational notes should be treated as untrusted inputs. Indirect prompt injection can influence an LLM-enabled application through retrieved content (Greshake et al., 2023). The prototype used typed outputs, role boundaries, source references and an input screen, but the current pilot did not complete an adversarial evaluation. Its source labels and local hashes were not authenticated supplier signatures. Authenticated ingestion, restricted execution permissions and adversarial tests remain requirements for deployment.

@@ paragraph 271
The simulator used idempotent execution receipts, and the language model did not submit purchase orders to an external system. An operational implementation would need independently enforced least privilege and approval controls at the actual execution endpoint. A successful local gate is preparation for that integration, not proof that an ERP or supplier API is protected.

@@ append 274
The experiment recorded calls, tokens and timing but did not measure energy use or carbon emissions. Nor did it estimate actual retailer markdowns, waste or workforce effects. Environmental and economic claims therefore remain conditional on future data. A retailer should include those costs when comparing an LLM-assisted process with a parser-based workflow.

@@ replace 276
The first limitation is the experimental environment. Only three FOODS items across ten stores were selected from M5, and sales were used as a demand proxy. Inventory, suppliers, wholesale economics, contracts and faults were simulated. The study cannot reconstruct the original retailer's true demand, operating incidents or profitability.

The second is the limited coverage. The numerical study used seven days at one origin, and the model-feasibility cases only two. The V2 pilot extended the window to fourteen days but retained two seeds and one origin. Initial stock, uncredited terminal inventory, shortage valuation and the five-second solver limit can influence the apparent trade-off. Steady-state performance and a complete severity matrix remain unmeasured.

The third is the language task. The documents were controlled grammars, and the V2 model interpreted 76 numeric terms rather than all structural constraint fields. Exact performance on those terms does not establish natural-contract understanding, general unit conversion or reliable exception reasoning. Caching also creates correlated exposures rather than additional independent trials.

The fourth is attribution. The strongest parser matched every LLM operational comparison, and the recovery improvement was available to both. Several changes separated V1 from V2, so the development progression cannot identify the causal contribution of one prompt, cache or role. Critic, memory and conversational-role ablations were not completed.

Finally, there was no field deployment, human participant study, measured organizational return on investment or full adversarial evaluation. Selected cached replays verify recorded software decisions, not latent reasoning. The research is a detailed and reproducible engineering demonstration with descriptive operating evidence; its adoption framework still requires organizational testing.

@@ replace 281
This dissertation investigated when an AI-assisted replenishment system has enough reliable evidence to act. The completed work shows why that question matters. Numerical optimization can be compromised by missing or corrupted information, and a language model can return a valid-looking response that still cannot support an executable order. A trustworthy process has to establish the state, validate the constraints and record the permission to act.

The experiments make a positive but bounded case for LLM agents in replenishment. After its task was narrowed to source-quoted numeric terms, the local model participated in a workflow that executed 186 nonzero replenishment actions across its two configurations, with no recorded committed-plan hard violation. The system maintained the strongest parser's cost and service outcomes. Those are useful feasibility results for incorporating language assistance into formal inventory decisions.

The largest measured operating improvement came from verified evidence recovery. Under derived-field collapse, mean cost fell by 10.93% and fill improved from 89% to 96%. Because the same improvement occurred without an LLM, it should be understood as a benefit of the recovery architecture. The model's ten incorrect stale-feed recovery requests also show why its authority must remain conditional.

The dissertation contributes a literature-informed decision schema, a link between evidence quality and autonomy, a tested hybrid interpretation-and-tool workflow, transparent M5 simulation conditions, reproducible trace evidence and a staged adoption framework. It does not establish all the original hypotheses. It demonstrates that the proposed direction can work within a controlled scope and identifies the comparisons needed to justify a wider commercial claim.

For a business reader, the conclusion is that LLM agents can be useful connective tools around replenishment. Their strongest potential lies in reducing the friction between business language and formal decision support. Organizations should preserve the numerical tools and independent controls that make that assistance dependable, and add autonomy only after measuring the model's incremental value.

@@ replace 285
The findings are bounded by the selected public benchmark, the simulated operational layers and the short evaluation windows. They cannot be transferred directly to fashion, luxury, industrial distribution or an entire retail network. The V2 evidence comes from two seeds, controlled supplier prose and one decision origin; it supports a feasible design, not a broadly validated performance guarantee.

The study also leaves important organizational questions unanswered. It did not measure whether planners review the trace faster, whether supplier-term maintenance becomes cheaper, whether the model resolves genuinely ambiguous exceptions, or whether the total process creates a financial return after all costs. The exact parser match makes those questions central to the next business case.

@@ replace 287
The next empirical step should compare the strengthened parser and the bounded LLM on a validated set of naturally occurring supplier documents, including changing vocabulary, conflicting versions, order-level minimums and unit conversions. The test should keep information access and numerical tools equal, measure fresh interpretations separately from cache reuse, and include the time required to maintain the parser. That comparison would address whether language flexibility creates an additional benefit where this pilot could not show one.

A longer simulation should then extend the seeds, origins, disturbance severities and replenishment horizon, with explicit treatment of terminal inventory and review delay. The model should be offered recovery only after deterministic eligibility checks. Critic, memory and role ablations would establish which parts of the agent architecture justify their complexity. These changes should be registered before evaluation rather than treated as already proven improvements.

The human-audit study remains essential. Experienced planners should compare the explanation formats under realistic workloads, with review time, error detection, override quality and confidence measured together. An approval-gated field pilot could follow, beginning with shadow recommendations and recorded planner decisions before any automatic execution.

The architecture may also be useful in procurement, maintenance or workforce scheduling, where quantitative decisions depend on fragmented evidence and textual rules. That transfer is a research proposition. The present dissertation's concrete contribution is to show how semantic assistance can be bounded, checked and connected to a reproducible replenishment decision.

@@ replace 346
This completed version retains the revised dissertation's title, eight chapters, principal section order, literature review and original reference entries. Chapter 6 has been renamed from expected findings to experimental findings. The abstract, methodology, evaluation protocol, governance discussion and conclusion have been updated to reflect the studies that actually finished.

The earlier literature-and-standards positioning is preserved. The canonical schema remains a compact research abstraction informed by ARTS, GS1 and the cited inventory/data-quality literature. No production-platform access, proprietary retailer telemetry or universal incident calibration has been added.

The empirical content now distinguishes the initial numerical benchmark, failed local-model feasibility cases, structured-rule controls and the revised parser/LLM recovery pilot. Benefits are attributed to the mechanism that produced them. Human-audit, field-return and general language-understanding claims remain future work.

Appendix B includes every completed run and the forecast backtest scores. Appendix C includes all remaining figures from the two final reports; figures already discussed in Chapter 6 are not repeated. Appendix D records configuration, development, audit and evidence-access details. Original plots and experimental data have been preserved rather than altered to strengthen the conclusion.
