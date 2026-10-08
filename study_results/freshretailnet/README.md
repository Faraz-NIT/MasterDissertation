# FreshRetailNet study and dual-benchmark dissertation

Download the [full Word dissertation](Dual_Benchmark_Dissertation_Final.docx),
the [dissertation PDF](Dual_Benchmark_Dissertation_Final.pdf), or the
[detailed FreshRetailNet report](FreshRetailNet_study_report.pdf).
The [report download ZIP](FreshRetailNet_report_download.zip) contains both PDFs,
the Word file, result tables and all new figures. On GitHub, select **Download raw file**.

The study validated the complete pinned FreshRetailNet release: 4,850,000 daily rows,
50,000 store–product series, 898 stores, 18 cities and 865 product IDs. Replenishment
experiments use a training-selected panel of **30 series**, or **0.06%** of the release.
Every main simulation run uses all 30 series. This is a bounded study, rather than an
evaluation of replenishment performance across all 50,000 series.

## Completed evidence

- Primary study: **360** conventional numerical runs and **32** matched parser/LLM
  runs, with seven simulated days per run. The numerical grid has 30 simulation seeds;
  the primary live-agent pilot has two seeds.
- Separately registered exploratory gate-transfer follow-up: **480** runs, four
  configurations, four scenarios and 30 simulation seeds, with **3,360** decisions.
- Independent policy analysis: **1,080** perishability/demand/calculator sensitivity
  runs and **60** valid-stockout gate ablations. These calculators use different units
  and supply assumptions and are not pooled with the main MILP study.
- Protected forecasting and artificial-mask recovery tests, including four rolling
  validation folds and the publisher's seven-day evaluation period.

This yields **2,012 completed simulation runs** and **14,084 run-days**, excluding the
separate training-only calibration and forecasting fits. An independent audit verifies
the primary and follow-up grid, source objects, event chains, physical stock balances,
cost arithmetic, grounding and physical model requests/responses. The receipts are in
[receipts/](receipts/); complete raw logs and source data are in the evidence archive.

## What the evidence supports

Raw LightGBM achieved **38.84% WAPE** on fully stocked evaluation days, versus
**42.84%** for seasonal naïve. Recovered forecasts did not beat raw LightGBM on that
target. Artificial masking identifies recovery error where sales are observed; naturally
lost demand during real stockouts remains unobserved.

The unmodified M5 spending cap held every normal, inventory-field-fault and feed-gap
day in the primary agent pilot. That transfer failure remains in the report. A separately
registered follow-up selected a cap of **1,850** from training-only proposals. Its
evaluation reuses the official holdout after the primary results were seen and is
explicitly **exploratory**. In its inventory-field-fault scenario, verified repair changed
LLM-arm mean simulated cost by **-11.71%** and fill by **+12.25
percentage points**. The parser receives the same verified repair. The matched outcomes below distinguish
any shared architectural benefit from an additional return from the language model.

The primary LLM/parser outcomes match in **16/
16** pairs. The exploratory follow-up matches in
**240/240** pairs. Primary agent
configurations have **0** actual committed-action constraint
violations; follow-up configurations have **0**.
The conventional MILP also has zero actual violations in the primary study, so the
LLM cannot receive unique safety credit. Wrong recovery requests are retained and
independent tools refuse stale evidence. Cached grounding is not a fresh semantic trial
for each simulation seed.

Sales are globally normalized amounts. Inventory, procurement, suppliers, lead times,
expiry, lost demand assumptions and costs are simulated. Main costs are an index,
not USD, CNY or retailer profit. The inherited MILP is age-unaware despite physical
FIFO expiry; the separate policy calculators examine age handling. The M5 comparison
is descriptive and uses within-dataset changes because horizons, products and economics
differ. No human participant study or production ROI was measured.

## Source attribution and reproduction

Data: **Dingdong-Inc/FreshRetailNet-50K**, CC BY 4.0,
https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K
at revision `08c1fab7f9257bc73679d415d65d644165d351d4`.
Publisher methods and counting discrepancies are recorded in the source receipts.
The locally hosted model is `ega-qwen2.5:1.5b-v2`; there were no paid API calls.
CPU, installation and human oversight costs are not monetized.

The complete pinned train/evaluation Parquet files, selected panel, saved forecast
tensors, requests/responses, content-addressed decision objects, SQLite logs, failed
development checks, protocols, audits and report sources are preserved byte for byte.
[archives.json](archives.json) records archive-part hashes and order;
[file_inventory.json.gz](file_inventory.json.gz) records every original path.
Parts are at most **48 MiB**, stored in ordinary Git without Git LFS.

After cloning the repository, reassemble and restore using Python 3.11 or later:

```bash
python scripts/freshretailnet_delivery.py --restore /tmp/freshretailnet-restored
```

Every part, joined archive and restored file is verified by SHA-256. Restoration
refuses to overwrite different existing bytes. Recorded absolute cloud paths remain
in provenance; restoration alone does not install dependencies or restart experiments.
For a compact read-only restoration, add `--link-identical`: all original paths are
restored, but identical files share hardlinks. Edits to one such file affect its aliases;
the default restoration writes separate copies.
Local model weights, runtime binaries, virtual environments and authentication are
excluded. Do not rerun the immutable primary protocol over existing evidence folders.
All original M5 delivery archives remain unchanged.
