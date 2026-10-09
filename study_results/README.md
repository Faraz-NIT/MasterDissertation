# M5 and FreshRetailNet study reports and complete evidence

The latest experiment is the [fresh no-repair Ollama study](ollama_clean_study_20261009/).
It completed 1,080 matched policy runs on 30 series per dataset, two weekly windows,
30 simulation seeds and three scenarios, using 7,560 fresh Qwen2.5 1.5B calls.
Download its [19-page PDF report](ollama_clean_study_20261009/Fresh_Ollama_Study_Report.pdf),
[editable Word report](ollama_clean_study_20261009/Fresh_Ollama_Study_Report.docx), or
[complete graphs, data, code and logs ZIP](ollama_clean_study_20261009/Fresh_Ollama_Study_download.zip).
The [15 labelled figures](ollama_clean_study_20261009/figures/) and
[independent audit](ollama_clean_study_20261009/analysis/audit_receipt.json) belong to the redesigned study.
Its outcomes are not combined with the earlier experiments below.

The earlier [rewritten Word dissertation](business_dissertation/LLM_Replenishment_Business_Dissertation.docx)
and [rewritten dissertation PDF](business_dissertation/LLM_Replenishment_Business_Dissertation.pdf)
present the previous study design in six accessible chapters, with 22 explicitly labelled graphs and concise
results and conclusion chapters. The [download ZIP](business_dissertation/LLM_Replenishment_Dissertation_download.zip)
includes both documents, the figures, editable manuscript and validation records. See the
[rewrite guide](business_dissertation/README.md) for formatting, evidence and reproduction details.

The previous [dual-benchmark Word dissertation](freshretailnet/Dual_Benchmark_Dissertation_Final.docx)
and [previous dissertation PDF](freshretailnet/Dual_Benchmark_Dissertation_Final.pdf) retain the
original eight-chapter structure. The [FreshRetailNet study folder](freshretailnet/)
contains its detailed PDF, graphs, individual result tables, M5 comparison, audit receipts and
complete evidence archives. Use the [FreshRetailNet report download ZIP](freshretailnet/FreshRetailNet_report_download.zip)
for the documents, tables and new graphs together.

The earlier [M5-only Word dissertation](dissertation/Evidence_Gated_Autonomy_Dissertation_Final.docx)
and [M5-only PDF](dissertation/Evidence_Gated_Autonomy_Dissertation_Final.pdf) remain as historical versions.
The original M5 evidence archives below are unchanged.

## M5 reports

Start with the [final V2 PDF](v2/M5_v2_pilot_report.pdf), or download the [small report ZIP](M5_report_download.zip) containing the PDF, result tables and nine graphs. The [HTML report](v2/M5_v2_pilot_report.html) and [Markdown report](v2/M5_v2_pilot_report.md) contain the same report narrative. On GitHub, open the PDF and use **Download raw file** to save it to your computer.

The V2 improvement pilot completed on 7 October 2026 UTC in approximately 60 minutes: all 30 selected FOODS series, four scenarios, two seeds, four matched arms, 32 runs, 448 decision days, 68 fresh model calls and zero committed-action constraint violations. It used 14 simulated days at one origin, rather than the full dissertation experiment grid.

In the derived-field-collapse scenario, verified recovery reduced mean simulated cost from USD 894.30 to USD 796.51 (10.93%) and increased fill rate from 89% to 96%. The strongest parser achieved the same improvement. LLM and parser results matched in all eight scenario/seed comparisons at each recovery setting. The model's recovery choices followed the instruction in only 10 of 20 calls; deterministic tools and gates contained the errors. The results support bounded evidence recovery, not an additional operational benefit from the LLM in this pilot.

## Reports and tables

- [V2 run results](v2/M5_v2_results.csv), [paired comparisons](v2/M5_v2_paired_descriptive.csv), [daily decisions](v2/M5_v2_decisions.csv), and [model calls](v2/M5_v2_model_calls.csv).
- [Original six-hour study PDF](v1/M5_six_hour_study_report.pdf), [original results](v1/M5_six_hour_results.csv), and [original compact evidence ZIP](v1/M5_six_hour_results_and_evidence.zip).
- [Revised dissertation supplied for study alignment](research_context/dissertation_revised_business_school.html).
- [Execution, reporting and audit helpers](../scripts/cloud_study/README.md), evaluated source under `src/ega/`, and tests under `tests/`.

The historical reports, failed development attempts, superseded runs and paused full-study checkpoints are retained in the complete archives. Use `v2/M5_v2_pilot_report.pdf` as the final V2 report; historical renderings are preserved as evidence, not additional completed studies.

## Complete files and logs

GitHub limits individual Git files to 100 MB. The complete evidence is therefore stored in ordinary Git as archive parts of at most 48 MiB, without Git LFS. [archives.json](archives.json) records every part's SHA-256, size and order. The compressed [study file inventory](study_file_inventory.json.gz) records each original path, hash and archive member.

There are two archives:

1. `M5_v2_complete_logs_and_evidence.zip`: the original, byte-identical V2 full export. It includes content-addressed objects, SQLite audit histories, complete request/response logs, grounding cache, failed and passing checks, frozen protocol/source/configuration, prepared panel, saved GRU and reports. Its SHA-256 is `1095db66afb2d34d059b9d702a670e21f433f7c22773407a4797277312606234`.
2. `M5_other_study_files.zip`: all remaining study output bytes, including the original studies, earlier development, paused experiments, export receipts, compact archives, other prepared panels and external helpers. Identical files share an archive member; the inventory restores every original path.

After cloning or downloading this repository, reassemble both archives with Python 3.11 or later:

```bash
python scripts/study_delivery.py
```

This verifies every archive part and the joined ZIP hashes, then writes the ZIPs into `study_results/reassembled/`. To additionally restore and verify every original study file in a separate directory:

```bash
python scripts/study_delivery.py --restore /tmp/m5-study-restored
```

The restored tree contains `results/`, `data/processed/` and `external_helpers/`. Restoration refuses to overwrite different existing files. Original recorded absolute cloud paths remain in historical provenance. Archived helpers refer to `/workspace/MasterDissertation` and `/workspace/tools`; restoration alone does not install dependencies, download the pinned language model or restart any experiment. The results include simulations and controlled document grammars, not live retailer deployment.

Full raw M5 competition downloads, language-model weights, installed binaries, virtual environments, authentication files and runtime/compiled caches are excluded. All existing study result files and logs are preserved in the inventories and archives.
