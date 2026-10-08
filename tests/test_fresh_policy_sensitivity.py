"""Checks of physical dynamics, information boundaries and paired scenarios."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


path = Path(__file__).resolve().parents[1] / "scripts/freshretailnet/policy_sensitivity.py"
spec = importlib.util.spec_from_file_location("fresh_policy_sensitivity", path)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def case(*, shelf=3, calculator="age_aware", gate="censoring_aware", demand=None, flag=False, forecast=None):
    f = np.ones((1, 7)) if forecast is None else np.asarray(forecast, dtype=float)
    d = np.ones((1, 7)) if demand is None else np.asarray(demand, dtype=float)
    return policy.simulate(["example"], [str(i) for i in range(7)], f, d,
        np.array([1.0]), np.array([0.0]), np.array([flag]), seed=7,
        shelf_life=shelf, demand_multiplier=1.0, calculator=calculator, gate=gate)


def test_final_eval_requires_both_frozen_protocol_and_selection(tmp_path):
    with pytest.raises(RuntimeError, match="protocol.json is absent"):
        policy.require_frozen_inputs(tmp_path)
    (tmp_path / "protocol.json").write_text(json.dumps({"status": "draft"}))
    with pytest.raises(RuntimeError, match="must be frozen"):
        policy.require_frozen_inputs(tmp_path)
    (tmp_path / "protocol.json").write_text(json.dumps({"status": "frozen"}))
    with pytest.raises(RuntimeError, match="selection receipt is absent"):
        policy.require_frozen_inputs(tmp_path)
    (tmp_path / "forecast").mkdir()
    (tmp_path / "forecast/selection_receipt.json").write_text(json.dumps({"recovery": {"method": "profile"}}))
    assert policy.require_frozen_inputs(tmp_path)[1]["recovery"]["method"] == "profile"


@pytest.mark.parametrize("shelf", [1, 3, 7])
def test_fifo_expiry_and_receipts_conserve_physical_inventory(shelf):
    result, daily, details = case(shelf=shelf)
    assert result["maximum_mass_balance_error"] < 1e-12
    assert result["initial_given_quantity"] + result["receipt_quantity"] == pytest.approx(
        result["served_quantity"] + result["expired_quantity"] + result["terminal_on_hand"])
    assert all(row["closing_on_hand"] >= -1e-12 for row in details)
    assert all(row["receipt_quantity"] >= 0 for row in daily)
    if shelf == 7:
        # The oldest seventh of the evenly aged opening balance serves first.
        # No new receipt can expire within the remaining six service dates.
        assert result["expired_quantity"] == pytest.approx(0)


def test_expiry_after_service_gives_receipt_one_full_service_day():
    result, daily, _ = case(shelf=1, demand=np.zeros((1, 7)), forecast=np.zeros((1, 7)))
    assert daily[0]["expired_quantity"] == pytest.approx(2.0)
    assert daily[0]["closing_on_hand"] == pytest.approx(0.0)
    assert result["expired_quantity"] == pytest.approx(2.0)


def test_order_precedes_current_evaluator_demand_and_same_day_truth_cannot_change_it():
    _, _, base = case()
    altered = np.ones((1, 7)); altered[0, 0] = 10_000
    _, _, changed = case(demand=altered)
    assert base[0]["ordered_quantity"] == changed[0]["ordered_quantity"]
    assert base[0]["proposed_order"] == changed[0]["proposed_order"]


def test_supply_opportunities_are_paired_across_policies():
    a = case(calculator="order_up_to")[2]
    b = case(calculator="age_aware")[2]
    assert [x["simulated_lead_days"] for x in a] == [x["simulated_lead_days"] for x in b]
    assert set(x["simulated_lead_days"] for x in a) <= {1, 2, 3}


def test_valid_stockout_does_not_hold_censoring_aware_gate():
    _, _, aware = case(flag=True)
    _, _, naive = case(flag=True, gate="naive_stockout_hold")
    assert not aware[0]["hold_due_to_valid_stockout"]
    assert naive[0]["hold_due_to_valid_stockout"]
    assert naive[0]["ordered_quantity"] == 0
    for day in range(1, 7):
        assert naive[day]["valid_previous_stockout"] == (naive[day - 1]["lost_quantity"] > 1e-12)


def test_age_aware_excludes_anticipated_expiring_residual_and_caps_cover():
    forecast = np.ones((1, 7))
    sigma = np.zeros(1)
    assert policy.target_quantity(forecast, 0, sigma, 1, "order_up_to")[0] == 2
    assert policy.target_quantity(forecast, 0, sigma, 1, "age_aware")[0] == 1
    assert policy.expected_expiring_after_service(np.array([[3.0, 0.0, 2.0]]), np.array([1.0]))[0] == 1


def test_life_one_policy_orders_for_receipt_after_current_stock_has_expired():
    _, _, rows = case(shelf=1)
    assert rows[0]["ordered_quantity"] == pytest.approx(1.0)
    assert rows[0]["served_quantity"] == pytest.approx(1.0)
    assert rows[0]["expired_quantity"] == pytest.approx(1.0)


def test_forecast_lookahead_repeats_frozen_weekday_profile_beyond_final_date():
    forecast = np.arange(1, 8, dtype=float)[None, :]
    sigma = np.zeros(1)
    assert policy.target_quantity(forecast, 6, sigma, 3, "order_up_to")[0] == 8
    assert policy.target_quantity(forecast, 6, sigma, 3, "age_aware")[0] == 3


def test_zero_demand_metrics_keep_undefined_ratios_explicit():
    result, _, _ = case(demand=np.zeros((1, 7)))
    assert result["fill_rate"] is None
    assert result["waste_per_demand"] is None
    assert result["bullwhip_ratio"] is None


def test_common_training_residual_scale_uses_weekly_differences():
    train = np.tile(np.arange(7), 3)[None, :].astype(float)
    assert policy.seasonal_sigma(train)[0] == pytest.approx(0.0)
