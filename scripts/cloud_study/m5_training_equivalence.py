#!/usr/bin/env python3
"""Read-only exact trained-model equivalence for separately recorded M5 phases.

No training or prediction is performed. Torch checkpoints use weights_only=True.
Raw file hashes and semantic hashes are both retained: Torch ZIP serialization
can differ while its actual tensor states are identical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def deep_fingerprint(path):
    import torch
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or set(checkpoint) != {"state_dict", "training_end", "config"}:
        raise ValueError("Unexpected deep checkpoint schema")
    states = checkpoint["state_dict"]
    if not isinstance(states, dict) or not states:
        raise ValueError("Empty or invalid deep state_dict")
    tensors = {}
    for name, value in sorted(states.items()):
        if not isinstance(value, torch.Tensor) or value.layout != torch.strided:
            raise ValueError(f"Unsupported checkpoint state: {name}")
        tensor = value.detach().cpu().contiguous()
        if (tensor.is_floating_point() or tensor.is_complex()) and not bool(torch.isfinite(tensor).all()):
            raise ValueError(f"Non-finite checkpoint state: {name}")
        tensors[name] = {"shape": list(tensor.shape), "dtype": str(tensor.dtype),
                         "sha256": hashlib.sha256(tensor.view(torch.uint8).numpy().tobytes()).hexdigest()}
    semantic = {"training_end": checkpoint["training_end"], "config": checkpoint["config"], "tensors": tensors}
    return {"path": str(Path(path).resolve()), "file_sha256": file_hash(path),
            "semantic_sha256": canonical_hash(semantic), **semantic}


def lightgbm_fingerprint(path):
    # Parse native text without invoking the C++ loader on a potentially corrupt
    # file. Every predictive field is compared; only serialized byte offsets and
    # post-model training-parameter prose are excluded from the semantic hash.
    text = Path(path).read_text()
    matches = list(re.finditer(r"^Tree=\d+\n", text, re.M))
    if not text.startswith("tree\n") or not matches or "end of trees" not in text:
        raise ValueError("Unsupported LightGBM text model")
    end = text.index("end of trees")
    header = dict(line.split("=", 1) for line in text[:matches[0].start()].splitlines() if "=" in line)
    sizes = [int(value) for value in header.pop("tree_sizes").split()]
    if len(sizes) != len(matches):
        raise ValueError("LightGBM tree-size inventory mismatch")
    numeric_fields = {"split_feature", "split_gain", "threshold", "decision_type", "left_child", "right_child",
                      "leaf_value", "leaf_weight", "leaf_count", "internal_value", "internal_weight", "internal_count",
                      "num_leaves", "num_cat", "is_linear", "shrinkage", "cat_boundaries", "cat_threshold"}
    trees = []
    for index, match in enumerate(matches):
        stop = matches[index + 1].start() if index + 1 < len(matches) else end
        block = text[match.start():stop]
        if len(block.encode()) != sizes[index]:
            raise ValueError("LightGBM tree byte-offset integrity failure")
        fields = {}
        for line in block.splitlines():
            if not line:
                continue
            if "=" not in line:
                raise ValueError("Malformed LightGBM tree field")
            name, value = line.split("=", 1)
            if name in fields:
                raise ValueError("Duplicate LightGBM tree field")
            if name in numeric_fields:
                values = [float(token) for token in value.split()]
                if not all(math.isfinite(number) for number in values):
                    raise ValueError("Non-finite LightGBM model state")
                fields[name] = values
            else:
                fields[name] = value
        if fields.get("Tree") != str(index) or not fields.get("leaf_value") or not fields.get("num_leaves"):
            raise ValueError("Incomplete or unordered LightGBM numerical trees")
        leaves = int(fields["num_leaves"][0])
        if len(fields["leaf_value"]) != leaves or len(fields.get("threshold", [])) != leaves - 1:
            raise ValueError("LightGBM numerical tree dimensions mismatch")
        trees.append(fields)
    categorical = next((line for line in text.splitlines() if line.startswith("pandas_categorical:")), None)
    model = {"header": header, "numerical_trees": trees, "pandas_categorical": categorical}
    return {"path": str(Path(path).resolve()), "file_sha256": file_hash(path),
            "semantic_sha256": canonical_hash(model), "trees": len(trees),
            "features": header.get("feature_names"), "objective": header.get("objective"),
            "comparison": "exact parsed native text-model header and every numerical tree field including splits, thresholds, leaves and shrinkage; serialized tree byte offsets validated separately"}


def validate_training_equivalence(base_output, extension_output):
    """Return a strict proof; valid=False for missing or mismatched artifacts.

