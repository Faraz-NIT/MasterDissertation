# Appendix A. Model and experimental settings

The main chapters describe the settings needed to interpret the business result. This appendix preserves the implementation details required to inspect the evaluated configuration. The source of these settings is the frozen protocol of the completed main study, together with its forecasting and execution receipts. Appendices E–I extend the supporting material to the architecture comparison, LangChain validation, prompts, sample catalogues and a separately labelled service-target illustration. The dissertation rewrite reads that completed evidence and does not start another model experiment.

[[TABLE:study_versions]]

[[TABLE:technical_settings]]

[[TABLE:model_environment]]

The three roles share one underlying model. They are separate native API calls with separate instructions and inputs. The generation settings do not update the model's weights. The two early development-preparation forecast files retained directly under the dataset folders are excluded from the primary forecast count. The four primary LightGBM fits are stored under the registered weekly-origin folders and identified by their saved model and panel hashes.

The model digest is 65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b. The primary study was published in repository commit 4721351c3745fd51db9fa10b86b7e9d9839a821c. These identifiers specify the evaluated model tag and the completed evidence version; they do not imply that the language model was trained by the dissertation author.

## A.1 Inventory, data and simulation assumptions

The final study uses a consistent simulated inventory ledger. It does not inject inaccurate stock records, phantom inventory, unrecorded losses or delayed stock updates, and it does not test inventory-record repairs. Demand and supply uncertainty change the physical outcomes; the recorded stock follows the simulated physical balance. Source verification checks supplier terms against current authenticated fields and does not establish an ability to correct false inventory counts.

Starting stock is the rounded-up equivalent of three average days of sales from the past 56 days, with no opening pipeline. RetailNet opening stock is distributed across three initial age batches. New deliveries receive a hypothetical three-day life, and older usable batches are consumed first. Remaining units expire after the day's sales opportunity at the end of their usable life. M5 has no expiry within the weekly horizon.

Each day begins with due deliveries. The policy then reads current stock, forecasts and supplier terms, proposes an order and passes the release checks. Accepted quantities enter the delivery pipeline. Sales consume available stock, and unmet demand is lost rather than backlogged. Purchase spend records accepted quantities at the assumed unit cost of one; cancelled quantities add no stock or pipeline. Opening stock plus accepted purchases is reconciled against sales, expiry, closing stock and closing pipeline.

[[TABLE:simulation_settings]]

Released sales are a proxy for demand. The simulation multiplies them by a mean-one lognormal draw with log-scale standard deviation 0.10. This produces random variation and is not a fixed plus-or-minus 10% bound. Announced promotions multiply the demand proxy and available forecast by 1.3 from simulation day index 2, the third day. The same demand realisation and supply-opportunity draws are used for matched policies. Supplier disruption doubles carton sizes and minimum orders, adds one delivery day and reduces dispatch capacity from the third day, subject to the implemented minimum feasible capacity.

The LightGBM model uses 150 trees, maximum depth five, at most 20 leaves and one fitting thread. Each dataset and weekly origin has its own fit on earlier observations, using at most 365 days and a recursive 14-day forecast. Historical weekly sales changes supply the uncertainty estimate; test outcomes do not supply forecast inputs. Four primary fits serve every policy in the matched experiments.

## A.2 Measures and aggregation

The simulator's daily inventory operating cost is 0.02 times closing stock, plus five times unmet demand, plus expired units. The sum over the episode is divided by demand for the primary normalized policy measure. These coefficients are assumptions. Purchase spend is recorded separately, and the index is not a complete retailer profit calculation. Actual acquisition margins, staff effort, cloud charges and closing-stock commercial value are not estimated.

For each dataset, scenario, policy and simulation seed, the two weekly episodes are aggregated using their totals. Fulfilment divides total sales by total demand. The expiry share divides total expired quantity by total opening stock plus receipts, counting the opening inventory from each independent weekly reset. Policy means average the resulting seed measures. Overall headline means then give equal weight to the three scenarios.

The overall paired cost effect first averages scenario-level cost-per-demand measures within a seed, then calculates the relative change against the matched comparator for that seed. The reported effect averages those thirty changes. This explains why the cost percentage should not be recomputed from the rounded values printed in the main table. The paired bootstrap resamples seeds ten thousand times and retains both origins inside each sampled seed.

[[TABLE:paired_intervals]]

The intervals describe the selected historical panels under the declared simulation draws. They do not provide a population estimate or independent uncertainty over the pretrained model's weights. In particular, the near-zero M5 difference against the structured-data planner has an interval that includes zero. The RetailNet agent-layer difference is slightly adverse. Both the favourable whole-package comparison and the limiting strong comparison are retained.

