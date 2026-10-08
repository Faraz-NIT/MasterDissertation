# Appendix A. Evidence guide and completed study register

The main chapters explain the completed findings. The repository retains the individual run tables, exact requests and responses, recorded decisions, fitted forecast models and audits. This rewrite changes the structure and presentation of the dissertation; it does not add simulations or alter the published experimental evidence. The evidence commit is f98e31e5fc8ecab39d058a53da7936a9b0dbfca5 in Faraz-NIT/MasterDissertation.

The M5 version-1 study contains 360 numerical runs, eight two-day live-prose runs and four two-day structured controls. The M5 version-2 pilot contains thirty-two fourteen-day matched runs. FreshRetailNet contains 392 primary runs, 480 exploratory cap-transfer runs and 1,140 separate policy calculations. Forecast fits and the training-only cap calibration are separate. A simulation seed is not a new historical period, and a cached interpretation is not a fresh model judgement.

[[TABLE:artifact_guide]]

[[TABLE:m5_numerical_summary]]

[[TABLE:retailnet_numerical_summary]]

## A.1 M5 numerical and forecast context

The original numerical experiments help explain the range of reference policies. They are not the same study as the improved matched reader pilot. The figures below use the retained numerical and pre-main-study forecasting evidence. Forecast backtests overlap in time and are descriptive; their ranking concerns the reduced panel rather than the complete M5 benchmark. Actual violated checks are reported separately from differences relative to a clean reference action.

[[FIGURE:m5_numerical_overview]]

[[FIGURE:m5_forecast_context]]

# Appendix B. Data sources and model settings

M5 source files are sales_train_evaluation.csv, calendar.csv and sell_prices.csv from the M5 competition data. The prepared thirty-series panel uses FOODS_1_001, FOODS_2_001 and FOODS_3_001 across ten stores. Its recorded history has 1,941 daily positions. Sales serve as an exogenous demand proxy; no true lost-demand observation is asserted. Inventory movements, supply rules and other operational objects were created for the experiment.

FreshRetailNet-50K was downloaded from Dingdong-Inc on Hugging Face at revision 08c1fab7f9257bc73679d415d65d644165d351d4. The source is licensed CC BY 4.0, with attribution to Dingdong and the dataset's authors. Training and evaluation file hashes and validation receipts are retained in the evidence. The release has 4.5 million training rows and 350,000 evaluation rows, with the same 50,000 series. The computational panel contains thirty training-selected pairs; release-level validation does not expand the scope of performance evaluation.

Availability flag 1 means out of stock. The sixteen operating-hour positions run from 06:00 to 21:00. Discounts outside the usual range were retained and flagged, rather than silently removed, and discount was excluded from the forecasting feature set. Daily and hourly sales agreed within numerical precision. Publisher descriptions and pinned-file counts are recorded separately where they differ. The experiment does not claim access to actual supplier contracts, opening inventory, shelf-life labels, procurement prices or natural unserved demand.

The language model in the improved studies was ega-qwen2.5:1.5b-v2, based on pretrained Qwen2.5 1.5B, with model digest afc65fa44af0fb5f81dd6d0066bdf668521db7077c36a9635c09d13376fe4c90. It was run using Ollama on CPU, with Q4_K_M representation, an 8,192-token working context, three threads, temperature zero and a fixed generation seed. The earlier M5 feasibility stage used a different frozen study tag and a larger working context; its settings and outcomes remain in the historical protocol. Neither tag represents language-model fine-tuning on the retail panels.

Forecasting used a small recurrent GRU model with thirty-two hidden units, ten fitting epochs and a fifty-six-day history, alongside LightGBM and simpler references in the relevant analyses. The main FreshRetailNet neural forecast was trained on the ninety historical training days and saved before evaluation. The cap calibration used an earlier training-only forecast and did not open the official evaluation file. In the separate forecasting study, rolling validation endpoints were 62, 69, 76 and 83, followed by seven-day predictions. Future realised contextual fields were excluded.

