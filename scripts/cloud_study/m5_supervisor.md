# M5 local-model execution supervisor

Use `/workspace/MasterDissertation/.venv/bin/python`; source files and tracked configs remain unchanged. Runtime study configs live in ignored `results/run_configs`. Each cloud task already has an isolated checkout; use that checkout without creating a worktree.

Read-only preflight (no downloads, service starts, or study processes):

```bash
/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_supervisor.py --once
```

Add `--no-network-probe` to omit the bounded official weight-storage check. Its verified HTTPS Range request reads at most 1024 bytes. Probe logs contain only host/status, never signed URL query values. A recurring supervisor probe waits at least 60 seconds; it retries a failed verified download only after the observed storage-connectivity signature changes. No verification is bypassed.

Prepare and measure the actual model, stopping before evaluation:

```bash
/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_supervisor.py --prepare
```

Prepare reuses an existing healthy local Ollama server and verified model; if absent, it starts only its own localhost server using supported OLLAMA variables and verifies official model downloads. It creates `ega-llama3.2:3b-cloud30` with context32768 and two inference threads, then pins the actual installed digest before any LLM evaluation. Structured functional validation retains actual token usage. Four real single-document template/prose extraction requests use the full 30-series entity catalog on development day1700, before holdout/evaluation. Labels are evaluated afterwards, never sent in prompts; failed schema/semantic results stay failures. `--full-development-pilot` adds an optional one-day, all30-series B9 prose simulation run, which can take hours on CPU. Development has a24-hour default command bound, configurable with `--development-timeout`; full studies have no wall-time cap.

Batch16 development diagnostics remain under `results/local_model_development_30series_batch16`, including observed omitted/incorrect rules. The accepted common study batch is1. Batch1 results use `results/local_model_development_30series_batch1`; revisions, batch sizes and outputs cannot be silently reused across the two designs.

After measured preparation and review, explicit full execution is:

```bash
/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_supervisor.py --run
```

This runs the frozen900-run template architecture study and540-run prose study sequentially through `m5_parallel.py`, each with one local inference worker, max15000calls/run, full30-series data and matched seeds/origins. Runtime is quantitatively reported and has no inferred user-authorization deadline. User chose this CPU instance despite the substantial duration. It does not launch or stop independently running numerical studies.

The supervisor checks a2GiB free-space reserve throughout owned jobs. Measured ZIP-deflate samples and expected request counts are retained with future numerical-stage storage in `results/run_configs/local_model_resource_preflight.json`. A static storage estimate is an estimate, not observed allocation; actual disk reserve remains independently enforced. Model-only time estimates exclude training, solver/reference work, cache effects, retry effects and scheduling. It does not claim that model installation establishes extraction quality.

`m5_parallel.py --pack-completed` verifies and packs completed worker runs every60seconds, defers nonempty SQLite WALs, and packs strictly after workers exit before merging. ZIP archives preserve every original object and byte; SQLite chains, object hashes and every archive entry are checked before removal. The first3 trace/certificate/proposal objects remain unpacked for the standard report. The driver and supervisor share an artifact-merge lock, so packed objects are not copied during deletion. Report generation refreshes on progress/completion and reads verified packed artifacts. Use `m5_pack_artifacts.py --restore CURRENT_RUN_DIRECTORY` before tools requiring fully unpacked objects; do not rely on old worker paths after merging.

`results/run_configs/supervisor_control.json` contains `epoch` and `pause_requested`. Setting `pause_requested:true`, or changing `epoch`, gracefully stops only process groups launched by this supervisor and preserves completed/partial outputs. A later run must use the current epoch. Control changes reflect actual user steering; elapsed time never counts as permission or a pause request. An existing server and unrelated worker PIDs are never signaled. Current state is retained in `supervisor_status.json`; driver progress is in `pipeline_status.json`.

Validation: eight isolated tests cover bounded probes, redirect/token redaction, invalid digest rejection, no experiment launches in read-only mode, actual resource reserve, epoch/pause controls and measured compression. A copied actual28-day M5 run with367objects was packed to9retained objects plus a verified2.42MB archive, merged with exact coverage, rendered as HTML, and merged again identically. No fixture data are reported as experimental study outcomes.

Limitations: automatic PDF/report completion cannot imply an unimplemented human study, LLM-only numeric comparator or severity sweep. Chronos needs separately verified pinned weights; library import or public metadata access alone does not establish model inference readiness. Cloud-process persistence depends on the cloud instance remaining alive; laptop shutdown does not stop an active cloud process, but live processes are not publication snapshots.