## A.3 Shared forecast context

The forecast is a common numerical input, not a language-model prediction. The table reports its error against the released sales proxy in each weekly window. Weighted absolute percentage error sums absolute errors across the series-days and divides by total observed sales. Mean absolute error uses the dataset's declared quantity convention. The errors are therefore context for the policy experiment, rather than an evaluation of LLM forecasting.

[[TABLE:forecast_context]]

The portfolio-total lines in the main methods graph can appear closer than the individual-series error figures because overprediction and underprediction can offset in a total. The forecast quality was identical across matched policies. Its limitations still constrain the operating world: the experiment does not claim that a successful allocation tool removed all demand-prediction uncertainty.

# Appendix B. Additional dataset-labelled figures

These figures provide detail behind the short results chapter. They use the complete audited study, and their captions identify the aggregation and comparison. M5 and RetailNet are always written in the titles or panel labels. The graphs should be read together with the source and quantity conventions in Chapter 4. None pools earlier repair experiments into the current results.

## B.1 Service through the week

[[FIGURE:m5_daily]]

[[FIGURE:retailnet_daily]]

The daily service plots pool the two episodes and the simulation seeds within each scenario. They describe how service developed within the weekly simulation. They do not treat each point as an independent replication. Lines overlap where the structured-data planner and agent workflow produced the same or very similar physical outcomes.

## B.2 Cost components and supplier interpretation

[[FIGURE:cost_components]]

[[FIGURE:source_accuracy]]

The component graph uses pooled demand as its denominator. The main policy table instead reports means of seed-level ratios. Both follow their declared definitions. The supplier-reading graph scores thirteen numerical fields per call and also checks supplier coverage for exact extraction. Each dataset has 420 calls per message style, with prose, memo and table represented across the full primary grid.

## B.3 Workload and paired effects

[[FIGURE:model_latency]]

[[FIGURE:paired_service]]

[[FIGURE:paired_cost]]

Latency bars show medians and the upper whisker shows the ninety-fifth percentile. That whisker is not a confidence interval. The paired-effect figures do use the declared seed-bootstrap intervals. Positive service effects favour the agents, while negative cost effects favour them. Separate axes allow the much smaller differences against the structured-data planner to remain visible.

## B.4 Held decisions

[[FIGURE:holds]]

A zero order is not a hold. The former is a permitted decision that needs no purchase; the latter is a decision that cannot be released through the workflow. The completed main study had no holds. The figure therefore states the zero result explicitly rather than implying that an empty-looking chart represents missing data. It also does not present a hold as a successful stock recommendation.

# Appendix C. Evidence, reproducibility and research boundaries

The evidence package contains the full registered experiment rather than selected successful examples. The protocol records the code and data hashes. Each matched case contains current supplier text, current rules, three raw model calls per agent day, proposals, release checks, committed quantities and the series-level stock outcomes. The independent audit reconstructs the physical process and recalculates the reported quantities. The dissertation's own validation checks connect its figures and headline values to those completed sources.

[[TABLE:current_evidence_locations]]

To reproduce the original analysis, use the complete repository and the saved study evidence. The analysis script reads the existing decisions and does not call Ollama. The original experiment script refuses to overwrite completed cases and uses its registered time window. A new inference experiment would need a new output directory and prospective protocol. The installed Ollama binary, model weights, virtual environments and full cached raw releases are not contained in the reading package; the source identifiers and hashes remain recorded.

The accompanying repository-ready code package contains only the relevant experiment code, tests, prepared panels, fitted forecasts, saved results, plots and logs. It contains 17,100 primary native model-call records across the three empirical stages. The full source-data releases, local model weights and environments are not embedded. The supplied Gilbert thesis guided presentation and is not redistributed or used as empirical evidence for retail replenishment.

## C.1 Verification and scope

The independent audits verify the complete registered decision grids, frozen source and data hashes, raw model-call hashes, supplier-field and priority scores, released quantities, physical stock balances and the cost calculation. They reconstruct FIFO consumption and supplier deliveries separately from the evaluated simulator. A zero order remains distinct from a held action. The main and architecture studies recorded no released constraint violations or holds under their controlled primary conditions.

The portable code package was checked after extraction into a separate folder: all sixteen relevant tests, all three saved-result audits and all four plot-generation scripts passed. These checks read completed evidence and did not create new experimental model responses. Development records remain separate from primary results, including failed checks and subsequent corrections. Known historical weeks are not unseen holdouts, and thirty simulation seeds are not thirty independently trained language models.