The main FreshRetailNet simulation multiplies normalized sales by 100 to create integer planning quantities. Its default physical shelf life is a simulated three days, using older stock first. The planning optimizer does not use a detailed age profile. The separate calculators retain normalized numerical quantities and use their own supply and cost conventions. Their default illustrative demand multiplier is 1.25, but that multiplier is an assumption rather than an estimate of actual natural lost demand. Their costs and waste measures must therefore be interpreted within that experiment.

[[TABLE:technical_settings]]

# Appendix C. Additional RetailNet analyses

The hourly recovery figure shows an identifiable reconstruction test on artificially hidden observed sales. It does not reveal the amount of demand lost during a natural stockout. The primary numerical overview belongs to the fixed-cap study, while the age-aware sensitivity belongs to the separate calculator analysis. These distinctions are preserved in the dataset labels and source notes so that readers can investigate the underlying findings without mixing unlike experiments.

[[FIGURE:retailnet_mask_recovery]]

[[FIGURE:retailnet_numerical_overview]]

[[FIGURE:retailnet_expiry_sensitivity]]

# Appendix D. Plain-language metric glossary

Fill rate is served simulated demand divided by total simulated demand. A higher value means that more of the demand in that experimental world was fulfilled. It is not automatically the same as the fraction of days without a stockout.

WAPE is total absolute forecast error divided by total target sales. A lower percentage means smaller errors relative to the target volume. It is not the percentage of predictions that were incorrect and is not a direct measure of true demand during naturally censored periods.

Simulated cost combines the purchases, holding costs and penalties specified by a simulation. M5 uses its own modelled monetary conventions. Main RetailNet costs and separate policy-calculator costs are indices with different units and assumptions, and should not be pooled or converted into retailer profit.

A held decision means the workflow did not permit an order to execute. A hold can be justified by missing evidence or approval conditions, but excessive holds can lower service. The real time and cost of human review were not measured here.

An actual constraint violation means that a committed order failed an active business restriction. A reference deviation means that an action differed from a clean reference beyond a tolerance. The latter does not by itself establish a rule breach, customer injury or realised economic harm.

Expiry share in the main service–waste figure is expired simulated quantity divided by opening stock plus receipts. Other technical exports retain expiry per demand and expiry per served quantity. Their denominators differ, so these values should not be interchanged.

A percentage change compares a value with its baseline in relative terms. A percentage-point change subtracts one percentage from another. Moving from 89% to 96% fill is a seven-percentage-point change.

An exploratory result comes from an analysis developed after relevant primary outcomes were seen or from reuse of the evaluation period. It can inform design and motivate further research, but should be confirmed on new evidence before being presented as an established deployment effect.

# Appendix E. Research presentation and AI assistance

The supplied dissertation by Mattéo Gilbert, Predicting Temperature Variations Across Europe Using Machine Learning and Geospatial Data for Climate Change Impact Analysis, was used as a structural reference. Its broad progression from context and the role of data to model development, findings, recommendations and future research informed this rewrite. Its prose, figures, climate findings, acknowledgements, personal details and research claims were not reused. The current retail research remains a different study with its own data and evidence.

AI assistance was used in software development, analysis support, drafting and editing during this research workflow. Experimental statements are tied to saved datasets, run tables, source receipts and independent checks. Responsibility for the final interpretation, citations and submission remains with the author. No human-participant study, employee interviews or operational deployment took place.

The main manuscript contains more than 15,000 words before references and appendices. The Word document declares Times New Roman throughout, with twelve-point, justified main text, 1.5 line spacing and one-inch margins. Graphs use explicit M5, RetailNet or combined dataset labels. RetailNet is the shortened presentation label for FreshRetailNet-50K. Detailed run files and the historical reports remain available separately so that the results and conclusion can stay concise.
