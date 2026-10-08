# Deadline-owned M5 study

This coordinator implements the user's revised six-hour scope. It accepts explicit frozen runtime configs, keeps all30 M5 series, and never defaults to the superseded900/540-run studies. It selects or downloads no model. Use the existing cloud checkout and repository virtualenv; no worktree is needed.

Read-only preflight:

```bash
/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_six_hour.py --once \
  --numeric-config /workspace/MasterDissertation/results/run_configs/six_hour_numeric.yaml \
  --job-deadline-utc 2026-10-08T01:31:00Z \
  --report-deadline-utc 2026-10-08T02:01:00Z
```

Add `--llm-config /absolute/frozen/runtime.yaml` for each selected local-LLM stage after model development measurements and its actual digest are frozen. To begin numeric work before the mandatory live-model config is frozen, pass `--wait-for-llm-config /absolute/future/runtime.yaml`. An optional future arm uses `--optional-llm-config /absolute/future/runtime.yaml`; its absent file never delays finalization once mandatory stages finish. Only these explicit future paths can be accepted, and actual-model/config validation occurs before launch. Use `--numeric-workers 1` with the selected three-thread local model to respect the four-core quota. Supplied configs must live in ignored `results/run_configs`, contain the genuine prepared30-series M5 panel, and use separate generated outputs. Before execution, the coordinator checks actual `/api/tags` identity against each configured model revision. Source files and tracked configs remain unchanged.

Explicit execution uses the same arguments with `--run`. One numerical driver with up to two seed workers and one LLM driver with a single inference worker run concurrently; multiple configs in either category queue sequentially. All owned driver processes run at nice10 and inherit supported local Ollama/cache paths. Full model requests and numerical outputs retain their genuine timestamps, token usage, errors, source links and experiment settings.

The requested absolute deadline is04:01 on8October2026 in Paris (02:01UTC). Owned study jobs stop at03:31Paris (01:31UTC), reserving30minutes for the final PDF. The coordinator enforces the cutoff independently of progress; a periodic PDF refresh is capped at60seconds or the time remaining before cutoff. Final generation uses the reserved reporting interval. Only newly owned process groups are interrupted. Existing baseline jobs and servers are not signaled.

A2GiB free-space reserve is enforced throughout. Each driver uses verified completed-run packing every60seconds and strictly before merging. Full object ZIPs and byte/hash/audit inventories are retained; the report uses actual completed summaries and preserved trace samples. Partial runs remain partial. Reports do not substitute interrupted audit objects for completed results.

`results/run_configs/six_hour_supervisor_control.json` stores the live execution epoch and `pause_requested`. An actual pause request or epoch change stops owned jobs; elapsed time is never treated as user approval. State is in `six_hour_supervisor_status.json`, actual model/config/resource evidence in `six_hour_runtime_preflight.json`, and stage coverage in `pipeline_status.json`. Freeze a new output for a changed model, config, horizon or seed grid; do not merge changed designs.

PDF refresh command:

```bash
/workspace/MasterDissertation/.venv/bin/python /workspace/MasterDissertation/results/report/generate_report.py --scope six-hour
```

The coordinator appends `--final-snapshot` at finalization. Output is `results/report/M5_six_hour_study_report.pdf`, with HTML, Markdown, graph PNGs, data and input hashes alongside it. Earlier full-study report files remain preserved. Report availability does not establish completion: coverage, failed stages, simulated inventory/supply, reduced solver settings and omitted full-dissertation checks must remain explicit. Numerical and LLM arms with different horizons/carriers/seeds must not be pooled as interchangeable replications.

Nine isolated validation tests passed. They check zero process launches in read-only preflight; the actual frozen96-run/672-decision/all30-series numerical scope; category and model-revision rejection; timezone/deadline rules; epoch controls; a real owned-process-group interrupt leaving another fixture process group alive; and final report scope/cutoff arguments. The tests launch no experiments. Existing packed-merge validation separately covers exact28-day trace coverage, verified full objects and repeatable merging. Actual new-model generations are measured separately before LLM launch.
