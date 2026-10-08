#!/usr/bin/env python3
"""Validate an external-source M5 analytical view without altering its sources."""
from __future__ import annotations

import csv
import itertools
import json
from pathlib import Path

from m5_training_equivalence import canonical_hash, file_hash, validate_training_equivalence


def config_projection(config):
    return {key: value for key, value in config.items() if key not in {"output", "seeds"}}


def keys(config):
    return set(itertools.product(config["policies"], config["scenarios"], map(int, config["seeds"]), range(int(config["origins"]))))


def validate_analytical_manifest(output, repo=Path("/workspace/MasterDissertation")):
    output, repo = Path(output).resolve(), Path(repo).resolve()
    inputs = set()
    result = {"valid": False, "complete": False, "errors": [], "rows": [], "sources": [],
              "config": {}, "manifest": {}, "training_equivalence": {}, "input_paths": inputs,
              "run_paths": [], "recorded_data": {}}
    def resolve(value):
        path = Path(value)
        return path.resolve() if path.is_absolute() else (repo / path).resolve()
    def read(path):
        inputs.add(path)
        return json.loads(path.read_text())
    def check_hash(path, expected):
        if not isinstance(expected, str) or len(expected) != 64 or path.is_symlink() or file_hash(path) != expected:
            raise ValueError(f"Missing/mismatched original-source SHA-256: {path}")
        inputs.add(path)
    try:
        manifest = read(output / "analytical_manifest.json")
        config = read(output / "resolved_config.json")
        result.update(manifest=manifest, config=config)
        if manifest.get("format") != "m5-analytical-original-sources-v1":
            raise ValueError("Unsupported analytical-manifest format")
        for field, filename in [("analytical_summary_sha256", "summary.csv"), ("analytical_resolved_config_sha256", "resolved_config.json"), ("analytical_study_summary_sha256", "study_summary.json")]:
            check_hash(output / filename, manifest[field])
        if not manifest.get("complete") or not manifest.get("exact_disjoint_identity_coverage"):
            raise ValueError("Analytical view is not attested complete with disjoint identity coverage")
        expected = keys(config)
        if len(expected) != 360 or set(map(int, config["seeds"])) != set(range(30)) or int(config["days"]) != 7:
            raise ValueError("Analytical view is not the frozen 360-run, thirty-seed, seven-day grid")
        if set(config["policies"]) != {"B1", "B2", "B3", "B4"} or set(config["scenarios"]) != {"normal", "derived_field_collapse", "feed_gap"} or int(config["origins"]) != 1:
            raise ValueError("Analytical policy/scenario/origin grid differs from the six-hour numerical design")
        if int(manifest.get("expected_runs", -1)) != len(expected) or int(manifest.get("expected_decisions", -1)) != 2520:
            raise ValueError("Analytical exposure counts differ from the configured grid")
        sources = {}
        source_keys = set()
        projection = config_projection(config)
        environment = None
        for source in manifest["sources"]:
            phase = str(source["phase"])
            root = resolve(source["output"])
            path = resolve(source["config_path"])
            if phase in sources or root == output or root not in [(repo / "results/six_hour_numeric").resolve(), (repo / "results/six_hour_numeric_extension").resolve()]:
                raise ValueError("Duplicate, self-referential or unrecognized numerical source phase")
            check_hash(path, source["config_sha256"])
            from ega.config import load_config
            frozen = load_config(path).model_dump(mode="json")
            resolved = root / "resolved_config.json"
            check_hash(resolved, source["resolved_config_sha256"])
            original = read(resolved)
            if config_projection(frozen) != config_projection(original) or set(map(int, frozen["seeds"])) != set(map(int, original["seeds"])):
                raise ValueError(f"{phase}: original resolved settings differ from the frozen source YAML")
            if config_projection(original) != projection or set(map(int, original["seeds"])) != set(map(int, source["seeds"])):
                raise ValueError(f"{phase}: source resolved settings/seeds differ from the analytical design")
            phase_keys = keys(original)
            if phase_keys & source_keys or len(phase_keys) != int(source["expected_runs"]):
                raise ValueError("Source identities overlap or configured exposure count differs")
            source_keys |= phase_keys
            merge = read(root / "merge_manifest.json")
            if not merge.get("complete") or not merge.get("all_chains_valid") or not merge.get("exact_identity_coverage") or int(merge.get("runs_merged", -1)) != len(phase_keys):
                raise ValueError(f"{phase}: source's complete merge and audit-chain evidence is missing")
            packages = read(root / "environment.json")
            if environment is not None and environment != packages:
                raise ValueError("Recorded phase runtime environments differ")
            environment = packages
            sources[phase] = {**source, "root": str(root), "config": original, "keys": phase_keys}
        if len(sources) != 2 or source_keys != expected:
            raise ValueError("Two original source phases do not cover the exact disjoint thirty-seed grid")
        result["sources"] = [{key: value for key, value in source.items() if key != "keys"} for source in sources.values()]
        proof_path = resolve(manifest["training_equivalence_path"])
        check_hash(proof_path, manifest.get("training_equivalence_sha256", manifest.get("training_equivalence_hash")))
        recorded_proof = read(proof_path)
        base = (repo / "results/six_hour_numeric").resolve()
        extension = next(Path(source["root"]) for source in sources.values() if Path(source["root"]) != base)
        actual_proof = validate_training_equivalence(base, extension)
        result["training_equivalence"] = actual_proof
        if not all(proof.get("valid") and proof.get("complete") for proof in [recorded_proof, actual_proof]):
            raise ValueError("Actual trained-model equivalence is missing or false")
        if any(recorded_proof.get(field) != actual_proof.get(field) for field in ["models", "training_config_sha256", "worker_attestations", "model_roots_checked", "recorded_data_sha256"]):
            raise ValueError("Recorded training proof no longer matches the actual model artifacts")
        for model in actual_proof["models"]:
            inputs.update(Path(phase["path"]) for phase in model["phases"])
        for worker in actual_proof["worker_attestations"]:
            inputs.update(Path(worker[field]) for field in ["resolved_config_path", "environment_path", "source_manifest_path"])
        encountered, rows, paths = set(), [], []
        data_manifest = None
        for entry in manifest["run_sources"]:
            identity = (str(entry["policy"]), str(entry["scenario"]), int(entry["seed"]), int(entry["origin"]))
            phase = sources.get(str(entry["phase"]))
            if not phase or identity not in phase["keys"] or identity in encountered:
                raise ValueError("Duplicate, out-of-scope or wrong-phase original run identity")
            encountered.add(identity)
            run = resolve(entry["run_path"])
            if run.parent != Path(phase["root"]) or run.name != f"{identity[0]}__{identity[1]}__seed{identity[2]}__origin{identity[3]}":
                raise ValueError("Original run path is outside its stated phase or identity")
            summary_path = resolve(entry["summary_path"])
            if summary_path != run / "summary.json":
                raise ValueError("Summary path does not reference the original run")
            for filename, field in [("summary.json", "summary_sha256"), ("daily.csv", "daily_sha256"), ("trace_index.json", "trace_index_sha256"), ("run_manifest.json", "run_manifest_sha256")]:
                check_hash(run / filename, entry[field])
            row = read(summary_path)
            row_identity = (str(row["policy"]), str(row["scenario"]), int(row["seed"]), int(row["origin"]))
            if row_identity != identity or row.get("chain_valid") is not True or int(row.get("trace_count", -1)) != 7:
                raise ValueError("Original summary identity/audit/trace coverage differs")
            with (run / "daily.csv").open(newline="") as source:
                daily = list(csv.DictReader(source))
            if len(daily) != 7 or any((str(item["policy"]), str(item["scenario"]), int(item["seed"]), int(item["origin"])) != identity for item in daily):
                raise ValueError("Original daily rows do not cover the exact configured run")
            if {int(item["day"]) for item in daily} != set(range(int(config["start_day"]), int(config["start_day"]) + 7)):
                raise ValueError("Original decision-day coverage differs from the analytical design")
            traces = read(run / "trace_index.json")
            if len(traces) != 7 or {int(trace["day"]) for trace in traces} != {int(item["day"]) for item in daily}:
                raise ValueError("Original trace index does not cover every configured decision day")
            original = read(run / "run_manifest.json")
            if config_projection(original["config"]) != projection or int(original["seed"]) != identity[2] or int(original["origin"]) != identity[3] or original["scenario"] != identity[1]:
                raise ValueError("Immutable original run config differs from the pooled design")
            panel = original["data"]
            if panel.get("series") != 30 or panel.get("synthetic") is not False or panel.get("dataset") != "M5":
                raise ValueError("Original source data is not the historical thirty-series M5 panel")
            if data_manifest is not None and data_manifest != panel:
                raise ValueError("Original source-panel manifests differ")
            data_manifest = panel
            rows.append(row)
            paths.append(str(run))
        if encountered != expected:
            raise ValueError("Original source run artifacts do not cover the exact full analytical grid")
        result.update(valid=True, complete=True, rows=rows, run_paths=paths,
                      recorded_data=data_manifest, environment=environment,
                      config_projection_sha256=canonical_hash(projection))
    except Exception as error:
        result["errors"].append(f"{type(error).__name__}: {error}")
    return result
