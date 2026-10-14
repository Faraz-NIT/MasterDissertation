# Selective delegation with LangGraph: architecture experiment and one dissertation chapter

This supplement designs and evaluates a selectively delegated LLM-agent workflow for
retail replenishment. The fixed comparison calls supplier, coordinator and critic roles
on every decision. The selective workflow parses declared supplier tables directly,
uses the same LLM for supplier prose, applies declared priorities through explicit rules,
and requests review when verification fails. All workflows run through a compiled
LangGraph state graph with recorded decision paths.

The registered grid has 30 selected series per dataset, two seven-day windows,
three operating situations, 30 fresh simulation seeds and three workflows: 1,080
policy runs. Shared forecasts, starting-state rules, demand and supplier opportunities
isolate the architecture comparison. The same numerical planner with already structured
information provides a strong reference. No inventory repair, sales recovery, model
fine-tuning or previous-response reuse is performed.

## Chapter and results

The complete study finished all 1,080 runs and 9,240 fresh primary model calls in
four hours. The independent audit passed, including all native response hashes,
graph paths, matched conditions and physical inventory balances. The selective
architecture used 77.78% fewer model calls and reduced mean decision time by
54.79% in M5 and 54.93% in RetailNet. Priority accuracy reached 100% in both datasets.
M5 inventory differences were inconclusive; RetailNet fill rate improved by 0.236
percentage points and the primary cost index fell by 1.176%, alongside an overall
expiry-share increase of 0.081 percentage points. The selective orders matched the
structured-information reference exactly. All four registered architecture criteria
were met; this does not establish a numerical benefit over that reference.

The deliverables are:

- [Single illustrated Word chapter](Selective_Agent_Architecture_Chapter.docx).
- [Reading PDF](Selective_Agent_Architecture_Chapter.pdf).
- [Editable chapter](chapter.md) and [chapter tables](chapter_tables.json).
- [Six labelled figures](figures/) and [full executable graph export](architecture_graph.mmd).
- [Registered protocol](protocol.json), [execution receipt](execution_receipt.json),
  [independent audit](analysis/audit_receipt.json), [results](analysis/analysis_summary.json),
  [paired comparisons](analysis/paired_effects.csv) and [diagnostics](analysis/diagnostics.csv).
- [Complete evidence ZIP](Selective_Architecture_Complete_Evidence.zip),
  [verified archive manifest](delivery_manifest.json) and
  [compressed inventory of every archived file](file_inventory.json.gz).

The document is one additional chapter covering design, methods, results, contribution
and limitations. It can be inserted after the existing findings and before the discussion
and conclusion; number it to match the final dissertation. It does not rebuild the earlier
full dissertation or change its empirical results.

## Interpretation and scope

The architecture targets fewer native model calls, lower measured decision time,
preserved or improved policy accuracy, and preserved service and simulated cost.
The last criterion uses explicitly frozen study tolerances. Superior inventory performance
is assessed separately and is not assumed. The chapter distinguishes architectural
improvements from changes in model intelligence or numerical planning.

The architecture was motivated by earlier diagnostics. Historical windows and past-only
LightGBM forecasts are reused deliberately, with new simulation seeds and fresh model
calls. These are not unseen temporal holdouts or independent model replications.
Supplier messages and operating rules are controlled. RetailNet uses normalised sales
proxies and a hypothetical three-day stock life. Costs are synthetic inventory indices;
staff time, deployment costs and realised profit are not measured.

## Code and complete logs

See the [engineering guide](../../scripts/architecture_study/README.md) and
[architecture tests](../../tests/test_selective_architecture.py).
The pinned `requirements.txt` records LangGraph, LangChain core and numerical dependencies.
Full native request/response records, graph traces, FIFO ledgers, development runs,
prepared panels, frozen code and execution logs remain available in the complete evidence
archive. The folder's `.gitignore` keeps these originals out of individual Git entries;
their bytes and hashes are preserved and verified in the ZIP. LLM weights and credentials
are excluded.

The supervisor produces the final analysis and chapter only after the whole registered
grid finishes. Read the execution and validation receipts for the actual completion status.
