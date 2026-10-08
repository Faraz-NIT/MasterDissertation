# M5 shortened study evidence

The report covers 30 prepared M5 item-store series: three FOODS items across ten stores. Observed M5 sales are a demand proxy; inventory, contracts, fulfillment, wholesale costs, disruptions and approvals are simulated.

The numerical grid has 360 runs: four policies, three scenarios, 30 simulation seeds, one historical origin and seven decision days (2016-02-02 to 2016-02-08). The original 96-run phase and disjoint 264-run extension were joined only after the complete grid, original provenance and every worker's trained-model states were verified. The extension was chosen after observing runtime capacity; analysis remains exploratory and conditional on this historical panel.

The separate two-day study has 8 prose comparison runs (four actually call the local LLM) plus 4 structured-rule controls. These use one seed over 2016-02-02 to 2016-02-03. The local Qwen2.5 1.5B model made 30 actual requests and used 112,739 tokens. Its unit errors triggered holds before numeric optimization. Initial stock served the two-day demand; low purchase expenditure during holds is not evidence of replenishment savings. Longer and shorter windows must not be pooled or ranked using a grand mean.

M5_six_hour_results.csv preserves the three comparison groups and original source paths. The PDF explains metrics, graphs, protocol limitations and the revised dissertation mapping. The full 30-seed numerical audit and strict captured-document grounding assessments are included. Earlier longer studies and development model checks are separate evidence, not additional replications in this study.

This is a report and analysis evidence export, not a complete cloud snapshot. It includes the prepared 30-series panel, source configurations, summaries and selected complete audit archives. Full numeric object archives remain in the cloud results and are not all included here. Selected audit ZIPs contain every original object for their case. To use the repository's cached replay tool, extract the objects.zip members into that case's artifacts directory so that artifacts/objects/<sha>.json exists. Preserve all original files and verify the supplied SHA inventories first.

The external helpers require the repository and its validated virtualenv; model weights and the virtualenv are not bundled. Repository commit and official local model digest are pinned in recorded manifests. Credentials are not required for public M5/local model artifacts. No human study, field ERP deployment, foundation comparison or complete dissertation hypothesis matrix was conducted.
