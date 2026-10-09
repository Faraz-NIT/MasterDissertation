# Fresh Ollama replenishment study — M5 and RetailNet

This folder is a new experiment. It uses a new agent design, newly selected panels,
freshly fitted forecasts and fresh local model calls. Earlier experiment outcomes
are not combined with it. There is no inventory repair, sales recovery or data-fault
layer, and model response caching and retries are disabled.

The completed, independently audited study contains **30 series per dataset, two seven-day
historical windows, 30 simulation seeds, three operating scenarios and three policies**.
It completed **1,080 runs, 7,560 portfolio days, 226,800 series-days and 7,560 fresh primary
Ollama calls**, with 7,560 unique response timestamps. See the
[execution receipt](execution_receipt.json) and [audit receipt](analysis/audit_receipt.json).
Live evaluation took 2.66 hours; preparation, reporting and publication were additional steps
within the registered four-to-five-hour budget.

Against conventional ordering, the complete workflow increased mean simulated fulfilment
by **25.28 percentage points in M5** and **0.78 points in RetailNet**, and reduced the
operating-cost index by **70.34%** and **4.52%**, respectively. Supplier extraction was
100% correct in the controlled messages. The same numerical planner without the LLM
matched or outperformed the agents, so these gains must also be credited to the planning
tool. The report provides the paired intervals and limitations.

## Documents and downloads

- [Study PDF](Fresh_Ollama_Study_Report.pdf)
- [Editable study Word report](Fresh_Ollama_Study_Report.docx)
- [HTML report](Fresh_Ollama_Study_Report.html)
- [Complete new study download ZIP](Fresh_Ollama_Study_download.zip)
- [All figures](figures/)

On GitHub, open a document or ZIP and choose **Download raw file**. The 19-page PDF,
editable Word report and 15 figures were generated after the independent numerical audit
passed. Figure titles explicitly identify M5, RetailNet, or both datasets.

## What is compared

1. **Conventional ordering:** an order-up-to policy with proportionate budget and
   capacity allocation, current structured rules and aggregate inventory position.
2. **Structured-data planner:** the same constrained-order tool, stock-age projection
   and business-priority rule used by the agents, supplied with current structured rules.
3. **Ollama agents:** three separate model calls for supplier reading, planning-tool
   coordination and proposal review. Independent source and action checks govern execution.

The scenarios are routine trading, a supplier disruption, and an announced promotion.
There is one forecasting family: LightGBM. There is one language model: pretrained
Qwen2.5 1.5B served locally through Ollama. It is not fine-tuned on retail data.
The machine has four allocated CPU cores and 32 GiB memory; inference uses the CPU.

The comparison with the conventional policy measures the complete workflow. The
structured-data comparison separates the language-model layer from the numerical tool.
No model-superiority claim is assumed in advance.

## Evidence

- [Frozen protocol](protocol.json) and [evaluated policy source](frozen_code/).
- [Data-preparation receipt](data/preparation_receipt.json), selected catalogs and model files.
- [All matched run folders](runs/), including full native Ollama request/response JSON and
  every portfolio decision with series-level stock, sales, demand, expiry and orders.
- [Execution log](logs/execution.log), [progress](progress.json) and [workflow events](workflow.jsonl).
- [Development](development/): preserved failed and passing prompt checks, benchmarks,
  training-only integration and numerical test receipt. These are excluded from primary results.
- [Analysis](analysis/): run/daily/seed tables, paired effects, model diagnostics and audit receipt.
- [Figure register](figure_register.json), [document checks](document_receipt.json),
  [complete file hashes and verified ZIP](delivery_manifest.json).

The primary numerical model files are under `data/M5/origin_1927`, `origin_1934`,
`data/RetailNet/origin_83` and `origin_90`. Files directly under each dataset folder
are initial development-preparation fits; they are not additional primary forecasts.
There are four primary fits of one shared forecasting family, not four competing models.
The protocol's source commit identifies the repository parent; the evaluated new
scripts are identified by their frozen byte hashes and copied into `frozen_code`.

## Interpretation

The quantity and cost conventions differ from commercial inventory accounts.
RetailNet uses normalized published sales multiplied by 100. Inventory, supplier
terms, budgets, delivery events and shelf life are simulated. The primary operating
cost index adds holding, unmet-demand penalties and expiry; purchase spend is recorded
separately to avoid counting acquisition and expiry twice. These are not retailer profits.

RetailNet's earlier window is a rolling holdout from its training file; its later window
is the official evaluation release. Historical periods were used in earlier work;
fresh execution does not make them previously unseen research holdouts. Confidence
intervals resample paired simulation seeds with weeks aggregated inside seed. They
describe these simulated panels, not the full retailer population.

## Regenerate the analysis and reports

From the complete repository with the required Python packages:

```bash
.venv/bin/python scripts/ollama_clean_study/analyze.py
python scripts/ollama_clean_study/report.py
python scripts/ollama_clean_study/deliver.py
```

The reporting Python environment needs matplotlib, pandas, numpy, python-docx,
PyMuPDF, reportlab and Pillow; Graphviz supplies the workflow figure. The execution
environment uses the repository core/ML dependencies plus `jsonschema` in
`scripts/ollama_clean_study/requirements.txt`.

The original execution has a fixed registered time window and refuses to overwrite
existing run cases. A future inference experiment needs a new output directory and a
newly registered time window. Regenerating reports reads completed evidence and does
not call Ollama. Full raw source caches and installed language-model weights are not
part of the download ZIP; their identifiers and hashes are recorded separately.
