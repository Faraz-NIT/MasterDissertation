"""Read-only, independent final audit of the bounded FreshRetailNet study.

Run after both core execution_complete receipts. This script never calls a
model, modifies a source run, repairs failed evidence or guesses missing rows.
Existing published audit functions are loaded without their report entry point;
their hashes are included in the receipt. Current physical model attempts are
counted from request-before-HTTP events, not cache imports or repeated proofs.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/freshretailnet"
ARMS = ["parser_no_recovery", "parser_recovery", "llm_no_recovery", "llm_recovery"]
PUBLISHED_COMMIT = "0d281178d6f67f27b68d90d25b0b3d145cc2c24c"
ASSESS_FUNCTIONS = {"inverse", "signature", "active_rules", "score_numeric_call",
                    "score_recovery_selection", "verify_recovery"}
ASSESS_CONSTANTS = {"FIELDS", "TOKEN", "NUM", "PATTERNS", "PARAMETERS"}
TOLERANCE = 1e-6


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")), encoding="utf8")
    temporary.replace(path)


def close(a, b, label):
    if not np.allclose(a, b, atol=TOLERANCE, rtol=1e-9):
        raise ValueError(f"{label}: accounting or stored-value mismatch")


def helpers():
    report_path = ROOT / "scripts/cloud_study/m5_v2_report.py"
    assessor_path = ROOT / "scripts/cloud_study/m5_v2_assess.py"
    spec = importlib.util.spec_from_file_location("fresh_legacy_readonly_report", report_path)
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    report.REPO = ROOT
    # The published assessor imports a report at an archival absolute path.
    # Load only its unchanged, independently written literal-proof functions
    # and constants, injecting the portable report module loaded above.
    tree = ast.parse(assessor_path.read_text(), filename=str(assessor_path))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ASSESS_FUNCTIONS:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                and target.id in ASSESS_CONSTANTS for target in node.targets):
            nodes.append(node)
    assessor = ModuleType("fresh_independent_source_assessor")
    assessor.__dict__.update(report=report, re=re, math=math, json=json, Counter=Counter)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(assessor_path), "exec"), assessor.__dict__)
    return report, assessor, {
        str(report_path.relative_to(ROOT)): sha(report_path),
        str(assessor_path.relative_to(ROOT)): sha(assessor_path),
        str(Path(__file__).relative_to(ROOT)): sha(__file__),
    }


def independently_parse(document, assessor, report):
    """Independent inverse of the disclosed RULE and prose source carriers."""
    if set(document) != {"source_ref", "text", "authenticated", "sha256"}:
        raise ValueError("Unexpected source-document schema")
    if document["authenticated"] is not True or report.digest(document["text"]) != document["sha256"]:
        raise ValueError("Source-document authentication/text hash mismatch")
    rules = [line[5:] for line in document["text"].splitlines() if line.startswith("RULE ")]
    if not rules:
        return assessor.inverse(document)[0]
    if len(rules) != 1:
        raise ValueError("Expected exactly one disclosed RULE clause per document")
    values = [value.strip() for value in rules[0].split("|")]
    fields = ["constraint_id", "entity", "scope", "parameter", "value", "unit",
              "conversion", "aggregation", "valid_from", "valid_to", "precedence"]
    if len(values) != len(fields):
        raise ValueError("RULE clause field count differs")
    rule = dict(zip(fields, values))
    rule["value"] = float(rule["value"])
    rule["conversion"] = None if rule["conversion"] == "none" else float(rule["conversion"])
    for field in ["valid_from", "valid_to", "precedence"]:
        rule[field] = int(rule[field])
    rule["source_ref"] = document["source_ref"]
    if rule["parameter"] not in assessor.PARAMETERS or not math.isfinite(rule["value"]):
        raise ValueError("RULE parameter or numeric term is invalid")
    if rule["conversion"] is not None and not math.isfinite(rule["conversion"]):
        raise ValueError("RULE conversion is nonfinite")
    return {field: rule[field] for field in assessor.FIELDS}


def immutable_inputs(protocol, report):
    proofs = []

    def verify(path, expected, category):
        path = Path(path)
        actual = sha(path)
        if actual != expected:
            raise ValueError(f"Registered input changed: {path}")
        proofs.append({"path": str(path), "sha256": actual,
                       "bytes": path.stat().st_size, "category": category})

    if protocol.get("status") != "frozen":
        raise ValueError("Final audit requires a frozen protocol")
    for name, expected in protocol["source_sha256"].items():
        verify(ROOT / name, expected, "frozen_live_code")
        verify(OUT / "frozen_code" / name, expected, "frozen_code_copy")
    for entry in protocol["configs"].values():
        verify(entry["path"], entry["sha256"], "registered_configuration")
    for field, path in [
        ("selection_sha256", OUT / "data/selected_series.csv"),
        ("prepared_train_sha256", OUT / "data/selected_train.parquet"),
        ("source_train_sha256", ROOT / "data/raw/freshretailnet/train.parquet"),
        ("source_eval_sha256", ROOT / "data/raw/freshretailnet/eval.parquet"),
    ]:
        verify(path, protocol[field], "registered_data_input")
    prepared = load(OUT / "data/preparation_complete.json")
    if prepared["protocol_sha256"] != sha(OUT / "protocol.json"):
        raise ValueError("Prepared data and frozen protocol hash differ")
    for name, expected in prepared["files_sha256"].items():
        verify(ROOT / name, expected, "prepared_panel")
    models = load(OUT / "shared/model_identities.json")
    for name, entry in models.items():
        verify(entry["path"], entry["sha256"], "shared_forecast_model:" + name)
        if int(entry["training_end"]) >= int(protocol["official_holdout"]["origin"]):
            raise ValueError("A shared forecasting model includes evaluation days")
    # Preserve the already published M5 evidence and evaluated snapshots. These
    # comparisons use recorded publication hashes, never fresh self-assertions.
    verify(ROOT / "study_results/v1/M5_six_hour_study_report.pdf",
           "e3aab72f8bbe2eced7b4b54cd3630eace763d1521cc464711554d5ad1dc298ba", "protected_M5_report")
    publication = load(ROOT / "study_results/publication_validation.json")
    verify(ROOT / "study_results/v2/M5_v2_pilot_report.pdf", publication["v2_pdf_sha256"], "protected_M5_report")
    verify(ROOT / "results/v2_pilot/protocol.json",
           "e03bde91d8ce6811b0387a8ea78fad5d764ba8d57c6a403758f6a11cfec4b0af", "protected_M5_protocol")
    for name, expected in load(ROOT / "results/v2_pilot/frozen_source_inventory.json").items():
        verify(ROOT / "results/v2_pilot/frozen_code" / name, expected, "protected_M5_frozen_source")
    for name in ["scripts/cloud_study/m5_v2_report.py", "scripts/cloud_study/m5_v2_assess.py",
                 "study_results/v1/M5_six_hour_results.csv", "study_results/v2/M5_v2_results.csv"]:
        old = subprocess.check_output(["git", "show", f"{PUBLISHED_COMMIT}:{name}"], cwd=ROOT)
        verify(ROOT / name, hashlib.sha256(old).hexdigest(), "published_M5_git_blob")
    return proofs, models


def workflow_proof(report, study=OUT):
    previous = "0" * 64
    count = 0
    stages = Counter()
    for count, line in enumerate((study / "workflow.jsonl").read_text().splitlines(), start=1):
        entry = json.loads(line)
        current = entry.pop("hash")
        if entry.get("previous_hash") != previous or report.digest(entry) != current:
            raise ValueError(f"Workflow chain differs at record {count}")
        stages[entry["stage"]] += 1
        previous = current
    return {"chain_valid": True, "records": count, "final_hash": previous,
            "sha256": sha(study / "workflow.jsonl"), "stages": dict(stages),
            "scope": "Snapshot of workflow bytes read after core completion; later reporting records may append."}


def perishable_and_constraints(trace, reader, daily_row, config):
    from ega.optimization import check_plan
    from ega.schemas import Plan

    refs = trace["references"]
    outcome = reader.load(refs["outcome"])
    evaluation = reader.load(trace["evaluation"])
    receipt = reader.load(refs["receipt"])
    plan = reader.load(refs["propose"])
    problem = evaluation["true_problem"]
    n = int(outcome["pairs"])
    vectors = {}
    for key in ["sales_by_series", "lost_by_series", "on_hand_by_series", "age_expired_by_series",
                "capacity_overflow_by_series", "in_transit_expired_by_series", "spoilage_by_series"]:
        values = np.asarray(outcome[key], dtype=float)
        if values.shape != (n,) or not np.isfinite(values).all() or (values < -TOLERANCE).any():
            raise ValueError("Nonfinite, negative or misaligned physical outcome: " + key)
        vectors[key] = values
    spoiled = vectors["age_expired_by_series"] + vectors["capacity_overflow_by_series"] + vectors["in_transit_expired_by_series"]
    close(spoiled, vectors["spoilage_by_series"], "Per-series waste decomposition")
    for scalar, vector in [("sales", "sales_by_series"), ("lost_sales", "lost_by_series"),
                           ("on_hand", "on_hand_by_series"), ("age_expired_units", "age_expired_by_series"),
                           ("capacity_overflow_units", "capacity_overflow_by_series"),
                           ("in_transit_expired_units", "in_transit_expired_by_series"),
                           ("spoilage_units", "spoilage_by_series")]:
        close(outcome[scalar], vectors[vector].sum(), scalar)
    close(outcome["demand"], outcome["sales"] + outcome["lost_sales"], "Demand service")
    close(outcome["stockout_pairs"], np.sum(vectors["lost_by_series"] > 0), "Stockout-pair count")
    close(outcome["arrived_units"], outcome["received_units"] + outcome["in_transit_expired_units"], "Receipt acceptance/discard")
    batch_totals = []
    if len(outcome["stock_batches_by_series"]) != n:
        raise ValueError("Closing age-batch catalog differs")
    for row in outcome["stock_batches_by_series"]:
        for batch in row:
            if not math.isfinite(batch["quantity"]) or batch["quantity"] <= 0 or batch["expiry_day"] <= trace["day"]:
                raise ValueError("Closing stock has a nonpositive or already expired age batch")
        batch_totals.append(sum(batch["quantity"] for batch in row))
    close(batch_totals, vectors["on_hand_by_series"], "FIFO age batches/closing stock")
    cost = np.asarray(problem["parameters"]["unit_cost"], dtype=float)
    close(outcome["spoilage"], np.sum(spoiled * cost), "Waste valuation")
    close(outcome["holding"], np.sum(vectors["on_hand_by_series"] * cost * config["solver"]["holding_rate"]), "Holding valuation")
    close(outcome["shortage"], np.sum(vectors["lost_by_series"] * cost * config["solver"]["shortage_multiplier"]), "Shortage valuation")
    violations = []
    committed = receipt["status"] == "executed"
    nonzero = any(order["quantity"] for order in plan["orders"]) or any(move["quantity"] for move in plan["transfers"])
    if committed and nonzero:
        violations = check_plan(Plan.model_validate(plan), {**problem, "lineage": plan["lineage"]})
    if violations != evaluation["violations"] or len(violations) != int(daily_row["hard_violations"]):
        raise ValueError("Recomputed committed true-constraint violations differ")
    # True_problem is read ONLY for post-decision physical/constraint audit.
    # It is never supplied to a model, recovery tool or production planner.
    opening = np.asarray(problem["on_hand"], dtype=float).copy()
    ids = [series["series_id"] for series in problem["series"]]
    index = {series: i for i, series in enumerate(ids)}
    transfer_out = np.zeros(n)
    if committed:
        for move in plan["transfers"]:
            if move["source_series"] in index and move["destination_series"] in index:
                i = index[move["source_series"]]
                quantity = min(float(move["quantity"]), max(0.0, opening[i]))
                opening[i] -= quantity
                transfer_out[i] += quantity
    close(opening, vectors["sales_by_series"] + vectors["age_expired_by_series"]
          + vectors["capacity_overflow_by_series"] + vectors["on_hand_by_series"], "Daily physical mass balance")
    observed = reader.load(refs["observe"])
    sourced = [row for row in observed["inventory"] if row.get("source_quantity") is not None]
    source_mismatches = 0
    for row in sourced:
        agreed = np.isclose(row["source_quantity"], observed["expected_inventory"][row["series_id"]],
                            atol=TOLERANCE, rtol=1e-9)
        source_mismatches += not agreed
        # The registered feed-gap disturbance reuses previous source rows while
        # retaining the current movement ledger. This disagreement is evidence
        # for refusal, not physical-state corruption. Current source rows must
        # still agree with their independent ledger.
        if observed["stage_days"].get("inventory") == trace["day"] and not agreed:
            raise ValueError("A current source quantity disagrees with the movement ledger")
    for key in ["demand", "sales", "lost_sales", "on_hand", "spoilage_units", "holding", "shortage", "spoilage"]:
        close(outcome[key], float(daily_row[key]), "Outcome/daily " + key)
    close(float(daily_row["cost"]), sum(float(daily_row[key]) for key in
          ["purchase", "fixed_order", "transfer", "holding", "shortage", "spoilage"]), "Daily cost components")
    autonomy = reader.load(refs["autonomy"])
    proposed_spend = None
    if "problem" in refs:
        proposed_spend = independent_proposal_spend(plan, reader.load(refs["problem"]))
        if "spend" in autonomy["inputs"]:
            close(proposed_spend, autonomy["inputs"]["spend"], "Recorded proposed spend")
    if committed and config["agent_v2"]["enabled"]:
        if not autonomy["permitted"] or proposed_spend is None or proposed_spend > config["gate"]["max_spend"] + TOLERANCE:
            raise ValueError("Committed gated action lacks permission or exceeds its recorded autonomous cap")
    return {"physical_mass_balance_valid": True, "batch_stock_balance_valid": True,
            "cost_accounting_valid": True, "true_constraints_recomputed": True,
            "recomputed_hard_violations": len(violations), "committed": committed,
            "actual_transfer_out_units": float(transfer_out.sum()),
            "age_expired_units": outcome["age_expired_units"],
            "capacity_overflow_units": outcome["capacity_overflow_units"],
            "in_transit_expired_units": outcome["in_transit_expired_units"],
            "source_quantity_ledger_checked_rows": len(sourced),
            "source_quantity_ledger_mismatch_rows": int(source_mismatches),
            "proposed_spend": proposed_spend, "autonomy_level": autonomy["level"],
            "autonomy_reasons": autonomy["reasons"], "autonomous_cap": config["gate"]["max_spend"],
            "action_signature": json.dumps({"orders": sorted(plan["orders"], key=lambda order: order["series_id"]),
                                             "transfers": sorted(plan["transfers"], key=lambda move: (move["source_series"], move["destination_series"]))}, sort_keys=True)}


def independent_proposal_spend(plan, problem):
    """Direct arithmetic inverse of the stated spend definition, not gate code."""
    indices = {series["series_id"]: index for index, series in enumerate(problem["series"])}
    purchase = sum(float(order["quantity"]) * problem["parameters"]["unit_cost"][indices[order["series_id"]]]
                   for order in plan["orders"])
    transfer = sum(float(move["quantity"]) * problem["config"]["transfer_cost"] for move in plan["transfers"])
    suppliers = {order["supplier"] for order in plan["orders"] if order["quantity"] > 0}
    fixed = sum(problem["supplier_parameters"][supplier]["fixed_cost"] for supplier in suppliers)
    return float(purchase + transfer + fixed)


def followup_inputs(protocol, report, assessor, inventory):
    """Prove follow-up immutability and independently reproduce train-only cap."""
    study = OUT / "gate_transfer"
    if protocol["status"] != "frozen":
        raise ValueError("Follow-up audit requires its frozen protocol")
    primary = load(OUT / "protocol.json")
    proofs, models = immutable_inputs(primary, report)

    def verify(path, expected, category):
        path = Path(path)
        if sha(path) != expected:
            raise ValueError("Protected follow-up input changed: " + str(path))
        proofs.append({"path": str(path), "sha256": expected, "bytes": path.stat().st_size, "category": category})

    for name, entry in protocol["protected_inputs"].items():
        verify(entry["path"], entry["sha256"], "followup_protected:" + name)
    for name in ["owner_code", "owner_tests"]:
        entry = protocol["protected_inputs"][name]
        relative = Path(entry["path"]).relative_to(ROOT)
        verify(study / "frozen_code" / relative, entry["sha256"], "followup_frozen_owner_copy")
    verify(study / "calibration/selection_receipt.json", protocol["calibration_selection_sha256"], "cap_selection")
    verify(study / "calibration/proposed_spends.csv", protocol["calibration_proposals_sha256"], "cap_proposals")
    verify(OUT / "shared/deep.pt", protocol["evaluation_forecast_tensor_sha256"], "unchanged_primary_evaluation_model")
    if protocol["model"] != primary["model"]:
        raise ValueError("Follow-up changed the primary local model identity/profile")
    allowed = {"output", "gate.max_spend", "gate.version", "agent_v2.cache_path", "llm.spend_ledger", "seeds"}
    changes = []
    for arm, entry in protocol["configs"].items():
        verify(entry["path"], entry["sha256"], "followup_config:" + arm)
        config = load(entry["path"])
        differences = report.config_differences(load(OUT / f"configs/{arm}.json"), config)
        if {difference["field"] for difference in differences} - allowed:
            raise ValueError("Follow-up configuration changed more than registered cap/version/delivery/seed scope")
        if (config["gate"]["max_spend"] != protocol["autonomous_cap"]
                or config["gate"]["two_person_spend"] != protocol["evaluation"]["final_two_person_cap"]
                or config["seeds"] != protocol["evaluation"]["seeds"]):
            raise ValueError("Follow-up resolved cap/approval/seed settings differ from its protocol")
        changes.append({"arm": arm, "differences_from_primary": differences})
    calibration = study / "calibration"
    config = load(calibration / "resolved_config.json")
    run = calibration / "B4__normal__seed4242__origin0"
    source = load(run / "summary.json")
    result = report.audit_run("training_only_cap_calibration", calibration, source, config, inventory)
    reader = report.VerifiedReader(run, inventory)
    daily = pd.read_csv(run / "daily.csv").set_index("day")
    spends = []
    cases = []
    for entry in load(run / "trace_index.json"):
        trace = reader.load(entry["trace_ref"])
        checked = perishable_and_constraints(trace, reader, daily.loc[entry["day"]], config)
        if checked["proposed_spend"] is None:
            raise ValueError("Training-only calibration lacks one of its seven proposals")
        spends.append(checked["proposed_spend"])
        forecast = reader.load(trace["references"]["forecast"])
        if forecast["training_end"] != 75 or forecast["training_end"] >= trace["day"]:
            raise ValueError("Calibration forecaster includes future/evaluation values")
        documents = reader.load(trace["references"]["source_documents"])
        expected, conflicts = assessor.active_rules([independently_parse(document, assessor, report) for document in documents], entry["day"])
        actual = reader.load(trace["references"]["ground_constraints"])
        if conflicts or actual["issues"] or {assessor.signature(rule) for rule in expected} != {assessor.signature(rule) for rule in actual["constraints"]}:
            raise ValueError("Training cap calibration's independent source proof failed")
        cases.append({"day": entry["day"], "trace_ref": entry["trace_ref"], "proposed_spend": checked["proposed_spend"],
                      "source_clauses": len(documents), "physical_mass_balance_valid": True})
    selection = load(calibration / "selection_receipt.json")
    proposals = pd.read_csv(calibration / "proposed_spends.csv")
    if (len(spends) != 7 or sorted(proposals.day) != list(range(76, 83))
            or selection["selection_uses_official_eval"] is not False or selection["model_training_end"] != 75):
        raise ValueError("Training-only cap receipt has invalid time scope")
    close(spends, selection["proposed_spends"], "Independent calibration proposals/receipt")
    close(spends, proposals.proposed_spend_index.to_numpy(), "Independent calibration proposals/CSV")
    p95 = float(np.quantile(spends, .95, method="linear"))
    selected = min(.8 * float(config["solver"]["budget"]), float(math.ceil(1.10 * p95 / 50) * 50))
    close(selected, selection["selected_cap"], "Independent registered cap formula")
    close(selected, protocol["autonomous_cap"], "Selected cap/follow-up protocol")
    source_train = pd.read_parquet(OUT / "data/selected_train.parquet")
    series_ids = pd.read_csv(calibration / "train_only_panel/series.csv").series_id.tolist()
    expected_sales = source_train[source_train.day_index < 83].pivot(index="series_id", columns="day_index", values="sale_amount").loc[series_ids, range(83)].to_numpy() * 100
    actual_sales = np.load(calibration / "train_only_panel/sales.npy", allow_pickle=False)
    if actual_sales.shape != (30, 83) or not np.array_equal(actual_sales, expected_sales.astype(np.float32)):
        raise ValueError("Calibration panel is not the stated training-only normalized slice")
    if load(calibration / "train_only_panel/manifest.json")["latest_included_day"] != 82:
        raise ValueError("Calibration panel contains a later historical/evaluation day")
    registration = load(study / "registered_protocol.json")
    if not (registration["registered_at_utc"] <= selection["completed_at_utc"] <= protocol["frozen_at_utc"]):
        raise ValueError("Follow-up registration/calibration/freeze chronology differs")
    proof = {"status": "VERIFIED", "calibration_cases": cases, "proposed_spends": spends, "p95": p95,
             "independently_selected_cap": selected, "train_only_panel_shape": list(actual_sales.shape),
             "official_eval_values_in_calibration": False, "forecast_training_end": 75,
             "calibration_run_proof": result[4], "configuration_changes": changes,
             "interpretation": "Cap arithmetic is independently reproduced from training-only proposals. Follow-up remains exploratory because primary evaluation motivated it."}
    return proofs, models, proof


def compare_pairs(rows, decisions):
    pairs = []
    for recovery in [False, True]:
        suffix = "recovery" if recovery else "no_recovery"
        left_arm, right_arm = "llm_" + suffix, "parser_" + suffix
        left = {(row["scenario"], int(row["seed"]), int(row["origin"])): row for row in rows if row["arm"] == left_arm}
        right = {(row["scenario"], int(row["seed"]), int(row["origin"])): row for row in rows if row["arm"] == right_arm}
        if set(left) != set(right):
            raise ValueError("Matched parser/LLM run grids differ")
        for identity in sorted(left):
            a, b = left[identity], right[identity]
            ad = sorted([d for d in decisions if d["arm"] == left_arm and d["run"] == Path(a["source_run_path"]).name], key=lambda d: d["day"])
            bd = sorted([d for d in decisions if d["arm"] == right_arm and d["run"] == Path(b["source_run_path"]).name], key=lambda d: d["day"])
            metrics = ["cost", "fill_rate", "mean_inventory", "stockout_rate", "hard_violations", "held_decisions", "executed_actions"]
            differences = {metric: float(a[metric]) - float(b[metric]) for metric in metrics}
            action_matches = [x["committed"] == y["committed"] and x["action_signature"] == y["action_signature"] for x, y in zip(ad, bd)]
            pairs.append({"recovery_enabled": recovery, "scenario": identity[0], "seed": identity[1], "origin": identity[2],
                          "llm_arm": left_arm, "parser_arm": right_arm, "days": len(ad),
                          **{metric + "_llm_minus_parser": value for metric, value in differences.items()},
                          "all_primary_metrics_equal": all(abs(value) <= TOLERANCE for value in differences.values()),
                          "action_days_equal": sum(action_matches), "all_action_days_equal": len(ad) == len(bd) and all(action_matches),
                          "interpretation": "Descriptive matched simulation comparison; equality is not a statistical noninferiority proof."})
    return pairs


def csv_write(path, records):
    frame = pd.DataFrame([{key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value
                          for key, value in row.items()} for row in records])
    if frame.empty and Path(path).name == "model_error_events.csv":
        frame = pd.DataFrame(columns=["arm", "run", "day", "artifact_ref", "role", "started_at_utc", "attempt", "error", "model_revision"])
    frame.to_csv(path, index=False)


def audit_stage_compact(label, stage_root, inventory, report, allow_partial=False):
    """Use published per-run proofs while bounding retained event memory.

    Every original object and chain event is still verified. Only physical
    request starts and model-validation events need to remain in memory for
    the second scoring pass; cache/source events remain in the original logs.
    This avoids holding hundreds of thousands of redundant proof objects when
    auditing the expanded four-arm grid.
    """
    stage_root = Path(stage_root)
    config_path = stage_root / "resolved_config.json"
    config = load(config_path)
    inventory[str(config_path)] = {"sha256": sha(config_path), "bytes": config_path.stat().st_size}
    summary_path = stage_root / "summary.csv"
    if not summary_path.exists():
        if not allow_partial:
            raise ValueError("Registered arm has no completed summary: " + label)
        source_rows = []
    else:
        inventory[str(summary_path)] = {"sha256": sha(summary_path), "bytes": summary_path.stat().st_size}
        with summary_path.open(newline="") as stream:
            source_rows = list(csv.DictReader(stream))
    identities = [report.row_identity(row) for row in source_rows]
    expected = report.expected_grid(config)
    if len(set(identities)) != len(identities) or set(identities) - expected:
        raise ValueError("Duplicate or unconfigured run identity in " + label)
    missing = expected - set(identities)
    if missing and not allow_partial:
        raise ValueError(f"{label}: {len(missing)} registered runs are missing")
    rows, traces, calls, events, proofs = [], [], [], [], []
    for source in source_rows:
        clean, trace_rows, call_rows, original_events, proof = report.audit_run(label, stage_root, source, config, inventory)
        rows.append(clean)
        traces.extend(trace_rows)
        calls.extend(call_rows)
        events.extend(event for event in original_events if event["stage"] == "llm_request_started"
                      or event["mechanism"] == "grounding_v2_validation")
        proofs.append(proof)
    stage = {"label": label, "root": str(stage_root), "config": config,
             "status": "PARTIAL" if missing else "COMPLETE", "expected_runs": len(expected),
             "completed_runs": len(rows), "missing_grid": [list(identity) for identity in sorted(missing)],
             "configured_days": config["days"], "seeds": config["seeds"], "scenarios": config["scenarios"],
             "policies": config["policies"], "origins": config["origins"], "start_day": config["start_day"],
             "model": config["llm"], "agent_v2": config["agent_v2"],
             "event_memory_note": "All original events verified; only request starts and numeric-validation events retained for scoring."}
    return stage, rows, traces, calls, events, proofs


def audit(allow_partial=False, followup=False):
    study = OUT / "gate_transfer" if followup else OUT
    target = study / "audit_independent" if followup else study / "audit"
    target.mkdir(parents=True, exist_ok=True)
    log = target / "audit.log"
    with log.open("a") as stream:
        stream.write("Read-only audit started " + datetime.now(timezone.utc).isoformat() + "\n")

    def progress(text):
        with log.open("a") as stream:
            stream.write(text + "\n")
        print(text, flush=True)

    report, assessor, helper_hashes = helpers()
    protocol = load(study / "protocol.json")
    if not allow_partial:
        complete_paths = [study / "execution_complete.json"] if followup else [study / "numerical/execution_complete.json", study / "agents/execution_complete.json"]
        for path in complete_paths:
            if load(path)["status"] != "COMPLETE":
                raise ValueError("Final audit requires complete execution receipts")
    inventory = {}
    calibration_proof = None
    if followup:
        immutable, models, calibration_proof = followup_inputs(protocol, report, assessor, inventory)
    else:
        immutable, models = immutable_inputs(protocol, report)
    progress(f"Registered and protected inputs verified: {len(immutable)}")
    stages, rows, traces, calls, events, run_proofs = [], [], [], [], [], []
    configs = {}
    stage_paths = [(arm, study / "agents" / arm) for arm in ARMS]
    if not followup:
        stage_paths.insert(0, ("numerical", study / "numerical"))
    for label, path in stage_paths:
        result = audit_stage_compact(label, path, inventory, report, allow_partial=allow_partial)
        stage, results, trace_rows, call_rows, v2_events, proofs = result
        configs[label] = stage["config"]
        stages.append(stage)
        rows.extend(results)
        traces.extend(trace_rows)
        calls.extend(call_rows)
        events.extend(v2_events)
        run_proofs.extend(proofs)
        progress(f"{label}: {stage['status']}, {len(results)} runs, {len(trace_rows)} decisions, {sum(p['object_count'] for p in proofs)} objects")
    source_counts = defaultdict(Counter)
    grounding, numeric_calls, selectors, recoveries, decisions, attempts, errors = [], [], [], [], [], [], []
    proofs_by_key = {(proof["arm"], proof["run"]): proof for proof in run_proofs}
    traces_by_key = defaultdict(list)
    events_by_key = defaultdict(list)
    for entry in traces:
        traces_by_key[(entry["arm"], entry["run"])].append(entry)
    for event in events:
        events_by_key[(event["arm"], event["run"], event["decision_id"])].append(event)
    seen_calls = set()
    for number, ((arm, run), trace_rows) in enumerate(traces_by_key.items(), start=1):
        reader = report.VerifiedReader(proofs_by_key[(arm, run)]["path"], inventory)
        daily = pd.read_csv(reader.run / "daily.csv").set_index("day")
        for row in trace_rows:
            trace = reader.load(row["trace_ref"])
            decision_events = events_by_key[(arm, run, row["decision_id"])]
            physical = perishable_and_constraints(trace, reader, daily.loc[row["day"]], configs[arm])
            decisions.append({"arm": arm, "run": run, "day": row["day"], **physical})
            documents = reader.load(trace["references"]["source_documents"])
            docs = {document["source_ref"]: document for document in documents}
            if len(docs) != len(documents):
                raise ValueError("Decision source identities are duplicated")
            expected, conflicts = assessor.active_rules([independently_parse(document, assessor, report) for document in documents], row["day"])
            expected_set = {assessor.signature(rule) for rule in expected}
            count = source_counts[arm]
            count["decisions"] += 1
            count["available_source_exposures"] += len(documents)
            count["independently_parsed_source_exposures"] += len(documents)
            actual_ref = trace["references"].get("ground_constraints")
            if actual_ref:
                actual = reader.load(actual_ref)
                actual_list = [assessor.signature(rule) for rule in actual["constraints"]]
                actual_set = set(actual_list)
                exact, false, omitted = expected_set & actual_set, actual_set - expected_set, expected_set - actual_set
                complete = expected_set == actual_set and len(actual_list) == len(actual_set) and not actual["issues"] and not conflicts
                case = {"arm": arm, "run": run, "day": row["day"], "sources": len(documents),
                        "expected_active_rules": len(expected_set), "recorded_active_rules": len(actual_set),
                        "exact_active_rules": len(exact), "false_active_rules": len(false), "omitted_active_rules": len(omitted),
                        "duplicate_recorded_rules": len(actual_list) - len(actual_set),
                        "complete_source_set_exact": complete, "issues": actual["issues"], "source_conflicts": conflicts}
                grounding.append(case)
                count["grounding_attempted_decisions"] += 1
                count["complete_source_set_exact_decisions"] += complete
                for key in ["sources", "expected_active_rules", "recorded_active_rules", "exact_active_rules",
                            "false_active_rules", "omitted_active_rules", "duplicate_recorded_rules"]:
                    count[key] += case[key]
                if physical["committed"] and (actual["issues"] or conflicts or false or omitted):
                    raise ValueError("Committed action consumed an incomplete or false source-grounded set")
            else:
                count["state_gated_unattempted_decisions"] += 1
                count["state_gated_unattempted_source_exposures"] += len(documents)
            validations = {ref: event["artifact"] for event in decision_events
                           if event["mechanism"] == "grounding_v2_validation"
                           for ref in event["artifact"].get("llm_refs", [])}
            for event in decision_events:
                if event["stage"] != "llm_request_started":
                    continue
                started = event["artifact"]
                if (started.get("model_revision") != protocol["model"]["digest"]
                        or started.get("request", {}).get("model") != protocol["model"]["name"]):
                    raise ValueError("Recorded physical attempt differs from registered model identity")
                attempts.append({"arm": arm, "run": run, "day": row["day"], "decision_id": row["decision_id"],
                                 "started_ref": event["payload"]["output"], "role": started["role"],
                                 "started_at_utc": started["started_at_utc"], "attempt": started["attempt"],
                                 "model_revision": started["model_revision"], "requested_model": started["request"]["model"],
                                 "request_sha256": report.digest(started["request"])})
            for ref in trace["llm"]["artifacts"]:
                call = reader.load(ref)
                if call.get("kind") not in {"llm_request_started", "llm_call", "llm_error"}:
                    continue
                leakage = report.discover_keys(call.get("request", {}))
                for payload in report.request_payloads(call.get("request", {})):
                    leakage.extend(report.discover_keys(payload))
                if leakage:
                    raise ValueError("Hidden evaluator context in recorded model request: " + str(leakage))
                if call.get("kind") == "llm_error":
                    errors.append({"arm": arm, "run": run, "day": row["day"], "artifact_ref": ref,
                                   "role": call.get("role"), "started_at_utc": call.get("started_at_utc"),
                                   "attempt": call.get("attempt"), "error": call.get("error"),
                                   "model_revision": call.get("model_revision")})
                if call.get("kind") != "llm_call":
                    continue
                if ref in seen_calls:
                    raise ValueError("Physical response duplicated across traces")
                seen_calls.add(ref)
                payloads = report.request_payloads(call["request"])
                if any("allowed_tools" in payload for payload in payloads):
                    result = assessor.score_recovery_selection(call)
                    selectors.append({"arm": arm, "run": run, "day": row["day"], "artifact_ref": ref, **result})
                    count["physical_selector_calls"] += 1
                    count["instruction_compliant_selector_calls"] += result["instruction_compliant"]
                    count["selector_semantic_error_calls"] += not result["instruction_compliant"]
                elif any(payload.get("documents") for payload in payloads):
                    attempt = "repair" if any("validation_errors" in payload or "correction_task" in payload for payload in payloads) else "initial"
                    result = assessor.score_numeric_call(call, docs, attempt)
                    accepted = validations.get(ref, {}).get("accepted")
                    if accepted is True and not result["complete_exact_numeric_batch"]:
                        raise ValueError("Production accepted an independently false numeric extraction")
                    numeric_calls.append({"arm": arm, "run": run, "day": row["day"], "artifact_ref": ref,
                                          "pipeline_validation_accepted": accepted, **result})
                    count["physical_extraction_calls"] += 1
                    count[attempt + "_extraction_calls"] += 1
                    for key in ["submitted_terms", "returned_terms", "exact_numeric_terms", "false_numeric_terms", "omitted_terms"]:
                        count[key] += result[key]
                else:
                    raise ValueError("Unexpected live model task outside registered extraction/selection")
            if trace.get("recovery"):
                result = assessor.verify_recovery(trace, reader, configs[arm]["gate"])
                recoveries.append({"arm": arm, "run": run, "day": row["day"], **result})
                if result["problems"]:
                    raise ValueError("Independent recovery proof failed: " + str(result["problems"]))
                count["recovery_tool_invocations"] += 1
                count["recovery_applied"] += result["applied"]
                count["recovery_derived_quantities_changed"] += result["changed_quantities"]
        if number % 30 == 0:
            progress(f"Physical, source and committed-action audit: {number}/{len(traces_by_key)} runs")
    counts = []
    for arm, counter in source_counts.items():
        record = {"arm": arm, **dict(counter)}
        for label, numerator, denominator in [
            ("active_rule_precision", "exact_active_rules", "recorded_active_rules"),
            ("active_rule_recall", "exact_active_rules", "expected_active_rules"),
            ("model_numeric_term_precision", "exact_numeric_terms", "returned_terms"),
            ("model_numeric_term_recall", "exact_numeric_terms", "submitted_terms"),
            ("eligible_complete_source_coverage", "complete_source_set_exact_decisions", "grounding_attempted_decisions"),
        ]:
            record[label] = counter[numerator] / counter[denominator] if counter[denominator] else None
        counts.append(record)
    pairs = compare_pairs(rows, decisions)
    workflow = workflow_proof(report, study)
    client_attempts = sum(int(row["llm_calls"]) for row in rows)
    if len(attempts) != client_attempts or len({attempt["started_ref"] for attempt in attempts}) != len(attempts):
        raise ValueError("Physical pre-HTTP attempts differ from independent run counters")
    if sum(call["tokens"] for call in calls) != sum(int(row["tokens"]) for row in rows):
        raise ValueError("Recorded model-response tokens differ from run counters")
    if (len(errors) != sum(int(row["llm_errors"]) for row in rows)
            or len(errors) != sum(proof["event_stages"].get("llm_request_error", 0) for proof in run_proofs)):
        raise ValueError("Independent model error objects/events differ from run counters")
    if any(call["model_revision"] != protocol["model"]["digest"] for call in calls):
        raise ValueError("Response metadata differs from the registered model revision")
    expected_runs = protocol["evaluation"]["expected_runs"] if followup else protocol["numerical"]["expected_runs"] + protocol["agent_factorial"]["expected_runs"]
    expected_decisions = protocol["evaluation"]["expected_decisions"] if followup else protocol["numerical"]["expected_decisions"] + protocol["agent_factorial"]["expected_decisions"]
    if not allow_partial and (len(rows) != expected_runs or len(traces) != expected_decisions):
        raise ValueError("Registered completed-run/decision totals differ")
    totals = {"runs": len(rows), "decisions": len(traces), "numerical_runs": sum(row["arm"] == "numerical" for row in rows),
              "agent_runs": sum(row["arm"] != "numerical" for row in rows),
              "objects_sha256_verified": sum(proof["object_count"] for proof in run_proofs),
              "sqlite_events_hash_verified": sum(proof["chain_event_count"] for proof in run_proofs),
              "physical_API_attempts": len(attempts), "physical_API_response_records": len(calls),
              "tokens": sum(call["tokens"] for call in calls), "client_or_schema_error_events": len(errors),
              "physical_extraction_responses": len(numeric_calls), "physical_selector_responses": len(selectors),
              "forbidden_model_context_findings": 0, "committed_true_constraint_violations": sum(int(row["hard_violations"]) for row in rows),
              "held_decisions": sum(int(row["held_decisions"]) for row in rows),
              "physical_mass_balance_cases_passed": len(decisions), "recovery_tool_invocations": len(recoveries),
              "recovery_applied": sum(case["applied"] for case in recoveries),
              "selector_instruction_compliant": sum(case["instruction_compliant"] for case in selectors),
              "selector_semantic_error_responses": sum(not case["instruction_compliant"] for case in selectors),
              "parser_llm_matched_pairs": len(pairs), "parser_llm_pairs_primary_metrics_equal": sum(pair["all_primary_metrics_equal"] for pair in pairs),
              "parser_llm_pairs_all_action_days_equal": sum(pair["all_action_days_equal"] for pair in pairs)}
    tables = {"run_summary.csv": rows, "decision_audit.csv": decisions, "model_calls.csv": calls,
              "physical_attempts.csv": attempts, "grounding_cases.csv": grounding,
              "model_error_events.csv": errors,
              "grounding_aggregates.csv": counts, "selector_calls.csv": selectors, "parser_llm_pairs.csv": pairs}
    for name, records in tables.items():
        csv_write(target / name, records)
    json_write(target / "numeric_extraction_cases.json", numeric_calls)
    json_write(target / "recovery_cases.json", recoveries)
    with gzip.open(target / "input_hashes.json.gz", "wt", encoding="utf8") as stream:
        json.dump(inventory, stream, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    result = {"schema_version": "freshretailnet-independent-audit-v1",
              "status": "VERIFIED_COMPLETE" if all(stage["status"] == "COMPLETE" for stage in stages) else "VERIFIED_PARTIAL",
              "generated_at_utc": datetime.now(timezone.utc).isoformat(), "source_protocol_sha256": sha(study / "protocol.json"),
              "study_scope": "exploratory_training_calibrated_gate_transfer" if followup else "locked_primary_study",
              "helper_sha256": helper_hashes, "totals": totals, "stages": stages, "run_proofs": run_proofs,
              "grounding_aggregates": counts, "workflow_proof": workflow, "immutable_input_proofs": immutable,
              "shared_model_proofs": models, "parser_llm_pairs": pairs,
              "independent_training_cap_proof": calibration_proof,
              "tables_sha256": {name: sha(target / name) for name in tables},
              "methods": ["Original objects are checked against canonical bytes and SHA256 content addresses, with read-only SQLite chain verification.",
                          "Independent literal inverse and validity/precedence resolver prove source tuples; source counts come from actual documents.",
                          "Recorded physical API starts are distinct from response records, schema errors, cache reuses and source exposures.",
                          "Committed action feasibility and physical accounting use evaluator evidence only after decisions; recovery proofs use observed inputs only.",
                          "Natural source stockouts do not reveal unobserved true demand; simulated spoilage and cost indices are conditional assumptions."],
              "limitations": ["Local hashes provide tamper detection, not signed or WORM storage.",
                              "The capable parser recognizes the disclosed grammar; model/parser equality does not establish general semantic superiority.",
                              "The core optimizer remains age-unaware; physical FIFO expiry is distinct from the independent age-aware policy sensitivity.",
                              "Live-agent comparisons use one seven-day origin; primary has two seeds and gate-transfer follow-up is exploratory even if its seed grid is expanded."]}
    json_write(target / "audit.json", result)
    progress(json.dumps({"status": result["status"], "totals": totals}, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-partial", action="store_true", help="Audit explicitly labeled completed-run snapshots; never marks an incomplete grid complete.")
    parser.add_argument("--followup", action="store_true", help="Audit the separately registered gate-transfer grid and reproduce its training-only cap, preserving primary audit outputs.")
    parser.add_argument("--self-check", action="store_true", help="Check portable helper loading and both source inverses without opening evaluation results.")
    args = parser.parse_args()
    if args.self_check:
        report, assessor, hashes = helpers()
        from ega.constraints import synthetic_contracts, render_templates
        from ega.agents.grounding_v2 import render_hybrid_prose
        from ega.schemas import Series
        series = [Series(series_id="A@S1", item_id="A", department="D", family="F", location="S1", cluster="C", supplier="SUP")]
        contracts = synthetic_contracts(series, [1.0], [True], 62, 4242, "normal", False, 3000)
        expected = {assessor.signature(contract.model_dump()) for contract in contracts}
        for variant in [0, 1]:
            for carrier in [render_templates, render_hybrid_prose]:
                actual = {assessor.signature(independently_parse(document.payload(), assessor, report)) for document in carrier(contracts, variant)}
                if actual != expected:
                    raise ValueError("Independent source inverse self-check failed")
        print(json.dumps({"status": "PASS", "carrier_variant_cases": 4, "clauses_per_case": len(contracts), "helper_sha256": hashes}))
        return
    try:
        audit(args.allow_partial, args.followup)
    except BaseException as exc:
        failure = {"status": "AUDIT_FAILED", "at_utc": datetime.now(timezone.utc).isoformat(),
                   "error_type": type(exc).__name__, "message": str(exc), "source_runs_modified": False}
        target = OUT / "gate_transfer/audit_independent" if args.followup else OUT / "audit"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        json_write(target / f"failures/audit_failure_{stamp}.json", failure)
        json_write(target / "audit_failure.json", failure)
        with (target / "audit.log").open("a") as stream:
            stream.write(json.dumps(failure, sort_keys=True) + "\n")
        raise


if __name__ == "__main__":
    main()