The outputs must contain actual resolved_config.json files. This validates
training settings and numerical model states, not run-grid coverage, data or
source/config provenance; those require separate manifest validation.
"""
    base, extension = Path(base_output).resolve(), Path(extension_output).resolve()
    result = {"format": "m5-exact-training-equivalence-v1", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "base_output": str(base), "extension_output": str(extension),
              "valid": False, "complete": False, "errors": [], "models": [],
              "validation_scope": "Read-only trained-model states and training config; no training, prediction, seed-grid or source-data validation"}
    try:
        configs = [json.loads((root / "resolved_config.json").read_text()) for root in [base, extension]]
        result["resolved_configs"] = [{"path": str(root / "resolved_config.json"), "sha256": file_hash(root / "resolved_config.json")} for root in [base, extension]]
        training = [{key: cfg[key] for key in ["dataset", "start_day", "warmup_days", "origin_stride", "origins", "forecast", "forecast_override"]} for cfg in configs]
        result["training_config_sha256"] = [canonical_hash(value) for value in training]
        if training[0] != training[1]:
            raise ValueError("Training settings differ between phases")
        if configs[0]["policies"] != configs[1]["policies"]:
            raise ValueError("Policy grids differ between phases")
        if configs[0].get("forecast_override"):
            raise ValueError("This proof requires native trained B2/B3/B4 forecasts without override")
        if not {"B2", "B3", "B4"}.issubset(configs[0]["policies"]):
            raise ValueError("This proof requires the registered numerical B2/B3/B4 model set")
        model_roots = [base, extension]
        worker_attestations = []
        recorded_data = None
        recorded_environment = json.loads((base / "environment.json").read_text())
        projection = lambda cfg: {key: value for key, value in cfg.items() if key not in {"output", "seeds"}}
        if projection(configs[0]) != projection(configs[1]):
            raise ValueError("Actual numerical phase settings differ beyond output and seeds")
        for phase_root, phase_config in zip([base, extension], configs):
            merge = json.loads((phase_root / "merge_manifest.json").read_text())
            if not merge.get("complete") or not merge.get("all_chains_valid") or not merge.get("exact_identity_coverage"):
                raise ValueError("All numerical source merges must be complete and audit/identity-valid")
            worker_root = Path(str(phase_root) + "_workers")
            workers = [Path(path).resolve() for path in merge.get("workers", [])]
            discovered = sorted(path.resolve() for path in worker_root.glob("w*") if path.is_dir() and (path / "resolved_config.json").exists())
            if not workers or set(workers) != set(discovered) or any(worker.parent != worker_root or worker.is_symlink() for worker in workers):
                raise ValueError("Numerical worker inventory is absent or differs from actual phase workers")
            phase_seeds = set()
            for worker in sorted(workers):
                worker_config_path = worker / "resolved_config.json"
                worker_config = json.loads(worker_config_path.read_text())
                seeds = set(map(int, worker_config["seeds"]))
                if projection(worker_config) != projection(phase_config) or seeds & phase_seeds:
                    raise ValueError("Actual numerical worker config differs or seed shards overlap")
                phase_seeds |= seeds
                environment_path = worker / "environment.json"
                if json.loads(environment_path.read_text()) != recorded_environment:
                    raise ValueError("Actual worker recorded environment differs from the base phase")
                manifest_paths = sorted(worker.glob("*/run_manifest.json"))
                if not manifest_paths:
                    raise ValueError("Actual worker source-data run-manifest evidence is missing")
                source = json.loads(manifest_paths[0].read_text())
                if projection(source["config"]) != projection(worker_config) or int(source["seed"]) not in seeds:
                    raise ValueError("Actual worker immutable run config/source seed differs from the worker shard")
                data = source["data"]
                if data.get("series") != 30 or data.get("synthetic") is not False or data.get("dataset") != "M5":
                    raise ValueError("Actual worker has no historical thirty-series M5 source attestation")
                if recorded_data is not None and data != recorded_data:
                    raise ValueError("Actual numerical workers record different data-source manifests")
                recorded_data = data
                worker_attestations.append({"phase_output": str(phase_root), "worker_output": str(worker), "seeds": sorted(seeds),
                                            "resolved_config_path": str(worker_config_path), "resolved_config_sha256": file_hash(worker_config_path),
                                            "environment_path": str(environment_path), "environment_sha256": file_hash(environment_path),
                                            "source_manifest_path": str(manifest_paths[0]), "source_manifest_sha256": file_hash(manifest_paths[0]),
                                            "recorded_data_sha256": canonical_hash(data)})
                model_roots.append(worker)
            if phase_seeds != set(map(int, phase_config["seeds"])):
                raise ValueError("Actual numerical worker seed shards do not cover their frozen phase")
        result["worker_attestations"] = worker_attestations
        result["model_roots_checked"] = list(map(str, model_roots))
        result["recorded_data_sha256"] = canonical_hash(recorded_data)
        from ega.forecasting.lightgbm_model import QuantileLightGBM
        expected_quantile_files = sorted(f"q{level}.txt" for level in QuantileLightGBM.levels)
        result["complete"] = True
        for origin in range(int(configs[0]["origins"])):
            expected_training_end = int(configs[0]["start_day"]) + origin * int(configs[0]["origin_stride"]) - int(configs[0]["warmup_days"]) - 1
            deep_paths = [root / f"model_deep_origin{origin}.pt" for root in model_roots]
            if not all(path.is_file() and not path.is_symlink() for path in deep_paths):
                result["complete"] = False
                result["errors"].append(f"Origin {origin}: actual deep model file missing/unsupported")
            else:
                states = [deep_fingerprint(path) for path in deep_paths]
                equal = len({state["semantic_sha256"] for state in states}) == 1 and all(state["training_end"] == expected_training_end for state in states)
                result["models"].append({"model": "deep", "origin": origin, "equal": equal,
                                         "expected_training_end": expected_training_end, "phases": states})
                if not equal:
                    result["errors"].append(f"Origin {origin}: deep tensors, training cutoff or checkpoint config differ")
            directories = [root / f"model_lightgbm_origin{origin}" for root in model_roots]
            names = [sorted(path.name for path in directory.glob("q*.txt")) for directory in directories]
            if names[0] != expected_quantile_files or any(names[0] != candidate for candidate in names[1:]) or any(not directory.is_dir() or directory.is_symlink() for directory in directories):
                result["complete"] = False
                result["errors"].append(f"Origin {origin}: actual LightGBM quantile model set missing/mismatched")
                continue
            for filename in names[0]:
                paths = [directory / filename for directory in directories]
                if any(path.is_symlink() for path in paths):
                    raise ValueError("Unsupported symlinked LightGBM artifact")
                states = [lightgbm_fingerprint(path) for path in paths]
                equal = len({state["semantic_sha256"] for state in states}) == 1
                result["models"].append({"model": "lightgbm", "origin": origin, "quantile_file": filename,
                                         "equal": equal, "phases": states})
                if not equal:
                    result["errors"].append(f"Origin {origin}/{filename}: parsed LightGBM numerical models differ")
        result["valid"] = bool(result["complete"] and result["models"] and not result["errors"] and all(row["equal"] for row in result["models"]))
    except Exception as error:
        result["errors"].append(f"{type(error).__name__}: {error}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = validate_training_equivalence(args.base, args.extension)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: result[key] for key in ["valid", "complete", "errors"]}))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
