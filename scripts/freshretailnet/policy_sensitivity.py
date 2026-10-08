"""Bounded native-unit FreshRetailNet policy and valid-stockout gate sensitivities.

These uncoupled calculators are separate from the authoritative MILP experiment.
All costs, shelf lives, supply and hidden demand multipliers are assumptions.
No policy receives a future historical stockout flag or realized evaluation sale.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SAFETY_FACTOR = 1.2816
FULFILLMENT = 0.98
RECOVERY_FORECAST_METHOD = {
    "raw_zero": "lightgbm_raw",
    "profile": "lightgbm_profile_recovered",
    "gbm": "lightgbm_gbm_recovered",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temp.replace(path)


def require_frozen_inputs(base: Path) -> tuple[dict, dict]:
    """Check authorization of final evaluation before any eval file is opened."""
    protocol_path = base / "protocol.json"
    selection_path = base / "forecast/selection_receipt.json"
    if not protocol_path.is_file():
        raise RuntimeError("Final evaluation blocked: protocol.json is absent")
    protocol = json.loads(protocol_path.read_text())
    if protocol.get("status") != "frozen":
        raise RuntimeError("Final evaluation blocked: protocol must be frozen")
    if not selection_path.is_file():
        raise RuntimeError("Final evaluation blocked: validation selection receipt is absent")
    selection = json.loads(selection_path.read_text())
    if selection.get("recovery", {}).get("method") not in RECOVERY_FORECAST_METHOD:
        raise RuntimeError("Unknown preselected recovery method; no eval-based fallback allowed")
    return protocol, selection


def keyed_uniform(seed: int, day: int, series_id: str) -> float:
    """Policy-independent supply draw, indexed by the business opportunity."""
    blob = f"FRN-F3-supply-v1:{seed}:{day}:{series_id}".encode()
    return int.from_bytes(hashlib.sha256(blob).digest()[:8], "big") / 2**64


def supply_delay(seed: int, day: int, series_id: str) -> int:
    x = keyed_uniform(seed, day, series_id)
    return 1 if x < 0.90 else 2 if x < 0.98 else 3


def seasonal_sigma(training: np.ndarray) -> np.ndarray:
    """Common train-only scale from weekly seasonal residuals, native units."""
    if training.ndim != 2 or training.shape[1] < 14:
        raise ValueError("Training matrix must have at least fourteen dates")
    residuals = training[:, 7:] - training[:, :-7]
    scale = np.std(residuals, axis=1, ddof=1)
    if not np.isfinite(scale).all():
        raise ValueError("Non-finite training residual scale")
    return scale


def target_quantity(
    forecast: np.ndarray, day: int, sigma: np.ndarray, shelf_life: int, calculator: str
) -> np.ndarray:
    """Lead-one/review-one target; a stated safety factor, not calibrated coverage.

    order_up_to covers today and tomorrow. age_aware targets the receipt horizon
    starting tomorrow, caps its cover at shelf life, and projects today's stock.
    The frozen seven-day profile repeats by weekday beyond the released horizon.
    """
    if calculator not in {"order_up_to", "age_aware"}:
        raise ValueError(f"Unknown calculator {calculator}")
    cover = 2 if calculator == "order_up_to" else min(shelf_life, 2)
    start = day if calculator == "order_up_to" else day + 1
    columns = [(start + k) % forecast.shape[1] for k in range(cover)]
    return forecast[:, columns].sum(axis=1) + SAFETY_FACTOR * math.sqrt(cover) * sigma


def expected_expiring_after_service(buckets: np.ndarray, mean_today: np.ndarray) -> np.ndarray:
    """Oldest-first expected sale before end-day expiry, using forecast only."""
    # Only the oldest bucket expires at this day end. Younger stock cannot
    # satisfy demand ahead of it under FIFO, so its expected residual is exact
    # under a deterministic mean-demand projection.
    return np.maximum(0.0, buckets[:, -1] - mean_today)


def simulate(
    series_ids: list[str],
    dates: list[str],
    forecast: np.ndarray,
    demand_proxy: np.ndarray,
    training_mean: np.ndarray,
    sigma: np.ndarray,
    initial_observed_stockout: np.ndarray,
    *,
    seed: int,
    shelf_life: int,
    demand_multiplier: float,
    calculator: str,
    gate: str = "censoring_aware",
) -> tuple[dict, list[dict], list[dict]]:
    """Simulate an arm using evaluator-only demand and shared supply opportunities.

    Receipt age zero serves on its arrival day, then remaining goods age. Goods
    expire after their L-th service opportunity. Opening stock is given equally
    across arms and evenly across ages; purchase is charged at order placement.
    """
    n, horizon = forecast.shape
    if demand_proxy.shape != forecast.shape or len(series_ids) != n or len(dates) != horizon:
        raise ValueError("Forecast, evaluator demand and identity shapes disagree")
    if shelf_life < 1 or demand_multiplier <= 0 or gate not in {"censoring_aware", "naive_stockout_hold"}:
        raise ValueError("Invalid simulation scenario")
    if np.any(forecast < 0) or np.any(demand_proxy < 0):
        raise ValueError("Negative sales/forecast values")

    opening = 2 * training_mean.astype(float)
    buckets = np.repeat((opening / shelf_life)[:, None], shelf_life, axis=1)
    pipeline: list[tuple[int, int, float, float]] = []  # actual arrival, series, delivered, paid ordered
    previous_stockout = initial_observed_stockout.astype(bool).copy()
    daily_rows: list[dict] = []
    series_rows: list[dict] = []
    order_history = []
    demand_history = []
    maximum_error = 0.0

    for day in range(horizon):
        start = buckets.sum(axis=1)
        received = np.zeros(n)
        retained = []
        for arrival, index, delivered, paid in pipeline:
            if arrival == day:
                received[index] += delivered
            else:
                retained.append((arrival, index, delivered, paid))
        pipeline = retained
        buckets[:, 0] += received
        available = buckets.sum(axis=1)
        outstanding = np.zeros(n)
        for _, index, delivered, _ in pipeline:
            outstanding[index] += delivered
        position = available + outstanding
        if calculator == "age_aware":
            # Project stock at the next-day receipt opportunity using the
            # approved forecast, not evaluator demand. Stock consumed today or
            # expired tonight cannot cover the receipt's future demand horizon.
            expected_service = np.minimum(available, forecast[:, day])
            position = available - expected_service - expected_expiring_after_service(buckets, forecast[:, day]) + outstanding
        target = target_quantity(forecast, day, sigma, shelf_life, calculator)
        proposed = np.maximum(0.0, target - position)
        held = previous_stockout.copy() if gate == "naive_stockout_hold" else np.zeros(n, dtype=bool)
        ordered = np.where(held, 0.0, proposed)
        ordered[ordered < 1e-12] = 0.0
        lead_days = np.array([supply_delay(seed, day, sid) for sid in series_ids])
        for index, quantity in enumerate(ordered):
            if quantity > 0:
                pipeline.append((day + int(lead_days[index]), index, FULFILLMENT * float(quantity), float(quantity)))

        # Evaluator demand is accessed only after the committed order above.
        demand = demand_proxy[:, day] * demand_multiplier
        remaining = demand.copy()
        for age in range(shelf_life - 1, -1, -1):
            take = np.minimum(buckets[:, age], remaining)
            buckets[:, age] -= take
            remaining -= take
        lost = np.maximum(0.0, remaining)
        served = demand - lost
        expired = buckets[:, -1].copy()
        buckets[:, -1] = 0.0
        if shelf_life > 1:
            buckets[:, 1:] = buckets[:, :-1].copy()
        buckets[:, 0] = 0.0
        end = buckets.sum(axis=1)
        mass_error = start + received - served - expired - end
        maximum_error = max(maximum_error, float(np.abs(mass_error).max(initial=0.0)))
        if np.abs(mass_error).max(initial=0.0) > 1e-9:
            raise AssertionError("Physical inventory conservation failed")
        if np.any(buckets < -1e-10):
            raise AssertionError("Negative physical age bucket")

        purchase_cost = ordered
        fixed_cost = (ordered > 0).astype(float) * 0.02
        holding_cost = end * 0.015
        shortage_cost = lost * 5
        expiry_cost = expired  # hypothetical indexed penalty
        total_cost = purchase_cost + fixed_cost + holding_cost + shortage_cost + expiry_cost
        expected_unfulfilled = ordered * (1 - FULFILLMENT)
        pending_quantity = np.zeros(n)
        for _, index, quantity, _ in pipeline:
            pending_quantity[index] += quantity

        for index, sid in enumerate(series_ids):
            series_rows.append({
                "day": day, "dt": dates[day], "series_id": sid,
                "forecast_mean": float(forecast[index, day]), "target": float(target[index]),
                "opening_on_hand": float(start[index]), "receipt_quantity": float(received[index]),
                "available_before_sales": float(available[index]), "proposed_order": float(proposed[index]),
                "ordered_quantity": float(ordered[index]), "simulated_lead_days": int(lead_days[index]),
                "valid_previous_stockout": bool(previous_stockout[index]),
                "hold_due_to_valid_stockout": bool(held[index]),
                "evaluator_demand_proxy": float(demand_proxy[index, day]), "simulated_demand": float(demand[index]),
                "served_quantity": float(served[index]), "lost_quantity": float(lost[index]),
                "expired_quantity": float(expired[index]), "closing_on_hand": float(end[index]),
                "closing_expected_pipeline": float(pending_quantity[index]),
                "expected_cancelled_quantity": float(expected_unfulfilled[index]),
                "purchase_cost_index": float(purchase_cost[index]), "fixed_cost_index": float(fixed_cost[index]),
                "holding_cost_index": float(holding_cost[index]), "shortage_cost_index": float(shortage_cost[index]),
                "expiry_cost_index": float(expiry_cost[index]), "total_cost_index": float(total_cost[index]),
                "mass_balance_error": float(mass_error[index]),
            })
        daily_rows.append({
            "day": day, "dt": dates[day], "opening_on_hand": float(start.sum()),
            "receipt_quantity": float(received.sum()), "ordered_quantity": float(ordered.sum()),
            "simulated_demand": float(demand.sum()), "served_quantity": float(served.sum()),
            "lost_quantity": float(lost.sum()), "expired_quantity": float(expired.sum()),
            "closing_on_hand": float(end.sum()), "closing_expected_pipeline": float(pending_quantity.sum()),
            "purchase_cost_index": float(purchase_cost.sum()), "fixed_cost_index": float(fixed_cost.sum()),
            "holding_cost_index": float(holding_cost.sum()), "shortage_cost_index": float(shortage_cost.sum()),
            "expiry_cost_index": float(expiry_cost.sum()), "total_cost_index": float(total_cost.sum()),
            "held_series": int(held.sum()), "nonzero_orders": int((ordered > 0).sum()),
            "stockout_series": int((lost > 1e-12).sum()), "maximum_mass_balance_error": float(np.abs(mass_error).max(initial=0.0)),
        })
        previous_stockout = lost > 1e-12  # own preceding simulated outcome, never future source flags
        order_history.append(ordered.sum())
        demand_history.append(demand.sum())

    daily = pd.DataFrame(daily_rows)
    demand_total = float(daily.simulated_demand.sum())
    received_total = float(daily.receipt_quantity.sum())
    expired_total = float(daily.expired_quantity.sum())
    served_total = float(daily.served_quantity.sum())
    cumulative_error = float(opening.sum() + received_total - served_total - expired_total - buckets.sum())
    variance_demand = float(np.var(demand_history, ddof=1)) if horizon > 1 else 0.0
    variance_orders = float(np.var(order_history, ddof=1)) if horizon > 1 else 0.0
    pending_paid = sum(paid for _, _, _, paid in pipeline)
    result = {
        "days": horizon, "series": n, "initial_given_quantity": float(opening.sum()),
        "simulated_demand": demand_total, "served_quantity": served_total,
        "lost_quantity": float(daily.lost_quantity.sum()), "expired_quantity": expired_total,
        "receipt_quantity": received_total, "ordered_quantity": float(daily.ordered_quantity.sum()),
        "fill_rate": served_total / demand_total if demand_total > 0 else None,
        "waste_per_demand": expired_total / demand_total if demand_total > 0 else None,
        "waste_per_opening_plus_receipts": expired_total / (float(opening.sum()) + received_total)
            if float(opening.sum()) + received_total > 0 else None,
        "waste_per_served": expired_total / served_total if served_total > 0 else None,
        "mean_closing_inventory": float(daily.closing_on_hand.mean()),
        "terminal_on_hand": float(buckets.sum()), "terminal_expected_pipeline": float(daily.closing_expected_pipeline.iloc[-1]),
        "terminal_paid_order_index": float(pending_paid),
        "held_series_days": int(daily.held_series.sum()), "nonzero_order_lines": int(daily.nonzero_orders.sum()),
        "stockout_series_day_rate": float(daily.stockout_series.sum() / (n * horizon)),
        "bullwhip_ratio": variance_orders / variance_demand if variance_demand > 1e-15 else None,
        "demand_variance": variance_demand, "order_variance": variance_orders,
        "maximum_mass_balance_error": maximum_error,
        "cumulative_mass_balance_error": cumulative_error,
        "true_hard_constraint_violations": 0,
        "cost_per_series_day_index": float(daily.total_cost_index.sum() / (n * horizon)),
    }
    for metric in ["purchase", "fixed", "holding", "shortage", "expiry", "total"]:
        result[f"{metric}_cost_index"] = float(daily[f"{metric}_cost_index"].sum())
    if abs(cumulative_error) > 1e-8:
        raise AssertionError("Cumulative physical inventory conservation failed")
    return result, daily_rows, series_rows


def load_inputs(base: Path) -> tuple[dict, dict, dict, dict]:
    protocol, selection = require_frozen_inputs(base)
    paths = {
        "protocol": base / "protocol.json",
        "selection_receipt": base / "forecast/selection_receipt.json",
        "train": base / "data/selected_train.parquet",
        "eval": base / "data/selected_eval.parquet",
        "forecasts": base / "forecast/forecasts_eval.csv",
        "source_code": Path(__file__).resolve(),
    }
    before = {name: sha(path) for name, path in paths.items()}
    train = pd.read_parquet(paths["train"])
    evaluation = pd.read_parquet(paths["eval"])
    predictions = pd.read_csv(paths["forecasts"])
    ids = sorted(train.series_id.unique())
    if len(ids) != 30:
        raise ValueError("Registered sensitivity requires all thirty selected series")
    train_dates = sorted(train.dt.unique())
    eval_dates = sorted(evaluation.dt.unique())
    if len(train_dates) != 90 or len(eval_dates) != 7 or max(train_dates) >= min(eval_dates):
        raise ValueError("Official chronological 90+7 split is required")
    if train.duplicated(["series_id", "dt"]).any() or evaluation.duplicated(["series_id", "dt"]).any():
        raise ValueError("Duplicate daily series keys")
    t = train.pivot(index="series_id", columns="dt", values="sale_amount").loc[ids, train_dates].to_numpy(float)
    y = evaluation.pivot(index="series_id", columns="dt", values="sale_amount").loc[ids, eval_dates].to_numpy(float)
    last = train[train.dt == train_dates[-1]].set_index("series_id").loc[ids]
    recovery_method = selection["recovery"]["method"]
    selected_method = RECOVERY_FORECAST_METHOD[recovery_method]
    matrices = {}
    for label, method in [("raw", "lightgbm_raw"), ("selected_recovery", selected_method)]:
        subset = predictions[predictions.method == method]
        if subset.duplicated(["series_id", "dt"]).any():
            raise ValueError(f"Duplicate forecast keys for {method}")
        matrix = subset.pivot(index="series_id", columns="dt", values="prediction").loc[ids, eval_dates].to_numpy(float)
        if not np.isfinite(matrix).all() or np.any(matrix < 0):
            raise ValueError(f"Invalid predictions for {method}")
        matrices[label] = matrix
    data = {
        "series_ids": ids, "dates": eval_dates, "forecast_matrices": matrices, "demand_proxy": y,
        "training_mean": t.mean(axis=1), "sigma": seasonal_sigma(t),
        "initial_observed_stockout": (last.stock_hour6_22_cnt.to_numpy() > 0),
        "recovery_method": recovery_method, "selected_forecast_method": selected_method,
        "validation_best_forecast": selection.get("forecast", {}).get("method"),
    }
    if not np.isfinite(y).all() or not np.isfinite(t).all() or np.any(y < 0) or np.any(t < 0):
        raise ValueError("Non-finite or negative source normalized sales")
    return protocol, selection, data, {"paths": paths, "hashes": before}


def run(base: Path, output: Path, seed_count: int = 30) -> dict:
    if seed_count != 30 and "development" not in str(output):
        raise ValueError("Reduced seed runs must use an explicitly named development output")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite retained sensitivity artifacts: {output}")
    started = utc()
    protocol, selection, data, inputs = load_inputs(base)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + f".partial-{os.getpid()}")
    partial.mkdir(exist_ok=False)
    assumptions = {
        "units": "Original globally normalized sales amounts; float quantities; no physical-unit or monetary claim",
        "cost_unit": "Dimensionless simulated cost index; separate from the scale100 authoritative MILP pipeline",
        "sample": "Thirty purposively selected training-only store-product pairs; seven official evaluation dates",
        "demand_world": "Observed evaluation sales proxy multiplied globally by assumed factors; not true lost demand",
        "multiplier_sensitivity": [1.0, 1.25, 1.5], "shelf_life_days": [1, 3, 7],
        "opening_inventory": "Two times each series' 90-day raw training mean, evenly divided across remaining ages",
        "opening_cost": "Given initial stock; no initial purchase charge; expiry on opening stock incurs the same penalty",
        "receipt_lifetime": "Receipt on d may serve d through d+L-1 inclusive; FIFO sales before end-of-day expiry",
        "order_up_to": "Target today's and next day's forecasts plus1.2816*sqrt(2)*train-only weekly-residual SD",
        "age_aware": "Target next-day receipt horizon cover=min(L,2); position is projected FIFO stock after today's forecast service/expiry plus outstanding pipeline",
        "calculator_comparison": "Different review/cover conventions; primary attribution is recovered-minus-raw within each calculator, not a pure expiry-only ablation",
        "future_horizon_edge": "Repeat the frozen seven-day forecast profile cyclically by weekday for lookahead beyond evaluation; no later actuals",
        "safety_factor": SAFETY_FACTOR, "uncertainty": "Common raw training weekly seasonal residual SD; not calibrated quantile guarantee",
        "supply_delay": "Contract lead1; keyed actual delay1/2/3 with probabilities0.90/0.08/0.02; inaccessible to policy",
        "fulfillment": FULFILLMENT, "cancelled_quantity": "Undelivered2% never enters physical inventory; purchase index charged on full ordered amount",
        "cost_coefficients": {"purchase_per_ordered_unit": 1.0, "fixed_per_nonzero_line": 0.02,
            "holding_per_closing_unit_day": 0.015, "shortage_per_unserved_unit": 5.0, "expiry_per_expired_unit": 1.0},
        "terminal": "No salvage/refund; report terminal on-hand and paid outstanding quantities separately",
        "constraints": "Uncoupled nonnegative continuous calculator; no supplier MOQ, budget, pack or shared capacity constraints",
        "gate_ablation": "Per-series naive hold on a valid prior stockout; origin uses last train mask, later own preceding simulated shortage",
        "f4_defaults": {"calculator": "age_aware", "history": "selected_recovery", "shelf_life_days": 3, "demand_multiplier": 1.25},
        "evaluation_mask_policy_access": False,
        "llm_calls": 0, "scope": "F3/F4/F6 deterministic sensitivities; main live-agent experiment is separate",
    }
    manifest = {
        "status": "RUNNING", "started_utc": started, "assumptions": assumptions,
        "input_hashes": inputs["hashes"], "input_paths": {key: str(value) for key, value in inputs["paths"].items()},
        "recovery_selection": data["recovery_method"], "recovered_forecast_method": data["selected_forecast_method"],
        "validation_best_forecast": data["validation_best_forecast"], "seeds": list(range(seed_count)),
        "selected_series": data["series_ids"], "evaluation_dates": data["dates"],
        "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
    }
    atomic_json(partial / "manifest.json", manifest)
    pd.DataFrame({"series_id": data["series_ids"], "mean_raw_train": data["training_mean"],
        "weekly_seasonal_residual_sd": data["sigma"], "last_train_valid_stockout": data["initial_observed_stockout"]}).to_csv(
            partial / "training_calibration.csv", index=False, float_format="%.17g")

    all_runs = []
    daily_writer = series_writer = None
    maximum_error = 0.0
    event_previous = "0" * 64
    scenarios = []
    for shelf_life in [1, 3, 7]:
        for multiplier in [1.0, 1.25, 1.5]:
            for seed in range(seed_count):
                for history in ["raw", "selected_recovery"]:
                    for calculator in ["order_up_to", "age_aware"]:
                        scenarios.append(("F3", seed, shelf_life, multiplier, history, calculator, "censoring_aware"))
    for seed in range(seed_count):
        for gate in ["censoring_aware", "naive_stockout_hold"]:
            scenarios.append(("F4", seed, 3, 1.25, "selected_recovery", "age_aware", gate))

    with (partial / "daily.csv").open("w", newline="") as daily_file, \
         (partial / "series_daily.csv").open("w", newline="") as series_file, \
         (partial / "events.jsonl").open("w") as event_file:
        for experiment, seed, shelf_life, multiplier, history, calculator, gate in scenarios:
            run_id = f"{experiment}_seed{seed:02d}_life{shelf_life}_m{multiplier:g}_{history}_{calculator}_{gate}"
            identity = {"run_id": run_id, "experiment": experiment, "seed": seed, "shelf_life_days": shelf_life,
                "demand_multiplier": multiplier, "history": history, "calculator": calculator, "gate": gate,
                "forecast_method": "lightgbm_raw" if history == "raw" else data["selected_forecast_method"]}
            result, daily_rows, series_rows = simulate(
                data["series_ids"], data["dates"], data["forecast_matrices"][history], data["demand_proxy"],
                data["training_mean"], data["sigma"], data["initial_observed_stockout"], seed=seed,
                shelf_life=shelf_life, demand_multiplier=multiplier, calculator=calculator, gate=gate)
            maximum_error = max(maximum_error, result["maximum_mass_balance_error"])
            row = identity | result
            all_runs.append(row)
            if daily_writer is None:
                daily_writer = csv.DictWriter(daily_file, fieldnames=list(identity) + list(daily_rows[0]))
                daily_writer.writeheader()
                series_writer = csv.DictWriter(series_file, fieldnames=list(identity) + list(series_rows[0]))
                series_writer.writeheader()
            daily_writer.writerows(identity | item for item in daily_rows)
            series_writer.writerows(identity | item for item in series_rows)
            event = {"sequence": len(all_runs), "previous_sha256": event_previous, "kind": "completed_simulation", "payload": row}
            canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
            event_previous = hashlib.sha256(canonical.encode()).hexdigest()
            event_file.write(json.dumps(event | {"sha256": event_previous}, sort_keys=True, allow_nan=False) + "\n")
            if len(all_runs) % 100 == 0:
                print(json.dumps({"completed": len(all_runs), "planned": len(scenarios), "utc": utc()}), flush=True)

    runs = pd.DataFrame(all_runs)
    runs.to_csv(partial / "runs.csv", index=False, float_format="%.17g")
    groups = ["experiment", "shelf_life_days", "demand_multiplier", "history", "calculator", "gate", "forecast_method"]
    means = runs.groupby(groups, dropna=False).agg(
        runs=("run_id", "size"), cost_index_mean=("total_cost_index", "mean"), cost_index_sd=("total_cost_index", "std"),
        fill_mean=("fill_rate", "mean"), fill_sd=("fill_rate", "std"), waste_per_demand_mean=("waste_per_demand", "mean"),
        waste_per_opening_plus_receipts_mean=("waste_per_opening_plus_receipts", "mean"),
        mean_inventory=("mean_closing_inventory", "mean"), held_series_days_mean=("held_series_days", "mean"),
        terminal_on_hand_mean=("terminal_on_hand", "mean"), terminal_pipeline_mean=("terminal_expected_pipeline", "mean"))
    means.reset_index().to_csv(partial / "descriptive_means.csv", index=False, float_format="%.17g")
    contrasts = []
    f3 = runs[runs.experiment == "F3"]
    for (life, multiplier, calculator), group in f3.groupby(["shelf_life_days", "demand_multiplier", "calculator"]):
        reference = group[group.history == "raw"].set_index("seed")
        treatment = group[group.history == "selected_recovery"].set_index("seed")
        for seed in reference.index:
            for metric in ["total_cost_index", "fill_rate", "waste_per_demand", "mean_closing_inventory"]:
                a, b = float(reference.loc[seed, metric]), float(treatment.loc[seed, metric])
                contrasts.append({"experiment": "F3", "seed": int(seed), "shelf_life_days": int(life),
                    "demand_multiplier": float(multiplier), "calculator": calculator,
                    "contrast": "selected_recovery_minus_raw", "metric": metric,
                    "reference": a, "treatment": b, "difference": b - a,
                    "relative_difference": (b - a) / a if abs(a) > 1e-15 else None})
    f4 = runs[runs.experiment == "F4"]
    for seed, group in f4.groupby("seed"):
        reference = group[group.gate == "naive_stockout_hold"].iloc[0]
        treatment = group[group.gate == "censoring_aware"].iloc[0]
        for metric in ["total_cost_index", "fill_rate", "waste_per_demand", "held_series_days"]:
            a, b = float(reference[metric]), float(treatment[metric])
            contrasts.append({"experiment": "F4", "seed": int(seed), "shelf_life_days": 3,
                "demand_multiplier": 1.25, "calculator": "age_aware",
                "contrast": "censoring_aware_minus_naive_hold", "metric": metric,
                "reference": a, "treatment": b, "difference": b - a,
                "relative_difference": (b - a) / a if abs(a) > 1e-15 else None})
    pd.DataFrame(contrasts).to_csv(partial / "paired_differences.csv", index=False, float_format="%.17g")
    unchanged = {name: sha(path) == inputs["hashes"][name] for name, path in inputs["paths"].items()}
    if not all(unchanged.values()):
        raise AssertionError(f"Input changed during simulation: {unchanged}")
    audit = {
        "status": "VERIFIED", "runs": len(runs), "F3_runs": int((runs.experiment == "F3").sum()),
        "F4_runs": int((runs.experiment == "F4").sum()), "run_days": len(runs) * 7,
        "series_days": len(runs) * 7 * 30, "maximum_daily_mass_balance_error": maximum_error,
        "maximum_cumulative_mass_balance_error": float(runs.cumulative_mass_balance_error.abs().max()),
        "input_hashes_unchanged": unchanged, "model_calls": 0,
        "future_historical_stockout_used_by_policy": False,
        "evaluated_target": "Observed sales proxy times assumed multiplier, not recovered real latent demand",
        "event_count": len(all_runs), "event_chain_final_sha256": event_previous,
        "recovery_selected_raw": data["recovery_method"] == "raw_zero",
        "undefined_bullwhip_runs": int(runs.bullwhip_ratio.isna().sum()),
        "true_hard_constraint_violations": 0,
        "violation_scope": "Only nonnegativity and physical balance tested; coupled supplier/budget constraints absent",
    }
    atomic_json(partial / "audit.json", audit)
    manifest.update({"status": "COMPLETE" if seed_count == 30 else "DEVELOPMENT_COMPLETE", "finished_utc": utc(),
        "run_count": len(runs), "artifact_hashes": {p.name: sha(p) for p in partial.iterdir() if p.is_file() and p.name != "manifest.json"}})
    atomic_json(partial / "manifest.json", manifest)
    partial.rename(output)
    print(json.dumps(audit, indent=2), flush=True)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "results/freshretailnet")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seeds", type=int, default=30)
    args = parser.parse_args()
    output = args.output or args.base / "policy_sensitivity"
    try:
        run(args.base, output, args.seeds)
    except Exception:
        failure_dir = args.base / "development"
        failure_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        atomic_json(failure_dir / f"policy_sensitivity_failure_{stamp}.json", {
            "utc": utc(), "exception": traceback.format_exc(), "output": str(output),
            "source_sha256": sha(Path(__file__).resolve()), "argv": sys.argv})
        raise


if __name__ == "__main__":
    main()
