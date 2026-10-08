#!/usr/bin/env python3
"""Run frozen M5 configs in seed workers and merge only exact, complete studies.

Execution helper outside the checkout; invoke with the repository virtualenv.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

for _name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_name] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"

REPO = Path("/workspace/MasterDissertation")
PYTHON = REPO / ".venv/bin/python"
STATUS = REPO / "results/run_configs/pipeline_status.json"
TOOLS = Path("/workspace/tools")
UNSPECIFIED_PROFILE = object()

from ega.config import load_config
from ega.agents.orchestrator import POLICIES
from ega.evaluation.report import render_report
from ega.experiment import summarize_study
from ega.util import atomic_json, digest, environment


def read_json(path):
    return json.loads(Path(path).read_text())


def status(stage, **fields):
    """Merge one stage update under a process lock, preserving all other fields."""
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    with STATUS.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = read_json(STATUS) if STATUS.exists() else {}
        stages = value.setdefault("stages", {})
        entry = stages.setdefault(stage, {})
        if "state" in fields and "status" not in fields:
            fields["status"] = "running" if fields["state"] == "validating_and_merging" else fields["state"]
        entry.update(fields)
        entry["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(STATUS, value)


def assert_workers_stopped(stage):
    value = read_json(STATUS) if STATUS.exists() else {}
    pids = value.get("stages", {}).get(stage, {}).get("worker_pids", [])
    live = []
    for pid in pids:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass  # An inaccessible process must be treated as still live.
        live.append(pid)
    if live:
        raise RuntimeError(f"Refusing merge while status-recorded worker PIDs are live: {live}")


def refresh_report(stage):
    """Refresh the combined report; its failure must not invalidate a complete study."""
    generator = REPO / "results/report/generate_report.py"
    if not generator.exists():
        return
    log_path = REPO / "results/logs" / f"{stage}_report.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with generator.with_name("refresh.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            status(stage, report_refresh={"state": "running", "log": str(log_path)})
            with log_path.open("a") as log:
                result = subprocess.run([str(PYTHON), str(generator)], cwd=REPO,
                                        env=dict(os.environ), stdout=log,
                                        stderr=subprocess.STDOUT, timeout=600)
            status(stage, report_refresh={"state": "complete" if result.returncode == 0 else "failed",
                                         "returncode": result.returncode, "log": str(log_path)})
    except Exception as exc:
        status(stage, report_refresh={"state": "failed", "error": str(exc), "log": str(log_path)})
        print(f"Report refresh failed; study remains complete: {exc}", file=sys.stderr, flush=True)


def pack_worker_outputs(workers, stage, strict=False):
    """Pack only completed generated runs in this driver's own worker outputs.

    Run in the driver's progress loop and once after workers exit, before merge.
    The shared merge lock prevents a supervisor or another cooperating helper
    copying raw objects while packing publishes its recoverable archive.
    """
    from m5_pack_artifacts import pack, registered_roots, run_lock, validate_scope
    logs = REPO / "results/logs"
    logs.mkdir(parents=True, exist_ok=True)
    packed = 0
    deferred = 0
    with (logs / "artifact_merge.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        roots = registered_roots()
        for folder, _ in workers:
            for summary in sorted(folder.glob("*__*__seed*__origin*/summary.json")):
                run = summary.parent
                manifest = run / "packing_manifest.json"
                if manifest.exists() and read_json(manifest).get("state") == "packed":
                    continue
                wal = run / "artifacts/audit.sqlite-wal"
                if wal.exists() and wal.stat().st_size and not strict:
                    deferred += 1
                    continue
                run, roots = validate_scope(run)
                try:
                    with run_lock(run):
                        result = pack(run, roots, 6)
                except BlockingIOError:
                    if strict:
                        raise
                    deferred += 1
                    continue
                packed += 1
                with (logs / f"{stage}_packing.jsonl").open("a") as stream:
                    stream.write(json.dumps(result) + "\n")
        if packed or deferred:
            status(stage, artifact_packing={"enabled": True, "packed_this_scan": packed,
                                            "deferred_live_runs": deferred,
                                            "updated_at_utc": datetime.now(timezone.utc).isoformat()})
    return packed


def identities(cfg):
    return set(itertools.product(cfg.policies, cfg.scenarios, cfg.seeds, range(cfg.origins)))


def identity_name(identity):
    policy, scenario, seed, origin = identity
    return f"{policy}__{scenario}__seed{seed}__origin{origin}"


def assert_config(path, expected):
    if path.exists() and read_json(path) != expected:
        raise ValueError(f"Frozen configuration differs at {path}; use a new output")


def load_worker_profile(config_path):
    """Read the optional frozen sidecar; never execute an unchecked wrapper."""
    sidecar = Path(config_path).with_suffix(".worker_profile.json")
    if not sidecar.exists():
        return None
    value = read_json(sidecar)
    if value.get("schema_version") != 1 or not isinstance(value.get("name"), str) or not value["name"]:
        raise ValueError("Worker profile requires schema_version1 and a nonempty name")
    raw_wrapper = value.get("wrapper", "")
    wrapper = Path(raw_wrapper)
    if not wrapper.is_absolute() or not wrapper.is_file() or wrapper.is_symlink():
        raise ValueError("Worker profile wrapper must be an existing absolute regular file")
    resolved = wrapper.resolve()
    if not resolved.is_relative_to(TOOLS) or str(resolved) != raw_wrapper:
        raise ValueError("Worker profile wrapper must be a canonical absolute path under /workspace/tools")
    expected = value.get("wrapper_sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or file_hash(resolved) != expected:
        raise ValueError("Frozen worker wrapper SHA-256 does not match actual file")
    extension = value.get("prompt_extension_sha256")
    if extension is not None and not re.fullmatch(r"[0-9a-f]{64}", extension):
        raise ValueError("Worker prompt-extension SHA-256 is invalid")
    return {"schema_version": 1, "name": value["name"], "sidecar": str(sidecar.resolve()),
            "sidecar_sha256": file_hash(sidecar), "wrapper": str(resolved),
            "wrapper_sha256": expected, "prompt_extension_sha256": extension}


def assert_execution_profile(folder, expected, create=False):
    """Keep serving provenance frozen independently of the repository config."""
    folder = Path(folder)
    recorded = folder / "execution_profile.json"
    if recorded.exists():
        if read_json(recorded) != expected:
            raise ValueError(f"Frozen execution profile differs at {recorded}; use a new output")
    elif expected is not None:
        if any(folder.glob("*__*__seed*__origin*/run_manifest.json")):
            raise ValueError(f"Existing unprofiled run artifacts cannot resume under a new worker profile: {folder}")
        if not create:
            raise ValueError(f"Frozen execution-profile metadata missing at {folder}")
        folder.mkdir(parents=True, exist_ok=True)
        atomic_json(recorded, expected)
    else:
        for manifest in folder.glob("*__*__seed*__origin*/run_manifest.json"):
            if read_json(manifest).get("environment", {}).get("execution_profile") is not None:
                raise ValueError("Profile sidecar removed from an existing profiled study; use a new output")


def validate_run(path, cfg, execution_profile=UNSPECIFIED_PROFILE):
    summary = read_json(path / "summary.json")
    identity = tuple(summary[key] for key in ("policy", "scenario", "seed", "origin"))
    if path.name != identity_name(identity) or identity not in identities(cfg):
        raise ValueError(f"Unexpected run identity in {path}")
    if summary.get("trace_count") != cfg.days or summary.get("chain_valid") is not True:
        raise ValueError(f"Incomplete traces or invalid chain in {path}")
    manifest = read_json(path / "run_manifest.json")
    if (execution_profile is not UNSPECIFIED_PROFILE
            and manifest.get("environment", {}).get("execution_profile") != execution_profile):
        raise ValueError(f"Run environment execution profile differs in {path}")
    if manifest.get("config") != cfg.model_dump(mode="json"):
        raise ValueError(f"Run configuration differs in {path}")
    policy, scenario, seed, origin = identity
    if (tuple(manifest.get(key) for key in ("scenario", "seed", "origin")) != identity[1:]
            or manifest.get("run_id") != f"{policy}-{scenario}-seed{seed}-origin{origin}"
            or manifest.get("policy_spec") != POLICIES[policy]
            or manifest.get("forecast") != (cfg.forecast_override or POLICIES[policy]["forecast"])
            or ("policy" in manifest and manifest["policy"] != policy)):
        raise ValueError(f"Run manifest identity differs in {path}")
    index = read_json(path / "trace_index.json")
    start = cfg.start_day + identity[3] * cfg.origin_stride
    if [entry["day"] for entry in index] != list(range(start, start + cfg.days)):
        raise ValueError(f"Missing or duplicate decision days in {path}")
    return identity, summary


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def assert_matching_tree(source, destination):
    if source.is_dir() != destination.is_dir():
        raise ValueError(f"Existing output type differs at {destination}")
    if source.is_file():
        a, b = source.stat(), destination.stat()
        same_inode = (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
        if not same_inode and (a.st_size != b.st_size or file_hash(source) != file_hash(destination)):
            raise ValueError(f"Existing output contents differ at {destination}")
        return
    # SQLite readers may create empty lock sidecars; they are not study artifacts.
    def files(root):
        return {p.relative_to(root) for p in root.rglob("*") if p.is_file()
                and not p.name.endswith(("-shm", "-wal"))}
    if files(source) != files(destination):
        raise ValueError(f"Existing output file list differs at {destination}")
    for relative in files(source):
        assert_matching_tree(source / relative, destination / relative)


def link_or_copy(source, destination):
    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copy2(source, destination)
    return str(destination)


def preserve_copy(source, destination):
    """Keep matching completed outputs; never remove or replace existing trees."""
    if destination.exists():
        assert_matching_tree(source, destination)
    elif source.is_dir():
        shutil.copytree(source, destination, copy_function=link_or_copy)
    else:
        link_or_copy(source, destination)


def merge(cfg, workers, output, execution_profile=None):
    expected = identities(cfg)
    sources, rows, models = {}, [], {}
    for folder, worker_cfg in workers:
        assert_execution_profile(folder, execution_profile)
        assert_config(folder / "resolved_config.json", worker_cfg.model_dump(mode="json"))
        worker_expected = identities(worker_cfg)
        found = set()
        for run in sorted(folder.glob("*__*__seed*__origin*")):
            if not (run / "summary.json").exists():
                raise ValueError(f"Partial worker run remains: {run}")
            identity, summary = validate_run(run, worker_cfg, execution_profile)
            if identity in sources:
                raise ValueError(f"Duplicate worker identity: {identity}")
            found.add(identity)
            sources[identity] = (run, summary, worker_cfg)
        if found != worker_expected:
            raise ValueError(f"Worker coverage differs in {folder}: missing {len(worker_expected-found)}, extra {len(found-worker_expected)}")
        for model in sorted(folder.glob("model_*")):
            if model.name in models:
                assert_matching_tree(models[model.name], model)
            else:
                models[model.name] = model
    if set(sources) != expected:
        raise ValueError(f"Study coverage differs: missing {len(expected-set(sources))}, extra {len(set(sources)-expected)}")
    # Validate all sources before producing any final study statistics or report.
    output.mkdir(parents=True, exist_ok=True)
    assert_execution_profile(output, execution_profile, create=True)
    assert_config(output / "resolved_config.json", cfg.model_dump(mode="json"))
    for previous in output.glob("*__*__seed*__origin*"):
        if previous.name not in {identity_name(i) for i in expected}:
            raise ValueError(f"Unexpected existing merged run: {previous}")
    for identity in sorted(expected):
        source, summary, worker_cfg = sources[identity]
        destination = output / identity_name(identity)
        if destination.exists():
            validate_run(destination, worker_cfg, execution_profile)
        preserve_copy(source, destination)
        rows.append({**summary, "path": str(destination)})
    for name, source in models.items():
        preserve_copy(source, output / name)
    import pandas as pd
    atomic_json(output / "resolved_config.json", cfg)
    merged_environment = environment()
    if execution_profile is not None:
        merged_environment["execution_profile"] = execution_profile
    atomic_json(output / "environment.json", merged_environment)
    pd.DataFrame(rows).to_csv(output / "summary.csv", index=False)
    summarize_study(output, cfg)
    report = render_report(output)
    manifest = {"complete": True, "runs_merged": len(rows), "runs_expected": len(expected),
                "decisions": len(rows) * cfg.days, "all_chains_valid": True,
                "exact_identity_coverage": True, "config_sha256": digest(cfg),
                "workers": [str(folder) for folder, _ in workers], "report": str(report)}
    if execution_profile is not None:
        manifest["execution_profile"] = execution_profile
    atomic_json(output / "merge_manifest.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--stage")
    parser.add_argument("--merge-only", action="store_true",
                        help="Validate and merge stopped workers; performs no training or job spawning")
    parser.add_argument("--pack-completed", action="store_true",
                        help="Verify and pack completed worker artifacts during progress and before merge; all original objects remain recoverable")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    config_path = Path(args.config).resolve()
    stage = args.stage or config_path.stem
    processes = []
    try:
        os.chdir(REPO)
        cfg = load_config(config_path)
        execution_profile = load_worker_profile(config_path)
        cfg.output = str(Path(cfg.output).resolve())
        output = Path(cfg.output)
        worker_root = output.with_name(output.name + "_workers")
        worker_root.mkdir(parents=True, exist_ok=True)
        with (worker_root / "driver.lock").open("a") as driver_lock:
            fcntl.flock(driver_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert_config(output / "resolved_config.json", cfg.model_dump(mode="json"))
            assert_execution_profile(output, execution_profile, create=True)
            assert_execution_profile(worker_root, execution_profile, create=True)
            workers = []
            for k in range(min(args.workers, len(cfg.seeds))):
                worker_cfg = cfg.model_copy(deep=True)
                worker_cfg.seeds = cfg.seeds[k::args.workers]
                folder = worker_root / f"w{k}"
                worker_cfg.output = str(folder)
                assert_config(folder / "resolved_config.json", worker_cfg.model_dump(mode="json"))
                assert_execution_profile(folder, execution_profile, create=True)
                workers.append((folder, worker_cfg))
            active_folders = {folder for folder, _ in workers}
            if any(folder not in active_folders and any(folder.glob("*__*__seed*__origin*"))
                   for folder in worker_root.glob("w[0-9]*") if folder.is_dir()):
                raise ValueError("Stale workers from a different partition; keep worker count unchanged or use a new output")
            expected = len(identities(cfg))
            if args.merge_only:
                assert_workers_stopped(stage)
                status(stage, state="validating_and_merging", config=str(config_path), output=str(output),
                       workers=len(workers), expected_runs=expected, expected_decisions=expected * cfg.days)
                if args.pack_completed:
                    pack_worker_outputs(workers, stage, strict=True)
                with (REPO / "results/logs/artifact_merge.lock").open("a") as merge_lock:
                    fcntl.flock(merge_lock, fcntl.LOCK_EX)
                    manifest = merge(cfg, workers, output, execution_profile)
                status(stage, state="complete", completed_runs=expected, completion=manifest, error=None)
                print(json.dumps(manifest, indent=2), flush=True)
                refresh_report(stage)
                return 0
            status(stage, state="running", config=str(config_path), output=str(output),
                   workers=len(workers), expected_runs=expected, expected_decisions=expected * cfg.days, error=None,
                   execution_profile=execution_profile)
            logs = REPO / "results/logs"
            logs.mkdir(parents=True, exist_ok=True)
            for k, (folder, worker_cfg) in enumerate(workers):
                log_path = logs / f"{stage}_w{k}.log"
                prefix = [str(PYTHON), execution_profile["wrapper"]] if execution_profile else [str(PYTHON), "-m", "ega"]
                command = [*prefix, "run", "--config", str(config_path),
                           "--seeds", *map(str, worker_cfg.seeds), "--output", str(folder), "--resume"]
                worker_env = dict(os.environ)
                if execution_profile is not None:
                    if load_worker_profile(config_path) != execution_profile:
                        raise ValueError("Frozen worker profile changed between validation and process launch")
                    worker_env["M5_EXECUTION_PROFILE_JSON"] = json.dumps(execution_profile, sort_keys=True)
                with log_path.open("a") as log:
                    process = subprocess.Popen(command, cwd=REPO, env=worker_env,
                                               stdout=log, stderr=subprocess.STDOUT)
                processes.append((process, log_path))
            status(stage, worker_pids=[process.pid for process, _ in processes],
                   logs=[str(log) for _, log in processes])
            last_update = 0
            last_pack = 0
            while any(process.poll() is None for process, _ in processes):
                if time.monotonic() - last_update >= 15:
                    completed = sum(1 for folder, _ in workers for _ in folder.glob("*__*__seed*__origin*/summary.json"))
                    status(stage, completed_runs=completed)
                    print(f"{stage}: {completed}/{expected} completed runs", flush=True)
                    last_update = time.monotonic()
                if args.pack_completed and time.monotonic() - last_pack >= 60:
                    pack_worker_outputs(workers, stage)
                    last_pack = time.monotonic()
                time.sleep(1)
            failures = [(process.returncode, str(log)) for process, log in processes if process.returncode != 0]
            if failures:
                raise RuntimeError(f"Workers failed: {failures}; completed runs are preserved for resume")
            status(stage, state="validating_and_merging", completed_runs=expected)
            if args.pack_completed:
                pack_worker_outputs(workers, stage, strict=True)
            with (logs / "artifact_merge.lock").open("a") as merge_lock:
                fcntl.flock(merge_lock, fcntl.LOCK_EX)
                manifest = merge(cfg, workers, output, execution_profile)
            status(stage, state="complete", completed_runs=expected, completion=manifest, error=None)
            print(json.dumps(manifest, indent=2), flush=True)
            refresh_report(stage)
            return 0
    except (Exception, KeyboardInterrupt) as exc:
        for process, _ in processes:
            if process.poll() is None:
                process.terminate()
        for process, _ in processes:
            if process.poll() is None:
                process.wait(timeout=30)
        status(stage, state="failed", error=str(exc))
        print(f"ERROR: {stage}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
