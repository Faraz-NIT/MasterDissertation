"""Separately registered, exploratory transfer of an autonomous spending cap.

The original FreshRetailNet study stays immutable. Its portability failure
motivated this follow-up after primary evaluation began, so train-only cap
calibration does not make this an untouched confirmatory experiment.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import traceback

import numpy as np
import pandas as pd

from ega.autonomy import plan_spend
from ega.config import ExperimentConfig
from ega.data.panel import Panel
from ega.forecasting.core import build_forecaster
from ega.optimization import check_plan
from ega.schemas import Plan, Series
from ega.util import atomic_json, canonical, digest, environment

ROOT = Path(__file__).resolve().parents[2]
PRIMARY = ROOT / "results/freshretailnet"
OUT = PRIMARY / "gate_transfer"
PROTOCOL = OUT / "protocol.json"
ARMS = {
    "parser_no_recovery": ("B4", False),
    "parser_recovery": ("B4", True),
    "llm_no_recovery": ("B10", False),
    "llm_recovery": ("B10", True),
}
GATE_VERSION = "gate-v2-FreshRetailNet-train-only-spend-transfer-exploratory-v1"
SCENARIOS = ["normal", "derived_field_collapse", "feed_gap", "capacity_cut"]
SEEDS = list(range(30))
RUNS_PER_ARM = len(SCENARIOS) * len(SEEDS)
EXPECTED_RUNS = len(ARMS) * RUNS_PER_ARM
EXPECTED_DECISIONS = EXPECTED_RUNS * 7
OWNER = None
PARSER_MODELS = None
PARSER_PANEL = None
PARSER_CONFIGS = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def primary_owner():
    global OWNER
    if OWNER is None:
        path = ROOT / "scripts/freshretailnet/run_study.py"
        spec = importlib.util.spec_from_file_location("frozen_freshretailnet_primary_owner", path)
        OWNER = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(OWNER)
    return OWNER


def audit(stage, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "workflow.jsonl"
    with (OUT / "workflow.lock").open("a") as locked:
        fcntl.flock(locked, fcntl.LOCK_EX)
        previous = "0" * 64
        if path.exists():
            with path.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 20000))
                lines = stream.read().splitlines()
            if lines:
                previous = json.loads(lines[-1])["hash"]
        row = {"recorded_at_utc": now(), "stage": stage, "payload": payload, "previous_hash": previous}
        row["hash"] = digest(row)
        with path.open("a") as stream:
            stream.write(canonical(row) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def guard():
    if datetime.now(timezone.utc) >= datetime.fromisoformat("2026-10-08T13:25:00+00:00"):
        raise TimeoutError("Follow-up cutoff reached; retain incomplete runs for reporting")
    if shutil.disk_usage(ROOT).free < 2 * 1024**3:
        raise RuntimeError("Disk reserve below two GiB")


def choose_cap(spends, budget=3000.0):
    values = np.asarray(spends, dtype=float)
    if values.shape != (7,) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Cap requires exactly seven finite nonnegative proposed spends")
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("Calibration budget must be positive")
    p95 = float(np.quantile(values, 0.95, method="linear"))
    unbounded = float(math.ceil(1.10 * p95 / 50.0) * 50.0)
    return {"proposed_spends": values.tolist(), "p95": p95, "rounded_buffered_p95": unbounded,
            "budget": float(budget), "budget_fraction_maximum": 0.8,
            "selected_cap": min(0.8 * float(budget), unbounded),
            "formula": "min(0.8*budget,ceil(1.10*p95(all_seven_proposed_spends)/50)*50)",
            "quantile_interpolation": "linear", "evaluation_spends_used": False}


def require_primary_complete(primary=PRIMARY):
    path = Path(primary) / "agents/execution_complete.json"
    if not path.is_file():
        raise RuntimeError("Follow-up live inference waits for primary agents/execution_complete.json")
    receipt = read(path)
    if receipt.get("status") != "COMPLETE" or receipt.get("runs") != 32:
        raise RuntimeError("Primary agent receipt is incomplete; do not overlap live inference")
    return receipt


def changed_fields(before, after, prefix=""):
    if isinstance(before, dict) and isinstance(after, dict):
        if set(before) != set(after):
            raise ValueError("Configuration structure changed")
        return [field for key in before for field in changed_fields(before[key], after[key], prefix + key + ".")]
    return [] if before == after else [prefix.rstrip(".")]


def final_config(original, output, cap, cache_path, spend_path):
    blob = original.model_dump() if isinstance(original, ExperimentConfig) else json.loads(json.dumps(original))
    baseline = json.loads(json.dumps(blob))
    blob["output"] = str(output)
    blob["gate"]["max_spend"] = float(cap)
    blob["gate"]["version"] = GATE_VERSION
    blob["agent_v2"]["cache_path"] = str(cache_path)
    blob["llm"]["spend_ledger"] = str(spend_path)
    blob["seeds"] = SEEDS.copy()
    config = ExperimentConfig.model_validate(blob)
    differences = changed_fields(baseline, config.model_dump())
    permitted = {"output", "gate.max_spend", "gate.version", "agent_v2.cache_path", "llm.spend_ledger", "seeds"}
    if set(differences) - permitted:
        raise ValueError("Unexpected final configuration change: " + repr(differences))
    if config.gate.two_person_spend != 2500:
        raise ValueError("Final two-person approval threshold must remain 2500")
    return config, differences


def source_inputs():
    original = read(PRIMARY / "protocol.json")
    if original.get("status") != "frozen":
        raise RuntimeError("Original study protocol must remain frozen")
    primary_owner().verify()
    paths = {
        "primary_protocol": PRIMARY / "protocol.json",
        "selected_train": PRIMARY / "data/selected_train.parquet",
        "selected_catalog": PRIMARY / "data/selected_series.csv",
        "prepared_catalog": ROOT / "data/processed/freshretailnet/series.csv",
        "primary_saved_deep": PRIMARY / "shared/deep.pt",
        "primary_saved_deep_training": PRIMARY / "shared/deep_training.json",
        "primary_model_identities": PRIMARY / "shared/model_identities.json",
        "owner_code": Path(__file__).resolve(),
        "owner_tests": ROOT / "tests/test_fresh_gate_transfer.py",
    }
    for arm in ARMS:
        paths["primary_config_" + arm] = PRIMARY / f"configs/{arm}.json"
    return original, paths


def verify(expected_status=None):
    protocol = read(PROTOCOL)
    if expected_status is not None and protocol["status"] != expected_status:
        raise RuntimeError(f"Follow-up protocol status is {protocol['status']}, expected {expected_status}")
    primary_owner().verify()
    for name, entry in protocol["protected_inputs"].items():
        if sha(entry["path"]) != entry["sha256"]:
            raise AssertionError("Protected follow-up input changed: " + name)
    if protocol.get("configs"):
        for arm, entry in protocol["configs"].items():
            if sha(entry["path"]) != entry["sha256"]:
                raise AssertionError("Frozen follow-up configuration changed: " + arm)
    return protocol


def register():
    if PROTOCOL.exists():
        raise FileExistsError("Do not overwrite a follow-up protocol")
    original, paths = source_inputs()
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = {
        "schema_version": "freshretailnet-exploratory-gate-transfer-v1",
        "status": "registered", "registered_at_utc": now(),
        "motivation": "Locked primary FreshRetailNet evaluation exposed a spending-cap portability problem after its evaluation began",
        "evidence_status": "Exploratory follow-up; official holdout already used by primary study; no confirmatory independence claim",
        "primary_protocol_unchanged": True,
        "calibration": {"source": "Only selected_train.parquet; official evaluation values never loaded",
            "start_day": 76, "days": 7, "warmup_days": 14, "seed": 4242,
            "panel_end_exclusive": 83, "train_end_exclusive": 76, "scenario": "normal", "policy": "B4",
            "model": "Same native GRU-negative-binomial family, deep_epochs10,max_windows12000; freshly trained through day75",
            "temporary_autonomous_cap": 3000.0, "temporary_two_person_cap": 3001.0,
            "other_gates": "Identical original policy, including source validation, independent critic and risk limits",
            "selection_formula": "min(0.8*budget,ceil(1.10*p95(all_seven_proposed_spends)/50)*50)",
            "quantile_interpolation": "linear", "maximum_cap": 2400.0,
            "missing_proposal": "Missing any of seven verified proposed spends invalidates calibration; retain artifacts, do not tune on eval"},
        "evaluation": {"arms": {name: {"policy": policy, "inventory_state_recovery": recovery}
                                     for name, (policy, recovery) in ARMS.items()},
            "scenarios": SCENARIOS, "seeds": SEEDS, "start_day": 90, "days": 7, "warmup_days": 14,
            "expected_runs": EXPECTED_RUNS, "expected_decisions": EXPECTED_DECISIONS,
            "runs_per_arm": RUNS_PER_ARM, "parser_workers": 2, "llm_inference_parallelism": 1,
            "forecast": "Original primary saved GRU tensors; no retraining of evaluation forecaster",
            "allowed_semantic_changes": ["gate.max_spend", "gate.version"],
            "sampling_changes": ["seeds expanded to0..29 before follow-up registration/calibration"],
            "delivery_changes": ["output", "agent_v2.cache_path", "llm.spend_ledger"],
            "final_two_person_cap": 2500.0, "fresh_cache": True,
            "live_inference_prerequisite": "Primary agents/execution_complete.json COMPLETE32runs",
            "demand_world": "Identical authoritative normalized-x100 perishable simulator and common keyed world; no changes to demand/constraints/prompts/model"},
        "cutoff_utc": "2026-10-08T13:25:00+00:00",
        "protected_inputs": {name: {"path": str(path), "sha256": sha(path)} for name, path in paths.items()},
        "primary_frozen_source_sha256": original["source_sha256"],
        "model": original["model"], "environment": environment(),
        "interpretation": ["Keep primary outcomes and follow-up outcomes separate; do not replace failed transfer evidence",
            "Training-only calibration limits direct tuning leakage but the question arose after primary outcomes were seen",
            "A higher cap may improve service and increase purchases/waste; compare cost and fill together",
            "Correct state recovery is not statistical demand recovery and not an incremental LLM effect",
            "Thirty simulator seeds still share one selected panel, one seven-day window, one trained forecaster and cached LLM proofs",
            "No real purchasing or monetary savings; results are indexed counterfactual simulator evidence"],
    }
    atomic_json(PROTOCOL, protocol)
    shutil.copyfile(PROTOCOL, OUT / "registered_protocol.json")
    for name in ["owner_code", "owner_tests"]:
        path = paths[name]
        dest = OUT / "frozen_code" / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    audit("followup_registered_before_calibration", {"protocol_sha256": sha(PROTOCOL),
          "registered_protocol_sha256": sha(OUT / "registered_protocol.json")})
    print(json.dumps({"phase": "registered", "protocol": str(PROTOCOL)}), flush=True)


def training_panel(frame, series, flags_path):
    """Physically exclude all rows after day82, including the official holdout."""
    frame = frame[frame.day_index < 83].copy()
    if len(frame) != 30 * 83 or frame.day_index.nunique() != 83:
        raise ValueError("Calibration needs all thirty selected series through day82")
    ids = [item.series_id for item in series]
    matrix = frame.pivot(index="series_id", columns="day_index", values="sale_amount").loc[ids, range(83)].to_numpy(float)
    # Reproduce the primary panel's storage rounding and normalized-x100 scale.
    sales = (matrix * 100).astype(np.float32)
    flags = frame.pivot(index="series_id", columns="day_index", values="stock_hour6_22_cnt").loc[ids, range(83)].to_numpy() > 0
    flags_path = Path(flags_path)
    flags_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(flags_path, flags, allow_pickle=False)
    dates = frame.groupby("day_index").dt.first().loc[range(83)].tolist()
    calendar = pd.DataFrame({"date": dates})
    parsed = pd.to_datetime(calendar.date)
    calendar["wday"] = parsed.dt.weekday + 1
    calendar["month"] = parsed.dt.month
    return Panel(series, sales, np.ones_like(sales), calendar, {
        "dataset": "Dingdong-Inc/FreshRetailNet-50K",
        "source_kind": "Observed selected training sales, normalized-x100; simulated inventory/supply/economics",
        "calibration_only": True, "latest_included_day": 82, "official_eval_values_loaded": False,
        "perishable_simulation": {"shelf_life_days": 3},
        "source_observed_stockout_path": str(flags_path),
        "terminal_salvage": False})


class ReadOnlyStore:
    def __init__(self, run):
        self.root = Path(run) / "artifacts"

    def load(self, ref):
        value = read(self.root / "objects" / f"{ref}.json")
        if digest(value) != ref:
            raise AssertionError("Content-addressed object failed: " + ref)
        return value

    def chain(self):
        db = sqlite3.connect(f"file:{self.root / 'audit.sqlite'}?mode=ro", uri=True)
        previous = "0" * 64
        counts = Counter()
        total = 0
        for decision, stage, payload, prior, value in db.execute(
                "SELECT decision_id,stage,payload,previous_hash,event_hash FROM events ORDER BY seq"):
            event = {"decision_id": decision, "stage": stage, "payload": json.loads(payload), "previous_hash": prior}
            if prior != previous or digest(event) != value:
                raise AssertionError("Artifact event-chain failed")
            previous = value
            counts[stage] += 1
            total += 1
        db.close()
        return {"events": total, "stages": dict(counts), "final_hash": previous}


def calibrate():
    verify("registered")
    guard()
    stage = OUT / "calibration"
    if stage.exists():
        raise FileExistsError("Retain existing calibration attempts; never overwrite")
    stage.mkdir()
    audit("training_only_calibration_started", {"start": 76, "train_end_exclusive": 76, "eval_values_loaded": False})
    frame = pd.read_parquet(PRIMARY / "data/selected_train.parquet")
    series = [Series.model_validate(row) for row in pd.read_csv(ROOT / "data/processed/freshretailnet/series.csv").to_dict("records")]
    panel = training_panel(frame, series, stage / "training_stockout_flags.npy")
    panel.save(stage / "train_only_panel")
    config = ExperimentConfig.model_validate(read(PRIMARY / "configs/parser_no_recovery.json"))
    config.output = str(stage)
    config.start_day = 76
    config.scenarios = ["normal"]
    config.seeds = [4242]
    config.document_carrier = "template"
    config.agent_v2.cache_path = str(stage / "verified_cache")
    config.gate.max_spend = config.solver.budget
    config.gate.two_person_spend = config.solver.budget + 1
    atomic_json(stage / "resolved_config.json", config)
    model = build_forecaster("deep", config.forecast).fit(panel, 76)
    model.save(stage / "deep_train76.pt")
    atomic_json(stage / "training.json", {"losses": model.losses, "training_end": model.training_end,
          "forecast_config": config.forecast.model_dump(), "tensor_sha256": sha(stage / "deep_train76.pt")})
    from ega import experiment
    from ega.freshretail.simulator import PerishableInventoryEnvironment
    experiment.InventoryEnvironment = PerishableInventoryEnvironment
    run = stage / "B4__normal__seed4242__origin0"
    summary = experiment.run_one(panel, config, "B4", "normal", 4242, 0, model, run)
    reader = ReadOnlyStore(run)
    spends = []
    for entry in read(run / "trace_index.json"):
        trace = reader.load(entry["trace_ref"])
        autonomy = reader.load(trace["references"]["autonomy"])
        if "problem" not in trace["references"] or "spend" not in autonomy["inputs"]:
            atomic_json(stage / "incomplete_calibration.json", {"day": trace["day"], "reasons": autonomy["reasons"],
                  "summary": summary, "selection_invalid": True})
            raise RuntimeError("Calibration day has no verified proposed spend; do not substitute eval values")
        proposed = reader.load(trace["references"]["propose"])
        problem = reader.load(trace["references"]["problem"])
        recomputed = plan_spend(Plan.model_validate(proposed), problem)
        if abs(recomputed - float(autonomy["inputs"]["spend"])) > 1e-6:
            raise AssertionError("Recorded calibration spend differs from its proposal")
        spends.append({"day": trace["day"], "date": panel.calendar.iloc[trace["day"]]["date"],
            "proposed_spend_index": recomputed, "permitted": autonomy["permitted"], "autonomy_level": autonomy["level"],
            "reasons": json.dumps(autonomy["reasons"]), "trace_ref": entry["trace_ref"],
            "proposal_ref": trace["references"]["propose"], "autonomy_ref": trace["references"]["autonomy"]})
    receipt = choose_cap([row["proposed_spend_index"] for row in spends], config.solver.budget)
    receipt.update({"status": "COMPLETE", "completed_at_utc": now(), "calibration_days": list(range(76, 83)),
        "date_range": [panel.calendar.iloc[76]["date"], panel.calendar.iloc[82]["date"]],
        "training_end_exclusive": 76, "source_selected_train_sha256": sha(PRIMARY / "data/selected_train.parquet"),
        "calibration_tensor_sha256": sha(stage / "deep_train76.pt"), "model_training_end": model.training_end,
        "temporary_autonomous_cap": config.gate.max_spend, "temporary_two_person_cap": config.gate.two_person_spend,
        "held_decisions": summary["held_decisions"], "all_days_recorded_including_holds": True,
        "hold_reason_counts": dict(Counter(reason for row in spends if not row["permitted"] for reason in json.loads(row["reasons"]))),
        "artifact_chain": reader.chain(), "selection_uses_official_eval": False})
    pd.DataFrame(spends).to_csv(stage / "proposed_spends.csv", index=False)
    atomic_json(stage / "selection_receipt.json", receipt)
    audit("training_only_spend_cap_selected", receipt)
    print(json.dumps({"phase": "calibrated", **receipt}), flush=True)


def freeze():
    protocol = verify("registered")
    selection = read(OUT / "calibration/selection_receipt.json")
    if selection["status"] != "COMPLETE" or selection["selected_cap"] <= 0 or selection["selected_cap"] > 2400:
        raise RuntimeError("Invalid train-only cap receipt")
    if choose_cap(selection["proposed_spends"], selection["budget"])["selected_cap"] != selection["selected_cap"]:
        raise AssertionError("Cap does not follow registered formula")
    configs = {}
    for arm in ARMS:
        original = read(PRIMARY / f"configs/{arm}.json")
        config, differences = final_config(original, OUT / "agents" / arm, selection["selected_cap"],
              OUT / "verified_cache", OUT / "evaluation_spend.json")
        path = OUT / f"configs/{arm}.json"
        atomic_json(path, config)
        configs[arm] = {"path": str(path), "sha256": sha(path), "changed_fields": differences}
    protocol.update(status="frozen", frozen_at_utc=now(), autonomous_cap=selection["selected_cap"],
         configs=configs, calibration_selection_sha256=sha(OUT / "calibration/selection_receipt.json"),
         calibration_proposals_sha256=sha(OUT / "calibration/proposed_spends.csv"),
         evaluation_forecast_tensor_sha256=sha(PRIMARY / "shared/deep.pt"))
    atomic_json(PROTOCOL, protocol)
    audit("followup_evaluation_frozen", {"protocol_sha256": sha(PROTOCOL), "cap": selection["selected_cap"],
          "evaluation_forecast_tensor_sha256": protocol["evaluation_forecast_tensor_sha256"]})
    print(json.dumps({"phase": "frozen", "cap": selection["selected_cap"], "sha256": sha(PROTOCOL)}), flush=True)


def completed_run(root, config):
    summary = read(root / "summary.json")
    manifest = read(root / "run_manifest.json")
    if manifest["config"] != config.model_dump() or not summary["chain_valid"] or summary["trace_count"] != 7:
        raise AssertionError("Existing run is not a complete identical-config run")
    ReadOnlyStore(root).chain()
    if len(read(root / "trace_index.json")) != 7 or len(pd.read_csv(root / "daily.csv")) != 7:
        raise AssertionError("Existing run lacks the seven registered decisions")
    return summary


def execute(labels):
    protocol = verify("frozen")
    guard()
    if any(ARMS[label][0] == "B10" for label in labels):
        primary_receipt = require_primary_complete()
        audit("primary_live_inference_completed_before_followup", {"sha256": sha(PRIMARY / "agents/execution_complete.json"),
              "primary_completed_at_utc": primary_receipt["completed_at_utc"]})
    owner = primary_owner()
    models = owner.load_models()
    if sha(PRIMARY / "shared/deep.pt") != protocol["evaluation_forecast_tensor_sha256"]:
        raise AssertionError("Original evaluation forecast tensors changed")
    panel = Panel.load(ROOT / "data/processed/freshretailnet")
    from ega import experiment
    from ega.freshretail.simulator import PerishableInventoryEnvironment
    experiment.InventoryEnvironment = PerishableInventoryEnvironment
    if any(ARMS[label][0] == "B10" for label in labels):
        tags = {item["name"]: item for item in owner.api("/api/tags")["models"]}
        if tags[protocol["model"]["name"]]["digest"] != protocol["model"]["digest"]:
            raise AssertionError("Original local LLM identity changed")
    for arm in labels:
        config = ExperimentConfig.model_validate(read(OUT / f"configs/{arm}.json"))
        stage = Path(config.output)
        stage.mkdir(parents=True, exist_ok=True)
        resolved = stage / "resolved_config.json"
        if resolved.exists() and read(resolved) != config.model_dump():
            raise AssertionError("Existing arm configuration changed")
        if not resolved.exists():
            atomic_json(resolved, config)
        rows = []
        for scenario in SCENARIOS:
            for seed in SEEDS:
                guard()
                root = stage / f"{config.policies[0]}__{scenario}__seed{seed}__origin0"
                if root.exists():
                    if not (root / "summary.json").exists():
                        raise FileExistsError("Incomplete run retained; cannot overwrite: " + str(root))
                    row = completed_run(root, config)
                    audit("completed_followup_run_reused_without_execution", {"arm": arm, "path": str(root),
                          "summary_sha256": sha(root / "summary.json")})
                else:
                    audit("followup_run_started", {"arm": arm, "scenario": scenario, "seed": seed,
                          "saved_forecast_sha256": protocol["evaluation_forecast_tensor_sha256"]})
                    print(json.dumps({"phase": "run_started", "arm": arm, "scenario": scenario, "seed": seed}), flush=True)
                    row = experiment.run_one(panel, config, config.policies[0], scenario, seed, 0, models["deep"], root)
                    audit("followup_run_completed", {"arm": arm, **row})
                rows.append(row)
                pd.DataFrame(rows).to_csv(stage / "summary.csv", index=False)
                print(json.dumps({"phase": "run_completed", "arm": arm, **row}), flush=True)
        atomic_json(stage / "execution_complete.json", {"status": "COMPLETE", "runs": RUNS_PER_ARM, "decisions": RUNS_PER_ARM * 7,
              "completed_at_utc": now(), "summary_sha256": sha(stage / "summary.csv")})
    summarize_if_complete()


def summarize_if_complete_locked():
    all_rows = []
    complete_arms = []
    for arm in ARMS:
        stage = OUT / "agents" / arm
        if not (stage / "execution_complete.json").exists():
            continue
        complete_arms.append(arm)
        for row in pd.read_csv(stage / "summary.csv").to_dict("records"):
            all_rows.append({"arm": arm, **row})
    pd.DataFrame(all_rows).to_csv(OUT / "summary_partial.csv", index=False)
    if len(complete_arms) == 4:
        if len(all_rows) != EXPECTED_RUNS:
            raise AssertionError("Unexpected follow-up factorial count")
        pd.DataFrame(all_rows).to_csv(OUT / "summary.csv", index=False)
        complete = {"status": "COMPLETE", "runs": EXPECTED_RUNS, "decisions": EXPECTED_DECISIONS, "completed_at_utc": now(),
            "protocol_sha256": sha(PROTOCOL), "summary_sha256": sha(OUT / "summary.csv"),
            "API_usage": read(OUT / "evaluation_spend.json") if (OUT / "evaluation_spend.json").exists() else {}}
        atomic_json(OUT / "execution_complete.json", complete)
        audit("separate_followup_factorial_completed", complete)


def summarize_if_complete():
    with (OUT / "summary.lock").open("a") as locked:
        fcntl.flock(locked, fcntl.LOCK_EX)
        if (OUT / "execution_complete.json").exists():
            if read(OUT / "execution_complete.json")["runs"] != EXPECTED_RUNS:
                raise AssertionError("Existing final receipt has the wrong grid")
            return
        summarize_if_complete_locked()


def parser_one(task):
    arm, scenario, seed = task
    guard()
    config = PARSER_CONFIGS[arm]
    root = Path(config.output) / f"{config.policies[0]}__{scenario}__seed{seed}__origin0"
    if root.exists():
        if not (root / "summary.json").exists():
            raise FileExistsError("Incomplete parser run retained: " + str(root))
        return arm, completed_run(root, config), True
    audit("followup_parser_run_started", {"arm": arm, "scenario": scenario, "seed": seed})
    from ega import experiment
    row = experiment.run_one(PARSER_PANEL, config, config.policies[0], scenario, seed, 0, PARSER_MODELS["deep"], root)
    return arm, row, False


def parsers():
    global PARSER_MODELS, PARSER_PANEL, PARSER_CONFIGS
    protocol = verify("frozen")
    guard()
    require_primary_complete()
    PARSER_MODELS = primary_owner().load_models()
    if sha(PRIMARY / "shared/deep.pt") != protocol["evaluation_forecast_tensor_sha256"]:
        raise AssertionError("Original saved evaluation tensors changed")
    PARSER_PANEL = Panel.load(ROOT / "data/processed/freshretailnet")
    from ega import experiment
    from ega.freshretail.simulator import PerishableInventoryEnvironment
    experiment.InventoryEnvironment = PerishableInventoryEnvironment
    labels = ["parser_no_recovery", "parser_recovery"]
    rows = {arm: [] for arm in labels}
    for arm in labels:
        config = ExperimentConfig.model_validate(read(OUT / f"configs/{arm}.json"))
        PARSER_CONFIGS[arm] = config
        stage = Path(config.output)
        stage.mkdir(parents=True, exist_ok=True)
        resolved = stage / "resolved_config.json"
        if resolved.exists() and read(resolved) != config.model_dump():
            raise AssertionError("Existing parser arm configuration changed")
        if not resolved.exists():
            atomic_json(resolved, config)
    tasks = [(arm, scenario, seed) for arm in labels for scenario in SCENARIOS for seed in SEEDS]
    audit("followup_parser_grid_started", {"runs": len(tasks), "workers": 2,
          "primary_agent_receipt_sha256": sha(PRIMARY / "agents/execution_complete.json")})
    with mp.get_context("fork").Pool(2) as pool:
        for arm, row, reused in pool.imap_unordered(parser_one, tasks, chunksize=1):
            rows[arm].append(row)
            stage = OUT / "agents" / arm
            pd.DataFrame(rows[arm]).sort_values(["scenario", "seed"]).to_csv(stage / "summary.csv", index=False)
            audit("followup_run_reused" if reused else "followup_run_completed", {"arm": arm, **row})
            print(json.dumps({"phase": "parser_run_completed", "arm": arm, "completed": sum(map(len, rows.values())),
                  "planned": len(tasks), "scenario": row["scenario"], "seed": row["seed"]}), flush=True)
    for arm in labels:
        stage = OUT / "agents" / arm
        if len(rows[arm]) != RUNS_PER_ARM:
            raise AssertionError("Parser arm workload count differs")
        atomic_json(stage / "execution_complete.json", {"status": "COMPLETE", "runs": RUNS_PER_ARM,
              "decisions": RUNS_PER_ARM * 7, "completed_at_utc": now(), "summary_sha256": sha(stage / "summary.csv")})
    verify("frozen")
    summarize_if_complete()


def agents():
    execute(["llm_no_recovery", "llm_recovery"])


def close(a, b, label):
    if not np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), atol=1e-6, rtol=1e-9):
        raise AssertionError(label)


def audit_results():
    protocol = verify("frozen")
    if read(OUT / "execution_complete.json")["status"] != "COMPLETE":
        raise RuntimeError("Follow-up audit requires all480 runs")
    rows = []
    all_daily = []
    decisions = []
    attempts = []
    chain_proofs = []
    objects = 0
    for arm in ARMS:
        config = read(OUT / f"configs/{arm}.json")
        for scenario in SCENARIOS:
            for seed in SEEDS:
                run = OUT / "agents" / arm / f"{ARMS[arm][0]}__{scenario}__seed{seed}__origin0"
                summary = completed_run(run, ExperimentConfig.model_validate(config))
                rows.append({"arm": arm, **summary})
                daily = pd.read_csv(run / "daily.csv").set_index("day")
                all_daily.extend({"arm": arm, "run": run.name, **row} for row in daily.reset_index().to_dict("records"))
                reader = ReadOnlyStore(run)
                chain_proofs.append({"arm": arm, "run": run.name, **reader.chain()})
                for path in (run / "artifacts/objects").glob("*.json"):
                    reader.load(path.stem)
                    objects += 1
                for entry in read(run / "trace_index.json"):
                    trace = reader.load(entry["trace_ref"])
                    refs = trace["references"]
                    plan = Plan.model_validate(reader.load(refs["propose"]))
                    autonomy = reader.load(refs["autonomy"])
                    outcome = reader.load(refs["outcome"])
                    evaluation = reader.load(trace["evaluation"])
                    receipt = reader.load(refs["receipt"])
                    problem = evaluation["true_problem"]
                    committed = receipt["status"] == "executed"
                    violations = check_plan(plan, {**problem, "lineage": plan.lineage.model_dump()}) if committed else []
                    if violations != evaluation["violations"] or len(violations) != int(daily.loc[trace["day"], "hard_violations"]):
                        raise AssertionError("Recomputed true hard-constraint violations differ")
                    if committed and (not autonomy["permitted"] or float(autonomy["inputs"].get("spend", 0)) > protocol["autonomous_cap"] + 1e-6):
                        raise AssertionError("Committed action exceeded follow-up autonomous cap")
                    sold = np.asarray(outcome["sales_by_series"])
                    expired = np.asarray(outcome["age_expired_by_series"])
                    overflow = np.asarray(outcome["capacity_overflow_by_series"])
                    on_hand = np.asarray(outcome["on_hand_by_series"])
                    transit_expiry = np.asarray(outcome["in_transit_expired_by_series"])
                    spoiled = np.asarray(outcome["spoilage_by_series"])
                    close(expired + overflow + transit_expiry, spoiled, "Waste components")
                    close(outcome["demand"], outcome["sales"] + outcome["lost_sales"], "Demand service")
                    opening = np.asarray(problem["on_hand"]).copy()
                    index = {series["series_id"]: i for i, series in enumerate(problem["series"])}
                    if committed:
                        for transfer in plan.transfers:
                            i = index[transfer.source_series]
                            opening[i] -= min(float(transfer.quantity), max(0, float(opening[i])))
                    close(opening, sold + expired + overflow + on_hand, "Physical conservation")
                    batch_total = []
                    for batches in outcome["stock_batches_by_series"]:
                        if any(item["expiry_day"] <= trace["day"] or item["quantity"] <= 0 for item in batches):
                            raise AssertionError("Closing batches expired or nonpositive")
                        batch_total.append(sum(item["quantity"] for item in batches))
                    close(batch_total, on_hand, "Closing FIFO batch balance")
                    close(daily.loc[trace["day"], "cost"], sum(float(daily.loc[trace["day"], key]) for key in
                          ["purchase", "fixed_order", "transfer", "holding", "shortage", "spoilage"]), "Indexed cost components")
                    action = {"orders": [order.model_dump() for order in plan.orders],
                              "transfers": [move.model_dump() for move in plan.transfers]}
                    decisions.append({"arm": arm, "run": run.name, "scenario": scenario, "seed": seed,
                        "day": trace["day"], "committed": committed, "nonzero_action": any(order.quantity for order in plan.orders)
                        or any(move.quantity for move in plan.transfers), "proposed_spend": autonomy["inputs"].get("spend"),
                        "autonomy_level": autonomy["level"], "reasons": json.dumps(autonomy["reasons"]),
                        "hard_violations": len(violations), "action_hash": digest(action), "forecast_ref": refs.get("forecast"),
                        "recovery_requested": trace.get("recovery") is not None, "trace_ref": entry["trace_ref"]})
                db = sqlite3.connect(f"file:{run / 'artifacts/audit.sqlite'}?mode=ro", uri=True)
                for decision, stage, payload in db.execute("SELECT decision_id,stage,payload FROM events WHERE stage='llm_request_started'"):
                    ref = json.loads(payload)["output"]
                    attempt = reader.load(ref)
                    attempts.append({"arm": arm, "run": run.name, "decision_id": decision, "request_ref": ref,
                        "role": attempt.get("role"), "started_at_utc": attempt.get("started_at_utc"), "attempt": attempt.get("attempt")})
                db.close()
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "results.csv", index=False)
    pd.DataFrame(all_daily).to_csv(OUT / "daily.csv", index=False)
    pd.DataFrame(decisions).to_csv(OUT / "decisions.csv", index=False)
    pd.DataFrame(attempts).to_csv(OUT / "model_attempts.csv", index=False)
    means = frame.groupby(["arm", "scenario"]).agg(runs=("seed", "size"), cost=("cost", "mean"),
        fill_rate=("fill_rate", "mean"), stockout_rate=("stockout_rate", "mean"), mean_inventory=("mean_inventory", "mean"),
        held_decisions=("held_decisions", "mean"), executed_actions=("executed_actions", "mean"), hard_violations=("hard_violations", "sum"),
        llm_calls=("llm_calls", "sum"), tokens=("tokens", "sum"))
    means.reset_index().to_csv(OUT / "descriptive_means.csv", index=False)
    pairs = []
    for recovery in [False, True]:
        suffix = "recovery" if recovery else "no_recovery"
        for scenario in SCENARIOS:
            for seed in SEEDS:
                a = frame[(frame.arm == "llm_" + suffix) & (frame.scenario == scenario) & (frame.seed == seed)].iloc[0]
                b = frame[(frame.arm == "parser_" + suffix) & (frame.scenario == scenario) & (frame.seed == seed)].iloc[0]
                pair = {"recovery": recovery, "scenario": scenario, "seed": seed}
                for metric in ["cost", "fill_rate", "mean_inventory", "held_decisions", "hard_violations", "executed_actions"]:
                    pair[metric + "_llm_minus_parser"] = float(a[metric]) - float(b[metric])
                pair["all_primary_metrics_equal"] = all(abs(pair[metric + "_llm_minus_parser"]) < 1e-6 for metric in
                    ["cost", "fill_rate", "mean_inventory", "held_decisions", "hard_violations", "executed_actions"])
                pairs.append(pair)
    pd.DataFrame(pairs).to_csv(OUT / "paired_llm_parser.csv", index=False)
    previous = "0" * 64
    workflow_count = 0
    for line in (OUT / "workflow.jsonl").read_text().splitlines():
        record = json.loads(line)
        value = record.pop("hash")
        if record["previous_hash"] != previous or digest(record) != value:
            raise AssertionError("Follow-up owner workflow chain failed")
        previous = value
        workflow_count += 1
    receipt = {"status": "VERIFIED", "checked_at_utc": now(), "runs": EXPECTED_RUNS, "decisions": len(decisions),
        "objects_verified": objects, "event_count": sum(item["events"] for item in chain_proofs),
        "event_chains": chain_proofs, "owner_workflow_snapshot_records": workflow_count, "owner_workflow_snapshot_final_hash": previous,
        "autonomous_cap": protocol["autonomous_cap"], "selected_from_training_only": True,
        "primary_forecast_tensors_sha256": sha(PRIMARY / "shared/deep.pt"),
        "hard_violations": int(frame.hard_violations.sum()), "held_decisions": int(frame.held_decisions.sum()),
        "nonzero_action_days": int(frame.executed_actions.sum()), "fresh_llm_request_attempts": len(attempts),
        "recorded_llm_calls": int(frame.llm_calls.sum()), "tokens": int(frame.tokens.sum()), "llm_errors": int(frame.llm_errors.sum()),
        "llm_parser_equal_run_pairs": sum(pair["all_primary_metrics_equal"] for pair in pairs), "llm_parser_pairs": len(pairs),
        "primary_experiment_unchanged": True,
        "scope": "Exploratory gate portability follow-up, separate from primary and F3; no full natural-language or human audit claim"}
    atomic_json(OUT / "audit.json", receipt)
    audit("followup_read_only_audit_completed", {key: value for key, value in receipt.items() if key != "event_chains"})
    print(json.dumps(receipt, indent=2), flush=True)


def main():
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["register", "calibrate", "freeze", "parsers", "agents", "audit"])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        # Separate execution locks permit the explicitly authorized parser pool
        # and serial LLM phase to coexist after primary inference is complete.
        lock_name = args.phase if args.phase in {"parsers", "agents", "audit"} else "setup"
        with (OUT / f"{lock_name}.phase.lock").open("a") as owner_lock:
            fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            {"register": register, "calibrate": calibrate, "freeze": freeze,
             "parsers": parsers, "agents": agents, "audit": audit_results}[args.phase]()
    except BaseException as exc:
        failure = {"phase": args.phase, "at_utc": now(), "type": type(exc).__name__,
                   "message": str(exc), "traceback": traceback.format_exc()}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        atomic_json(OUT / "failures" / f"{args.phase}_{stamp}.json", failure)
        audit("followup_phase_failed_retained", failure)
        raise


if __name__ == "__main__":
    main()