## C.2 Reproduction commands

The following commands run from the root of the extracted code package after installing its pinned dependencies. The audit command writes derived CSV files and audit receipts in that copy. Verify archived bytes before running it. Fresh inference requires a running local model with the recorded digest, a separate output location and a newly frozen protocol; the archived scripts protect completed cases against overwriting.

[[CODE:reproduction]]

Official dataset locations are https://www.kaggle.com/competitions/m5-forecasting-accuracy/data and https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K. The RetailNet source revision recorded for preparation is 08c1fab7f9257bc73679d415d65d644165d351d4, under the release's CC-BY-4.0 licence. Data-preparation receipts record the full-source file hashes. M5 uses published unit sales; RetailNet uses published normalised sale_amount values multiplied by 100. The final study does not recover latent demand using stockout flags.

## C.3 Use of AI-assisted tools

AI-assisted tools supported manuscript drafting, document production and the generation of analysis and reporting code. The local Qwen model was separately the subject of the empirical study, performing the recorded replenishment roles. These uses should be distinguished: the writing assistant's output is not an experimental response from Qwen, and Qwen's measured supplier-reading accuracy is not a claim about the drafting process. Numerical assertions are grounded in the saved experiment and its independent checks.

The dissertation does not report invented interviews, participants, acknowledgments, live purchasing or retailer financial accounts. Illustrative retail examples in the background chapters are explanations, rather than additional observations. The user-supplied thesis provides organisational guidance. The final author should review the dissertation, confirm the interpretation and follow the school's applicable disclosure requirements before submission. This statement describes the assistance used rather than asserting that a supervisor has already approved the work.

# Appendix D. Short glossary

An agent role is a defined model-assisted responsibility within the workflow, such as supplier reading or review. A language model is the pretrained system that produces the role's response. The three roles in this study use one model family. Ollama is the local serving software. Inference means using existing model weights; fitting or training adjusts a model using data. LightGBM is the numerical forecasting family fitted to the retail histories.

A store–product series is the sales history of one product at one store. A portfolio groups thirty such series for a joint replenishment decision. A weekly origin is the date at which the forecast and simulation episode begin. A simulation seed identifies one declared set of demand and supply draws. A lead time is the delay before a permitted purchase can arrive. A delivery pipeline contains goods that have been accepted for future arrival but are not yet on hand.

A carton rule restricts quantities to package multiples. A minimum order specifies the smallest nonzero line allowed. Supplier capacity limits the total quantity dispatched by a supplier group. FIFO means first-in, first-out use of stock. Expiry is the end of a batch's hypothetical usable life in the simulator. Fulfilment is the share of the declared demand served. The operating-cost index is the study's synthetic assessment measure, rather than observed currency or retailer profit.

Source verification checks an extraction against the current authenticated contract fields. A release gate applies the conditions required to execute a proposal. A hold prevents a decision from executing; it does not automatically create an alternative order. A paired comparison assesses policies under the same declared operating world. A bootstrap interval summarises uncertainty by resampling those paired simulation seeds, with related episode data kept inside each seed.


LangGraph coordinates steps through a graph with explicit state and conditional routes. LangChain is the library used for the later implementation; its LangChain Expression Language (LCEL) connects runnable steps and branches. A StructuredTool exposes a function with declared input fields. A JSON schema specifies the permitted structure and values of a response.

# Appendix E. Selective architecture and LangChain extension

## E.1 The extension of the earlier agent

The previous agent calls a supplier reader, a coordinator and a critic on each portfolio day. The selective extension retains supplier interpretation, source verification, the numerical planner and hard release checks. It changes delegation: complete declared tables are parsed directly, prose reaches the supplier LLM, and announced business priorities are applied through an explicit route. Failed or unknown conditions hold the order and request LLM review. A model approval cannot override a failed check.

The original fixed agent is rerun as the matched baseline for the architecture comparison. The model digest, prompts, historical panels, forecasts and numerical planner remain constant, while seeds 201–230 supply fresh simulation draws and native model responses. The 1,080 policy runs are a full architecture comparison executed through LangGraph 1.0.10. All three workflows share that framework, which helps isolate the delegation design rather than the mere introduction of a software library.

[[FIGURE:langchain_agent_extension]]

## E.2 Full architecture results

[[TABLE:architecture_diagnostics]]

[[TABLE:architecture_effects]]

