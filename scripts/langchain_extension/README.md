# LangChain extension of the previous replenishment agent

The contribution is selective delegation in the existing agent, with its
numerical planner, source verification, native model settings and release
constraints retained. The framework itself is not claimed as original work.

`chain.py` runs real LangChain LCEL sequences and conditional `RunnableBranch`
objects. The unchanged numerical planner is exposed as a `StructuredTool`.
The previous frozen graph nodes are reused as ordinary functions; the compiled
LangGraph is never invoked by this chain. Imports retain `langgraph` as a
dependency because the original module constructs its unused graph on import.

The fixed three-role baseline and structured-input comparator run through the
same LangChain chain. Native model calls retain the original prompts, JSON
schemas and generation settings rather than introducing adapter-specific prompt
changes. No conversation memory, external tracing or response cache is enabled.

## Evidence scopes

1. The completed 30-seed architecture study was executed with LangGraph:
   `study_results/architecture_study_20261013`. Its results remain attributed
   to that implementation.
2. `replay.py` supplies archived responses and reconstructs all 7,560 earlier
   decisions through LangChain. This is a software regression, not live inference.
3. `validation_run.py` uses fresh local-model calls, seed 233, all 30 series per
   dataset, both origins and all three scenarios: 36 matched runs, 252 portfolio
   decisions. It is implementation validation, not a new 30-seed study.

The output location is deliberately fixed to protect earlier evidence. The
scripts refuse to overwrite frozen protocols, replay receipts or live runs.
Reproduction in a populated checkout requires a separately named output
location and corresponding explicit protocol change. Do not delete published
evidence to make these commands execute again.

## Verified workflow

Run from `/workspace/MasterDissertation`, with the local model server available
and the model digest matching the frozen protocol:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python -m pytest -q tests/test_langchain_extension.py tests/test_selective_architecture.py tests/test_ollama_clean_study.py
# Create development/tests.json from the completed test execution, then:
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/langchain_extension/validation_run.py freeze
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/langchain_extension/replay.py
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/langchain_extension/validation_run.py run
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/langchain_extension/validate.py
XDG_CACHE_HOME=/tmp/langchain-chapter-cache MPLCONFIGDIR=/tmp/langchain-matplotlib python scripts/langchain_extension/report.py
```

Use LibreOffice with a temporary user profile to render the Word document to PDF.
`verify_document.py` checks the complete manuscript, tables, figure count,
formatting and page bounds and exports rendered review pages. All new native
responses, inputs, decisions and audit receipts are retained in the study folder.

The archived previous model outputs required for the regression are included in
the original study's `Selective_Architecture_Complete_Evidence.zip`. Extract
that archive into its study folder if ignored `runs/` and `data/` directories
are absent in a fresh Git clone. They are not silently downloaded or reused by
the fresh live validation.
