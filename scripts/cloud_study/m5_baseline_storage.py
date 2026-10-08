#!/usr/bin/env python3
"""Conservative storage watcher for two registered numeric M5 stages.

Dry-run by default. --run enables verified packing; no jobs are signaled or restarted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time

REPO = Path("/workspace/MasterDissertation")
STATUS = REPO / "results/run_configs/pipeline_status.json"
WATCH_STATUS = REPO / "results/run_configs/baseline_storage_status.json"
MERGE_LOCK = REPO / "results/logs/artifact_merge.lock"
STAGES = ("main_study_stage1", "llm_prose_reference_30series")
GIB = 1024 ** 3

spec = importlib.util.spec_from_file_location("m5_packing", "/workspace/tools/m5_pack_artifacts.py")
packing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packing)


def read_json(path):
    return json.loads(path.read_text())


def pid_live(pid):
    """Read process state; never send a process signal, including signal zero."""
    try:
        raw = (Path("/proc") / str(int(pid)) / "stat").read_text()
        state = raw[raw.rfind(")") + 2:].split()[0]
        return state not in {"Z", "X"}
    except (FileNotFoundError, ProcessLookupError):
        return False
    except (PermissionError, ValueError, IndexError):
        return True


def completed(run):
    try:
        summary = read_json(run / "summary.json")
        index = read_json(run / "trace_index.json")
        manifest = read_json(run / "run_manifest.json")
        cfg = manifest["config"]
        policy, scenario, seed, origin = [summary[key] for key in ("policy", "scenario", "seed", "origin")]
        start = cfg["start_day"] + origin * cfg["origin_stride"]
        valid = (summary.get("chain_valid") is True and summary.get("trace_count") == cfg["days"]
                 and run.name == f"{policy}__{scenario}__seed{seed}__origin{origin}"
                 and [entry["day"] for entry in index] == list(range(start, start + cfg["days"]))
                 and manifest.get("execution_environment") == "simulator_only"
                 and "m5" in cfg["dataset"].lower())
        return {"identity": run.name, "policy": policy, "scenario": scenario, "origin": origin,
                "path": run, "days": cfg["days"]} if valid else None
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return None


def stage_snapshot(name, metadata, end_guard):
    output = Path(metadata["output"])
    output = (REPO / output).resolve() if not output.is_absolute() else output.resolve()
    pids = metadata.get("worker_pids", [])
    count = int(metadata.get("workers") or len(pids))
    worker_root = output.with_name(output.name + "_workers")
    worker_runs, workers = [], []
    for k in range(count):
        folder = worker_root / f"w{k}"
        cfg_path = folder / "resolved_config.json"
        if not cfg_path.exists():
            workers.append({"worker": k, "initialized": False, "live": pid_live(pids[k]) if k < len(pids) else True})
            continue
        cfg = read_json(cfg_path)
        expected = len(cfg["policies"]) * len(cfg["scenarios"]) * len(cfg["seeds"]) * cfg["origins"]
        runs = [value for run in sorted(folder.glob("*__*__seed*__origin*"))
                if run.is_dir() and (value := completed(run)) is not None]
        worker_runs.extend(runs)
        live = pid_live(pids[k]) if k < len(pids) else True
        workers.append({"worker": k, "expected_runs": expected, "completed_runs": len(runs),
                        "remaining_runs": expected - len(runs), "live": live, "initialized": True})
    merged_runs = [value for run in sorted(output.glob("*__*__seed*__origin*"))
                   if run.is_dir() and (value := completed(run)) is not None]
    state = metadata.get("state") or metadata.get("status") or "unknown"
    live = any(worker["live"] for worker in workers)
    near_end = any(worker["live"] and worker.get("remaining_runs", 0) <= end_guard for worker in workers)
    expected = int(metadata.get("expected_runs") or sum(worker.get("expected_runs", 0) for worker in workers))
    initialized = all(worker.get("initialized") for worker in workers)
    expected_workers = sum(worker.get("expected_runs", 0) for worker in workers)
    unique_completed = {run["identity"] for run in [*worker_runs, *merged_runs]}
    reason = None
    if state == "validating_and_merging":
        reason = "merge_in_progress"
    elif not initialized:
        reason = "workers_not_initialized"
    elif expected_workers != expected:
        reason = "registered_expected_count_differs_from_worker_configs"
    elif live and near_end:
        reason = f"live_worker_within_{end_guard}_runs_of_end"
    elif not live and state != "complete":
        reason = "workers_stopped_waiting_for_verified_stage_completion"
    elif not live and len(unique_completed) != expected:
        reason = "complete_state_has_inexact_run_coverage"
    targets = worker_runs if live else [*worker_runs, *merged_runs]
    return {"name": name, "state": state, "expected_runs": expected, "workers": workers,
            "workers_live": live, "completed_run_identities": len(unique_completed),
            "worker_run_locations": len(worker_runs), "merged_run_locations": len(merged_runs),
            "skip_reason": reason, "runs": [*worker_runs, *merged_runs], "targets": targets}


def discover(end_guard):
    document = read_json(STATUS)
    metadata = document.get("stages", {})
    snapshots = []
    for name in STAGES:
        if name in metadata and metadata[name].get("output"):
            snapshots.append(stage_snapshot(name, metadata[name], end_guard))
    return snapshots


def fixture_discovery(root):
    root = root.resolve()
    runs = []
    for run in sorted(root.glob("*__*__seed*__origin*")):
        value = completed(run)
        if value is not None:
            packing.validate_scope(run, root)
            runs.append(value)
    return [{"name": "copied_fixture_dry_run", "state": "complete", "expected_runs": len(runs),
             "workers": [], "workers_live": False, "completed_run_identities": len(runs),
             "worker_run_locations": 0, "merged_run_locations": len(runs),
             "skip_reason": None, "runs": runs, "targets": runs}]


def packing_state(run):
    path = run / "packing_manifest.json"
    if not path.exists():
        return None
    value = read_json(path)
    if value.get("format") != packing.FORMAT:
        raise ValueError(f"Unknown existing packing manifest is preserved: {path}")
    return value


def run_fingerprint(run):
    observed = {}
    for relative in ("summary.json", "trace_index.json", "run_manifest.json", "packing_manifest.json",
                     "artifacts/audit.sqlite", "artifacts/audit.sqlite-wal", "artifacts/objects.zip", "artifacts/objects"):
        try:
            info = (run / relative).stat()
            observed[relative] = [info.st_size, info.st_mtime_ns]
        except FileNotFoundError:
            observed[relative] = None
    return packing.digest(observed)


def resource_snapshot(snapshots):
    report = []
    physical_files = {}
    global_samples = []
    per_stage = []
    for snapshot in snapshots:
        samples = {}
        stage_archive_files = {}
        loose_object_count = 0
        archive_bytes_logical = 0
        archived_locations = restored_locations = unarchived_locations = 0
        for run in snapshot["runs"]:
            path = run["path"]
            value = packing_state(path)
            if value is not None:
                archive_path = path / "artifacts/objects.zip"
                archive_stat = archive_path.stat()
                physical_files[(archive_stat.st_dev, archive_stat.st_ino)] = archive_stat.st_size
                stage_archive_files[(archive_stat.st_dev, archive_stat.st_ino)] = archive_stat.st_size
                archive_bytes_logical += archive_stat.st_size
                current_object_bytes = 0
                for obj in (path / "artifacts/objects").glob("*.json"):
                    loose_object_count += 1
                    info = obj.stat()
                    physical_files[(info.st_dev, info.st_ino)] = info.st_size
                    current_object_bytes += info.st_size
                kept_bytes = sum(value["original_objects"][name]["bytes"] for name in value["kept_hashes"])
                record = {"packed_bytes": archive_stat.st_size + kept_bytes,
                          "archive_bytes": archive_stat.st_size,
                          "original_bytes": value["original_object_bytes"],
                          "object_count": value["original_object_count"],
                          "policy": run["policy"], "scenario": run["scenario"], "origin": run["origin"]}
                samples.setdefault(run["identity"], record)
                archived_locations += value.get("state") == "packed"
                restored_locations += value.get("state") != "packed"
            else:
                unarchived_locations += 1
                for obj in (path / "artifacts/objects").glob("*.json"):
                    loose_object_count += 1
                    info = obj.stat()
                    physical_files[(info.st_dev, info.st_ino)] = info.st_size
        stage = {key: value for key, value in snapshot.items() if key not in {"runs", "targets"}}
        stage.update(verified_archive_manifest_locations=archived_locations + restored_locations,
                     packed_locations=archived_locations, restored_locations=restored_locations,
                     unpacked_locations=unarchived_locations, compression_sample_count=len(samples),
                     archive_bytes_logical=archive_bytes_logical,
                     archive_bytes_physical=sum(stage_archive_files.values()),
                     loose_object_file_locations=loose_object_count,
                     original_objects_over_unique_archived_runs=sum(row["object_count"] for row in samples.values()),
                     archive_observation="Entry and archive hashes were verified by packing helper; this watcher reads recorded manifests and current file sizes without repeating full archive verification.")
        per_stage.append((stage, list(samples.values())))
        global_samples.extend(samples.values())
    for stage, own_samples in per_stage:
        sample = own_samples or global_samples
        if sample:
            mean_packed = sum(row["packed_bytes"] for row in sample) / len(sample)
            mean_raw = sum(row["original_bytes"] for row in sample) / len(sample)
            remaining = max(0, stage["expected_runs"] - stage["completed_run_identities"])
            stage["projection"] = {
                "source": "own completed runs" if own_samples else "other watched 30-series numeric stage",
                "sample_count": len(sample), "sampled_policies": sorted({row["policy"] for row in sample}),
                "sampled_scenarios": sorted({row["scenario"] for row in sample}),
                "sampled_origins": sorted({row["origin"] for row in sample}),
                "mean_packed_bytes_per_run": round(mean_packed),
                "mean_original_bytes_per_run": round(mean_raw),
                "projected_full_stage_packed_bytes": round(mean_packed * stage["expected_runs"]),
                "projected_remaining_packed_bytes": round(mean_packed * remaining),
                "remaining_unproduced_runs": remaining,
                "warning": "Observed-sample estimate, not a storage guarantee; policy, scenario and origin coverage may be sparse. Current physical usage includes raw completed runs awaiting packing; projection excludes other stages, reports, live partial runs, models and datasets."}
        else:
            stage["projection"] = {"source": "unavailable; no verified compression samples"}
        report.append(stage)
    free = shutil.disk_usage(REPO).free
    return {"stages": report, "watched_objects_and_archives_physical_bytes": sum(physical_files.values()),
            "counting_note": "Archive/object inode deduplication avoids double-counting worker/merged hardlinks. Other run files and active partial runs are excluded.",
            "filesystem_free_bytes": free}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Enable verified packing; default only discovers/reports")
    parser.add_argument("--once", action="store_true", help="One discovery/packing pass")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--end-guard", type=int, default=4)
    parser.add_argument("--reserve-gib", type=float, default=2)
    parser.add_argument("--fixture-root", type=Path, help="Dry-run discovery of copied packing fixture only")
    args = parser.parse_args(argv)
    if args.interval < 1 or args.end_guard < 0 or args.reserve_gib < 2:
        parser.error("Interval must be positive, end guard nonnegative and reserve at least2GiB")
    if args.run and args.fixture_root:
        parser.error("Fixture discovery is dry-run only")
    current_nice = os.getpriority(os.PRIO_PROCESS, 0)
    if current_nice < 10:
        os.nice(10 - current_nice)
    reserve = int(args.reserve_gib * GIB)
    blocked = {}
    while True:
        snapshots = fixture_discovery(args.fixture_root) if args.fixture_root else discover(args.end_guard)
        events = []
        low_disk = shutil.disk_usage(REPO).free < reserve
        if args.run and not low_disk:
            MERGE_LOCK.parent.mkdir(parents=True, exist_ok=True)
            for snapshot in snapshots:
                if snapshot["skip_reason"]:
                    continue
                for candidate in snapshot["targets"]:
                    if shutil.disk_usage(REPO).free < reserve:
                        low_disk = True
                        break
                    path = candidate["path"]
                    value = packing_state(path)
                    if value is not None and value.get("state") == "packed":
                        continue
                    if str(path) in blocked and blocked[str(path)]["fingerprint"] == run_fingerprint(path):
                        continue  # A permanent failure is retried only after relevant files change.
                    with MERGE_LOCK.open("a") as merge_lock:
                        try:
                            fcntl.flock(merge_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            events.append({"stage": snapshot["name"], "state": "skipped_global_merge_lock"})
                            break
                        # Old loaded drivers have no lock; also recheck their
                        # stage/worker end guard immediately before each pack.
                        fresh = next((stage for stage in discover(args.end_guard) if stage["name"] == snapshot["name"]), None)
                        if fresh is None or fresh["skip_reason"]:
                            events.append({"stage": snapshot["name"], "state": "skipped_changed_stage_guard"})
                            break
                        try:
                            run, roots = packing.validate_scope(path)
                            packing.validate_completed_run(run, roots)
                            with packing.run_lock(run):
                                events.append(packing.pack(run, roots, 6))
                        except (ValueError, OSError, KeyError, packing.sqlite3.Error, packing.zipfile.BadZipFile) as exc:
                            transient = "WAL" in str(exc) or "temporarily unavailable" in str(exc)
                            events.append({"run": str(path), "state": "transient_skip" if transient else "packing_error",
                                           "error": str(exc)})
                            if not transient:
                                blocked[str(path)] = {"fingerprint": run_fingerprint(path), "error": str(exc)}
                        else:
                            blocked.pop(str(path), None)
                    if low_disk:
                        break
                if low_disk:
                    break
            snapshots = discover(args.end_guard)
        low_disk = low_disk or shutil.disk_usage(REPO).free < reserve
        result = {"state": "stopped_low_disk" if low_disk else "watching",
                  "dry_run": not args.run, "interval_seconds": args.interval,
                  "reserve_bytes": reserve, "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                  "events": events, "blocked_runs": blocked, **resource_snapshot(snapshots)}
        WATCH_STATUS.parent.mkdir(parents=True, exist_ok=True)
        packing.atomic_json(WATCH_STATUS, result)
        print(json.dumps(result), flush=True)
        if low_disk:
            print("Storage reserve threatened; this watcher stops. Other jobs are left running.", flush=True)
            return 2
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
