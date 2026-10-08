#!/usr/bin/env python3
"""Verified, recoverable object packing for completed, registered M5 runs.

Keep standard report objects for the first three decisions. Full audit/replay and
model-call inspection require --restore. No experiment jobs are launched.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile
import zipfile

REPO = Path("/workspace/MasterDissertation")
STATUS = REPO / "results/run_configs/pipeline_status.json"
REF = re.compile(r"[0-9a-f]{64}")
OBJECT = re.compile(r"([0-9a-f]{64})\.json")
FORMAT = "m5-objects-zip-deflate-v1"
BLOCK = 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def stream_hash(stream):
    result = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(BLOCK), b""):
        result.update(block)
        size += len(block)
    return result.hexdigest(), size


def file_info(path):
    with path.open("rb") as stream:
        sha, size = stream_hash(stream)
    return {"sha256": sha, "bytes": size}


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False,
                                     encoding="utf8", prefix=".packing-") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    os.replace(temporary, path)


def reject_symlinks(path):
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError(f"Symlink paths are refused: {parent}")
    if path.is_dir():
        for entry in path.rglob("*"):
            if entry.is_symlink():
                raise ValueError(f"Symlink entries are refused: {entry}")
            if not entry.is_dir() and not entry.is_file():
                raise ValueError(f"Nonregular entry is refused: {entry}")


def registered_roots():
    document = read_json(STATUS)
    result = set()
    for metadata in document.get("stages", {}).values():
        raw = metadata.get("output") if isinstance(metadata, dict) else None
        if raw:
            root = Path(raw)
            root = (REPO / root).resolve() if not root.is_absolute() else root.resolve()
            if root.is_relative_to(REPO / "results"):
                result.add(root)
    return result


def belongs_to_registered_root(folder, roots):
    if folder in roots:
        return True
    return (re.fullmatch(r"w[0-9]+", folder.name) is not None
            and any(folder.parent == root.with_name(root.name + "_workers") for root in roots))


def validate_scope(run, fixture_root=None):
    run = run.absolute()
    reject_symlinks(run)
    run = run.resolve()
    roots = registered_roots()
    if fixture_root is not None:
        fixture_root = fixture_root.absolute()
        reject_symlinks(fixture_root)
        fixture_root = fixture_root.resolve()
        if (fixture_root.parent != Path("/tmp")
                or not fixture_root.name.startswith("m5_pack_test_")
                or run.parent != fixture_root):
            raise ValueError("Fixture override permits only /tmp/m5_pack_test_*/<copied-run>")
        proof = read_json(fixture_root / ".m5_pack_fixture.json")
        if (proof.get("purpose") != "copied M5 artifact packing validation"
                or proof.get("run_name") != run.name
                or proof.get("summary_sha256") != file_info(run / "summary.json")["sha256"]):
            raise ValueError("Copied fixture provenance does not match")
        source = Path(proof["source_run"]).resolve()
        if not belongs_to_registered_root(source.parent, roots) or source.name != run.name:
            raise ValueError("Fixture source is not a registered generated run")
    else:
        if not belongs_to_registered_root(run.parent, roots):
            raise ValueError(f"Unregistered generated output path is refused: {run}")
        tracked = subprocess.run(["git", "ls-files", "-z", "--", str(run.relative_to(REPO))],
                                 cwd=REPO, check=True, capture_output=True).stdout
        if tracked:
            raise ValueError("Tracked files are refused")
    return run, roots


def validate_completed_run(run, roots):
    summary = read_json(run / "summary.json")
    index = read_json(run / "trace_index.json")
    manifest = read_json(run / "run_manifest.json")
    cfg = manifest["config"]
    policy, scenario, seed, origin = [summary[k] for k in ("policy", "scenario", "seed", "origin")]
    name = f"{policy}__{scenario}__seed{seed}__origin{origin}"
    if run.name != name or manifest.get("run_id") != f"{policy}-{scenario}-seed{seed}-origin{origin}":
        raise ValueError("Run identity does not match generated manifest")
    if [manifest[k] for k in ("scenario", "seed", "origin")] != [scenario, seed, origin]:
        raise ValueError("Manifest identity differs from summary")
    if (policy not in cfg["policies"] or scenario not in cfg["scenarios"] or seed not in cfg["seeds"]
            or not 0 <= origin < cfg["origins"]):
        raise ValueError("Run identity is outside its frozen configuration")
    if manifest.get("execution_environment") != "simulator_only" or "m5" not in cfg["dataset"].lower():
        raise ValueError("Only generated M5 simulation artifacts are supported")
    output = Path(cfg["output"])
    output = (REPO / output).resolve() if not output.is_absolute() else output.resolve()
    if not belongs_to_registered_root(output, roots):
        raise ValueError("Manifest output is not a registered generated output")
    days = cfg["days"]
    start = cfg["start_day"] + origin * cfg["origin_stride"]
    if (summary.get("chain_valid") is not True or summary.get("trace_count") != days
            or [entry["day"] for entry in index] != list(range(start, start + days))):
        raise ValueError("Only complete, chain-valid runs with exact decision coverage may be packed")
    database = run / "artifacts/audit.sqlite"
    wal = database.with_name(database.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("SQLite has a live/uncheckpointed WAL; wait until the run is closed")
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        previous = "0" * 64
        roots = {entry["trace_ref"] for entry in index}
        event_count = 0
        for decision, stage, raw_payload, recorded_previous, recorded_hash in connection.execute(
                "SELECT decision_id,stage,payload,previous_hash,event_hash FROM events ORDER BY seq"):
            payload = json.loads(raw_payload)
            event = {"decision_id": decision, "stage": stage, "payload": payload, "previous_hash": previous}
            if recorded_previous != previous or digest(event) != recorded_hash:
                raise ValueError("Actual SQLite audit chain does not verify")
            previous = recorded_hash
            event_count += 1
            for reference in [payload.get("output"), *payload.get("inputs", [])]:
                if isinstance(reference, str) and REF.fullmatch(reference):
                    roots.add(reference)
        if event_count == 0:
            raise ValueError("Empty audit chain is refused")
    return index, roots, {"run_id": manifest["run_id"], "event_count": event_count,
                          "chain_terminal_hash": previous,
                          "summary_sha256": file_info(run / "summary.json")["sha256"],
                          "run_manifest_sha256": file_info(run / "run_manifest.json")["sha256"],
                          "trace_index_sha256": file_info(run / "trace_index.json")["sha256"]}


def inventory(objects):
    result = {}
    if not objects.is_dir():
        raise ValueError("Objects directory is absent")
    for path in objects.iterdir():
        match = OBJECT.fullmatch(path.name)
        if not path.is_file() or not match:
            raise ValueError(f"Unknown object entry is refused: {path}")
        record = file_info(path)
        if record["sha256"] != match[1]:
            raise ValueError(f"Object SHA filename does not match bytes: {path}")
        result[path.name] = record
    return result


def references(value):
    if isinstance(value, str):
        if REF.fullmatch(value):
            yield value
    elif isinstance(value, dict):
        for member in value.values():
            yield from references(member)
    elif isinstance(value, list):
        for member in value:
            yield from references(member)


def closure(roots, objects, records):
    seen = set()
    pending = list(roots)
    while pending:
        reference = pending.pop()
        name = reference + ".json"
        if name in seen:
            continue
        if name not in records:
            raise ValueError(f"Required audit artifact is absent: {name}")
        seen.add(name)
        value = read_json(objects / name)
        if digest(value) != reference:
            raise ValueError(f"Object is not canonical hash-addressed JSON: {name}")
        pending.extend(ref for ref in references(value) if ref + ".json" in records and ref + ".json" not in seen)
    return seen


def report_keep(index, objects, records):
    kept = set()
    recurse = set()
    for entry in index[:3]:
        reference = entry["trace_ref"]
        trace = read_json(objects / (reference + ".json"))
        kept.add(reference + ".json")
        for key in ("certify_state", "propose"):
            recurse.add(trace["references"][key])
    # Do not recurse through trace.llm.artifacts: they are fully recoverable from
    # the archive, but retaining them would keep most raw calls in four-day runs.
    return kept | closure(recurse, objects, records)


def archive_entries(archive, records):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names) != len(set(names)) or set(names) != {"objects/" + name for name in records}:
        raise ValueError("Archive entry list differs from original object inventory")
    for entry in entries:
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if kind not in (0, stat.S_IFREG) or entry.is_dir() or entry.flag_bits & 1:
            raise ValueError("Nonregular/encrypted archive entries are refused")
    return entries


def verify_archive(path, records, originals=None):
    with zipfile.ZipFile(path) as archive:
        for entry in archive_entries(archive, records):
            name = entry.filename.removeprefix("objects/")
            with archive.open(entry) as stream:
                sha, size = stream_hash(stream)
            if {"sha256": sha, "bytes": size} != records[name] or sha != OBJECT.fullmatch(name)[1]:
                raise ValueError(f"Archive object hash or size differs: {name}")
            if originals is not None:
                with archive.open(entry) as archived, (originals / name).open("rb") as original:
                    while True:
                        a, b = archived.read(BLOCK), original.read(BLOCK)
                        if a != b:
                            raise ValueError(f"Archive bytes differ from original: {name}")
                        if not a:
                            break


def load_packing(run, provenance):
    path = run / "packing_manifest.json"
    value = read_json(path)
    if value.get("format") != FORMAT or value.get("provenance") != provenance:
        raise ValueError("Packing manifest is unrecognized or run provenance changed")
    records = value["original_objects"]
    if digest(records) != value["original_object_inventory_sha256"] or len(records) != value["original_object_count"]:
        raise ValueError("Packing object inventory is inconsistent")
    for name, record in records.items():
        match = OBJECT.fullmatch(name)
        if not match or record["sha256"] != match[1]:
            raise ValueError("Packing inventory contains unsafe object names or hashes")
    if (set(value["kept_hashes"]) | set(value["archived_hashes"]) != set(records)
            or set(value["kept_hashes"]) & set(value["archived_hashes"])):
        raise ValueError("Packing kept/archived partition differs from original inventory")
    for group in ("kept_hashes", "archived_hashes"):
        if any(recorded != records[name]["sha256"] for name, recorded in value[group].items()):
            raise ValueError("Packing partition hashes are inconsistent")
    archive = run / "artifacts/objects.zip"
    if file_info(archive)["sha256"] != value["archive_sha256"]:
        raise ValueError("Archive SHA-256 differs from verified manifest")
    verify_archive(archive, records)
    return value, records, archive


def pack(run, roots, level):
    index, audit_roots, provenance = validate_completed_run(run, roots)
    objects = run / "artifacts/objects"
    archive = run / "artifacts/objects.zip"
    manifest_path = run / "packing_manifest.json"
    current = inventory(objects)
    if manifest_path.exists():
        value, records, archive = load_packing(run, provenance)
        if any(name not in records or record != records[name] for name, record in current.items()):
            raise ValueError("Current objects contain new or changed files; nothing will be removed")
        kept = set(value["kept_hashes"])
        if not kept <= set(current):
            raise ValueError("Required standard-report objects are missing; restore first")
    else:
        if archive.exists():
            raise ValueError("Existing archive without a recognized manifest is preserved; packing refused")
        records = current
        owned = closure(audit_roots, objects, records)
        if owned != set(records):
            raise ValueError(f"{len(set(records)-owned)} object files are not reachable from our audit; unknown files preserved")
        kept = report_keep(index, objects, records)
        with tempfile.NamedTemporaryFile(dir=archive.parent, prefix=".objects-", suffix=".zip", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=level, allowZip64=True) as packed:
                for name in sorted(records):
                    packed.write(objects / name, "objects/" + name)
            verify_archive(temporary_path, records, originals=objects)
            # Publish without overwriting any existing archive, including races.
            os.link(temporary_path, archive)
        finally:
            temporary_path.unlink(missing_ok=True)
        value = {"format": FORMAT, "state": "verified_archive", "provenance": provenance,
                 "original_object_count": len(records), "original_objects": records,
                 "original_object_inventory_sha256": digest(records),
                 "archive": "artifacts/objects.zip", "archive_sha256": file_info(archive)["sha256"],
                 "archive_bytes": archive.stat().st_size,
                 "original_object_bytes": sum(record["bytes"] for record in records.values()),
                 "kept_hashes": {name: records[name]["sha256"] for name in sorted(kept)},
                 "archived_hashes": {name: records[name]["sha256"] for name in sorted(set(records)-kept)},
                 "verification": "Every archive entry checked against original bytes, original SHA-256, size and SHA filename before removal; actual SQLite chain verified.",
                 "standard_report_first_three_decisions_available": True,
                 "full_trace_access": "Full artifacts preserved in verified archive; restore before full audit/replay/model-call inspection.",
                 "recovery_instructions": "Restore the CURRENT run directory with /workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_pack_artifacts.py --restore <CURRENT_RUN_DIRECTORY>. Archives remain valid after merging/moving a run within registered outputs; do not rely on old worker paths.",
                 "recovery_example_at_pack_time": f"/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_pack_artifacts.py --restore {run}",
                 "created_at_utc": datetime.now(timezone.utc).isoformat()}
        atomic_json(manifest_path, value)
    # A successful archive alone does not authorize deleting changed/new files.
    current = inventory(objects)
    if any(name not in records or record != records[name] for name, record in current.items()):
        raise ValueError("Objects changed during packing; verified archive kept but no files removed")
    removed_bytes = 0
    for name in sorted(set(current)-kept):
        path = objects / name
        if file_info(path) != records[name]:
            raise ValueError(f"Object changed before removal: {name}")
        removed_bytes += records[name]["bytes"]
        path.unlink()
    value.update(state="packed", removed_objects=len(records)-len(kept),
                 removed_logical_bytes=sum(records[name]["bytes"] for name in set(records)-kept),
                 updated_at_utc=datetime.now(timezone.utc).isoformat())
    atomic_json(manifest_path, value)
    return {"run": str(run), "state": "packed", "original_objects": len(records),
            "kept_objects": len(kept), "removed_this_call_bytes": removed_bytes,
            "archive_bytes": value["archive_bytes"],
            "note": "Other hardlinks may retain physical disk space; full traces archived and recoverable."}


def restore(run, roots):
    _, _, provenance = validate_completed_run(run, roots)
    value, records, archive_path = load_packing(run, provenance)
    objects = run / "artifacts/objects"
    current = inventory(objects)
    if any(name not in records or record != records[name] for name, record in current.items()):
        raise ValueError("Conflicting or unknown existing files are preserved; restoration refused")
    restored = 0
    with zipfile.ZipFile(archive_path) as archive:
        for name in sorted(set(records)-set(current)):
            path = objects / name
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=objects, prefix=".restore-", delete=False) as destination:
                    temporary_path = Path(destination.name)
                    with archive.open("objects/" + name) as source:
                        for block in iter(lambda: source.read(BLOCK), b""):
                            destination.write(block)
                    destination.flush()
                    os.fsync(destination.fileno())
                if file_info(temporary_path) != records[name]:
                    raise ValueError(f"Restored temporary bytes do not verify: {name}")
                try:
                    os.link(temporary_path, path)
                except FileExistsError:
                    if file_info(path) != records[name]:
                        raise ValueError(f"Conflicting file appeared during restore: {path}")
                else:
                    restored += 1
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            if file_info(path) != records[name]:
                raise ValueError(f"Restored bytes do not verify: {path}")
    if inventory(objects) != records:
        raise ValueError("Restored full object inventory differs")
    value.update(state="restored", updated_at_utc=datetime.now(timezone.utc).isoformat())
    atomic_json(run / "packing_manifest.json", value)
    return {"run": str(run), "state": "restored", "objects": len(records),
            "restored_this_call": restored, "archive_retained": True}


@contextmanager
def run_lock(run):
    with (run / "artifacts/packing.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--pack", nargs="+", metavar="RUN")
    action.add_argument("--restore", nargs="+", metavar="RUN")
    parser.add_argument("--level", type=int, choices=range(1, 10), default=6,
                        help="ZIP deflate compression level (default6; one CPU process)")
    parser.add_argument("--fixture-root", type=Path,
                        help="Copied fixture override requiring /tmp/m5_pack_test_* provenance marker")
    args = parser.parse_args(argv)
    for raw in args.pack or args.restore:
        run, roots = validate_scope(Path(raw), args.fixture_root)
        # Rejected/incomplete runs must not receive even a new lock file.
        validate_completed_run(run, roots)
        with run_lock(run):
            result = pack(run, roots, args.level) if args.pack else restore(run, roots)
        print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile, KeyError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1)
