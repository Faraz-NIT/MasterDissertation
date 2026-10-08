"""Narrow, audited recovery from independently reconciled observed evidence.

This tool never receives a simulator, clean snapshot, evaluator problem or oracle.
``source_quantity`` and ``expected_inventory`` must already be present in the
observed snapshot. They represent simulated operational source/ledger evidence,
not measurements independently authenticated by this module. Freshness relies
on the supplied table-stage dates; the schema has no per-row source timestamp.

Recovery changes only derived inventory quantities. It cannot repair missing or
stale feeds, invent quantities, clear quality checks, or authorize an order.
The caller must use the returned snapshot's independently recomputed certificate
in its ordinary gate. The same tool can be made available to every policy.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from math import isfinite
from typing import Callable

from .config import GateConfig
from .quality import certify
from .schemas import Snapshot
from .util import digest


RECOVERY_VERSION = "observed-ledger-recovery-v1"
RECOVERY_ACTION = "reconcile_derived_inventory"
# Fixed absolute tolerance in inventory units; it cannot be changed by a model.
SOURCE_RECONCILIATION_TOLERANCE = 1e-8
RecordCallback = Callable[..., str]


def recover_snapshot(
    snapshot: Snapshot,
    gate: GateConfig,
    record: RecordCallback | None = None,
) -> tuple[Snapshot, dict]:
    """Return a new snapshot and an evidence report, preserving the observation.

    ``record(stage, object, inputs=())`` must persist the exact object and return
    its canonical content hash, as the orchestrator's recording callback does.
    If omitted, references remain computable but the report explicitly records
    that evidence has not been persisted. Successful recovery is a deterministic
    tool result, not evidence of successful model reasoning or order execution.
    """
    observed = snapshot.model_copy(deep=True)
    before_hash = digest(observed)
    certificate_before = certify(observed, gate)
    checks = {check.name: check for check in certificate_before.checks}

    def emit(stage: str, obj, inputs=()) -> str:
        expected_hash = digest(obj)
        if record is None:
            return expected_hash
        reference = record(stage, deepcopy(obj), inputs=tuple(inputs))
        if reference != expected_hash:
            raise ValueError("Recovery audit callback returned an invalid content reference")
        return reference

    observed_ref = emit("recovery_observed_snapshot", observed)
    before_certificate_ref = emit(
        "recovery_observed_certificate", certificate_before, [observed_ref]
    )
    catalog_ids = [series.series_id for series in observed.series]
    inventory_ids = [row.series_id for row in observed.inventory]
    catalog_locations = sorted({series.location for series in observed.series})
    reasons: list[str] = []
    evidence = {
        "decision_day": observed.lineage.day,
        "stage_days": dict(observed.stage_days),
        "catalog_series_ids": catalog_ids,
        "inventory_series_ids": inventory_ids,
        "source_row_count": observed.source_row_count,
        "loaded_row_count": len(observed.inventory),
        "catalog_locations": catalog_locations,
        "source_locations": list(observed.source_locations),
        "loaded_locations": list(observed.loaded_locations),
        "required_checks": {
            name: checks[name].model_dump()
            for name in ("stock_movement_balance", "inventory_distribution_shift")
        },
        "source_reconciliation_tolerance_units": SOURCE_RECONCILIATION_TOLERANCE,
        "rows": [],
    }
    required_anomaly = all(
        checks[name].outcome == "hard_fail"
        for name in ("stock_movement_balance", "inventory_distribution_shift")
    )
    if not required_anomaly:
        reasons.append("required_movement_and_derived_collapse_anomalies_absent")

    if not catalog_ids or len(set(catalog_ids)) != len(catalog_ids):
        reasons.append("empty_or_duplicate_catalog")
    if any(count != 1 for count in Counter(inventory_ids).values()):
        reasons.append("duplicate_inventory_records")
    if set(inventory_ids) != set(catalog_ids):
        reasons.append("incomplete_or_unknown_inventory_series")
    if observed.source_row_count != len(inventory_ids) or len(inventory_ids) != len(catalog_ids):
        reasons.append("source_inventory_count_mismatch")
    if (
        sorted(observed.source_locations) != catalog_locations
        or sorted(observed.loaded_locations) != catalog_locations
    ):
        reasons.append("incomplete_or_duplicate_location_coverage")
    # Movement reconciliation needs current inventory and current sales. The
    # product catalog supplies the identity/location coverage being checked.
    for stage in ("inventory", "sales", "products"):
        if observed.stage_days.get(stage) != observed.lineage.day:
            reasons.append(f"source_stage_not_current:{stage}")
    if set(observed.expected_inventory) != set(catalog_ids):
        reasons.append("incomplete_or_unknown_ledger_series")
    for index, row in enumerate(observed.inventory):
        expected = observed.expected_inventory.get(row.series_id)
        row_evidence = {
            "series_id": row.series_id,
            "quantity_ref": f"inventory[{index}].quantity",
            "quantity_before": row.quantity,
            "source_quantity_ref": f"inventory[{index}].source_quantity",
            "source_quantity": row.source_quantity,
            "ledger_ref": f"expected_inventory[{row.series_id!r}]",
            "ledger_expected": expected,
            "inventory_stage_ref": "stage_days['inventory']",
            "inventory_stage_day": observed.stage_days.get("inventory"),
            "reconciled": False,
        }
        evidence["rows"].append(row_evidence)
        if row.unit != "unit":
            reasons.append(f"unsupported_inventory_unit:{row.series_id}")
        if row.source_quantity is None:
            reasons.append(f"source_quantity_unavailable:{row.series_id}")
        elif not isfinite(row.source_quantity) or row.source_quantity < 0:
            reasons.append(f"source_quantity_invalid:{row.series_id}")
        if expected is None or not isfinite(expected) or expected < 0:
            reasons.append(f"ledger_quantity_unavailable_or_invalid:{row.series_id}")
        if row.source_quantity is not None and expected is not None:
            reconciled = (
                isfinite(row.source_quantity)
                and isfinite(expected)
                and abs(row.source_quantity - expected) <= SOURCE_RECONCILIATION_TOLERANCE
            )
            row_evidence["reconciled"] = reconciled
            if not reconciled:
                reasons.append(f"source_ledger_disagreement:{row.series_id}")

    reasons = sorted(set(reasons))
    precheck = {
        "version": RECOVERY_VERSION,
        "requested_action": RECOVERY_ACTION,
        "observed_snapshot_ref": observed_ref,
        "observed_certificate_ref": before_certificate_ref,
        "eligible": not reasons,
        "refusal_reasons": reasons,
        "evidence": evidence,
        "evidence_limitations": [
            "Source and ledger values are observations supplied by the simulator, not independently authenticated here.",
            "Freshness is checked from table-stage metadata; the observed schema has no per-row source timestamp.",
        ],
    }
    precheck_ref = emit(
        "recovery_precheck", precheck, [observed_ref, before_certificate_ref]
    )
    recovered = observed.model_copy(deep=True)
    changes = []
    if not reasons:
        for index, row in enumerate(recovered.inventory):
            if row.quantity != row.source_quantity:
                changes.append({
                    **evidence["rows"][index],
                    "quantity_after": row.source_quantity,
                })
                row.quantity = row.source_quantity
        # A previous certificate cannot certify the revised state. Preserve all
        # other lineage fields, and derive the new version from audited inputs.
        recovered.lineage.certificate_hash = ""
        recovered.lineage.snapshot_version = digest({
            "recovery_version": RECOVERY_VERSION,
            "action": RECOVERY_ACTION,
            "observed_snapshot_hash": before_hash,
            "precheck_ref": precheck_ref,
            "inventory_after": recovered.inventory,
        })
    recovered_ref = emit(
        "recovery_result_snapshot", recovered, [observed_ref, precheck_ref]
    )
    certificate_after = certify(recovered, gate)
    certificate_after_ref = emit(
        "recovery_result_certificate", certificate_after, [recovered_ref, precheck_ref]
    )
    report = {
        "version": RECOVERY_VERSION,
        "action": RECOVERY_ACTION,
        "status": "applied" if not reasons else ("not_applicable" if not required_anomaly else "refused"),
        "applied": not reasons,
        "refusal_reasons": reasons,
        "before_snapshot_hash": before_hash,
        "after_snapshot_hash": digest(recovered),
        "before_snapshot_version": observed.lineage.snapshot_version,
        "after_snapshot_version": recovered.lineage.snapshot_version,
        "changed_fields": changes,
        "quality_before": certificate_before.quality,
        "quality_after": certificate_after.quality,
        "hard_fail_before": certificate_before.hard_fail,
        "hard_fail_after": certificate_after.hard_fail,
        "certificate_before": certificate_before.model_dump(),
        "certificate_after": certificate_after.model_dump(),
        "audit_persisted": record is not None,
        "audit_refs": {
            "observed_snapshot": observed_ref,
            "observed_certificate": before_certificate_ref,
            "precheck": precheck_ref,
            "result_snapshot": recovered_ref,
            "result_certificate": certificate_after_ref,
        },
        "attribution": "deterministic evidence-reconciliation tool; model reasoning and replenishment benefit are not established",
    }
    emit("recovery_report", report, list(report["audit_refs"].values()))
    return recovered, report
