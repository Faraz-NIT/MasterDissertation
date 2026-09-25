# Validation performed for this delivery

Date: 2026-09-23. All experiments below use generated synthetic data; **none are M5 empirical findings**.

## Executed checks

- **67 automated tests passed** on Python 3.13.5 / Linux x86-64, including actual CPU LightGBM and native GRU/NB training/prediction, past-only fixtures, M5-shaped CSV import, state-fault checks, optimization, local idempotency/tampering, grounding, statistics and end-to-end replay/audit export.
- **18 bundled demonstration runs**: B1/D0/D1 × normal/feed-gap/inventory-collapse × two independent seeds, six decision days each. All **108 decisions** reproduced their action and state certificate in cached-evidence replay. See `examples/validated_demo/replay_validation.json`.
- **56 additional scenario runs**: D0/D1 across all **28 registered scenarios**, one seed, three decision days. Every audit chain verified. These are scenario-coverage smoke tests, not powered efficacy estimates.
- **Six actual ML-baseline runs**: B2/B3/B4 × normal/inventory-collapse, with a small trained LightGBM/GRU configuration. Every audit chain verified.
- Separate past-only forecast backtests completed for seasonal naive, LightGBM and GRU/NB. Controlled six-case template grounding completed with labels excluded from extraction inputs.
- Editable package build/install succeeded with already-installed dependencies, using `pip install -e . --no-build-isolation --no-deps`. Source and scripts compile.

There are **294 simulated evaluation decisions** across the 18 + 56 + 6 validation runs. Warm-up periods and unit-test decisions are not included in that count.

## Environment

Python 3.13.5; NumPy 2.3.5; pandas 2.2.3; SciPy 1.17.0; Pydantic 2.13.4; PyYAML 6.0.3; HTTPX 0.28.1; PyTorch 2.10.0+cpu; LightGBM 4.6.0. `requirements-tested-core.txt` pins the tested direct core dependencies. Optional CPU Torch wheels can have platform-specific suffixes; that file deliberately does not force a GPU wheel or private index.

## Not executed or not established

- No actual downloaded M5 data was supplied; import was tested with a generated M5-format fixture.
- No live LLM calls or Chronos model downloads were made. The HTTP adapter was tested against mocked HTTP responses, not a fake model presented as B10. B6–B10 and B5 require user configuration/weights for real experiments.
- No TFT/Moirai reproduction, proprietary telemetry calibration, real supplier workbook study, human-subject study or enterprise execution was performed.
- General XLSX value-reading support is supplied, but no real supplier workbook was validated here; month/cluster helper behavior is covered by tests.
- No fresh network-based dependency resolution, other operating-system installation, Docker image build or provider compatibility guarantee is claimed. The CI workflow is included, not claimed to have run on GitHub.
- Passing tests and reproducing cached decisions do not prove the dissertation's hypotheses, security against every injection, or causal faithfulness of hidden model computation.

Raw validation logs and compact extended-run summaries are in `examples/validation/`. Full replay artifacts are included for the 108-decision synthetic demo only. Inspect `README.md` and `docs/IMPLEMENTATION_MATRIX.md` before designing final research experiments.
