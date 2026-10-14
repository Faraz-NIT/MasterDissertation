# LangChain agent contribution chapter

This is one additional dissertation chapter building on the previous fixed
three-role replenishment agent. It presents the author's selective-delegation
design and its evaluated consequences. The strongest measured gains concern
model calls, processing time and application of the declared business priority.
M5 inventory performance remains essentially unchanged; RetailNet improves
modestly in service and simulated cost, with slightly more expiry.

The standalone Word and PDF documents contain seven figures and four tables.
They use Times New Roman 12-point body text, 1.5 spacing, justified paragraphs
and one-inch margins. Insert the chapter after the main findings, then update
chapter, figure and table numbers when assembling the complete dissertation.

## Evidence provenance

- The completed 1,080-run, 30-seed architecture comparison used **LangGraph**.
  Its primary evidence remains in `../architecture_study_20261013`.
- The new implementation uses **LangChain LCEL** and `StructuredTool` through
  `scripts/langchain_extension/chain.py`.
- Recorded-response regression reproduced all **7,560** earlier portfolio
  decisions, without new inference. This checks software consistency.
- Fresh LangChain validation completed **36 matched policy runs**, **252
  portfolio decisions** and **300 fresh native model calls**, using one new
  seed, all 30 series per dataset, both origins and all three scenarios.
  It is implementation validation, not a fresh 30-seed performance study.
- All **16** relevant tests passed. The independent physical-ledger and model
  provenance audit verified the fresh evidence without issues.

`evidence_map.json` identifies the primary and validation sources by hash.
`runs/` contains all new native requests/responses and decisions; `data/`
contains the matching historical inputs and frozen forecasts. `development/`
contains the explicitly labelled archived-response regression and test receipts.
The source study's existing complete-evidence ZIP contains its earlier raw runs.

The model is pretrained Qwen2.5:1.5b Q4_K_M served with Ollama 0.40.0, used for
inference only. The cloud instance allocated four CPU cores and 32 GiB, with no
GPU. There was no retail fine-tuning. Forecasts and the numerical planner remain
unchanged from the previous architecture study.

Results and graphs have not been modified to manufacture improvements. The
chapter foregrounds the substantial measured efficiency and policy-reliability
gains and keeps the inventory findings and limitations explicit.
