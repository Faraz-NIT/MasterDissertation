#!/usr/bin/env python3
"""Own only a frozen seeds8–29 numeric extension inside the six-hour budget.

Read-only preflight by default. --run creates exactly one new child process group;
only that owned group may be stopped. Original simulation provenance stays intact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"

import pandas as pd
from ega.config import load_config
from ega.experiment import summarize_study
from ega.util import atomic_json, digest
from m5_parallel import status as pipeline_status

REPO = Path("/workspace/MasterDissertation")
CONFIGS = REPO / "results/run_configs"
BASE_CONFIG = CONFIGS / "six_hour_numeric.yaml"
EXT_CONFIG = CONFIGS / "six_hour_numeric_extension.yaml"
COMBINED = REPO / "results/six_hour_numeric_30seeds"
STATE = CONFIGS / "six_hour_numeric_extension_owner.json"
CONTROL = CONFIGS / "six_hour_supervisor_control.json"
PYTHON = REPO / ".venv/bin/python"
STAGE = "six_hour_numeric_extension"
JOB_CUTOFF = "2026-10-08T01:31:00+00:00"
REPORT_CUTOFF = "2026-10-08T02:01:00+00:00"
GIB = 1024 ** 3


def utc():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text())


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Deadline requires an explicit timezone offset")
    return parsed.timestamp()


def output_path(cfg):
    value = Path(cfg.output)
    value = REPO / value if not value.is_absolute() else value
    if any(part.is_symlink() for part in (value, *value.parents)):
        raise ValueError("Symlinked output roots are not accepted")
    value = value.resolve()
    if not value.is_relative_to(REPO / "results"):
        raise ValueError("Only generated study output roots are accepted")
    return value


def grid(cfg):
    return set(itertools.product(cfg.policies, cfg.scenarios, cfg.seeds, range(cfg.origins)))


def study_settings(cfg):
    value = cfg.model_dump(mode="json") if hasattr(cfg, "model_dump") else dict(cfg)
    return {key: member for key, member in value.items() if key not in {"output", "seeds"}}


def validate_configs(base_path=BASE_CONFIG, extension_path=EXT_CONFIG):
    if Path(base_path).resolve() != BASE_CONFIG or Path(extension_path).resolve() != EXT_CONFIG:
        raise ValueError("Owner scope is restricted to the two explicit frozen six-hour numeric configs")
    base, extension = load_config(base_path), load_config(extension_path)
    if base.seeds != list(range(8)) or extension.seeds != list(range(8, 30)):
        raise ValueError("Base seeds must be 0–7 and extension seeds 8–29, without gaps or overlaps")
    if study_settings(base) != study_settings(extension):
        raise ValueError("Frozen phase settings differ beyond seeds/output; pooling and launch refused")
    if (base.policies != ["B1", "B2", "B3", "B4"] or base.days != 7 or base.origins != 1
            or base.scenarios != ["normal", "derived_field_collapse", "feed_gap"] or base.llm.enabled
            or base.solver.horizon != 7 or base.solver.scenarios != 4 or base.solver.time_limit != 5):
        raise ValueError("Unexpected numeric design; this owner cannot expand another study")
    if (output_path(base) != REPO / "results/six_hour_numeric"
            or output_path(extension) != REPO / "results/six_hour_numeric_extension"):
        raise ValueError("Output scope differs from the frozen base/extension roots")
    if grid(base) & grid(extension) or len(grid(base)) != 96 or len(grid(extension)) != 264:
        raise ValueError("Phase grids are not the exact disjoint 96/264-cell design")
    dataset = Path(base.dataset)
    dataset = REPO / dataset if not dataset.is_absolute() else dataset
    manifest = read_json(dataset / "manifest.json")
    if manifest.get("dataset") != "M5" or manifest.get("series") != 30 or manifest.get("synthetic") is not False:
        raise ValueError("Both phases must use all 30 prepared real M5 series")
    return base, extension


def verify_grid(cfg, phase):
    root = output_path(cfg)
    resolved = read_json(root / "resolved_config.json")
    if study_settings(resolved) != study_settings(cfg) or resolved["seeds"] != cfg.seeds:
        raise ValueError(f"{phase}: actual resolved settings/seeds differ from frozen config")
    found, rows, records = set(), [], []
    for run in sorted(root.glob("*__*__seed*__origin*")):
        if not (run / "summary.json").exists():
            raise ValueError(f"{phase}: partial run remains: {run.name}")
        summary = read_json(run / "summary.json")
        identity = tuple(summary[key] for key in ("policy", "scenario", "seed", "origin"))
        if identity in found or identity not in grid(cfg):
            raise ValueError(f"{phase}: duplicate/unexpected identity {identity}")
        policy, scenario, seed, origin = identity
        if run.name != f"{policy}__{scenario}__seed{seed}__origin{origin}":
            raise ValueError("Source run directory identity differs")
        manifest = read_json(run / "run_manifest.json")
        source_cfg = manifest["config"]
        if (study_settings(source_cfg) != study_settings(cfg) or seed not in source_cfg["seeds"]
                or manifest.get("run_id") != f"{policy}-{scenario}-seed{seed}-origin{origin}"
                or tuple(manifest.get(key) for key in ("scenario", "seed", "origin")) != (scenario, seed, origin)):
            raise ValueError(f"{phase}: source run configuration/provenance differs")
        start = cfg.start_day + origin * cfg.origin_stride
        index = read_json(run / "trace_index.json")
        daily = pd.read_csv(run / "daily.csv", usecols=["day", "policy", "scenario", "seed", "origin"])
        expected_days = list(range(start, start + cfg.days))
        if (summary.get("chain_valid") is not True or summary.get("trace_count") != cfg.days
                or [entry["day"] for entry in index] != expected_days
                or daily.day.tolist() != expected_days
                or any(set(daily[key]) != {expected} for key, expected in zip(
                    ("policy", "scenario", "seed", "origin"), identity))):
            raise ValueError(f"{phase}: incomplete/invalid daily traces or audit flag")
        found.add(identity)
        rows.append({**summary, "path": str(run), "source_phase": phase})
        records.append({"policy": policy, "scenario": scenario, "seed": seed, "origin": origin,
                        "phase": phase, "run_path": str(run), "summary_path": str(run / "summary.json"),
                        **{key: file_hash(run / filename) for key, filename in (
                            ("summary_sha256", "summary.json"), ("daily_sha256", "daily.csv"),
                            ("trace_index_sha256", "trace_index.json"), ("run_manifest_sha256", "run_manifest.json"))}})
    if found != grid(cfg):
        raise ValueError(f"{phase}: missing {len(grid(cfg)-found)} expected cells")
    return rows, records


def guard(now, cutoff, free_bytes, reserve_bytes):
    if now >= cutoff:
        return "hard_job_deadline_reached"
    if free_bytes < reserve_bytes:
        return "disk_reserve_threatened"
    return None


def signal_owned(process, owned_pgid, signum):
    """Only a freshly spawned group owned by this process can be signaled."""
    if process.poll() is not None:
        return False
    if owned_pgid != process.pid or owned_pgid == os.getpgrp() or os.getpgid(process.pid) != owned_pgid:
        raise RuntimeError("Child process-group ownership does not match; no signal sent")
    os.killpg(owned_pgid, signum)
    return True


def stop_owned(process, pgid):
    for signum, grace in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        if process.poll() is not None:
            return
        signal_owned(process, pgid, signum)
        end = time.monotonic() + grace
        while process.poll() is None and time.monotonic() < end:
            time.sleep(.2)
    if process.poll() is None:
        raise RuntimeError("Owned process did not terminate after bounded cleanup")


def build_combined(base, extension):
    base_rows, base_sources = verify_grid(base, "base")
    ext_rows, ext_sources = verify_grid(extension, "extension")
    combined = base.model_copy(deep=True)
    combined.seeds, combined.output = list(range(30)), str(COMBINED)
    actual = {tuple(row[key] for key in ("policy", "scenario", "seed", "origin")) for row in [*base_rows, *ext_rows]}
    if grid(base) & grid(extension) or actual != grid(combined) or len(actual) != 360:
        raise ValueError("Combined grid is not exactly 360 disjoint original source cells")
    proof_tool = Path("/workspace/tools/m5_training_equivalence.py")
    if not proof_tool.exists():
        raise ValueError("Actual trained-model equivalence validator is not ready; source grids preserved")
    spec = importlib.util.spec_from_file_location("m5_training_proof", proof_tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    proof = module.validate_training_equivalence(output_path(base), output_path(extension))
    if proof.get("valid") is not True or proof.get("complete") is not True:
        raise ValueError(f"Trained-model equality is unproven: {proof.get('errors')}")
    sources = []
    for phase, cfg, path in (("base", base, BASE_CONFIG), ("extension", extension, EXT_CONFIG)):
        sources.append({"phase": phase, "output": str(output_path(cfg)), "config_path": str(path),
                        "config_sha256": file_hash(path), "resolved_config_sha256": file_hash(output_path(cfg) / "resolved_config.json"),
                        "seeds": cfg.seeds, "expected_runs": len(grid(cfg))})
    if COMBINED.exists() and any(COMBINED.iterdir()):
        existing_path = COMBINED / "analytical_manifest.json"
        if not existing_path.exists():
            raise ValueError("Refusing to overwrite an unrecognized or unfinished analytical output")
        existing = read_json(existing_path)
        if (existing.get("format") != "m5-analytical-original-sources-v1"
                or existing.get("complete") is not True
                or existing.get("sources") != sources
                or existing.get("run_sources") != [*base_sources, *ext_sources]
                or any(COMBINED.glob("*__*__seed*__origin*"))):
            raise ValueError("Existing analytical output has conflicting source provenance")
        for key, name in (("training_equivalence_sha256", "training_equivalence.json"),
                          ("analytical_summary_sha256", "summary.csv"),
                          ("analytical_resolved_config_sha256", "resolved_config.json"),
                          ("analytical_study_summary_sha256", "study_summary.json")):
            if existing.get(key) != file_hash(COMBINED / name):
                raise ValueError(f"Existing analytical output hash mismatch: {name}")
        return {"path": str(COMBINED), "runs": 360, "decisions": 2520,
                "manifest_sha256": file_hash(existing_path), "preserved_existing": True}
    COMBINED.mkdir(parents=True, exist_ok=True)
    atomic_json(COMBINED / "training_equivalence.json", proof)
    pd.DataFrame([*base_rows, *ext_rows]).to_csv(COMBINED / "summary.csv", index=False)
    atomic_json(COMBINED / "resolved_config.json", combined)
    summarize_study(COMBINED, combined)
    study = read_json(COMBINED / "study_summary.json")
    study["analytical_scope"] = "30 simulation seeds, seven days, one origin, conditional on one30series panel and fixed forecast training seed42; source phases are not additional independent studies."
    study["warning"] = "Numeric-only30seed analytical view; no thirty-seed LLM claim or full dissertation completion. Original run provenance/archives remain at source paths."
    atomic_json(COMBINED / "study_summary.json", study)
    manifest = {"format": "m5-analytical-original-sources-v1", "complete": True,
                "exact_disjoint_identity_coverage": True, "expected_runs": 360,
                "expected_decisions": 2520, "series": 30, "seeds": list(range(30)),
                "days": 7, "origins": 1, "created_at_utc": utc(),
                "sources": sources, "run_sources": [*base_sources, *ext_sources],
                "training_equivalence_path": str(COMBINED / "training_equivalence.json"),
                "training_equivalence_sha256": file_hash(COMBINED / "training_equivalence.json"),
                "analytical_summary_sha256": file_hash(COMBINED / "summary.csv"),
                "analytical_resolved_config_sha256": file_hash(COMBINED / "resolved_config.json"),
                "analytical_study_summary_sha256": file_hash(COMBINED / "study_summary.json"),
                "reason": "Observed runtime capacity; no metric-directed expansion",
                "pooling_note": "Analytical union of disjoint seed cohorts under matched settings and actual trained-model equality. Count original identities once; do not add source phases as independent auxiliary replications.",
                "provenance_note": "Only analytical summaries/manifests written here; no original per-run manifests, trace archives, or source files cloned, changed or relabelled."}
    atomic_json(COMBINED / "analytical_manifest.json", manifest)
    return {"path": str(COMBINED), "runs": 360, "decisions": 2520, "manifest_sha256": file_hash(COMBINED / "analytical_manifest.json")}


def refresh_report(report_cutoff, final):
    generator = REPO / "results/report/generate_report.py"
    log_path = REPO / "results/logs/six_hour_numeric_extension_report.log"
    with generator.with_name("refresh.lock").open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= report_cutoff:
                    return {"state": "blocked_report_lock_at_deadline"}
                time.sleep(.5)
        remaining = report_cutoff - time.time()
        if remaining <= 0:
            return {"state": "report_deadline_elapsed"}
        command = [str(PYTHON), str(generator), "--scope", "six-hour", "--report-prefix", "M5_six_hour_study_report"]
        if final:
            command.append("--final-snapshot")
        try:
            with log_path.open("a") as log:
                result = subprocess.run(command, cwd=REPO, env=dict(os.environ), stdout=log,
                                        stderr=subprocess.STDOUT, timeout=min(600, remaining))
            return {"state": "complete" if result.returncode == 0 else "failed", "returncode": result.returncode, "log": str(log_path)}
        except subprocess.TimeoutExpired:
            return {"state": "report_refresh_timeout", "log": str(log_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--once", action="store_true", help="Read-only preflight; default unless --run")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1,
                        help="Fresh seed workers; use two only when local LLM inference is idle")
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--reserve-gib", type=float, default=2)
    parser.add_argument("--job-deadline-utc", default=JOB_CUTOFF)
    parser.add_argument("--report-deadline-utc", default=REPORT_CUTOFF)
    args = parser.parse_args(argv)
    if args.run and args.once or args.poll_seconds <= 0 or args.reserve_gib < 2:
        parser.error("Choose --run or --once; poll interval positive and reserve at least 2 GiB")
    cutoff, report_cutoff = instant(args.job_deadline_utc), instant(args.report_deadline_utc)
    if cutoff > instant(JOB_CUTOFF) or report_cutoff > instant(REPORT_CUTOFF) or report_cutoff <= cutoff:
        parser.error("Cannot extend the user budget; report cutoff must follow job cutoff")
    os.chdir(REPO)
    base, extension = validate_configs()
    verify_grid(base, "base")
    reason = guard(time.time(), cutoff, shutil.disk_usage(REPO).free, args.reserve_gib * GIB)
    preflight = {"mode": "read_only_preflight", "base_complete_runs": 96, "extension_expected_runs": 264,
                 "extension_seeds": extension.seeds, "base_config_sha256": file_hash(BASE_CONFIG),
                 "extension_config_sha256": file_hash(EXT_CONFIG), "frozen_settings_equal_except_output_seeds": True,
                 "disjoint_identity_coverage": True, "job_deadline_utc": args.job_deadline_utc,
                 "report_deadline_utc": args.report_deadline_utc, "launch_guard": reason,
                 "numeric_workers": args.workers, "owned_job_launches": 0}
    if not args.run:
        print(json.dumps(preflight, indent=2))
        return 0
    if reason:
        raise RuntimeError(f"Launch refused: {reason}")
    control = read_json(CONTROL)
    epoch = control.get("epoch")
    if not epoch or control.get("pause_requested"):
        raise RuntimeError("Six-hour execution control is paused or missing its execution epoch")
    with STATE.with_suffix(".lock").open("a") as owner_lock:
        fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = {**preflight, "mode": "owned_numeric_extension", "owner_pid": os.getpid(),
                 "launch_id": uuid.uuid4().hex, "epoch": epoch, "started_at_utc": utc(),
                 "reason": "Runtime-only extension; no metric-direction selection"}
        pipeline_status(STAGE, state="prepared", config_path=str(EXT_CONFIG), output=str(output_path(extension)),
                        expected_runs=264, expected_decisions=1848, required=True, budget_study=True,
                        series=30, workers=args.workers)
        log_path = REPO / "results/logs/six_hour_numeric_extension_driver.log"
        command = [str(PYTHON), "/workspace/tools/m5_parallel.py", "--config", str(EXT_CONFIG),
                   "--workers", str(args.workers), "--stage", STAGE, "--pack-completed"]
        with log_path.open("a") as log:
            process = subprocess.Popen(command, cwd=REPO, env=dict(os.environ), stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        pgid = os.getpgid(process.pid)
        if pgid != process.pid or pgid == os.getpgrp():
            raise RuntimeError("Fresh child process-group isolation failed")
        os.setpriority(os.PRIO_PROCESS, process.pid, 10)
        state.update(child_pid=process.pid, child_pgid=pgid, log=str(log_path), owned_job_launches=1, phase="running")
        atomic_json(STATE, state)
        stop_reason = None
        try:
            while process.poll() is None:
                stop_reason = guard(time.time(), cutoff, shutil.disk_usage(REPO).free, args.reserve_gib * GIB)
                current_control = read_json(CONTROL)
                if current_control.get("pause_requested") or current_control.get("epoch") != epoch:
                    stop_reason = "explicit_pause_or_epoch_change"
                if file_hash(EXT_CONFIG) != preflight["extension_config_sha256"] or file_hash(BASE_CONFIG) != preflight["base_config_sha256"]:
                    stop_reason = "frozen_configuration_changed"
                if stop_reason:
                    stop_owned(process, pgid)
                    break
                state.update(updated_at_utc=utc(), disk_free_bytes=shutil.disk_usage(REPO).free)
                atomic_json(STATE, state)
                time.sleep(min(args.poll_seconds, max(.05, cutoff-time.time())))
        except BaseException:
            stop_owned(process, pgid)
            raise
        state.update(finished_at_utc=utc(), child_returncode=process.poll(), stop_reason=stop_reason,
                     phase="stopped" if stop_reason else "numeric_extension_finished")
        if stop_reason:
            pipeline_status(STAGE, state="budget_stopped", stop_reason=stop_reason,
                            note="Only completed source cells remain eligible; incomplete extension cannot form30seed evidence")
        elif process.returncode == 0:
            try:
                state["analytical_view"] = build_combined(base, extension)
            except Exception as exc:
                state["analytical_view"] = {"state": "unproven", "error": str(exc)}
        state["report_refresh"] = refresh_report(report_cutoff, final=time.time() >= cutoff)
        atomic_json(STATE, state)
        print(json.dumps(state, indent=2), flush=True)
        return 0 if process.returncode == 0 and not stop_reason else 2


if __name__ == "__main__":
    raise SystemExit(main())
