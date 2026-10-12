# Appendix A. Model and experimental settings

The main chapters describe the settings needed to interpret the business result. This appendix preserves the implementation details required to inspect the evaluated configuration. The source of these settings is the frozen protocol of the completed October 2026 study, together with its training and execution receipts. The dissertation rewrite reads that completed evidence and does not start another model experiment.

[[TABLE:technical_settings]]

The three roles share one underlying model. They are separate native API calls with separate instructions and inputs. The generation settings do not update the model's weights. The two early development-preparation forecast files retained directly under the dataset folders are excluded from the primary forecast count. The four primary LightGBM fits are stored under the registered weekly-origin folders and identified by their saved model and panel hashes.

The model digest is 65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b. The primary study was published in repository commit 4721351c3745fd51db9fa10b86b7e9d9839a821c. These identifiers specify the evaluated model tag and the completed evidence version; they do not imply that the language model was trained by the dissertation author.

## A.1 Measures and aggregation

The simulator's daily inventory operating cost is 0.02 times closing stock, plus five times unmet demand, plus expired units. The sum over the episode is divided by demand for the primary normalized policy measure. These coefficients are assumptions. Purchase spend is recorded separately, and the index is not a complete retailer profit calculation. Actual acquisition margins, staff effort, cloud charges and closing-stock commercial value are not estimated.

For each dataset, scenario, policy and simulation seed, the two weekly episodes are aggregated using their totals. Fulfilment divides total sales by total demand. The expiry share divides total expired quantity by total opening stock plus receipts, counting the opening inventory from each independent weekly reset. Policy means average the resulting seed measures. Overall headline means then give equal weight to the three scenarios.

The overall paired cost effect first averages scenario-level cost-per-demand measures within a seed, then calculates the relative change against the matched comparator for that seed. The reported effect averages those thirty changes. This explains why the cost percentage should not be recomputed from the rounded values printed in the main table. The paired bootstrap resamples seeds ten thousand times and retains both origins inside each sampled seed.

[[TABLE:paired_intervals]]

The intervals describe the selected historical panels under the declared simulation draws. They do not provide a population estimate or independent uncertainty over the pretrained model's weights. In particular, the near-zero M5 difference against the structured-data planner has an interval that includes zero. The RetailNet agent-layer difference is slightly adverse. Both the favourable whole-package comparison and the limiting strong comparison are retained.

## A.2 Shared forecast context

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

[[TABLE:evidence_locations]]

To reproduce the original analysis, use the complete repository and the saved study evidence. The analysis script reads the existing decisions and does not call Ollama. The original experiment script refuses to overwrite completed cases and uses its registered time window. A new inference experiment would need a new output directory and prospective protocol. The installed Ollama binary, model weights, virtual environments and full cached raw releases are not contained in the reading package; the source identifiers and hashes remain recorded.

The new dissertation package contains the Word and PDF documents, all figures, editable chapter sources, bibliography, build helpers and validation records. It is a document delivery package. The much larger complete experiment package remains separately linked in the repository. The supplied Gilbert thesis is not redistributed, and its content is not used as empirical evidence for retail replenishment. The rewrite brief records its title, author, page count and source hash solely to identify the structural reference.

## C.1 Use of AI-assisted tools

AI-assisted tools supported manuscript drafting, document production and the generation of analysis and reporting code. The local Qwen model was separately the subject of the empirical study, performing the recorded replenishment roles. These uses should be distinguished: the writing assistant's output is not an experimental response from Qwen, and Qwen's measured supplier-reading accuracy is not a claim about the drafting process. Numerical assertions are grounded in the saved experiment and its independent checks.

The dissertation does not report invented interviews, participants, acknowledgments, live purchasing or retailer financial accounts. Illustrative retail examples in the background chapters are explanations, rather than additional observations. The user-supplied thesis provides organisational guidance. The final author should review the dissertation, confirm the interpretation and follow the school's applicable disclosure requirements before submission. This statement describes the assistance used rather than asserting that a supervisor has already approved the work.

# Appendix D. Short glossary

An agent role is a defined model-assisted responsibility within the workflow, such as supplier reading or review. A language model is the pretrained system that produces the role's response. The three roles in this study use one model family. Ollama is the local serving software. Inference means using existing model weights; fitting or training adjusts a model using data. LightGBM is the numerical forecasting family fitted to the retail histories.

A store–product series is the sales history of one product at one store. A portfolio groups thirty such series for a joint replenishment decision. A weekly origin is the date at which the forecast and simulation episode begin. A simulation seed identifies one declared set of demand and supply draws. A lead time is the delay before a permitted purchase can arrive. A delivery pipeline contains goods that have been accepted for future arrival but are not yet on hand.

A carton rule restricts quantities to package multiples. A minimum order specifies the smallest nonzero line allowed. Supplier capacity limits the total quantity dispatched by a supplier group. FIFO means first-in, first-out use of stock. Expiry is the end of a batch's hypothetical usable life in the simulator. Fulfilment is the share of the declared demand served. The operating-cost index is the study's synthetic assessment measure, rather than observed currency or retailer profit.

Source verification checks an extraction against the current authenticated contract fields. A release gate applies the conditions required to execute a proposal. A hold prevents a decision from executing; it does not automatically create an alternative order. A paired comparison assesses policies under the same declared operating world. A bootstrap interval summarises uncertainty by resampling those paired simulation seeds, with related episode data kept inside each seed.
