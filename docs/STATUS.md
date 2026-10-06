# Project status and resume sheet

Updated 6 Oct 2026, 11:20. Everything below is on disk; nothing lives only in a chat session. If a session, a credit
balance or the machine goes away, start from here.

## Where things are

| What | Where |
|---|---|
| Code, configs, docs, tests | branch `stage2-gate-v2` (two commits ahead of `main`); merge with `git checkout main && git merge --ff-only stage2-gate-v2` |
| Every experiment result, trace, artifact store, audit chain | `results/<study>/<policy>__<scenario>__seed<k>__origin<j>/` (git-ignored; copy the folder, never `git archive`) |
| Index of all results with headline numbers | `results/RESULTS.md`, `results/results_summary.json` (`python scripts/export_results.py`) |
| Narrative report with figures | `results/report/pilot_results.pdf` (`python scripts/make_report.py`) |
| Logs of every run and driver | `results/logs/` (`*.log`; `*.done` marks finished driver steps) |
| Local mirror of results and docs | `~/Downloads/ega-results-backup/` (refreshed by `scripts/checkpoint_study.sh`) |
| M5 data | `data/raw/m5/` and `data/processed/{m5,m5_smoke}/`; if missing: `python scripts/fetch_m5.py` then `ega prepare` as in README |
| LLM key | git-ignored `.env` (`set -a; . ./.env; set +a`); never in tracked files |

## Decisions frozen (6 Oct 2026)

- Gate v2: extra spend beyond the order-up-to baseline as a share of budget, cap 0.03, `gate-v2-spend-deviation-2026-10-06`.
- Primary configuration: `approval_mode: oracle`, `approval_delay: 1` (simulated delayed release of held plans); `hold` is the ablation.
- "Harmful" executions reported split into `violation_executions` and `reference_deviations`.
- Pilots run before 6 Oct used gate v1; their hold counts are not citable. Details: `docs/GATE_CALIBRATION.md`.

## Running now

`results/main_study_stage1_workers/w0..w3`: stage-1 main study (B1–B4, 30 seeds, 28 days, 4 scenarios, 480 runs),
launched 6 Oct 11:03 as four niced workers, about one day. Each completed run is final on disk the moment its
`summary.json` exists. A checkpoint loop merges completed runs into `results/main_study_stage1` every 30 minutes,
rebuilds the index and report, and mirrors `results/` to the backup folder.

- Progress: `ls results/main_study_stage1_workers/w*/*/summary.json | wc -l`
- Resume after any interruption (reboot, kill): `PY=.venv/bin/python scripts/run_main_study.sh configs/main_study_stage1.yaml`
  (workers skip finished runs, redo the one partial run each, merge and render at the end)
- Checkpoint loop: `PY=.venv/bin/python scripts/checkpoint_study.sh configs/main_study_stage1.yaml`

## Done and on disk

Backtests (4 models); M5 pilot (B1, D0, D1); B1–B4 pilot; gate calibration (two windows); first LLM pilot (Cerebras
gpt-oss-120b, B4 and B6–B10); stage 2 on Cerebras: hostile note with the screen off (20 runs), fixed-evidence
reliability (30 replications), prose grounding (6 cases); grounding template benchmark; sensitivity sweep; audit
packets; gate v2 validation repeats (30-series B4 with dropped holds and with simulated approval; 2-series LLM pilot).

## Still open

1. Stage 2 of the deterministic study: the other 13 scenarios of `configs/deterministic_study.yaml`, same runner.
2. LLM arms (B9, B10, optionally B8) at the 30-seed design: needs paid Cerebras credit (about $285 estimated); the free
   tier's 150 requests/hour makes it infeasible. Run with `ega run --config configs/llm_study.cerebras.yaml` adapted to
   the stage-1 settings, with `--resume`; `results/llm_spend.json` and the 429 log lines show spend and waits.
3. Dissertation text: gate redesign and calibration, hostile-note result, fixed-evidence determinism, prose grounding.
4. B5 needs Chronos weights; the human audit needs institutional approval first.

## If Cerebras credit or quota runs out mid-run

Nothing is lost: every finished decision and run is on disk, the client stops cleanly on quota (`ProviderQuotaExhausted`)
and `ega run --resume` or `scripts/run_llm_cerebras.sh` continues from the next unfinished run. Top up, re-export the
key, re-run the same command.