Native model calls fall from 7,560 to 1,680 across the two datasets, a 77.78% reduction. Mean whole-decision time falls by 54.79% in M5 and 54.93% in RetailNet. Supplier-field accuracy and declared-priority accuracy are 100% in the selective workflow, with no released rule violations. These measures describe the controlled messages and declared event policies, not independent improvements in the pretrained model's reasoning.

The paired M5 intervals do not establish service or cost superiority. RetailNet shows a fill-rate gain of 0.236 percentage points and a 1.176% reduction in the operating-cost index. Its expiry share rises by 0.081 percentage points, concentrated in promotion. The selective orders match the structured-information reference throughout. The reference receives already prepared facts, and staff effort to prepare those facts is not measured.

[[FIGURE:architecture_model_calls]]

[[FIGURE:architecture_priority_accuracy]]

[[FIGURE:architecture_inventory_effects]]

[[FIGURE:architecture_retailnet_expiry]]

[[TABLE:architecture_hypotheses]]

Architecture criteria A1–A4 were frozen before these main runs. The performance-preservation tolerances are study choices, rather than retailer-approved service targets. Service and cost superiority are assessed separately. These criteria should not be confused with the dissertation's H1–H4 framework, which was articulated when the literature review was rewritten after the main study.

## E.3 LangChain implementation and separate validation

The extension is also implemented using LangChain core 1.6.10. Runnable sequences and conditional branches connect the roles, and a StructuredTool exposes the unchanged numerical planner. The earlier graph functions are reused as ordinary functions; the compiled LangGraph is not invoked by the LangChain chain. Native request formatting, prompts, generation settings, source checks and the release rule are retained. Conversation memory, external tracing, retries and response caches are disabled.

Two checks support that implementation. A recorded-response regression supplies the previously saved model outputs and reconstructs all 7,560 archived portfolio decisions. It reproduces the orders, priorities, role paths and inventory outcomes exactly, with zero new native model calls. This checks software consistency when model outputs are held constant.

Fresh LangChain validation then uses seed 233, both origins, all three scenarios and all thirty series in each dataset. It completes 36 matched policy runs, 252 portfolio days and 300 fresh native model calls. All three workflows use the LangChain chain in this comparison. The validation passes the independent ledger and model-provenance checks. It is one-seed implementation validation; it is not a new thirty-seed LangChain performance study and provides no new bootstrap interval estimate.

[[TABLE:langchain_validation]]

[[FIGURE:langchain_fresh_langchain_validation]]

Sixteen relevant engineering checks cover the original simulator, selective delegation and LangChain implementation. They include table parsing, source mismatches, ambiguous event flags, failed-check holds and the actual planning-tool interface. A complete valid table proceeds without an LLM supplier call; prose delegates to the reader. In development checks, a model approval cannot release an order whose source, route or quantity checks fail. The primary cases did not require unresolved exception handling, and no employee resolution was simulated.

# Appendix F. Agent instructions, message formats and response contracts

The following instructions and in-context examples are copied from the frozen main-study protocol and retained in the architecture and LangChain implementations. Each role uses a separate request and role-specific input. Supplier examples demonstrate field extraction; critic examples demonstrate pass/hold behaviour. The coordinator has no in-context examples. These examples are prompt content, not additional training or evaluation observations.

## F.1 Supplier-information agent

[[VERBATIM:prompt_supplier]]

Example 1; message role: user.

[[VERBATIM:example_supplier_1]]

Example 2; message role: assistant.

[[VERBATIM:example_supplier_2]]

## F.2 Replenishment coordinator

[[VERBATIM:prompt_planner]]

## F.3 Independent review role

[[VERBATIM:prompt_critic]]

Example 1; message role: user.

[[VERBATIM:example_critic_1]]

Example 2; message role: assistant.

[[VERBATIM:example_critic_2]]

Example 3; message role: user.

[[VERBATIM:example_critic_3]]

Example 4; message role: assistant.

[[VERBATIM:example_critic_4]]


## F.4 Controlled supplier-message formats

The study rotates prose, a reordered memo and a declared table. The three samples below use the same invented agreement to show the formatting only. They are not observed retailer messages or additional experiment outcomes. A budget is appended to every format. The controlled wording supports exact field scoring and limits claims about arbitrary live communications.

Prose format.

[[VERBATIM:message_0]]

Reordered memo format.

[[VERBATIM:message_1]]

Declared table format.

[[VERBATIM:message_2]]


## F.5 Complete response schemas and verification

