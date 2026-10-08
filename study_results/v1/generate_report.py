#!/usr/bin/env python3
"""Refresh a factual, standalone report from current M5 run artifacts only.

Run with the repository .venv Python. Never launches or modifies experiments.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import io
import importlib.util
import itertools
import json
import math
import os
import re
import statistics
import subprocess
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The cloud home is read-only; keep report renderer caches in an allowed path.
os.environ.setdefault("MPLCONFIGDIR", "/tmp/m5-report-render-cache/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/m5-report-render-cache")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                               TableStyle, Image, PageBreak)

POLICIES = {
    "B1": "Deterministic seasonal-naive forecast + order-up-to control",
    "B2": "Trained LightGBM quantile forecast + (s,S) control",
    "B3": "Trained native GRU/negative-binomial forecast + stochastic MILP",
    "B4": "B3 + deterministic evidence gate; no LLM",
    "B5": "Chronos forecast adapter; requires separate weights",
    "B6": "Single generalist LLM + shared numerical tools",
    "B7": "LLM roles with free-form shared messages + validated action boundary",
    "B8": "Typed LLM roles without critic",
    "B9": "Typed LLM roles + critic, fixed autonomy",
    "B10": "Typed LLM roles + critic + per-decision evidence gate",
    "D0": "Deterministic seasonal-forecast optimizer software control; no LLM",
    "D1": "D0 + deterministic evidence gate software control; no LLM",
}
WARNINGS = []
LOADED_HASHES = {}
ARCHIVE_SHA_CACHE = {}
PACKING_FORMAT = "m5-objects-zip-deflate-v1"
DIRECT_METRICS = ("cost", "fill_rate", "harmful_executions")


def read_json(path, default=None):
    try:
        content = path.read_bytes()
        LOADED_HASHES[str(path)] = hashlib.sha256(content).hexdigest()
        return json.loads(content)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        WARNINGS.append(f"Could not read {path}: {type(exc).__name__}; possibly still being written.")
        return default


def read_yaml(path):
    try:
        content = path.read_bytes()
        LOADED_HASHES[str(path)] = hashlib.sha256(content).hexdigest()
        return yaml.safe_load(content) or {}
    except (OSError, ValueError, yaml.YAMLError) as exc:
        WARNINGS.append(f"Could not read config {path}: {type(exc).__name__}.")
        return {}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class PackedArtifactReader:
    """Read selected content-addressed JSON from loose files or a verified ZIP.

    This never restores, deletes or alters a run. Archive SHA checks are cached
    using file identity/size/mtime and expected SHA; individual reads also verify
    the requested object SHA and length against its original inventory.
    """
    def __init__(self, run):
        self.run = Path(run)
        self.path = self.run / "packing_manifest.json"
        self.manifest = read_json(self.path, {})
        self.records = {}
        self.archive = self.run / "artifacts/objects.zip"
        if not self.manifest:
            return
        manifest = self.manifest
        if manifest.get("format") != PACKING_FORMAT or manifest.get("archive") != "artifacts/objects.zip":
            raise ValueError("Unrecognized packing manifest format or archive path")
        records = manifest.get("original_objects", {})
        if len(records) != manifest.get("original_object_count") or canonical_hash(records) != manifest.get("original_object_inventory_sha256"):
            raise ValueError("Packing inventory count/hash differs")
        for name, record in records.items():
            if not re.fullmatch(r"[0-9a-f]{64}\.json", name) or record.get("sha256") != name[:-5]:
                raise ValueError("Packing inventory object name/hash differs")
        kept, archived = manifest.get("kept_hashes", {}), manifest.get("archived_hashes", {})
        if set(kept) & set(archived) or set(kept) | set(archived) != set(records):
            raise ValueError("Packing inventory partitions differ")
        if any(digest != records[name]["sha256"] for group in [kept, archived] for name, digest in group.items()):
            raise ValueError("Packing partition object hashes differ")
        for key, filename in [("summary_sha256", "summary.json"),
                              ("run_manifest_sha256", "run_manifest.json"),
                              ("trace_index_sha256", "trace_index.json")]:
            if sha256(self.run / filename) != manifest.get("provenance", {}).get(key):
                raise ValueError("Packed run's original provenance changed")
        stat = self.archive.stat()
        expected_sha = manifest.get("archive_sha256")
        cache_key = f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{expected_sha}"
        actual_sha = ARCHIVE_SHA_CACHE.get(cache_key)
        if actual_sha is None:
            actual_sha = sha256(self.archive)
            ARCHIVE_SHA_CACHE[cache_key] = actual_sha
        if actual_sha != expected_sha or stat.st_size != manifest.get("archive_bytes"):
            raise ValueError("Packing archive's current SHA/size differs")
        LOADED_HASHES[str(self.archive)] = actual_sha
        with zipfile.ZipFile(self.archive) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or set(names) != {"objects/" + name for name in records}:
                raise ValueError("Archive members differ from original inventory")
            if any(entry.is_dir() or entry.flag_bits & 1 or entry.file_size != records[entry.filename.removeprefix("objects/")]["bytes"] for entry in entries):
                raise ValueError("Archive members have invalid type/encryption/length")
        self.records = records

    def load(self, reference, prefer_archive=False):
        if not re.fullmatch(r"[0-9a-f]{64}", reference):
            raise ValueError("Artifact reference must be a content SHA-256")
        name = reference + ".json"
        loose = self.run / "artifacts/objects" / name
        if loose.exists() and not prefer_archive:
            content = loose.read_bytes()
        elif name in self.records:
            with zipfile.ZipFile(self.archive) as archive:
                content = archive.read("objects/" + name)
        else:
            raise FileNotFoundError(f"Object is absent from both loose files and a verified archive: {name}")
        if hashlib.sha256(content).hexdigest() != reference:
            raise ValueError("Requested artifact's bytes fail its content SHA-256")
        if name in self.records and len(content) != self.records[name]["bytes"]:
            raise ValueError("Requested artifact's size differs from original inventory")
        return json.loads(content)

    def summary(self):
        if not self.manifest:
            return None
        index = read_json(self.run / "trace_index.json", [])
        loose = sum((self.run / "artifacts/objects" / (entry["trace_ref"] + ".json")).exists() for entry in index)
        return {"run": str(self.run), "state": self.manifest.get("state"),
                "verification": "Current archive SHA/size, member inventory, original inventory hash and run provenance checked; selected reads also verify each object's SHA/size",
                "original_objects": len(self.records), "kept_loose_objects": len(self.manifest["kept_hashes"]),
                "trace_decisions": len(index), "loose_trace_decisions": loose,
                "archive_bytes": self.manifest["archive_bytes"], "archive_sha256": self.manifest["archive_sha256"],
                "original_object_inventory_sha256": self.manifest["original_object_inventory_sha256"],
                "full_traces_available": all(entry["trace_ref"] + ".json" in self.records for entry in index),
                "helper_verification_record": self.manifest.get("verification"),
                "recovery_instructions": self.manifest.get("recovery_instructions")}


def relative(path, repo):
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)


def resolve(path, repo):
    path = Path(path)
    return path if path.is_absolute() else repo / path


def redact(value):
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            lower = str(key).lower()
            is_secret = lower in {"api_key", "secret", "token", "password", "authorization", "access_token", "refresh_token"}
            out[key] = "[REDACTED]" if is_secret else redact(val)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def numeric(row, key):
    try:
        value = float(row.get(key, ""))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def number(value, digits=3):
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}" if digits else f"{value:,.0f}"
    return str(value)


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def csv_rows(path):
    try:
        with path.open(newline="") as stream:
            return list(csv.DictReader(stream))
    except (OSError, csv.Error):
        return []


def row_key(row):
    return (str(row.get("policy")), str(row.get("scenario")),
            int(row.get("seed", -1)), int(row.get("origin", 0)))


def expected_keys(config):
    return set(itertools.product([str(x) for x in config.get("policies", [])],
                                 [str(x) for x in config.get("scenarios", [])],
                                 [int(x) for x in config.get("seeds", [])],
                                 range(int(config.get("origins", 1)))))


def cells_from_rows(rows, config):
    grouped = defaultdict(list)
    for row in sorted(rows, key=row_key):
        grouped[row_key(row)[:2]].append(row)
    cells = []
    for (policy, scenario), cell_rows in grouped.items():
        by_seed = defaultdict(list)
        for row in cell_rows:
            by_seed[int(row["seed"])].append(row)
        seed_costs = [mean([numeric(row, "cost") for row in seed_rows]) for seed_rows in by_seed.values()]
        cells.append({
            "policy": policy, "scenario": scenario,
            "runs": len(cell_rows), "seeds": len(by_seed),
            "seed_origin_complete": all(len(v) == int(config.get("origins", 1)) for v in by_seed.values()),
            "mean_cost": mean(seed_costs),
            "mean_fill_rate": mean([mean([numeric(row, "fill_rate") for row in v]) for v in by_seed.values()]),
            "mean_cycle_service_level": mean([mean([numeric(row, "cycle_service_level") for row in v]) for v in by_seed.values()]),
            "mean_stockout_rate": mean([mean([numeric(row, "stockout_rate") for row in v]) for v in by_seed.values()]),
            "mean_bullwhip": mean([mean([numeric(row, "bullwhip") for row in v]) for v in by_seed.values()]),
            "mean_inventory": mean([mean([numeric(row, "mean_inventory") for row in v]) for v in by_seed.values()]),
            "mean_inventory_turns_window": mean([mean([numeric(row, "inventory_turns_window") for row in v]) for v in by_seed.values()]),
            "harmful_executions": sum(numeric(row, "harmful_executions") or 0 for row in cell_rows),
            "violation_executions": sum(numeric(row, "violation_executions") or 0 for row in cell_rows),
            "reference_deviations": sum(numeric(row, "reference_deviations") or 0 for row in cell_rows),
            "hard_violations": sum(numeric(row, "hard_violations") or 0 for row in cell_rows),
            "executed_actions": sum(numeric(row, "executed_actions") or 0 for row in cell_rows),
            "held_decisions": sum(numeric(row, "held_decisions") or 0 for row in cell_rows),
            "llm_calls": sum(numeric(row, "llm_calls") or 0 for row in cell_rows),
            "llm_errors": sum(numeric(row, "llm_errors") or 0 for row in cell_rows),
            "fallback_decisions": sum(numeric(row, "fallback_decisions") or 0 for row in cell_rows),
        })
    return cells


def inspect_stage(name, config, config_path, meta, repo, allow_analytical=True):
    output = resolve(config.get("output", meta.get("output", f"results/{name}")), repo)
    if allow_analytical and (output / "analytical_manifest.json").exists():
        return inspect_analytical_stage(name, config, config_path, meta, repo, output)
    keys = expected_keys(config)
    dirs = [output]
    worker_root = Path(str(output) + "_workers")
    if worker_root.exists():
        dirs += sorted(p for p in worker_root.iterdir() if p.is_dir())
    rows, run_paths, partial_dirs = {}, {}, []
    packing, packing_errors = [], []
    recorded_data = {}
    input_paths = set()
    for directory in dirs:
        for summary_path in sorted(directory.glob("*/summary.json")):
            row = read_json(summary_path, {})
            if not row or not row.get("policy"):
                continue
            try:
                key = row_key(row)
            except (ValueError, TypeError):
                WARNINGS.append(f"Malformed key in {summary_path}.")
                continue
            daily = csv_rows(summary_path.parent / "daily.csv")
            target_days = int(config.get("days", 0))
            if target_days and len(daily) != target_days:
                partial_dirs.append(relative(summary_path.parent, repo))
                continue
            if keys and key not in keys:
                WARNINGS.append(f"Unexpected run key {key} in {summary_path}; excluded from configured stage.")
                continue
            if key in rows:
                if rows[key].get("cost") != row.get("cost"):
                    WARNINGS.append(f"Worker and merged summaries disagree for {name} {key}; merged artifact takes priority.")
                continue
            rows[key] = row
            run_paths[key] = summary_path.parent
            if (summary_path.parent / "packing_manifest.json").exists():
                input_paths.add(summary_path.parent / "packing_manifest.json")
                try:
                    reader = PackedArtifactReader(summary_path.parent)
                    packed_summary = reader.summary()
                    if not packed_summary["full_traces_available"]:
                        raise ValueError("Original packing inventory does not cover every trace decision")
                    packing.append(packed_summary)
                    input_paths.add(reader.archive)
                except (ValueError, OSError, zipfile.BadZipFile, KeyError) as exc:
                    message = f"{name} packing validation failed for {summary_path.parent.name}: {exc}"
                    WARNINGS.append(message)
                    packing_errors.append(message)
            input_paths.add(summary_path)
            input_paths.add(summary_path.parent / "daily.csv")
            if (summary_path.parent / "run_manifest.json").exists():
                input_paths.add(summary_path.parent / "run_manifest.json")
                if not recorded_data:
                    recorded_data = read_json(summary_path.parent / "run_manifest.json", {}).get("data", {})
        for run_dir in directory.glob("*__*__seed*__origin*"):
            if run_dir.is_dir() and not (run_dir / "summary.json").exists():
                partial_dirs.append(relative(run_dir, repo))
    # A study-level CSV alone is not sufficient to certify a completed run.
    summary = csv_rows(output / "summary.csv") if allow_analytical else []
    for row in summary:
        try:
            key = row_key(row)
        except (TypeError, ValueError):
            continue
        if key not in rows:
            WARNINGS.append(f"Study CSV contains {name} {key} without a complete per-run summary and daily file; excluded from completion count.")
    for artifact in [output / "summary.csv", output / "study_summary.json", output / "paired_comparisons.csv",
                     output / "resolved_config.json", output / "environment.json", config_path]:
        if artifact and artifact.exists():
            input_paths.add(artifact)
    planned = len(keys) or meta.get("expected_runs")
    completed = len(rows)
    reported_status = str(meta.get("state", meta.get("status", "unreported"))).lower()
    required = bool(meta.get("required", reported_status not in {"superseded", "archived", "cancelled"}))
    blocker = meta.get("blocker", "")
    if planned and completed == planned:
        status = "COMPLETE"
    elif completed or partial_dirs or reported_status in {"running", "failed"}:
        status = "PARTIAL"
    elif reported_status == "blocked" or blocker:
        status = "BLOCKED"
    else:
        status = "UNRUN"
    invalid_chains = sum(str(row.get("chain_valid", "")).lower() == "false" for row in rows.values())
    if invalid_chains:
        WARNINGS.append(f"{name}: {invalid_chains} completed run(s) have invalid audit chains.")
    cells = cells_from_rows(list(rows.values()), config)
    study_summary = read_json(output / "study_summary.json", {})
    resolved_config = read_json(output / "resolved_config.json", {})
    environment = read_json(output / "environment.json", {})
    if not resolved_config or not environment:
        for directory in dirs:
            resolved_config = resolved_config or read_json(directory / "resolved_config.json", {})
            environment = environment or read_json(directory / "environment.json", {})
            for artifact in [directory / "resolved_config.json", directory / "environment.json"]:
                if artifact.exists():
                    input_paths.add(artifact)
    return {"name": name, "status": status, "reported_status": reported_status,
            "required": required,
            "expected": planned, "completed": completed, "config": redact(config),
            "config_path": relative(config_path, repo) if config_path else None,
            "config_sha256": sha256(config_path) if config_path and config_path.exists() else None,
            "output": relative(output, repo), "blocker": blocker,
            "cells": cells, "partial_run_dirs": partial_dirs,
            "resolved_config": redact(resolved_config), "environment": redact(environment),
            "run_recorded_data": recorded_data,
            "packing": packing, "packing_errors": packing_errors,
            "invalid_chains": invalid_chains, "rows": list(rows.values()),
            "source_run_paths": [str(path.resolve()) for path in run_paths.values()],
            "study_summary": study_summary, "input_paths": input_paths,
            "paired_comparisons": csv_rows(output / "paired_comparisons.csv"),
            "llm_calls": sum(numeric(row, "llm_calls") or 0 for row in rows.values()),
            "llm_errors": sum(numeric(row, "llm_errors") or 0 for row in rows.values()),
            "tokens": sum(numeric(row, "tokens") or 0 for row in rows.values()),
            "fallbacks": sum(numeric(row, "fallback_decisions") or 0 for row in rows.values())}


def inspect_analytical_stage(name, config, config_path, meta, repo, output):
    """A verified analytical view references original runs; it creates no runs."""
    if not config:
        config = read_json(output / "resolved_config.json", {})
    config_path = config_path or output / "resolved_config.json"
    stage = inspect_stage(name, config, config_path, {**meta, "required": False}, repo, allow_analytical=False)
    helper_path = Path("/workspace/tools/m5_analytical_validation.py")
    training_path = Path("/workspace/tools/m5_training_equivalence.py")
    sys.path.insert(0, str(helper_path.parent))
    spec = importlib.util.spec_from_file_location("m5_report_analytical_validation", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    validation = helper.validate_analytical_manifest(output, repo)
    stage["input_paths"].update(validation["input_paths"])
    stage["input_paths"].update([helper_path, training_path])
    stage["analytical_validation"] = {key: value for key, value in validation.items() if key not in {"input_paths", "rows", "run_paths", "config"}}
    stage["analytical_source_outputs"] = [source["root"] for source in validation.get("sources", [])]
    stage["analytical_view"] = True
    if not validation["valid"]:
        stage["status"] = "BLOCKED"
        stage["blocker"] = "Analytical pooling withheld: " + "; ".join(validation["errors"])
        WARNINGS.append(stage["blocker"])
        return stage
    stage.update(config=redact(validation["config"]), resolved_config=redact(validation["config"]),
                 rows=validation["rows"], completed=len(validation["rows"]), expected=360, status="COMPLETE",
                 cells=cells_from_rows(validation["rows"], validation["config"]),
                 run_recorded_data=validation["recorded_data"], environment=validation["environment"],
                 source_run_paths=validation["run_paths"],
                 invalid_chains=0, partial_run_dirs=[], blocker="", llm_calls=0, llm_errors=0, tokens=0, fallbacks=0)
    for run_path in validation["run_paths"]:
        run = Path(run_path)
        if (run / "packing_manifest.json").exists():
            stage["input_paths"].add(run / "packing_manifest.json")
            try:
                reader = PackedArtifactReader(run)
                packing = reader.summary()
                if not packing["full_traces_available"]:
                    raise ValueError("Original packed trace inventory is incomplete")
                stage["packing"].append(packing)
                stage["input_paths"].add(reader.archive)
            except (ValueError, OSError, zipfile.BadZipFile, KeyError) as error:
                stage["packing_errors"].append(str(error))
    if stage["packing_errors"]:
        stage["status"] = "BLOCKED"
        stage["blocker"] = "Analytical packing proof failed: " + "; ".join(stage["packing_errors"])
        stage["analytical_validation"]["valid"] = False
    return stage


def direct_gate_comparison(stage):
    """Frozen B10-B9 contrast; run only after the entire >=30-seed grid completes."""
    config = stage["config"]
    seeds = {int(seed) for seed in config.get("seeds", [])}
    if stage["status"] != "COMPLETE" or len(seeds) < 30 or not {"B9", "B10"}.issubset(config.get("policies", [])):
        return []
    from ega.evaluation.metrics import paired_bootstrap, holm
    rows = []
    for scenario in config.get("scenarios", []):
        for metric in DIRECT_METRICS:
            values = {}
            for policy in ["B10", "B9"]:
                by_seed = defaultdict(list)
                for row in stage["rows"]:
                    value = numeric(row, metric)
                    if row["policy"] == policy and row["scenario"] == scenario and value is not None:
                        by_seed[int(row["seed"])].append(value)
                if set(by_seed) != seeds or any(len(v) != int(config.get("origins", 1)) for v in by_seed.values()):
                    WARNINGS.append(f"{stage['name']}: complete independent pairs unavailable for B10-B9 {scenario}/{metric}; all direct inference withheld.")
                    return []
                values[policy] = [statistics.mean(by_seed[seed]) for seed in sorted(seeds)]
            result = paired_bootstrap(values["B10"], values["B9"], seed=42, resamples=5000, confidence=.95)
            rows.append({"scenario": scenario, "policy": "B10", "reference": "B9", "metric": metric, **result})
    adjusted = holm([row["wilcoxon_p"] for row in rows])
    for row, pvalue in zip(rows, adjusted):
        row["holm_adjusted_wilcoxon_p"] = pvalue
        row["holm_family"] = "B10-B9: frozen cost, fill_rate, harmful_executions across all configured scenarios in this stage"
    return rows


PROSE_RULE = re.compile(r"^Contract clause (.+?) \(precedence (-?\d+), aggregation (\w+)\): (.+?) must comply with (\w+) = (\S+) (\S+) at (\w+) scope, valid from day (\d+) to day (\d+) inclusive; conversion (\S+)\.$")
PROSE_RULE_ALTERNATE = re.compile(r"^Rule (.+?)\. For entity (.+?), scope (\w+), (\w+) is (\S+) (\S+)\. Aggregation level: (\w+)\. Effective from day (\d+) to day (\d+), both inclusive\. Precedence (-?\d+)\. Conversion: (\S+)\.$")
TUPLE_FIELDS = ["entity", "scope", "parameter", "value", "unit", "conversion", "aggregation", "valid_from", "valid_to", "precedence", "source_ref"]


def inspect_trace_details(stage):
    """Read actual proposal diagnostics and submitted-rule extraction evidence."""
    solver_cells = defaultdict(list)
    grounded_days, holds, errors = [], [], []
    for path in stage.get("source_run_paths", []):
        run = Path(path)
        row = read_json(run / "summary.json", {})
        key = (row.get("policy"), row.get("scenario"))
        try:
            reader = PackedArtifactReader(run) if (run / "packing_manifest.json").exists() else None
            def load(reference):
                loose = run / "artifacts/objects" / (reference + ".json")
                if loose.exists():
                    stage["input_paths"].add(loose)
                if reader:
                    return reader.load(reference)
                content = loose.read_bytes()
                if hashlib.sha256(content).hexdigest() != reference:
                    raise ValueError("Loose object content hash mismatch")
                LOADED_HASHES[str(loose)] = reference
                return json.loads(content)
            index = read_json(run / "trace_index.json", [])
            stage["input_paths"].add(run / "trace_index.json")
            for entry in index:
                trace = load(entry["trace_ref"])
                proposal = load(trace["references"]["propose"])
                diagnostic = proposal.get("solver", {})
                solver_cells[key].append({"day": entry["day"], "seed": row.get("seed"), "origin": row.get("origin"),
                                          "method": proposal.get("method"), **diagnostic})
                reasons = trace.get("autonomy", {}).get("reasons", [])
                reason_text = "; ".join(map(str, reasons))
                dimensional = re.search(r"[^;]+: dimensional mismatch [^;]+", reason_text)
                execution = trace.get("execution")
                receipt_ref = trace.get("references", {}).get("receipt") or (execution if isinstance(execution, str) and re.fullmatch(r"[0-9a-f]{64}", execution) else None)
                receipt = load(receipt_ref) if receipt_ref else execution if isinstance(execution, dict) else {}
                held = proposal.get("method") == "hold" or receipt.get("status") == "held" or receipt.get("held") is True
                if held:
                    holds.append({"policy": key[0], "scenario": key[1], "seed": row.get("seed"), "origin": row.get("origin"),
                                  "day": entry["day"], "solver_status": diagnostic.get("status"),
                                  "first_recorded_dimensional_mismatch": dimensional.group(0).strip() if dimensional else None,
                                  "missing_required_fields_reported": reason_text.count("missing required"),
                                  "reason_excerpt": reason_text[:450]})
                if key[0] not in {"B9", "B10"} or stage["config"].get("document_carrier") != "prose":
                    continue
                available = load(trace["references"]["source_documents"])
                available_refs = {document["source_ref"] for document in available}
                available_documents = {document["source_ref"]: document for document in available}
                sent_refs, call_rows = set(), []
                for reference in trace.get("llm", {}).get("artifacts", []):
                    call = load(reference)
                    if "constraint" not in str(call.get("role", "")):
                        continue
                    payload = None
                    for message in call.get("request", {}).get("messages", []):
                        if message.get("role") == "user":
                            try:
                                candidate = json.loads(message["content"])
                                if isinstance(candidate, dict) and "documents" in candidate:
                                    payload = candidate
                            except (ValueError, TypeError):
                                pass
                    if payload is None:
                        continue
                    expected = set()
                    for document in payload["documents"]:
                        match = PROSE_RULE.fullmatch(document["text"])
                        alternate = PROSE_RULE_ALTERNATE.fullmatch(document["text"]) if not match else None
                        from ega.util import digest
                        if not (match or alternate) or digest(document["text"]) != document.get("sha256") or available_documents.get(document["source_ref"]) != document:
                            raise ValueError("Submitted source is outside the exact controlled-prose grammar/hash")
                        if match:
                            constraint_id, precedence, aggregation, entity, parameter, value, unit, scope, start, end, conversion = match.groups()
                        else:
                            constraint_id, entity, scope, parameter, value, unit, aggregation, start, end, precedence, conversion = alternate.groups()
                        rule = dict(entity=entity, scope=scope, parameter=parameter, value=float(value), unit=unit,
                                    conversion=None if conversion == "none" else float(conversion), aggregation=aggregation,
                                    valid_from=int(start), valid_to=int(end), precedence=int(precedence), source_ref=document["source_ref"])
                        from ega.schemas import Constraint
                        from ega.constraints import render_prose
                        labelled = Constraint.model_validate({**rule, "constraint_id": constraint_id, "confidence": 1.0, "provenance": "authenticated_source"})
                        if render_prose([labelled], variant=0 if match else 1)[0].text != document["text"]:
                            raise ValueError("Controlled-prose inverse does not roundtrip exactly to the captured source")
                        expected.add(json.dumps(rule, sort_keys=True, separators=(",", ":")))
                        sent_refs.add(document["source_ref"])
                    response = call.get("response", {})
                    try:
                        from ega.agents.llm import Extraction
                        parsed = Extraction.model_validate(json.loads(response["choices"][0]["message"]["content"]))
                        actual = {json.dumps({field: constraint.model_dump()[field] for field in TUPLE_FIELDS}, sort_keys=True, separators=(",", ":")) for constraint in parsed.constraints}
                        validated = True
                    except (KeyError, IndexError, TypeError, ValueError):
                        actual, validated = set(), False
                    call_rows.append({"call_ref": reference, "source_rules_submitted": len(expected),
                                      "validated_response": validated, "returned_rules": len(actual) if validated else None,
                                      "exact_rules": len(expected & actual), "false_rules": len(actual - expected) if validated else None,
                                      "omitted_submitted_rules": len(expected - actual), "elapsed_seconds": call.get("elapsed_seconds"),
                                      "actual_usage": response.get("usage", {})})
                grounded_days.append({"policy": key[0], "scenario": key[1], "seed": row.get("seed"), "origin": row.get("origin"),
                                          "day": entry["day"], "available_source_documents": len(available_refs),
                                          "distinct_source_documents_submitted": len(sent_refs), "unprocessed_source_documents": len(available_refs - sent_refs),
                                          "call_rows": call_rows,
                                          "first_recorded_dimensional_mismatch": dimensional.group(0).strip() if dimensional else None,
                                          "source_inverse_roundtrip_exact": True if call_rows else None})
        except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
            errors.append(f"{run.name}: trace-detail inspection incomplete: {error}")
    solvers = []
    for (policy, scenario), proposals in sorted(solver_cells.items()):
        attempts = [proposal for proposal in proposals if proposal.get("method") == "stochastic_milp" and proposal.get("status") != "not_run"]
        gaps = [numeric(proposal, "gap") for proposal in attempts]
        gaps = [gap for gap in gaps if gap is not None]
        solvers.append({"policy": policy, "scenario": scenario, "proposal_traces": len(proposals), "milp_attempts": len(attempts),
                        "feasible": sum(proposal.get("feasible") is True for proposal in attempts),
                        "optimal": sum(proposal.get("optimal") is True for proposal in attempts),
                        "time_limit_incumbents": sum(proposal.get("feasible") is True and proposal.get("optimal") is not True and (proposal.get("status") == 1 or "time limit" in str(proposal.get("message", "")).lower()) for proposal in attempts),
                        "reported_gap_n": len(gaps), "mean_reported_gap": mean(gaps), "max_reported_gap": max(gaps) if gaps else None,
                        "mean_reported_seconds": mean([numeric(proposal, "seconds") for proposal in attempts]), "recorded_proposals": proposals})
    return {"solver_diagnostics": solvers, "held_trace_examples": holds,
            "submitted_document_grounding": grounded_days, "errors": errors,
            "grounding_definition": "Exact eleven-field tuples against only the controlled source documents present in each captured extraction request; later unprocessed documents are coverage gaps, not extraction omissions. Repeated calls are descriptive request records, not independent replications."}


def exploratory_numeric_intervals(stage):
    """Only the independently verified full analytical grid is eligible."""
    if stage["status"] != "COMPLETE" or stage["packing_errors"] or not stage.get("analytical_validation", {}).get("valid"):
        return []
    if set(map(int, stage["config"].get("seeds", []))) != set(range(30)) or len(stage["rows"]) != 360:
        return []
    import numpy as np
    rows = {row_key(row): row for row in stage["rows"]}
    intervals = []
    for scenario in stage["config"]["scenarios"]:
        for metric in ["cost", "fill_rate", "hard_violations"]:
            differences = []
            for seed in range(30):
                left = numeric(rows.get(("B4", scenario, seed, 0), {}), metric)
                right = numeric(rows.get(("B3", scenario, seed, 0), {}), metric)
                if left is None or right is None:
                    return []
                differences.append(left - right)
            values = np.asarray(differences)
            indices = np.random.default_rng(42).integers(0, 30, (5000, 30))
            lower, upper = np.quantile(values[indices].mean(axis=1), [.025, .975])
            intervals.append({"scenario": scenario, "contrast": "B4 minus B3", "metric": metric,
                              "pairs": 30, "mean_difference": float(values.mean()), "ci_low": float(lower), "ci_high": float(upper),
                              "method": "exploratory paired percentile bootstrap, 5000 resamples, seed42; no p-value or multiplicity adjustment",
                              "design": "post-launch runtime-based numerical extension; not confirmatory dissertation registration"})
    return intervals


def historical_windows(stage, repo):
    config = stage["config"]
    if not config or not config.get("dataset"):
        return []
    path = resolve(config["dataset"], repo) / "calendar.csv"
    calendar = csv_rows(path)
    if not calendar:
        return []
    stage["input_paths"].add(path)
    windows = []
    for origin in range(int(config.get("origins", 1))):
        start = int(config["start_day"]) + origin * int(config.get("origin_stride", 28))
        end = start + int(config["days"]) - 1
        training = start - int(config["warmup_days"]) - 1
        if training < 0 or end >= len(calendar):
            continue
        windows.append({"origin": origin, "training_end_index": training, "training_end_date": calendar[training].get("date"),
                        "decision_start_index": start, "decision_end_index": end,
                        "decision_start_date": calendar[start].get("date"), "decision_end_date": calendar[end].get("date"),
                        "calendar_source": relative(path, repo)})
    return windows


def load_runtime_readiness(repo, scope="full"):
    folder = repo / "results/run_configs"
    identity_path = folder / ("six_hour_model_identity.json" if scope == "six-hour" and (folder / "six_hour_model_identity.json").exists() else "ollama_model_identity.json")
    chronos_path = folder / "chronos_model_metadata.json"
    paths = [p for p in [identity_path, chronos_path] if p.exists()]
    readiness_paths = set()
    for directory in [folder, repo / "results", repo / "results/logs"]:
        for pattern in ["*readiness*.json", "*preflight*.json", "*throughput*.json", "*supervisor*state*.json", "*supervisor*status*.json"]:
            readiness_paths.update(directory.glob(pattern))
    readiness_paths.update((repo / "results").glob("*/development_manifest.json"))
    paths += sorted(readiness_paths)
    grounding_paths = set((repo / "results").glob("*/grounding_results.json")) | set((repo / "results").glob("*/grounding/grounding_results.json"))
    for incremental in (repo / "results").glob("*/grounding/incremental_grounding_results.json"):
        grounding_paths.add(incremental)
    grounding_paths = sorted(grounding_paths)
    paths += grounding_paths
    return {"ollama_identity": read_json(identity_path, {}),
            "chronos_metadata": read_json(chronos_path, {}),
            "readiness_records": [{"path": relative(p, repo), "data": redact(read_json(p, {})),
                                   "evidence_role": "current bounded-study preparation" if scope == "six-hour" and "six_hour" in relative(p, repo) else "retained auxiliary preparation" if scope == "six-hour" else "recorded preparation"} for p in sorted(readiness_paths)],
            "grounding_benchmarks": [{"path": relative(p, repo), "data": read_json(p, {}),
                                     "evidence_role": "current bounded-study development" if scope == "six-hour" and "six_hour" in relative(p, repo) else "retained auxiliary grounding" if scope == "six-hour" else "recorded grounding"} for p in grounding_paths],
            "paths": paths}


def apply_current_readiness(stages, readiness):
    identity = readiness["ollama_identity"]
    revision = identity.get("digest", "")
    valid_identity = bool(re.fullmatch(r"[0-9a-f]{64}", revision) and identity.get("model"))
    for stage in stages:
        blocker = str(stage["blocker"])
        llm = stage["config"].get("llm", {})
        obsolete_network = any(word in blocker.lower() for word in ["403", "registry access", "storage-domain", "network policy", "model weights blocked"])
        stage["readiness_observations"] = []
        if valid_identity and llm.get("enabled") and llm.get("model") == identity["model"]:
            pinned = llm.get("model_revision") == revision
            stage["readiness_observations"].append("Verified registry download and local registration are attested by ollama_model_identity.json; this alone does not validate functional inference or full-study readiness.")
            stage["readiness_observations"].append("Configured model digest matches registered identity." if pinned else "The run config has not yet been frozen to the registered model digest; model/preflight validation is separate.")
            if obsolete_network:
                stage["superseded_pipeline_blocker"] = blocker
                stage["blocker"] = "" if pinned else "Run configuration's model revision is pending; freeze the actual registered digest after functional model/preflight validation."
                if stage["completed"] == 0:
                    stage["status"] = "BLOCKED" if not pinned else "PARTIAL" if stage["reported_status"] == "running" else "UNRUN"
                stage["readiness_observations"].append("Earlier model-storage network denial is superseded by the later verified registered-model identity.")
        if "B5" in stage["config"].get("policies", []) and readiness["chronos_metadata"].get("revision"):
            stage["readiness_observations"].append("Pinned Chronos metadata revision has been obtained; it does not attest downloaded model weights or tested foundation inference.")
            old_metadata_denial = "api currently" in blocker.lower() or ("403" in blocker and "metadata" in blocker.lower() and not any(word in blocker.lower() for word in ["safetensors", "remaining", ".hf.co"]))
            if old_metadata_denial:
                stage["superseded_pipeline_blocker"] = blocker
                stage["blocker"] = "Chronos revision metadata is available; complete weight download and tested foundation inference remain unverified by this report's readiness evidence."


def add_runtime_readiness(doc, readiness):
    doc.heading("Model preparation and functional readiness")
    identity = readiness["ollama_identity"]
    if identity:
        doc.para(f"Recorded local model: {identity.get('model', 'unrecorded')}; registered digest: {identity.get('digest', 'unrecorded')}; parameter size: {identity.get('details', {}).get('parameter_size', 'unrecorded')}; quantization: {identity.get('details', {}).get('quantization_level', 'unrecorded')}. Source attestation: {identity.get('source', 'unrecorded')}. This establishes the recorded verified download/registration step, not successful end-to-end experimental decisions.")
    else:
        doc.para("No current registered local-model identity artifact is available.")
    doc.para("Readiness records below are separate from completed simulation results: model registration, validated structured responses, measured throughput, configuration freeze and a completed study are different milestones. Historical network failures in earlier audit/validation snapshots do not override a later verified identity. Successful preflight calls do not count as completed full-study runs.")
    if readiness["readiness_records"]:
        for record in readiness["readiness_records"]:
            doc.para(record.get("evidence_role", "Recorded readiness") + " source: " + record["path"])
            doc.code(record["path"] + " readiness snapshot", record["data"])
            selected = {key: value for key, value in record["data"].items() if key in {"state", "status", "phase", "success", "ready", "validated", "complete", "development_only", "series", "day", "pilot_runs", "model", "model_name", "model_revision", "model_digest", "digest", "blocker", "error", "completed_at", "updated_at", "updated_at_utc", "elapsed_seconds", "calls", "llm_calls", "llm_errors", "tokens", "tokens_per_second", "seconds_per_call", "preflight_passed", "functional_usage"}}
            if selected:
                doc.para("Readiness summary: " + json.dumps(selected, sort_keys=True))
            if record["data"].get("pending_frozen_llm_configs"):
                doc.para("This readiness snapshot records agentic configs awaiting freeze/registration: " + ", ".join(map(str, record["data"]["pending_frozen_llm_configs"])) + ". Registered stage configs and actual run artifacts take precedence if this preparation snapshot later becomes stale.")
            if record["path"].endswith("ollama_cloud30_functional_readiness.json"):
                response = record["data"].get("response", {})
                choices = response.get("choices", [])
                usage = response.get("usage", {})
                try:
                    actual = json.loads(choices[0]["message"]["content"])
                except (KeyError, IndexError, TypeError, ValueError):
                    actual = None
                matched = actual == {"value": 2} and bool(choices) and choices[0].get("finish_reason") != "length"
                actual_usage = bool(usage.get("prompt_tokens", 0) > 0 and usage.get("completion_tokens", 0) > 0)
                doc.para(f"Recorded functional check: requested structured value matched={matched}; positive actual input/output usage={actual_usage}; prompt tokens={usage.get('prompt_tokens', 'unrecorded')}; completion tokens={usage.get('completion_tokens', 'unrecorded')}; elapsed seconds={number(numeric(record['data'], 'elapsed_seconds'))}. This validates this small structured call, not supplier-rule accuracy, inventory performance or full-study throughput.")
            if record["path"].endswith("local_model_resource_preflight.json"):
                preflight = record["data"]
                doc.para(f"Measured resource preflight: passed={preflight.get('passed', 'unrecorded')}; blockers={preflight.get('blockers', [])}. Measurements: {json.dumps(preflight.get('measurement', {}), sort_keys=True)}. Successful-path model-only projection at mean={number(numeric(preflight, 'successful_path_model_only_days_at_mean'))} days, at p95={number(numeric(preflight, 'successful_path_model_only_days_at_p95'))} days. These are development-sample planning estimates, not elapsed full-experiment results; they exclude additional training, optimization, scheduling, retries and reports.")
            if record["path"].endswith("local_model_resource_preflight_incremental.json"):
                preflight = record["data"]
                doc.para(f"Incremental resource evidence: {preflight.get('actual_development_responses', 'unrecorded')} actual development responses; first extraction request={number(numeric(preflight, 'first_extraction_request_seconds'))} seconds; planned successful-path requests before retries={number(numeric(preflight, 'successful_path_request_count_before_retries'), 0)}. The recorded same-latency multiplication is {number(numeric(preflight, 'coarse_same_latency_projection_days'))} days. This is a scale illustration from an initial request, not a representative completion forecast or an executed study duration.")
                for limitation in preflight.get("limitations", []):
                    doc.para("Incremental estimate limit: " + str(limitation))
    else:
        doc.para("No separate functional preflight/readiness JSON has been written at this snapshot. Functional readiness remains unattested here until its actual results appear.")
    chronos = readiness["chronos_metadata"]
    if chronos:
        doc.para(f"Recorded foundation metadata: {chronos.get('model_id', 'unrecorded')} at revision {chronos.get('revision', 'unrecorded')}. Metadata retrieval is not evidence that the model.safetensors download or inference succeeded.")
    if readiness["grounding_benchmarks"]:
        doc.heading("Controlled grounding benchmarks — actual current artifacts")
        doc.para("Incremental and final snapshots from the same development folder can describe the same responses. They are shown as recorded snapshots and are not pooled or counted as independent replications. Retained development configurations with different batch sizes also remain separate from frozen evaluation studies.")
        for benchmark in readiness["grounding_benchmarks"]:
            data = benchmark["data"]
            if not data:
                continue
            doc.para(f"Source: {benchmark['path']}; evidence role={benchmark.get('evidence_role', 'recorded grounding')}; reader mode={data.get('mode', 'local LLM development sample' if data.get('development_only') else 'unrecorded')}; model={data.get('model', 'not recorded')}; model revision={data.get('model_revision', 'not recorded')}; development_only={data.get('development_only', False)}; incremental={data.get('incremental', False)}; complete={data.get('complete', 'not recorded')}; total LLM calls={data.get('llm_calls', 'not recorded')}; errors={data.get('llm_errors', 'not recorded')}; tokens={data.get('tokens', 'not recorded')}. {data.get('warning', data.get('note', ''))}")
            doc.table(["Case / carrier", "Whole set exact", "Tuple precision", "Tuple recall", "False / omitted", "Errors eligible for solver", "Escalated"],
                      [[f"{case.get('case_id', 'development batch')} / {case.get('carrier')}", case.get("whole_set_exact_match"), number(numeric(case, "field_tuple_precision")), number(numeric(case, "field_tuple_recall")), f"{case.get('false_constraints', '—')} / {case.get('omitted_constraints', '—')}", case.get("residual_errors_eligible_for_solver", "—"), case.get("escalated", "—")] for case in data.get("cases", [])],
                      [1.9, .7, .85, .85, .8, .9, .7])
            rule_cases = [case for case in data.get("cases", []) if "exact_rules" in case]
            if rule_cases:
                doc.table(["Case / carrier / batch", "Exact / false / omitted rules", "Calls", "Seconds", "Request result"],
                          [[f"{index + 1} / {case.get('carrier', '—')} / {case.get('batch_size', data.get('document_batch_size', '—'))}",
                            f"{case.get('exact_rules', '—')} / {case.get('false_rules', 'unmeasured')} / {case.get('omitted_rules', '—')}",
                            case.get("calls", "—"), number(numeric(case, "elapsed_seconds")),
                            "request failed" if case.get("error") else "response received; see exact-rule counts"] for index, case in enumerate(rule_cases)],
                          [1.9, 1.6, .5, .7, 2])
                for index, case in enumerate(rule_cases):
                    if case.get("error"):
                        doc.para(f"Development case {index + 1} request error: {case['error']}")
                doc.para("These exact-rule counts and durations come from the recorded development cases. Failed requests can have recorded omissions without a validated returned-rule set; missing false-rule/precision fields remain unmeasured. Serving-model selection uses these development samples, which are excluded from inventory-policy comparisons.")
            measured_cases = [case for case in data.get("cases", []) if case.get("actual_usage")]
            if measured_cases:
                doc.table(["Carrier", "Source docs", "Constraints returned", "Schema valid / finish", "Input / output tokens", "Seconds"],
                          [[case.get("carrier"), case.get("source_documents", "—"), case.get("constraints_returned", "—"), f"{case.get('schema_valid', '—')} / {case.get('finish_reason', '—')}", f"{case['actual_usage'].get('prompt_tokens', '—')} / {case['actual_usage'].get('completion_tokens', '—')}", number(numeric(case, "elapsed_seconds"))] for case in measured_cases],
                          [.8, .6, .9, 1, 1.2, .8])
                doc.para("Schema-valid responses can still omit or misground rules. Missing residual-error/escalation fields remain unmeasured rather than zero. Development samples do not establish a favorable LLM effect or confirmatory full-study performance.")
                if any(case.get("whole_set_exact_match") is False or (case.get("false_constraints") or 0) > 0 or (case.get("omitted_constraints") or 0) > 0 for case in measured_cases):
                    doc.para("The measured development samples above contain actual extraction failures: whole-set mismatches, omissions or false constraints remain errors despite valid JSON and a normal finish reason.")
        doc.para("Deterministic-template results measure the parser control. Controlled LLM corpus results measure that recorded carrier/case set; neither is a validated natural-language supplier population or evidence that pending M5 studies finished.")


def load_dissertation(args, repo):
    alignment_path = args.alignment or repo / "results/run_configs/dissertation_alignment.json"
    alignment = read_json(alignment_path, {})
    text_path = args.dissertation_text or Path(alignment.get("source", {}).get("text_path", "/workspace/tools/revised_dissertation.txt"))
    source_path = args.dissertation or Path("/workspace/attachments/36b83580-a543-4d02-aed3-f0cabd365670/dissertation_revised_business_school.html")
    evidence = {"alignment": alignment, "alignment_path": str(alignment_path), "paths": []}
    if alignment_path.exists():
        evidence["paths"].append(alignment_path)
    if text_path.exists():
        content = text_path.read_bytes()
        LOADED_HASHES[str(text_path)] = hashlib.sha256(content).hexdigest()
        lines = content.decode("utf-8").splitlines()
        wording = {}
        for line in lines:
            match = re.match(r"^(RQ[1-7]|H[1-8])(?:\s+—|\.)", line.strip())
            if match:
                wording[match.group(1)] = line.strip()
        evidence.update({"text_path": str(text_path), "text_sha256": LOADED_HASHES[str(text_path)], "wording": wording})
        evidence["paths"].append(text_path)
    if source_path.exists():
        evidence.update({"source_path": str(source_path), "source_filename": source_path.name, "source_sha256": sha256(source_path)})
        evidence["paths"].append(source_path)
    return evidence


def add_dissertation_alignment(doc, evidence, stages, checks, readiness=None):
    if not evidence.get("wording") and not evidence.get("alignment"):
        return
    doc.heading("Alignment with the user's revised dissertation")
    doc.para(f"Reference document: {evidence.get('source_filename', 'revised dissertation extracted text')}. Uploaded-file SHA-256: {evidence.get('source_sha256', 'not available')}. Extracted-text SHA-256: {evidence.get('text_sha256', 'not available')}. The document supplies the research specification and expected managerial discussion; its expected findings are not results of this execution.")
    doc.para("The user requested the complete experiment and accepted all thirty prepared item-store series for the B9/B10 agent comparison and matched references. A previous ten-series reference or two-series connectivity pilot is a distinct panel, not evidence that the thirty-series comparison has finished. Each stage below must retain its own actual dataset manifest, matched seeds, origins, decision horizon and model digest. This thirty-series panel is still a subset of full M5.")
    live_calls = sum(stage["llm_calls"] for stage in stages)
    control_runs = sum(sum(row["policy"] in {"B1", "B2", "B3", "B4", "D0", "D1"} for row in stage["rows"]) for stage in stages)
    model_blocked = any(stage["status"] == "BLOCKED" and any(policy in {f"B{i}" for i in range(6, 11)} for policy in stage["config"].get("policies", [])) for stage in stages)
    grounding_calls = sum(benchmark["data"].get("llm_calls", sum(bool(case.get("actual_usage")) for case in benchmark["data"].get("cases", []))) for benchmark in (readiness or {}).get("grounding_benchmarks", []))
    agent_status = "PARTIAL" if live_calls or grounding_calls else "BLOCKED" if model_blocked else "UNRUN"
    current_scope = {
        "RQ1": ("PARTIAL" if control_runs else "UNRUN", "Current summaries and forecast holdouts support descriptive cost/service, stockout and bullwhip measurement for the completed controls. Full matched agent-versus-baseline performance remains conditional on completed stage grids."),
        "RQ2": ("PARTIAL" if control_runs else "UNRUN", "Harm, true-constraint violation, reference-deviation and hold counts are available for completed simulations. They do not yet establish an agent gate effect over the complete revised design; direct B10-B9 analysis waits for a full matched grid."),
        "RQ3": (agent_status, "Live extraction and controlled grounding evaluations are required for exact typed-rule accuracy and errors reaching the solver. A model call count alone is not a grounding-accuracy result; template parser controls do not measure an LLM's semantic contribution."),
        "RQ4": (agent_status, "Role, free-form/typed, critic and memory ablations must retain matched tools, panels and autonomy settings. Coordination tokens, calls and latency can be measured after execution. An empty/unapproved memory store cannot establish a memory benefit."),
        "RQ5": ("PARTIAL" if control_runs or live_calls else "UNRUN", "Completed-run logs record violations, LLM/schema errors and fallback decisions. Equivalent-input repetitions, tool-validity analysis and reliability over every planned class remain separate checks; sample safety is not universal reliability."),
        "RQ6": ("PARTIAL" if checks else "UNRUN", "Stored sample replay and trace audit provide technical artifact evidence for their selected decisions. They do not establish causal sensitivity of every cited field, superiority over free-form rationales, or faithfulness of pending agent runs."),
        "RQ7": ("UNRUN", "No participant review-time, accuracy, trust-calibration or workload measurements are present in this automated report. Simulator approval and technical trace audit cannot answer a human-audit question."),
        "H1": ("UNIMPLEMENTED", "There is no LLM-only numerical-action policy: B6 and the multi-agent variants share deterministic tools. The first clause is untestable in the current artifact. Matched optimizer comparison can address part of the clean-state clause, without a predefined equivalence margin proving closeness."),
        "H2": (agent_status, "The matched B8/B10 critic ablation can measure critic effects only after it executes; B9/B10 primarily isolates autonomy, not critic presence. Tail risk, violations, latency and compute must be reported together."),
        "H3": (agent_status, "A matched B7/B10 ablation and grounding/tool-validity outputs are needed. Typed-schema implementation by itself is not evidence of fewer errors or a performance gain."),
        "H4": ("PARTIAL" if control_runs else agent_status, "Completed deterministic gates support descriptive simple-fault checks. B9/B10 isolates gating after the full matched grid. Additional language-model benefit from ambiguous cross-source reconciliation is unestablished when triage cannot apply approved state repairs."),
        "H5": (agent_status, "Measure template/prose and coupled/ambiguous constraint families separately using ground truth. Exact extraction, false constraints, escalation and errors reaching the optimizer need actual controlled outputs; do not inherit historical provider results."),
        "H6": ("PARTIAL" if checks else "UNRUN", "Sample replay/audit has been recorded. Structured-versus-free-form trace comparisons and planned counterfactual/deletion sensitivity must be evaluated separately before this comparative hypothesis is answered."),
        "H7": ("UNRUN", "The reviewer experiment is unexecuted; no human accuracy/time/trust effect may be fabricated from technical traces."),
        "H8": ("PARTIAL" if control_runs else "UNRUN", "Simulation cost, harm and escalation support conditional safety-adjusted utility. The full demand/supply/data-shock, severity and initialization design remains to be completed, and several severity controls may require implementation changes."),
    }
    audit_map = {row.get("id"): row for group in ["research_questions", "hypotheses"] for row in evidence.get("alignment", {}).get(group, [])}
    for group, ids in [("Exact revised research questions and evidence coverage", [f"RQ{i}" for i in range(1, 8)]), ("Exact revised hypotheses and evidence coverage", [f"H{i}" for i in range(1, 9)])]:
        doc.heading(group)
        for identifier in ids:
            if identifier in evidence.get("wording", {}):
                doc.para(evidence["wording"][identifier])
            status, scope = current_scope[identifier]
            doc.para(f"Current evidence scope — {status}: {scope}")
            audit_row = audit_map.get(identifier, {})
            if audit_row.get("required_contrast"):
                doc.para("Implementation audit's required contrast: " + str(audit_row["required_contrast"]))
            if audit_row.get("status"):
                doc.para("Implementation audit snapshot status: " + str(audit_row["status"]) + ". This describes implementation/design coverage at audit time, not an empirical hypothesis verdict; live execution is reported separately.")
            for gap in audit_row.get("gaps", []):
                doc.para("Remaining implementation or design gap: " + str(gap))
    alignment = evidence.get("alignment", {})
    if alignment.get("experiment_groups"):
        doc.heading("Whole-experiment design coverage")
        doc.para("The audit's proposed experiment groups are requirements and plans, not completed runs. Actual execution is counted separately from output artifacts. A completed shortened stage does not silently satisfy rolling origins, severity bands or missing baseline/ablation requirements in the revised specification.")
        if alignment.get("design", {}).get("numeric_note"):
            doc.para("Numerical protocol origin: " + alignment["design"]["numeric_note"])
        def seed_count(row):
            value = row.get("seeds", "—")
            return len(value) if isinstance(value, list) else value
        doc.table(["Planned group", "Policies", "Seeds / origins / days", "Required runs", "Remaining gaps"],
                  [[str(row.get("id", "—")), ", ".join(row["policies"]) if isinstance(row.get("policies"), list) else str(row.get("policies", "—")), f"{seed_count(row)} / {row.get('origins', '—')} / {row.get('days', '—')}", str(row.get("expected_runs", "—")), "; ".join(str(gap) for gap in row.get("gaps", [])) or "See design mapping"] for row in alignment["experiment_groups"]],
                  [1.4, 1.3, 1.2, .7, 2.2])
    for field, title in [("limitations", "Revised-design implementation limits"),
                         ("metrics_gaps", "Metrics and analysis still missing or limited"),
                         ("readiness_gaps", "Readiness gaps recorded by the implementation audit")]:
        if alignment.get(field):
            doc.heading(title)
            for limitation in alignment[field]:
                doc.para("Audit snapshot: " + str(limitation))
    if alignment.get("resource_plan"):
        doc.heading("Compute scope — execution planning, not a throughput finding")
        plan = alignment["resource_plan"]
        doc.para(f"The selected machine has an audited CPU quota of {plan.get('cpu_quota', 'unrecorded')} cores and {plan.get('memory_gib', 'unrecorded')} GiB memory. Parallel workers share those resources; visible CPU count and delegated agents do not create extra inference capacity.")
        for key in ["local_llm_parallel", "call_budget", "whole_protocol_computational_warning"]:
            if plan.get(key):
                doc.para("Planning consideration: " + str(plan[key]))
        doc.para("Candidate configurations remain unregistered until selected and frozen. Their matrix sizes and call budgets are planned exposures, not successful calls, runtime estimates measured on the loaded model, or completed evidence.")
    if alignment:
        doc.code("Revised dissertation implementation/design mapping", alignment)
    doc.heading("Managerial adoption discussion — proposed, not an empirical finding")
    doc.para("The revised business-school dissertation proposes an adoption sequence: establish lineage and deterministic state checks; formalize supplier and assortment constraints; introduce structured traces; use LLMs for document interpretation and anomaly triage; grant bounded autonomy only for decision classes with measured reliability. This sequence is a discussion framework, not measured organizational value, demonstrated ROI, a field deployment, or evidence that reviewers calibrated trust better.")
    doc.para("For a manager, the relevant future comparison includes service and cost alongside harmful executions, holds, resolution delay, review workload, latency, local inference resource use and the residual error that reaches numerical tools. A conservative hold can delay replenishment and carry an operational cost. Decisions about adoption remain conditional on complete matched evidence, validation on the intended retail process and the unexecuted human-audit component.")


class Document:
    def __init__(self, title, out, prefix="M5_experiment_report"):
        self.title = title
        self.prefix = prefix
        self.md = [f"# {title}\n"]
        self.web = [f"<h1>{html.escape(title)}</h1>"]
        self.pdf = []
        self.out = out
        font_dir = Path(matplotlib.get_data_path()) / "fonts/ttf"
        for name, filename in [("M5DejaVu", "DejaVuSans.ttf"), ("M5DejaVu-Bold", "DejaVuSans-Bold.ttf"),
                               ("M5DejaVu-Oblique", "DejaVuSans-Oblique.ttf"), ("M5DejaVu-BoldOblique", "DejaVuSans-BoldOblique.ttf")]:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
        pdfmetrics.registerFontFamily("M5DejaVu", normal="M5DejaVu", bold="M5DejaVu-Bold", italic="M5DejaVu-Oblique", boldItalic="M5DejaVu-BoldOblique")
        self.styles = getSampleStyleSheet()
        for style in self.styles.byName.values():
            if not hasattr(style, "fontName"):
                continue
            previous = style.fontName
            style.fontName = "M5DejaVu-BoldOblique" if "Bold" in previous and "Oblique" in previous else "M5DejaVu-Bold" if "Bold" in previous else "M5DejaVu-Oblique" if "Oblique" in previous or "Italic" in previous else "M5DejaVu"
        for key in ["Normal", "BodyText"]:
            self.styles[key].fontSize = 9
            self.styles[key].leading = 12
        self.pdf.append(Paragraph(html.escape(title), self.styles["Title"]))

    def heading(self, text):
        self.md.append(f"\n## {text}\n")
        self.web.append(f"<h2>{html.escape(text)}</h2>")
        self.pdf.extend([Spacer(1, 10), Paragraph(html.escape(text), self.styles["Heading2"])])

    def para(self, text):
        self.md.append(text + "\n")
        self.web.append(f"<p>{html.escape(text)}</p>")
        self.pdf.extend([Paragraph(html.escape(text), self.styles["BodyText"]), Spacer(1, 6)])

    def table(self, headers, rows, widths=None):
        if not rows:
            self.para("No completed observations are available for this table.")
            return
        rows = [[str(c) for c in row] for row in rows]
        self.md += ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
        self.md += ["| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in row) + " |" for row in rows]
        self.md.append("")
        self.web.append("<div class='tablewrap'><table><thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in rows) + "</tbody></table></div>")
        wrapped = [[Paragraph(html.escape(str(c)), self.styles["Normal"]) for c in row] for row in [headers] + rows]
        if widths:
            total = sum(widths)
            widths = [w / total * 7.05 * inch for w in widths]
        else:
            widths = [7.05 * inch / len(headers)] * len(headers)
        table = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceaf1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor("#8196a4")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        self.pdf.extend([table, Spacer(1, 8)])

    def plot(self, path, caption):
        self.md += [f"![{caption}]({path.name})\n", caption + "\n"]
        encoded = base64.b64encode(path.read_bytes()).decode()
        self.web.append(f"<figure><img src='data:image/png;base64,{encoded}' alt='{html.escape(caption)}'><figcaption>{html.escape(caption)}</figcaption></figure>")
        from PIL import Image as PillowImage
        with PillowImage.open(path) as im:
            width, height = im.size
        scale = min(7.05 * inch / width, 4.4 * inch / height)
        self.pdf.extend([Image(str(path), width=width * scale, height=height * scale),
                         Paragraph(html.escape(caption), self.styles["BodyText"]), Spacer(1, 8)])

    def code(self, title, value):
        text = yaml.safe_dump(value, sort_keys=True)
        self.md.append(f"\n### {title}\n\n```yaml\n{text}```\n")
        self.web.append(f"<details><summary>{html.escape(title)}</summary><pre>{html.escape(text)}</pre></details>")
        # Full configs are preserved in the HTML, Markdown and JSON; PDF has a readable selected snapshot.

    def save(self):
        css = "body{font:16px/1.55 system-ui,sans-serif;color:#163044;max-width:1160px;margin:36px auto;padding:0 24px}h1{font-size:32px}h2{border-bottom:2px solid #dceaf1;padding-bottom:6px;margin-top:36px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #dceaf1}th{background:#dceaf1}tr:nth-child(even){background:#f3f6f8}.tablewrap{overflow:auto}img{max-width:100%}figure{margin:22px 0}figcaption{font-size:13px;color:#526977}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#f3f6f8;padding:16px}details{margin:12px 0}"
        (self.out / f"{self.prefix}.md").write_text("\n".join(self.md))
        (self.out / f"{self.prefix}.html").write_text("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>" + html.escape(self.title) + "</title><style>" + css + "</style><body>" + "\n".join(self.web) + "</body></html>")
        def footer(canvas, doc):
            canvas.setFont("M5DejaVu", 8)
            canvas.drawString(.6 * inch, .35 * inch, "Current M5 experiment artifacts; see snapshot status and limitations.")
            canvas.drawRightString(7.9 * inch, .35 * inch, str(doc.page))
        SimpleDocTemplate(str(self.out / f"{self.prefix}.pdf"), title=self.title,
                          author="Current experiment artifacts", pagesize=(8.5 * inch, 11.7 * inch),
                          leftMargin=.6 * inch, rightMargin=.6 * inch,
                          topMargin=.6 * inch, bottomMargin=.65 * inch).build(self.pdf, onFirstPage=footer, onLaterPages=footer)


def plot_progress(stages, path):
    fig, ax = plt.subplots(figsize=(10, max(2.7, len(stages) * .6 + 1)))
    labels = [s["name"] for s in stages]
    counts = [s["completed"] for s in stages]
    targets = [s["expected"] or max(s["completed"], 1) for s in stages]
    y = range(len(stages))
    ax.barh(y, targets, color="#e5ecf0", label="Configured total")
    ax.barh(y, counts, color="#267899", label="Completed artifacts")
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    for i, s in enumerate(stages):
        target = s["expected"] if s["expected"] is not None else "unconfigured"
        ax.text(targets[i] + max(targets) * .01, i, f"{counts[i]}/{target} ({s['status']})", va="center", fontsize=9)
    ax.set_xlim(0, max(targets or [1]) * 1.7)
    ax.set_xlabel("Policy × scenario × independent seed × origin runs")
    ax.set_title("Execution progress at report generation time")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_grounding_latency(readiness, path):
    observations = []
    for benchmark in readiness["grounding_benchmarks"]:
        if benchmark.get("evidence_role") != "current bounded-study development":
            continue
        data = benchmark["data"]
        model = str(data.get("model", "unrecorded model")).removeprefix("ega-").removesuffix("-sixhour")
        for index, case in enumerate(data.get("cases", [])):
            elapsed = numeric(case, "elapsed_seconds")
            if elapsed is not None:
                batch = case.get("batch_size", data.get("document_batch_size", "unrecorded"))
                observations.append((f"{model} | {case.get('carrier', 'unrecorded')} | batch {batch} | case {index + 1}", elapsed, bool(case.get("error"))))
    if not observations:
        return False
    fig, ax = plt.subplots(figsize=(10, max(3, len(observations) * .43 + 1)))
    ax.barh(range(len(observations)), [row[1] for row in observations],
            color=["#c97836" if row[2] else "#267899" for row in observations])
    ax.set_yticks(range(len(observations)), [row[0] for row in observations], fontsize=8)
    ax.invert_yaxis()
    for index, (_, elapsed, failed) in enumerate(observations):
        ax.text(elapsed + max(row[1] for row in observations) * .02, index,
                f"{elapsed:.1f}s; {'request failed' if failed else 'response received'}", va="center", fontsize=8)
    ax.set_xlim(0, max(row[1] for row in observations) * 1.6)
    ax.set_xlabel("Actual recorded development request time (seconds)")
    ax.set_title("Live grounding development timings; model and batch settings remain separate")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True


def plot_live_grounding(assessment, path):
    """Separate conditional extraction quality from end-to-end document coverage."""
    accuracy, coverage = assessment.get("conditional_grounding", {}), assessment.get("coverage", {})
    if not accuracy or not coverage:
        return False
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    scores = [numeric(accuracy, "tuple_precision"), numeric(accuracy, "tuple_recall")]
    axes[0].barh([0, 1], [score or 0 for score in scores], color=["#267899", "#437d56"])
    axes[0].set_yticks([0, 1], ["Exact tuple precision", "Exact tuple recall"])
    axes[0].set_xlim(0, 1.15)
    for index, score in enumerate(scores):
        if score is not None:
            axes[0].text(score + .02, index, f"{score:.1%}", va="center")
    axes[0].set_title("Quality on actually submitted documents", fontsize=10)
    counts = [coverage.get("distinct_submitted_document_exposures_on_extraction_days", 0), coverage.get("unprocessed_document_exposures_on_extraction_days", 0)]
    axes[1].barh([0, 1], counts, color=["#267899", "#c39d4c"])
    axes[1].set_yticks([0, 1], ["Submitted exposures", "Later unprocessed exposures"])
    axes[1].set_xlim(0, max(counts + [1]) * 1.22)
    for index, count in enumerate(counts):
        axes[1].text(count + max(counts + [1]) * .02, index, str(count), va="center")
    axes[1].set_title("Coverage on seven extraction days", fontsize=10)
    for ax in axes:
        ax.invert_yaxis()
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Actual local-model grounding: conditional quality and early-abort coverage", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True


def plot_tradeoffs(stage, out, image_prefix):
    cells = stage["cells"]
    labels = [f"{cell['policy']} / {dict(derived_field_collapse='collapse', feed_gap='feed gap').get(cell['scenario'], cell['scenario'])} (n={cell['seeds']})" for cell in cells]
    colors_by_policy = {"B1": "#748c9b", "B2": "#c39d4c", "B3": "#267899", "B4": "#437d56", "B9": "#985b7d", "B10": "#735f98"}
    bars = [colors_by_policy.get(cell["policy"], "#267899") for cell in cells]
    plots = []
    for suffix, pairs in [
        ("cost_service", [("mean_cost", "Mean simulated cost"), ("mean_fill_rate", "Mean fill rate")]),
        ("violations_holds", [("hard_violations", "Actual hard-constraint violations (total)"), ("held_decisions", "Held decisions (total)")]),
        ("deviations_execution", [("reference_deviations", "Reference-deviation flags (total)"), ("executed_actions", "Executed decisions (total)")])]:
        fig, axes = plt.subplots(1, 2, figsize=(10.5, max(3.6, len(cells) * .31 + 1.3)), sharey=True)
        for ax, (metric, label) in zip(axes, pairs):
            values = [cell.get(metric) for cell in cells]
            ax.barh(range(len(cells)), [value or 0 for value in values], color=bars)
            ax.set_yticks(range(len(cells)), labels, fontsize=8)
            ax.set_title(label, fontsize=10)
            ax.spines[["top", "right"]].set_visible(False)
            if metric == "mean_fill_rate":
                ax.set_xlim(0, 1.08)
            else:
                ax.set_xlim(0, max([value or 0 for value in values] + [1]) * 1.3)
            for index, value in enumerate(values):
                if value is not None:
                    ax.text(value, index, " " + number(value, 3 if metric.startswith("mean_") else 0), va="center", fontsize=7)
        axes[0].invert_yaxis()
        fig.suptitle(f"{stage['name']}: completed exposure only; {stage['status']}", fontsize=10)
        fig.tight_layout()
        path = out / f"{image_prefix}{stage['name']}_{suffix}.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        plots.append(path)
    return plots


def plot_forecasts(rows, path):
    models = sorted({str(row.get("model")) for row in rows})
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.5))
    for ax, key, title in zip(axes, ["wrmsse", "coverage_95"], ["Subset hierarchical WRMSSE (lower is better)", "95% predictive interval coverage"]):
        values = [mean([numeric(row, key) for row in rows if row.get("model") == model]) for model in models]
        ax.bar(models, values, color="#267899")
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", rotation=20)
        ax.spines[["top", "right"]].set_visible(False)
        if key == "coverage_95":
            ax.axhline(.95, color="#b56640", linestyle="--", linewidth=1, label="Nominal 95%")
            ax.set_ylim(0, 1)
            ax.legend(fontsize=8)
    fig.suptitle("Actual forecast backtests; means across recorded origins, no uncertainty intervals", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_outcomes(stage, path):
    cells = stage["cells"]
    labels = [f"{c['policy']} / {c['scenario']}\nn={c['seeds']} seeds" for c in cells]
    fig, axes = plt.subplots(2, 1, figsize=(10, max(4, len(cells) * .18 + 3)))
    y = list(range(len(cells)))
    axes[0].bar(y, [c["mean_cost"] or 0 for c in cells], color="#267899")
    axes[0].set_ylabel("Mean simulated run cost")
    axes[0].set_title(f"{stage['name']}: completed runs only ({stage['status']})")
    axes[1].bar(y, [c["harmful_executions"] for c in cells], color="#b56640")
    axes[1].set_ylabel("Composite harm flags (total)")
    axes[1].set_xticks(y, labels, rotation=60, ha="right", fontsize=7)
    axes[0].set_xticks([])
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--llm-blocker", default="")
    parser.add_argument("--alignment", type=Path, help="Implementation/design mapping JSON; optional")
    parser.add_argument("--dissertation", type=Path, help="Original uploaded revised dissertation")
    parser.add_argument("--dissertation-text", type=Path, help="Extracted plain text for exact RQ/H wording")
    parser.add_argument("--scope", choices=["full", "six-hour"], default="full")
    parser.add_argument("--protocol-file", type=Path, help="Frozen bounded-study protocol JSON")
    parser.add_argument("--report-prefix", help="Output report filename stem")
    parser.add_argument("--final-snapshot", action="store_true", help="Mark this document final for the bounded cutoff; execution coverage stays factual")
    parser.add_argument("--timezone", default="UTC", help="IANA timezone for displayed snapshot and deadline timestamps (default UTC)")
    args = parser.parse_args()
    try:
        display_zone = ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        parser.error("Unknown IANA display timezone: " + args.timezone)
    repo = args.repo.resolve()
    out = (args.out or repo / "results/report").resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefix = args.report_prefix or ("M5_six_hour_study_report" if args.scope == "six-hour" else "M5_experiment_report")
    if not re.fullmatch(r"[A-Za-z0-9_]+", prefix):
        raise ValueError("Report filename prefix must contain letters, digits or underscores")
    protocol_path = args.protocol_file or repo / "results/run_configs/six_hour_protocol.json"
    bounded_protocol = read_json(protocol_path, {}) if args.scope == "six-hour" else {}
    global ARCHIVE_SHA_CACHE
    archive_cache_path = out / "report_archive_checks.json"
    ARCHIVE_SHA_CACHE = read_json(archive_cache_path, {})
    status_path = args.status_file or repo / "results/run_configs/pipeline_status.json"
    status_doc = read_json(status_path, {})
    metadata = status_doc.get("stages", {})
    candidates = [repo / "configs/main_study_stage1.yaml"] + sorted((repo / "results/run_configs").glob("*.yaml"))
    stages_by_output = {}
    for config_path in candidates:
        config = read_yaml(config_path)
        if "m5" not in str(config.get("dataset", "")).lower() or not config.get("output"):
            continue
        name = Path(config["output"]).name
        stages_by_output[str(config["output"])] = (name, config, config_path)
    # Status explicitly identifies selected stages, including ones not yet configured.
    stages = []
    consumed = set()
    for name, meta in metadata.items():
        if not isinstance(meta, dict):
            continue
        configured_path = meta.get("config_path", meta.get("config"))
        config_path = resolve(configured_path, repo) if configured_path else None
        config = read_yaml(config_path) if config_path and config_path.exists() else {}
        if not config and meta.get("output") in stages_by_output:
            _, config, config_path = stages_by_output[meta["output"]]
        if config and "m5" not in str(config.get("dataset", "")).lower():
            continue
        consumed.add(str(config.get("output", meta.get("output", ""))))
        stages.append(inspect_stage(name, config, config_path, meta, repo))
    for output, (name, config, config_path) in stages_by_output.items():
        if output not in consumed:
            stages.append(inspect_stage(name, config, config_path, {}, repo))
    known_outputs = {resolve(stage["output"], repo).resolve() for stage in stages}
    for manifest_path in sorted((repo / "results").glob("*/analytical_manifest.json")):
        if manifest_path.parent.resolve() not in known_outputs:
            name = manifest_path.parent.name
            config = read_json(manifest_path.parent / "resolved_config.json", {})
            stages.append(inspect_stage(name, config, manifest_path.parent / "resolved_config.json", {"required": False, "output": str(manifest_path.parent)}, repo))
    if not any(any(p in {f"B{i}" for i in range(6, 11)} for p in s["config"].get("policies", [])) for s in stages):
        blocker = args.llm_blocker
        stages.append(inspect_stage("local_ollama_agent_study", {}, None,
                                    {"status": "blocked" if args.llm_blocker else "planned", "blocker": blocker}, repo))
    if args.llm_blocker:
        for stage in stages:
            if any(p in {f"B{i}" for i in range(6, 11)} for p in stage["config"].get("policies", [])) and stage["completed"] < (stage["expected"] or 1):
                stage["blocker"] = args.llm_blocker
                if stage["completed"] == 0:
                    stage["status"] = "BLOCKED"
    stages.sort(key=lambda s: (0 if "smoke" in s["name"] else 1 if "pilot" in s["name"] else 2 if "main" in s["name"] else 3, s["name"]))
    protocol_names = bounded_protocol.get("stage_names", bounded_protocol.get("stages", []))
    if isinstance(protocol_names, dict):
        protocol_names = list(protocol_names)
    protocol_names = set(protocol_names) if isinstance(protocol_names, list) and all(isinstance(name, str) for name in protocol_names) else set()
    if args.scope == "six-hour":
        for stage in stages:
            scope_value = str(metadata.get(stage["name"], {}).get("scope", "")).lower()
            stage["current_scope"] = stage["name"] in protocol_names or "six_hour" in stage["name"] or "sixhour" in stage["name"] or "six-hour" in stage["name"] or scope_value in {"six-hour", "six_hour", "sixhour"}
            if not stage["current_scope"]:
                stage["required"] = False
    else:
        for stage in stages:
            stage["current_scope"] = True
    for analytical in stages:
        if analytical.get("analytical_validation", {}).get("valid") and not analytical["packing_errors"]:
            originals = {Path(path).resolve() for path in analytical["analytical_source_outputs"]}
            for stage in stages:
                if resolve(stage["output"], repo).resolve() in originals:
                    stage["represented_by"] = analytical["name"]
    current_stages = [stage for stage in stages if stage["current_scope"] and not stage.get("represented_by")]
    for stage in current_stages:
        stage["trace_details"] = inspect_trace_details(stage) if args.scope == "six-hour" and stage["completed"] else {}
        stage["historical_windows"] = historical_windows(stage, repo)
    runtime_readiness = load_runtime_readiness(repo, args.scope)
    apply_current_readiness(stages, runtime_readiness)
    for stage in stages:
        stage["direct_b10_b9_comparisons"] = direct_gate_comparison(stage) if args.scope == "full" else []
        stage["exploratory_numeric_intervals"] = exploratory_numeric_intervals(stage) if args.scope == "six-hour" else []
    now = datetime.now(display_zone).isoformat(timespec="seconds")
    git_sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tracked_changes = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    manifests = []
    for manifest_path in sorted((repo / "data/processed").glob("*/manifest.json")):
        manifest = read_json(manifest_path, {})
        if manifest.get("dataset") == "M5" and manifest.get("synthetic") is False:
            manifests.append((manifest_path, manifest))
    execution_protocol_path = repo / "results/run_configs/execution_protocol.json"
    execution_protocol = read_json(execution_protocol_path, {})
    validation_manifest_path = repo / "results/run_configs/validation_manifest.json"
    validation_manifest = read_json(validation_manifest_path, {})
    check_paths = sorted((repo / "results/logs").glob("*replay*.json")) + sorted((repo / "results/logs").glob("*trace_audit*.json"))
    bounded_trace_validation = repo / "results/report/six_hour_trace_validation.json"
    if args.scope == "six-hour" and bounded_trace_validation.exists():
        check_paths.append(bounded_trace_validation)
    checks = {relative(p, repo): read_json(p, {}) for p in check_paths}
    live_assessment_path = repo / "results/report/six_hour_live_grounding_assessment.json"
    live_assessment = read_json(live_assessment_path, {}) if args.scope == "six-hour" else {}
    numerical_audit_path = Path("/workspace/tools/m5_final_numeric_audit.json")
    numerical_audit = read_json(numerical_audit_path, {}) if args.scope == "six-hour" else {}
    packing_validation_path = Path("/workspace/tools/m5_pack_validation.json")
    packing_validation = read_json(packing_validation_path, {})
    archive_reader_validation_path = Path("/workspace/tools/m5_report_archive_reader_validation.json")
    archive_reader_validation = read_json(archive_reader_validation_path, {})
    dissertation = load_dissertation(args, repo)
    forecasts = []
    forecast_paths = sorted((repo / "results").glob("forecast_*.json"))
    for path in forecast_paths:
        recorded = read_json(path, [])
        if isinstance(recorded, list):
            forecasts += [dict(row, source=relative(path, repo), evaluation_role="pre-main-study holdout" if "holdout_" in path.name else "overlapping descriptive backtest") for row in recorded]
    paths = {p for s in stages for p in s["input_paths"]}
    paths.update(forecast_paths)
    paths.update(p for p, _ in manifests)
    paths.add(Path(__file__).resolve())
    paths.update(p for p in [execution_protocol_path, validation_manifest_path] + check_paths if p.exists())
    if live_assessment:
        paths.add(live_assessment_path)
        assessor_path = Path("/workspace/tools/m5_live_grounding_assess.py")
        if assessor_path.exists():
            paths.add(assessor_path)
        assessor_validation_path = Path("/workspace/tools/m5_live_grounding_assess_validation.json")
        if assessor_validation_path.exists():
            paths.add(assessor_validation_path)
    if numerical_audit:
        paths.add(numerical_audit_path)
    paths.update(dissertation["paths"])
    paths.update(runtime_readiness["paths"])
    if args.scope == "six-hour" and protocol_path.exists():
        paths.add(protocol_path)
    if packing_validation_path.exists():
        paths.add(packing_validation_path)
    if archive_reader_validation_path.exists():
        paths.add(archive_reader_validation_path)
    if status_path.exists():
        paths.add(status_path)
    input_inventory = [{"path": relative(p, repo), "sha256": LOADED_HASHES.get(str(p)) or sha256(p)} for p in sorted(paths) if p.exists()]
    required_stages = [s for s in stages if s["required"]]
    agent_stages = [s for s in required_stages if any(p in {f"B{i}" for i in range(6, 11)} for p in s["config"].get("policies", []))]
    completed = sum(s["completed"] for s in current_stages)
    calls = sum(s["llm_calls"] for s in current_stages)
    successful_agent_use = all(all(sum(numeric(row, "tokens") or 0 for row in s["rows"] if row["policy"] == policy) > 0 or sum((numeric(row, "llm_calls") or 0) - (numeric(row, "llm_errors") or 0) for row in s["rows"] if row["policy"] == policy) > 0 for policy in s["config"].get("policies", []) if policy in {f"B{i}" for i in range(6, 11)}) for s in agent_stages)
    overall = "COMPLETE" if required_stages and all(s["status"] == "COMPLETE" and not s["invalid_chains"] and not s["packing_errors"] and s["reported_status"] != "failed" for s in required_stages) and agent_stages and calls > 0 and successful_agent_use else "PARTIAL" if completed or any(s["status"] == "PARTIAL" for s in current_stages) else "BLOCKED" if any(s["status"] == "BLOCKED" for s in required_stages) else "UNRUN"
    title = f"Six-hour M5 study — {'final snapshot ' if args.final_snapshot else ''}{overall}" if args.scope == "six-hour" else f"M5 agentic experiment report — {overall}"
    doc = Document(title, out, prefix)
    doc.para(f"Snapshot generated {now} ({args.timezone}). This report uses current results under this checkout; repository examples and dissertation narrative are not treated as outputs of this execution.")
    doc.para(f"Overall execution status: {overall}. There are {completed} completed current-scope configured runs and {number(calls, 0)} recorded LLM calls in those completed runs. A completed deterministic control is not an LLM agent experiment. This is the latest available report; a PARTIAL or BLOCKED report is not a completed experiment.")
    if args.scope == "six-hour":
        doc.heading("Business results at this snapshot")
        numerical_results = [stage for stage in current_stages if stage["status"] == "COMPLETE" and stage["config"].get("days") == 7 and set(stage["config"].get("policies", [])) == {"B1", "B2", "B3", "B4"}]
        for stage in numerical_results:
            doc.para(f"Completed numerical evidence: {stage['name']}, {stage['completed']} runs, {len(stage['config'].get('seeds', []))} simulation seeds, seven decision days and all thirty selected series. These are simulated operational tradeoffs, not measured retailer outcomes.")
            doc.table(["Policy / scenario", "Mean cost", "Mean fill", "Hard violations", "Holds", "Reference deviations"],
                      [[f"{cell['policy']} / {cell['scenario']}", number(cell["mean_cost"]), number(cell["mean_fill_rate"]), number(cell["hard_violations"], 0), number(cell["held_decisions"], 0), number(cell["reference_deviations"], 0)] for cell in stage["cells"]],
                      [2.3, 1, .8, 1, .8, 1.1])
            contrasts = {(cell["policy"], cell["scenario"]): cell for cell in stage["cells"]}
            if ("B3", "feed_gap") in contrasts and ("B4", "feed_gap") in contrasts:
                b3, b4 = contrasts["B3", "feed_gap"], contrasts["B4", "feed_gap"]
                doc.para(f"In the feed-gap simulation, B3 recorded {number(b3['hard_violations'], 0)} actual hard violations and {number(b3['held_decisions'], 0)} holds; the gated B4 recorded {number(b4['hard_violations'], 0)} hard violations and {number(b4['held_decisions'], 0)} holds. Mean fill was {number(b3['mean_fill_rate'])} for B3 and {number(b4['mean_fill_rate'])} for B4. The gate can reduce execution while changing service and cost. These exploratory observations do not prove long-run superiority or adequate statistical power.")
        live_results = [stage for stage in current_stages if stage["config"].get("llm", {}).get("enabled") and {"B9", "B10"} & set(stage["config"].get("policies", []))]
        for stage in live_results:
            rows = [row for row in stage["rows"] if row["policy"] in {"B9", "B10"}]
            if not rows:
                doc.para(stage["name"] + ": no completed B9/B10 simulation runs are available in this snapshot.")
                continue
            executions = sum(numeric(row, "executed_actions") or 0 for row in rows)
            holds = sum(numeric(row, "held_decisions") or 0 for row in rows)
            doc.para(f"Actual local-model feasibility evidence: {stage['config']['llm'].get('model')}; {len(rows)} completed B9/B10 runs, {number(sum(numeric(row, 'llm_calls') or 0 for row in rows), 0)} recorded calls, {number(executions, 0)} executed decisions and {number(holds, 0)} held decisions. The completed cases contain invalid or incomplete grounding, including recorded dimensional mismatches. Fail-closed validation prevents those invalid extractions from proceeding. An executed LLM replenishment benefit has not been established by these held cases. These findings concern this small local model, serving profile and controlled corpus; they do not generalize to all LLM systems.")
        if live_assessment:
            accuracy = live_assessment.get("conditional_grounding", {})
            coverage = live_assessment.get("coverage", {})
            doc.para(f"Strict post-hoc grounding measured {accuracy.get('exact_tuples', '—')} exact eleven-field tuples among {accuracy.get('returned_unique_tuples', '—')} returned tuples and {accuracy.get('expected_unique_tuples', '—')} actually submitted source rules: precision={number(numeric(accuracy, 'tuple_precision'))}, recall={number(numeric(accuracy, 'tuple_recall'))}. It identified {accuracy.get('false_tuples', '—')} wrong tuples and {accuracy.get('omitted_submitted_tuples', '—')} omitted submitted tuples; the recorded field mismatches were unit errors. Only 16 of 157 available documents were submitted on each of {coverage.get('extraction_decision_days', '—')} extraction days before early abort; later unprocessed documents are coverage gaps. One fault-gated day had no extraction. These are descriptive repeated exposures, not independent grounding trials.")
        doc.para("Initial inventory can satisfy two days of sales even when every replenishment decision is held. Purchase expenditure is charged immediately, terminal stock has no salvage credit, and shortage/replenishment effects beyond the window are omitted. Structured controls can therefore buy inventory for future days while all-held prose cases appear cheaper. Low short-window cost must not be called LLM savings or evidence of equivalent long-run service. Mean inventory, holds and execution are reported alongside cost/fill. The seven-day numerical template grid, two-day prose parser comparators, live model arms and separate two-day structured-rule controls retain their own horizons and carriers.")
        short_cells = [(stage, cell) for stage in current_stages if stage["config"].get("days") == 2 for cell in stage["cells"]]
        if short_cells:
            doc.table(["Two-day stage / policy / scenario", "Cost", "Fill", "Mean inventory", "Exec / held"],
                      [[f"{stage['name']} / {cell['policy']} / {cell['scenario']}", number(cell["mean_cost"]), number(cell["mean_fill_rate"]), number(cell["mean_inventory"]), f"{number(cell['executed_actions'], 0)} / {number(cell['held_decisions'], 0)}"] for stage, cell in short_cells],
                      [3, .85, .6, .85, .9])
        doc.para("Managerial interpretation is conditional: grounding reliability, actual hard violations, holds, service and latency must be assessed together. Historical M5 sales from thirty selected FOODS item-store series are combined with simulated inventory, suppliers and replenishment; no organizational ROI, field deployment or human-review benefit is measured.")
        doc.para("Historical study dates are distinct from cloud execution timestamps: the registered model-training data end on 2016-01-18 (index1815, M5d_1816); numerical decisions cover 2016-02-02 through 2016-02-08 (indices1830–1836, d_1831–d_1837); two-day model/control decisions cover 2016-02-02 through 2016-02-03. The prepared panel's calendar.csv supplies the per-stage mappings below; 2026 timestamps record execution and report preparation.")
        doc.para("Grounding safeguard limit relevant to RQ3/H3: the deployed prose verifier checks source references, entity allowlists, dimensions/ranges, conflicts and required coverage. Full source-value/scope/precedence equality is checked only for the deterministic RULE carrier. Holding the observed unit errors does not prove that every semantically wrong prose field would be caught. The strict inverse-prose assessor is an after-the-fact measurement, not a deployed repair or a hidden deterministic replacement for the model. No model-grounded proposal reached the optimizer in these held live cases.")
        doc.heading("Reduced protocol and six-hour scope")
        if args.final_snapshot:
            doc.para("Document status: final bounded-study snapshot. Execution and missing-data labels remain factual; finalization of this document does not turn unfinished experiments into completed runs or complete the full revised dissertation.")
        doc.para("The user changed the objective to a study bounded to six hours while preserving all thirty prepared M5 item-store series. The long-stage studies are retained as auxiliary history and are not pooled into this study's run count, policy estimates or significance claims. This shortened protocol does not complete the full revised dissertation, thirty-seed confirmatory comparisons, the complete rolling-origin/severity matrix, or the human-audit study.")
        doc.para("This report describes the bounded numerical controls, actual live-model grounding checks, and closed-loop LLM decisions completed within the registered scope. Planned or deadline-interrupted runs remain unrun/partial. There are no paired significance or thirty-seed power claims for this shortened study. Short decision horizons can hide service effects through warmup stock and lead times, so small cost/fill differences must not be generalized to long-run replenishment.")
        if bounded_protocol:
            doc.code("Frozen six-hour study protocol", redact(bounded_protocol))
            for key in ["requested_at_utc", "started_at_utc", "start_utc", "deadline_utc", "deadline_at_utc", "report_cutoff_utc", "report_reserve_start_utc", "job_cutoff_utc", "experiment_cutoff_utc", "report_deadline_utc"]:
                if bounded_protocol.get(key):
                    try:
                        stamp = datetime.fromisoformat(str(bounded_protocol[key]).replace("Z", "+00:00")).astimezone(display_zone).isoformat(timespec="seconds")
                    except ValueError:
                        stamp = str(bounded_protocol[key])
                    doc.para(key.removesuffix("_utc").replace("_", " ") + ": " + stamp + " (" + args.timezone + ").")
            if bounded_protocol.get("limitations"):
                for limitation in bounded_protocol["limitations"]:
                    doc.para("Bounded protocol limit: " + str(limitation))
            numerical = bounded_protocol.get("numerical", {})
            if numerical:
                configured_seeds = numerical.get("seeds", [])
                count = len(configured_seeds) if isinstance(configured_seeds, list) else configured_seeds
                doc.para(f"Frozen numerical subset: policies={numerical.get('policies', [])}; scenarios={numerical.get('scenarios', [])}; seeds={count}; origins={numerical.get('origins', 'unrecorded')}; decision days={numerical.get('days', 'unrecorded')}; configured runs={numerical.get('expected_runs', 'unrecorded')}. All thirty prepared series are retained. Forecast/solver settings are read from each actual run config and are not pooled with the old long-study settings.")
            if bounded_protocol.get("agentic"):
                agentic = bounded_protocol["agentic"]
                doc.para("Frozen live-model subset: " + json.dumps(agentic, sort_keys=True) + ". It uses the original repository FORMAT_CONVENTIONS and the recorded common model digest. The separately tested documented-format variant was not selected for evaluation.")
            if bounded_protocol.get("serving_selection"):
                doc.para("Development selection disclosure: " + json.dumps(bounded_protocol["serving_selection"], sort_keys=True))
            if bounded_protocol.get("fault_timing_note"):
                doc.para("Fault timing: " + str(bounded_protocol["fault_timing_note"]))
            if bounded_protocol.get("structured_reference"):
                doc.para("Separate structured-rule short-window control: " + json.dumps(bounded_protocol["structured_reference"], sort_keys=True))
            if bounded_protocol.get("numerical_extension"):
                doc.para("Numerical extension registration: " + json.dumps(bounded_protocol["numerical_extension"], sort_keys=True) + ". The completed initial cohort was available before extension launch. Expansion was motivated by measured runtime capacity, and the combined analysis remains exploratory rather than a confirmatory dissertation registration.")
        else:
            doc.para("A frozen six-hour protocol JSON has not yet been written. No missing numerical scope is fabricated from the long-study configs.")
    doc.heading("Execution status and remaining work")
    doc.para("COMPLETE means every configured policy/scenario/seed/origin run has a per-run summary and the configured number of daily rows. PARTIAL means execution has started or some runs are complete. BLOCKED records a stated missing prerequisite. UNRUN means no completed run or startup evidence is available. Completion counts are calculated from artifacts, even when pipeline status is stale; completion does not by itself establish audit validity, statistical power, or model quality. Overall execution completion applies to stages marked required; superseded or archived studies retain their actual artifacts separately. Configured-run completion also does not satisfy unimplemented dissertation requirements.")
    doc.table(["Stage", "Status", "Required", "Complete / target", "Decision days", "Policies", "Carrier"],
              [[s["name"], s["status"], "yes" if s["required"] else "no", f"{s['completed']} / {s['expected'] if s['expected'] is not None else 'unconfigured'}", s["config"].get("days", "—"), ", ".join(s["config"].get("policies", [])) or "—", s["config"].get("document_carrier", "template" if s["config"] else "—")] for s in stages],
              [2, .85, .55, .85, .65, 1.2, .75])
    for s in stages:
        if s.get("represented_by"):
            doc.para(f"{s['name']} retains its original phase provenance and is represented in the verified {s['represented_by']} analytical view. Its runs are counted once in report totals and policy summaries.")
        if s.get("analytical_validation", {}).get("valid"):
            doc.para(f"{s['name']} is a verified external-source analytical union, not another experiment. It covers the disjoint original cohorts only after complete source coverage, matching immutable configs/data/environment and exact actual trained states across every merged and worker model. Original run paths and hash-verified archives remain unchanged.")
        if s["blocker"]:
            blocker_label = "Required stage prerequisite/blocker" if s["required"] else "Auxiliary stage's historically reported prerequisite"
            doc.para(f"{s['name']} {blocker_label}: {s['blocker']}")
        for observation in s["readiness_observations"]:
            doc.para(s["name"] + " readiness observation: " + observation)
        if s["reported_status"] != "unreported":
            doc.para(f"{s['name']}: pipeline-reported status={s['reported_status']}; observed artifact status={s['status']}. In-progress run directories without complete summaries: {len(s['partial_run_dirs'])}.")
    image_prefix = prefix + "_" if args.scope == "six-hour" else ""
    progress_path = out / (image_prefix + "execution_progress.png")
    plot_progress(current_stages, progress_path)
    doc.plot(progress_path, "Configured run completion; worker and merged copies of the same run are counted once.")
    add_runtime_readiness(doc, runtime_readiness)
    if args.scope == "six-hour":
        grounding_plot = out / (image_prefix + "grounding_latency.png")
        if plot_grounding_latency(runtime_readiness, grounding_plot):
            doc.plot(grounding_plot, "Actual development extraction timings. Receiving a response does not establish semantic correctness; exact-rule results are reported above. Different models and batch sizes are separate cases, without pooling, extrapolated completion promises or policy-benefit claims.")
        if live_assessment:
            doc.heading("Actual live-model grounding and document coverage")
            accuracy, coverage = live_assessment.get("conditional_grounding", {}), live_assessment.get("coverage", {})
            usage, roles = live_assessment.get("actual_usage_totals", {}), live_assessment.get("role_counts", {})
            validation = live_assessment.get("stage_validation", {})
            error_records = live_assessment.get("llm_errors", [])
            error_count = len(error_records) if isinstance(error_records, list) else error_records
            doc.para(f"The independent captured-request assessment validates the actual {validation.get('validated_runs', '—')}-run grid and {validation.get('decision_days', '—')} decision days, with SQLite chains and selected object hashes verified. There were {live_assessment.get('llm_requests', '—')} recorded requests: {live_assessment.get('supplier_extraction_requests', '—')} supplier extractions and {roles.get('state reconciliation agent', '—')} state triage requests; {usage.get('total_tokens', '—')} tokens ({usage.get('prompt_tokens', '—')} input, {usage.get('completion_tokens', '—')} output), {number(numeric(live_assessment, 'llm_elapsed_seconds'), 1)} seconds summed request time, and {error_count} recorded request errors. API success and schema validity remain distinct from semantic accuracy.")
            doc.para("Expected tuples are recovered only from documents actually present in each captured model request. The assessor authenticates source payload SHA-256, strictly inverts the known public prose renderer and requires exact re-rendering before comparing all eleven constraint fields. It does not recall the model or supply it with labels. Confidence, constraint identifiers and provenance are outside the eleven-field tuple score. Exact precision is exact returned tuples divided by returned unique tuples; recall uses expected actually submitted tuples. Later unprocessed documents contribute to coverage, not the submitted-omission denominator.")
            doc.table(["Conditional grounding measure", "Actual value"],
                      [["Proven submitted / expected tuples", f"{accuracy.get('truth_proven_document_exposures', '—')} / {accuracy.get('expected_unique_tuples', '—')}"],
                       ["Exact / false returned tuples", f"{accuracy.get('exact_tuples', '—')} / {accuracy.get('false_tuples', '—')}"],
                       ["Omitted submitted tuples", accuracy.get("omitted_submitted_tuples", "—")],
                       ["Exact tuple precision / recall", f"{number(numeric(accuracy, 'tuple_precision'), 5)} / {number(numeric(accuracy, 'tuple_recall'), 5)}"],
                       ["Unit mismatches / duplicate / unknown-source extras", f"{accuracy.get('field_mismatch_counts', {}).get('unit', '—')} / {accuracy.get('duplicate_returned_rule_occurrences', '—')} / {accuracy.get('unknown_extra_source_rule_occurrences', '—')}"],
                       ["Unproven sources / invalid response requests", f"{accuracy.get('excluded_unproven_document_exposures', '—')} / {accuracy.get('invalid_response_requests', '—')}"],
                       ["Available / submitted / later unprocessed exposures", f"{coverage.get('available_document_exposures_on_extraction_days', '—')} / {coverage.get('distinct_submitted_document_exposures_on_extraction_days', '—')} / {coverage.get('unprocessed_document_exposures_on_extraction_days', '—')}"],
                       ["Extraction days / days with no extraction", f"{coverage.get('extraction_decision_days', '—')} / {coverage.get('days_without_extraction_requests', '—')}" ]], [4.8, 2.2])
            case_rows = []
            for case in live_assessment.get("decision_cases", []):
                requests = case.get("supplier_request_rows", [])
                exact, false, omitted = (sum(request.get(key, 0) for request in requests) for key in ("exact_tuples", "false_tuples", "omitted_submitted_tuples"))
                case_rows.append([f"{case.get('policy')} / {case.get('scenario')} / {case.get('day')}",
                                  f"{case.get('distinct_source_documents_submitted', 0)} / {case.get('available_source_documents', 0)}", case.get("extraction_requests", 0),
                                  f"{exact} / {false} / {omitted}" if requests else "not assessed: no extraction"])
            doc.table(["Decision case (M5 index)", "Submitted / available", "Calls", "Exact / false / omitted"], case_rows, [2.8, 1.2, .6, 2.4])
            live_plot = out / (image_prefix + "live_grounding_quality_coverage.png")
            if plot_live_grounding(live_assessment, live_plot):
                doc.plot(live_plot, "Captured evaluation requests only. Repeated document exposures are not independent trials; conditional extraction accuracy does not imply full-document coverage or successful replenishment.")
    doc.heading("Data, design and interpretation limits")
    doc.para("M5 supplies historical observed sales, calendar and prices. Sales are used as an exogenous demand proxy and may be censored by historical stockouts; latent demand is not recovered. Inventory, replenishment, supplier documents, lead times, capacity, approval, faults and operational constraints are simulated. Simulated run costs and harm outcomes are not measured retailer operations.")
    doc.para("The prepared data are selected panels, not all 30,490 bottom-level M5 series or the official competition evaluation. Fault rates are synthetic and uncalibrated unless a configuration explicitly records calibration. Simulated delayed oracle approval is a reviewer model, not a human audit study. Findings are conditional on this panel, window, solver, forecast training, fault definitions and approval model.")
    doc.table(["Prepared panel", "Series", "Historical days", "Selection", "Synthetic sales?"],
              [[relative(p.parent, repo), m.get("series", "—"), m.get("days", "—"), json.dumps(m.get("selection", {}), sort_keys=True), m.get("synthetic")] for p, m in manifests],
              [1.5, .5, .7, 3.5, .7])
    doc.para(("The archived main stage-1 design" if args.scope == "six-hour" else "The main stage-1 design") + " requires 480 runs: four deterministic policies × four fault scenarios × thirty independent seeds × one origin. It uses 28 decision days per run. The shortened study has its own registered seed count and horizon. Other stages retain their own panel, carrier and horizon; their cost totals must not be pooled as interchangeable replications. The remaining scenarios and any policies absent from registered configs are unrun in this report.")
    doc.table(["Policy", "Actual architecture"], [[p, POLICIES.get(p, "See resolved configuration")] for p in sorted({p for s in stages for p in s["config"].get("policies", [])})], [1, 6])
    doc.para("The native deep model is a trained GRU with a negative-binomial likelihood, not an exact DeepAR or TFT reproduction. LLM roles share deterministic numerical tools and schema validation. LLM calls, errors and explicit fallback decisions are reported separately; a held decision or deterministic fallback does not prove successful semantic reasoning. A seasonal forecast override changes the baseline and must be read in that stage's config.")
    if args.scope == "full":
        add_dissertation_alignment(doc, dissertation, stages, checks, runtime_readiness)
    else:
        doc.heading("Revised dissertation coverage under the reduced study")
        doc.para(f"Source: {dissertation.get('source_filename', 'unavailable')}; SHA-256: {dissertation.get('source_sha256', 'unavailable')}. The short study supplies descriptive evidence relevant to performance, grounding, safety flags and technical auditability. It does not answer the full architecture/memory, severity, equivalent-run, human-audit or universal-reliability hypotheses. No LLM-only numerical-action arm is implemented. Managerial staged adoption remains discussion, not an empirical organizational outcome.")
        doc.para("Managerial discussion: a staged rollout would first establish sales-data lineage and deterministic checks, then introduce structured supplier-rule interpretation and auditable traces, and grant bounded autonomy only where matched validation demonstrates adequate reliability. These are proposed adoption conditions. This study does not measure organizational ROI, real reviewer workload, calibrated human trust or field service improvements.")
    doc.heading("Forecast backtests")
    if args.scope == "six-hour":
        doc.para("These are supplementary previously generated forecast backtests, not additional runs completed inside the six-hour budget. They do not establish that every earlier forecast-scoring hyperparameter matches the reduced study; each current simulation's resolved configuration is the authority. They are shown separately from current-scope outcome counts and are not used here for model selection or confirmatory inference.")
    doc.para("Backtests below come from results/forecast_*.json. Training ends before each recorded test origin. Preferred holdouts at origins 1760/1788 end by index 1815, before main-study warmup at 1816. Earlier descriptive backtests at 1800/1828 overlap the main-study window and must not be used for model selection. No model or gate settings were retuned on those evaluation scores. WRMSSE, weighted scaled pinball and CRPS are scores for the selected hierarchy; full_m5_shape=false means they are not full official M5 benchmark results. Forecast accuracy alone does not establish replenishment quality or an LLM effect.")
    for role in ["pre-main-study holdout", "overlapping descriptive backtest"]:
        role_rows = [r for r in forecasts if r["evaluation_role"] == role]
        if role_rows:
            doc.heading("Forecast scores — " + role)
            doc.table(["Model", "Origin / train end", "Nodes", "WRMSSE", "Scaled pinball", "CRPS", "95% coverage"],
                      [[r.get("model"), f"{r.get('origin')} / {r.get('training_end')}", r.get("nodes"), number(numeric(r, "wrmsse")), number(numeric(r, "weighted_scaled_pinball")), number(numeric(r, "crps")), number(numeric(r, "coverage_95"))] for r in role_rows],
                      [1.1, 1.2, .6, .8, .9, .7, .9])
    if forecasts:
        forecast_plot = out / (image_prefix + "forecast_backtests.png")
        plotted = [r for r in forecasts if r["evaluation_role"] == "pre-main-study holdout"] or forecasts
        plot_forecasts(plotted, forecast_plot)
        doc.plot(forecast_plot, "Means over the preferred nonoverlapping holdout origins when available. No confidence intervals or statistical significance claims are inferred from these origins.")
    doc.heading("Observed simulation outcomes")
    doc.para("Tables include completed runs only, separated by stage and policy/scenario. n is the number of distinct independent seeds; rolling origins are averaged within seed for reported means. The repository's harmful_executions endpoint is a composite flag for true-constraint violations or material action deviation from a same-forecast clean-evidence MILP reference. The code does not require a fault or demonstrate that corrupted evidence caused the deviation. Legitimate classical policies can therefore receive reference-deviation flags in clean normal runs. Composite flags must not all be interpreted as unsafe or corruption-caused orders; true violations and reference deviations are reported separately. Hard violations evaluate committed plans against the simulator's hidden true planning problem. The simulator can clamp physical transfers to available stock, so a plan violation does not imply negative physical inventory. Totals depend on completed exposure.")
    if dissertation.get("alignment", {}).get("harm_definition_caveat"):
        doc.para("Implementation audit's harm-definition caveat: " + str(dissertation["alignment"]["harm_definition_caveat"]))
    doc.para("Partial cells can be selected by execution order and are unsuitable for policy ranking or confirmatory inference. This report makes no claim of statistical power, equivalence, significance, or treatment benefit from partial/pilot data. The repository's thirty-seed requirement is a protocol minimum, not proof of adequate power. Zero observed harms is not a universal safety guarantee.")
    for s in current_stages:
        doc.heading(s["name"] + " — " + s["status"])
        config = s["config"]
        panel = s["run_recorded_data"]
        doc.para(f"Output: {s['output']}; config: {s['config_path'] or 'not available'}; dataset: {config.get('dataset', 'not configured')}; series attested by completed-run manifest: {panel.get('series', 'no completed-run manifest yet')}. Seeds configured: {len(config.get('seeds', []))}; origins: {config.get('origins', 1) if config else '—'}; start index: {config.get('start_day', '—')}; warmup: {config.get('warmup_days', '—')}; decision days: {config.get('days', '—')}; approval: {config.get('approval_mode', 'default')} with delay {config.get('approval_delay', 'default')}; forecast override: {config.get('forecast_override') or 'none recorded'}. M5 index 0 corresponds to d_1.")
        for window in s.get("historical_windows", []):
            doc.para(f"Historical origin {window['origin']}: training data end {window['training_end_date']} at index{window['training_end_index']} (d_{window['training_end_index'] + 1}); decisions {window['decision_start_date']} to {window['decision_end_date']} at indices{window['decision_start_index']}–{window['decision_end_index']} (d_{window['decision_start_index'] + 1}–d_{window['decision_end_index'] + 1}). Source: {window['calendar_source']}.")
        if config.get("days") == 2 and config.get("document_carrier") == "prose" and {"B3", "B4"} & set(config.get("policies", [])):
            doc.para("B3/B4 in this prose stage are intentional deterministic-parser comparators. The parser requires the structured RULE carrier and recognizes no rules in controlled prose, so missing required constraint coverage causes holds. They are not structured-rule oracle benchmarks. Separate registered two-day template controls are shown under their own stage; the seven-day numerical template costs are not pooled into this comparison.")
        doc.table(["Policy / scenario", "n seeds / runs", "Mean cost", "Mean fill", "Harm total", "True violation / ref deviation", "Holds total"],
                  [[f"{c['policy']} / {c['scenario']}", f"{c['seeds']} / {c['runs']}", number(c["mean_cost"]), number(c["mean_fill_rate"]), number(c["harmful_executions"], 0), f"{number(c['violation_executions'], 0)} / {number(c['reference_deviations'], 0)}", number(c["held_decisions"], 0)] for c in s["cells"]],
                  [2.2, .85, .85, .7, .7, 1.1, .7])
        doc.table(["Policy / scenario", "LLM calls", "LLM errors", "Fallback decisions"],
                  [[f"{c['policy']} / {c['scenario']}", number(c["llm_calls"], 0), number(c["llm_errors"], 0), number(c["fallback_decisions"], 0)] for c in s["cells"]], [3, 1, 1, 1])
        doc.table(["Policy / scenario", "Cycle service", "Stockout rate", "Bullwhip", "Mean inventory", "Inventory turns"],
                  [[f"{c['policy']} / {c['scenario']}", number(c["mean_cycle_service_level"]), number(c["mean_stockout_rate"]), number(c["mean_bullwhip"]), number(c["mean_inventory"]), number(c["mean_inventory_turns_window"])] for c in s["cells"]],
                  [2.2, .9, .9, .8, 1, 1])
        doc.para(f"Completed-run recorded tokens={number(s['tokens'], 0)}; LLM calls={number(s['llm_calls'], 0)}; LLM errors={number(s['llm_errors'], 0)}; fallback decisions={number(s['fallbacks'], 0)}; invalid audit chains={s['invalid_chains']}. Counts exclude unfinished runs. Local-model tokens are not assigned a fabricated dollar value.")
        details = s.get("trace_details", {})
        solvers = [row for row in details.get("solver_diagnostics", []) if row["policy"] in {"B3", "B4", "B9", "B10"}]
        if solvers:
            doc.heading(s["name"] + " actual proposal-solver diagnostics")
            doc.table(["Policy / scenario", "MILP attempts", "Feasible / optimal", "Time-limit incumbent", "Mean / max gap", "Mean seconds"],
                      [[f"{row['policy']} / {row['scenario']}", row["milp_attempts"], f"{row['feasible']} / {row['optimal']}", row["time_limit_incumbents"], f"{number(row['mean_reported_gap'], 5)} / {number(row['max_reported_gap'], 5)}", number(row["mean_reported_seconds"])] for row in solvers],
                      [2.1, .7, 1, 1, 1.3, .8])
            doc.para("These counts read every available completed-run proposal trace, including verified ZIP objects. A feasible incumbent is not necessarily optimal. Gaps are reported relative fractions (0.001 means 0.1%) over proposals that report a finite gap; missing gaps are not zero. The five-second solver limit can select different incumbents and affect cost comparisons. Held decisions can have solver status not_run; solver feasibility does not establish that a proposal was executed or safe under hidden simulator truth.")
        examples = details.get("held_trace_examples", [])
        if examples and config.get("days") == 2:
            doc.table(["Recorded held case", "Solver status", "First dimensional mismatch / reason excerpt"],
                      [[f"{case['policy']} / {case['scenario']} / day {case['day']}", case["solver_status"], case["first_recorded_dimensional_mismatch"] or case["reason_excerpt"][:170]] for case in examples[:16]],
                      [2, .9, 4.1])
            doc.para("Dimensional mismatch is a specific invalid supplied rule. Missing-required-field messages can also reflect documents never processed after early abort; they are not all model extraction omissions. Submitted-document grounding accuracy is evaluated only against captured input batches, with unprocessed coverage shown separately. Item aliases are permitted by verification; a dropped store suffix is a wrong tuple/scope, not automatically an unknown-entity runtime error.")
        for observation in details.get("errors", []):
            doc.para("Trace-detail limitation: " + observation)
        if s["study_summary"].get("results"):
            doc.para("The repository also wrote study_summary.json with replication-level cost/CVaR and utility. It is preserved in report_data.json. It may lag live worker results; this report's tables are refreshed from complete per-run artifacts. Run-level daily CVaR is not substituted for replication-level tail risk.")
        if s["cells"] and len(s["cells"]) <= 24:
            if args.scope == "six-hour":
                for outcome_path in plot_tradeoffs(s, out, image_prefix):
                    doc.plot(outcome_path, "Descriptive simulated tradeoffs at the completed exposure (n is simulation seeds). Actual hard violations, holds, reference deviations and executed decisions remain distinct endpoints. Short-window inventory accounting and incomplete cells limit policy comparisons; no LLM savings or significance is inferred.")
            else:
                outcome_path = out / f"{image_prefix}{s['name']}_outcomes.png"
                plot_outcomes(s, outcome_path)
                doc.plot(outcome_path, "Descriptive simulated outcomes from completed cells; exposure and panel differ across stages. The harmful execution count combines distinct mechanisms detailed in the table.")
    doc.heading("Descriptive analysis only" if args.scope == "six-hour" else "Paired inference — complete thirty-seed grids only")
    if args.scope == "six-hour":
        doc.para("No significance tests or confirmatory hypothesis decisions are generated for the six-hour scope. Run and seed counts are shown as actually completed. Grounding sample proportions are descriptive, with no independence or power claim; equal seeds match random streams but do not turn a small pilot into a confirmatory study. Earlier long-study paired comparisons are preserved in their original report and are excluded here.")
        eligible = [stage for stage in current_stages if stage["exploratory_numeric_intervals"]]
        if not eligible:
            doc.para("Exploratory thirty-seed numerical intervals remain pending. They require the entire disjoint 360-run grid plus original-source, configuration, packing and every-worker trained-model equality proof; partial extension data are not eligible.")
        for stage in eligible:
            doc.para("The numerical extension was registered after the initial completed cohort was available and was justified by runtime capacity, not as a confirmatory dissertation design. The fixed B4-minus-B3 cost/fill/actual-hard-violation intervals below are explicitly exploratory: thirty matched simulation seeds, one origin, seven days, 5,000 paired percentile bootstrap resamples with seed42 and unadjusted 95% intervals. No p-values, significance-driven superiority or statistical-power claims are made. These intervals condition on this panel and fixed trained forecast, and do not establish zero-event safety, equivalence or external validity.")
            doc.table(["Scenario", "Metric", "Pairs", "B4 minus B3 mean", "Exploratory 95% interval"],
                      [[row["scenario"], row["metric"], row["pairs"], number(row["mean_difference"], 5), f"[{number(row['ci_low'], 5)}, {number(row['ci_high'], 5)}]"] for row in stage["exploratory_numeric_intervals"]],
                      [1.6, 1.2, .55, 1.45, 2.1])
    else:
        doc.para("Inference remains pending for partial studies and is withheld for pilots with fewer than thirty configured independent seeds. For complete grids, repository paired_comparisons.csv uses per-seed origin averages, 5,000 paired bootstrap resamples (seed 42), unadjusted 95% intervals, Wilcoxon signed-rank p-values and Holm adjustment over the repository's within-study comparison family. These intervals do not establish statistical power or equivalence.")
        doc.para("The frozen direct gate contrast is B10 minus B9 for cost, fill_rate and harmful_executions, across all scenarios configured in the local agent study. It uses the same paired bootstrap/Wilcoxon method after every configured seed and origin completes. Holm adjusts that contrast's fixed metric × scenario family separately from the repository's first-policy-reference family. Negative cost/harm differences favor B10; positive fill differences favor B10. Reported 95% bootstrap intervals are not adjusted for multiplicity. No significance is computed here from partial data.")
    for stage in (stages if args.scope == "full" else []):
        if len(stage["config"].get("seeds", [])) < 30:
            continue
        doc.heading(stage["name"] + " paired comparisons")
        if stage["status"] != "COMPLETE":
            doc.para(f"Pending: {stage['completed']}/{stage['expected']} runs complete. No paired significance table is generated for this incomplete grid.")
            continue
        comparisons = [row for row in stage["paired_comparisons"] if (numeric(row, "n_pairs") or 0) >= 30]
        if not comparisons:
            doc.para("Repository paired comparison table is pending final consolidation or contains no complete thirty-seed comparisons.")
        if comparisons:
            doc.para("Repository reference comparisons (policy minus reference):")
            doc.table(["Scenario / contrast", "Metric", "Pairs", "Mean difference", "95% bootstrap CI", "Holm p"],
                      [[f"{r['scenario']} / {r['policy']}-{r['reference']}", r["metric"], number(numeric(r, "n_pairs"), 0), number(numeric(r, "mean_difference")), f"[{number(numeric(r, 'ci_low'))}, {number(numeric(r, 'ci_high'))}]", number(numeric(r, "holm_adjusted_wilcoxon_p"), 5)] for r in comparisons],
                      [2, 1.25, .5, .85, 1.15, .7])
        if stage["direct_b10_b9_comparisons"]:
            doc.para("Direct B10-B9 gate contrast; separate Holm family across the frozen three metrics and configured scenarios:")
            doc.table(["Scenario", "Metric", "Pairs", "Mean difference", "95% bootstrap CI", "Holm p"],
                      [[r["scenario"], r["metric"], r["n_pairs"], number(r["mean_difference"]), f"[{number(r['ci_low'])}, {number(r['ci_high'])}]", number(r["holm_adjusted_wilcoxon_p"], 5)] for r in stage["direct_b10_b9_comparisons"]],
                      [1.4, 1.4, .5, .9, 1.2, .7])
    doc.heading("Validation and reproducibility checks")
    if numerical_audit:
        totals = numerical_audit.get("artifact_totals", {})
        doc.para(f"Independent final numerical source audit: valid={numerical_audit.get('valid')}, verified at {numerical_audit.get('verified_at_utc')}. It checked {totals.get('run_count', '—')} original source runs, {totals.get('trace_count', '—')} traces, {totals.get('sqlite_events', '—')} SQLite chain events and {totals.get('original_objects', '—')} original objects. Exact disjoint coverage, immutable source hashes, all-worker trained-model equality and every archive entry's bytes/hash/size were verified. No original run manifests were cloned. This establishes source and artifact integrity, not causal grounding faithfulness or treatment superiority.")
        doc.para(f"Lossless verified archives occupy {totals.get('archive_bytes', '—')} bytes for {totals.get('original_object_bytes', '—')} bytes of original objects. {totals.get('current_recoverably_removed_objects', '—')} currently removed loose objects remain recoverable; packing states at audit time: {json.dumps(numerical_audit.get('packing_states', {}), sort_keys=True)}. Full replay tools need a restore unless they implement the verified ZIP reader. The standalone audit and its SHA-256 are included in the report input inventory.")
    if validation_manifest:
        test_result = validation_manifest.get("pytest", {})
        if test_result:
            doc.para(f"Recorded existing test-suite validation: passed={test_result.get('passed', '—')}, failed={test_result.get('failed', '—')}, skipped={test_result.get('skipped', '—')}. Skip reason: {test_result.get('skip_reason', 'not recorded')}. This is the recorded validation manifest; report generation does not rerun the suite.")
        if validation_manifest.get("dataset_acquisition"):
            doc.para("Dataset acquisition provenance: " + validation_manifest["dataset_acquisition"])
        if validation_manifest.get("ollama"):
            doc.para("Local Ollama recorded setup: " + json.dumps(validation_manifest["ollama"], sort_keys=True))
    for name, check in checks.items():
        if not check:
            continue
        if name.endswith("six_hour_trace_validation.json"):
            doc.para("Selected six-hour replay/faithfulness evidence: " + str(check.get("scope", "unrecorded scope")) + ". " + str(check.get("limitation", "")))
            doc.table(["Selected policy / day", "Replay result", "Chain / state match", "Completeness", "Consumption precision / recall"],
                      [[f"{case['policy']} / {case['day']}", case["replay"].get("replay_status"), f"{case['replay'].get('chain_valid')} / {case['replay'].get('state_certificate_matches')}", number(numeric(case.get("trace_audit", {}), "completeness")), f"{number(numeric(case.get('trace_audit', {}), 'consumption_precision'))} / {number(numeric(case.get('trace_audit', {}), 'consumption_recall'))}"] for case in check.get("results", [])],
                      [1.2, 2.2, 1, .8, 1.8])
            doc.para("The B3 feed-gap day1833 case reproduces its recorded observed problem/action/hash while the simulator daily file records a hard violation of the committed plan. An empty independent_violations list against the observed planning problem is not proof of safety under hidden simulator truth. Ground truth is stored after the decision inside reader.load(trace['evaluation'])['true_problem'], outside trace.references; it is distinct from the observed problem and was not supplied to the model. Independent checks of that post-decision truth are preserved in this selected audit artifact. Physical transfers can be clamped to available stock, so a committed-plan violation is not a negative-inventory claim. The B4 hold and two selected live B10 collapse holds reproduce fail-closed behavior. These four deliberately selected cases are not a random sample or full exact-action replay audit. Consumption scores below one remain reported; structural deletion of a required forecast blocks reconstruction but does not establish semantic context faithfulness or causal importance.")
            doc.code(name + " full selected evidence", check)
            continue
        doc.para(name + ": " + json.dumps(check, sort_keys=True))
    doc.para("Sample replay and trace-audit results validate their selected recorded decisions; they are not audits of every pending study run or re-executions of an LLM. Live functional and grounding validation are reported separately from these cached replay checks.")
    doc.heading("Reproducibility and artifact provenance")
    inventory_filename = "report_input_hashes.json" if args.scope == "full" else prefix + "_input_hashes.json"
    doc.para(f"Current checkout commit: {git_sha}. Tracked working-tree changes at report time: {'present' if tracked_changes else 'none'}. This attests the current checkout only; original per-run manifests do not necessarily contain a code SHA. Run configuration, environment and data evidence are taken from their actual artifacts. {inventory_filename} records SHA-256 for every input file used by this report.")
    if execution_protocol:
        protocol_role = "Retained earlier launch protocol" if args.scope == "six-hour" else "Launch protocol"
        doc.para(f"{protocol_role} recorded code commit: {execution_protocol.get('code_commit', 'unrecorded')}; model: {execution_protocol.get('model', 'unrecorded')}; model revision: {execution_protocol.get('model_revision', 'unrecorded')}. Models selected for the bounded study are identified separately in their current identity and frozen run configs. Findings from earlier local or historical hosted models cannot be inherited by a changed-model run.")
        for limitation in execution_protocol.get("limitations", []):
            doc.para("Launch protocol's recorded scope: " + limitation + " Current required/auxiliary stage settings in the execution table take precedence if the registered scope has since expanded.")
        doc.code("Execution protocol", redact(execution_protocol))
    doc.table(["Raw M5 source", "SHA-256 recorded by preparation manifest"],
              sorted({(name, digest) for _, manifest in manifests for name, digest in manifest.get("raw_sha256", {}).items()}), [1.5, 5.5])
    doc.para("The raw-source hashes above are recorded by the prepared-data manifests; report generation does not independently rehash large raw files. Per-panel catalog hashes and complete safe config snapshots are included in the HTML/Markdown and report_data.json. The input hash inventory permits detecting changes between report snapshots.")
    doc.heading("Lossless object packing and full-trace access")
    packing_stages = [stage for stage in stages if not stage.get("represented_by")]
    packed_runs = list({record["run"]: record for stage in packing_stages for record in stage["packing"]}.values())
    doc.para(f"Current configured run artifacts with recognized packing manifests: {len(packed_runs)}. Packing stores the full original content-addressed JSON object inventory in artifacts/objects.zip and keeps the first three trace/certificate/proposal objects loose for standard reports. Missing loose copies of archived objects are not missing data when the inventory, archive and provenance verify. Summaries, daily rows, trace indices and the SQLite audit chain remain separate artifacts.")
    if packed_runs:
        doc.table(["Stage", "Packed/restored runs", "Trace decisions available", "Loose trace decisions", "ZIP logical bytes"],
                  [[stage["name"], len(stage["packing"]), sum(record["trace_decisions"] for record in stage["packing"]), sum(record["loose_trace_decisions"] for record in stage["packing"]), number(sum(record["archive_bytes"] for record in stage["packing"]), 0)] for stage in packing_stages if stage["packing"]],
                  [2.2, 1, 1.2, 1.1, 1.5])
        doc.para("The report checks current archive SHA/size, exact ZIP-member inventory, original inventory hash and unchanged run provenance. Archive SHA checks are reused only for the same file identity, size, modification time and expected checksum. Packing records attest byte-by-byte verification of original objects and the actual audit chain before removal. Full trace indices remain counted even when only three trace objects are loose.")
    if packing_validation:
        doc.para(f"Packing helper validation used a copied fixture, not experiment-output modification: original objects={packing_validation.get('original_objects', 'unrecorded')}; retained after packing={packing_validation.get('retained_after_pack', 'unrecorded')}; archive bytes={packing_validation.get('archive_bytes', 'unrecorded')}; actual outputs modified={packing_validation.get('actual_experiment_outputs_modified', 'unrecorded')}. These helper checks do not imply that all real study runs have been packed or independently audited.")
    if archive_reader_validation:
        doc.para(f"This report's selected-object ZIP reader was checked on a copied fixture: archive/loose JSON equality={archive_reader_validation.get('archive_and_loose_equal')}; unknown reference refused={archive_reader_validation.get('unknown_reference_refused')}; whole-run restoration performed by that check={archive_reader_validation.get('whole_run_restored_by_test')}; actual experiment outputs modified={archive_reader_validation.get('actual_experiment_outputs_modified')}.")
    doc.para("Selected JSON can be read directly with this generator's PackedArtifactReader, which validates the requested object's original SHA-256 and byte length without whole-run restoration. Existing full replay, audit, grounding-artifact inspection and human-packet tools need restoration unless they explicitly use such a ZIP reader. Restore the CURRENT run directory with /workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_pack_artifacts.py --restore <CURRENT_RUN_DIRECTORY>; use the current merged location rather than a former worker path. This report performs no restoration or packing.")
    doc.table(["Stage", "Input config SHA-256"], [[s["name"], s["config_sha256"] or "Unavailable"] for s in stages], [1.7, 5.3])
    for s in stages:
        if s["config"]:
            doc.code(s["name"] + " input configuration", s["config"])
        if s["resolved_config"]:
            doc.code(s["name"] + " resolved configuration (observed output/first worker)", s["resolved_config"])
        if s["environment"]:
            doc.code(s["name"] + " recorded runtime packages", s["environment"])
    for p, manifest in manifests:
        doc.code(relative(p, repo), manifest)
    if WARNINGS:
        doc.heading("Artifact validation observations")
        for warning in WARNINGS:
            doc.para(warning)
    doc.heading("Refresh and completion criteria")
    refresh_command = ".venv/bin/python results/report/generate_report.py" + (" --scope six-hour" if args.scope == "six-hour" else "")
    doc.para(f"Refresh this report after workers complete or readiness changes using {refresh_command} from the repository root. The generator launches no experiments. Completed configured execution requires actual run artifacts and separately reviewed audit/error outcomes. A blocked or partial snapshot remains labeled as such; the six-hour subset does not complete unimplemented dissertation requirements.")
    doc.save()
    public_stages = [{k: v for k, v in s.items() if k != "input_paths"} for s in stages]
    data = {"generated_at": now, "overall_status": overall, "scope": args.scope,
            "display_timezone": args.timezone,
            "final_snapshot": args.final_snapshot,
            "bounded_protocol": redact(bounded_protocol), "checkout_sha": git_sha,
            "tracked_changes": bool(tracked_changes), "stages": public_stages,
            "forecast_backtests": forecasts,
            "execution_protocol": redact(execution_protocol),
            "runtime_readiness": {key: value for key, value in runtime_readiness.items() if key != "paths"},
            "packing_helper_validation": packing_validation,
            "archive_reader_validation": archive_reader_validation,
            "validation_manifest": redact(validation_manifest), "sample_checks": checks,
            "live_grounding_assessment": live_assessment, "final_numeric_audit": numerical_audit,
            "dissertation_alignment": {key: value for key, value in dissertation.items() if key != "paths"},
            "prepared_data": [{"path": relative(p, repo), "manifest": m} for p, m in manifests],
            "warnings": WARNINGS}
    data_name = "report_data.json" if args.scope == "full" else prefix + "_data.json"
    hash_name = "report_input_hashes.json" if args.scope == "full" else prefix + "_input_hashes.json"
    (out / data_name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (out / hash_name).write_text(json.dumps({"generated_at": now, "inputs": input_inventory}, indent=2) + "\n")
    archive_cache_path.write_text(json.dumps(ARCHIVE_SHA_CACHE, sort_keys=True) + "\n")
    print(json.dumps({"overall_status": overall, "completed_runs": completed,
                      "llm_calls": calls, "output": str(out),
                      "stages": [{"name": s["name"], "status": s["status"], "complete": s["completed"], "target": s["expected"]} for s in stages]}))


if __name__ == "__main__":
    main()