The native interface requests JSON conforming to the following role-specific schemas. A schema-valid response is still checked for correct source fields and supplier coverage. For supplier extraction, thirteen numerical slots are scored: four terms for each of three suppliers, plus the budget. Duplicate or missing suppliers fail exact verification even if the JSON parses. The coordinator must request the declared numerical tool and select one of the two named priorities. The critic must return approve or hold.

Supplier-information agent: JSON schema.

[[CODE:schema_supplier]]

Replenishment coordinator: JSON schema.

[[CODE:schema_planner]]

Independent review role: JSON schema.

[[CODE:schema_critic]]


The hard release condition requires verified current source fields, valid routing, solver feasibility and passing action checks. Failure holds the action; the system does not substitute a comparator's order. A permitted zero purchase is not a held decision. In the selective workflow, a recognised but malformed table or an unknown promotion flag also prevents automatic release. The deterministic checks retain authority even when the review model returns approve.

# Appendix G. Dataset windows and complete selected-series catalogues

## G.1 Data sources, selection and evaluation windows

Thirty store–product series are selected from each dataset using training-only volume strata and deterministic hash ordering, ten per stratum. M5 selection uses eligible FOODS series with selection-period average sales from 0.5 to 30. RetailNet selection uses series complete across the first 62 training dates and a selection-period normalised average from 0.02 to 1. The same selected identifiers are retained in both test windows and all three empirical stages.

[[TABLE:dataset_windows]]

RetailNet's earlier window is a rolling holdout within the published training release; the later window is the official evaluation release. M5 windows are taken from the end of the evaluation-history sales file. The selected histories were previously inspected, which limits claims of unseen-period confirmation. Stock, supplier groups, ordering terms and costs are constructed for the simulation rather than recovered from these sales files.

The catalogue means below are the values used for series selection. They differ from the past-56-day averages used to initialise stock. RetailNet catalogue means use published normalised sale_amount before multiplication by 100. Strata are coded 0, 1 and 2; the labels identify the selection bands and do not represent product categories.

## G.2 M5: all thirty selected series

[[TABLE:m5_catalogue]]

## G.3 RetailNet: all thirty selected series

[[TABLE:retailnet_catalogue]]


# Appendix H. Research-question alignment and provenance

## H.1 Research questions and hypotheses

The main dissertation asks whether the LLM-agent replenishment system improves service and simulated cost, which benefits belong to its language component, which tasks it performs reliably, and how the findings differ between M5 and RetailNet. The following table maps those questions to the reported assessments. It preserves the comparison with the same numerical planner, which helps attribute performance to the appropriate component.

[[TABLE:research_alignment]]

H1–H4 are the analytical framework introduced in the revised literature review, not a preregistered confirmatory test plan. The separate architecture criteria A1–A4 were frozen before the matched architecture evaluation. H4 needs an explicit cross-dataset comparison of effects. Different statistical verdicts within the two datasets do not establish a difference between them, and perishability alone cannot be identified as the cause of the descriptive gap.

## H.2 Model and evidence identifiers

The common pretrained model digest is shown below. It identifies the locally served Qwen model used by all three empirical stages. The tag name alone is insufficient if a future model release changes its underlying content.

[[CODE:model_digest]]

[[TABLE:source_identifiers]]

These protocol hashes identify the settings inspected for the appendix. Full source-file and prepared-data hashes are stored inside those protocols, and raw native response hashes remain with the decision records. The source package provides a complete manifest for file-level checking. Its archival comparison distinguishes the full LangGraph architecture experiment from the later LangChain implementation validation. The LangChain port does not turn the earlier full study into fresh LangChain inference.

# Appendix I. Illustrative service target, separate from empirical results

The later contribution chapter includes an optional illustration of a 3% relative improvement in demand satisfied. This is an assumed planning target. It was not achieved as a measured 3% improvement in the experiments and is excluded from their empirical effect estimates. For completeness, the calculation is reproduced below without changing the actual results.

The assumed rate equals the previous fixed agent's unrounded measured fill rate multiplied by 1.03. A 3% relative increase is different from three percentage points. It corresponds to about 2.72 additional units satisfied per 100 units of demand in M5 and 2.52 in RetailNet. Rounding the printed baseline first can slightly change the displayed last digit; the calculation uses the archived unrounded values.

[[TABLE:illustrative_target]]

No cost, expiry or profit improvement follows automatically from this assumption. Such effects depend on the inventory and supply needed to achieve the service target. The empirical tables in the preceding appendices retain the observed simulation results and their stated uncertainty.
