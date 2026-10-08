"""Physical, accounting and information-boundary checks for fresh-retail runs."""
from __future__ import annotations

import json

import numpy as np
import pytest

from ega.freshretail.simulator import PerishableInventoryEnvironment, StockBatch
from ega.schemas import Lineage, Order, Plan, Transfer
from ega.simulator import InventoryEnvironment, Shipment


def make_env(panel, config, first=140):
    return PerishableInventoryEnvironment(panel, first, 7, "fresh-test", config)


def set_stock(env, groups):
    env.batches = [[StockBatch(float(quantity), expiry) for quantity, expiry in group] for group in groups]
    env.on_hand = np.asarray([sum(batch.quantity for batch in row) for row in env.batches], dtype=float)
    env.ledger = env.on_hand.copy()
    env.previous_start = env.on_hand.copy()
    env.pending = []
    env._assert_stock_balance()


def make_plan(env, orders=(), transfers=()):
    return Plan(lineage=Lineage(snapshot_version="test", run_id=env.run_id, day=env.day),
                method="physical-test", orders=list(orders), transfers=list(transfers),
                objective=None, components={}, solver={}, active_constraints=[])


def make_problem(env):
    return {"parameters": {"unit_cost": [2.0] * env.panel.n, "lead_time": [1] * env.panel.n},
            "supplier_parameters": {series.supplier: {"capacity": 1000, "fixed_cost": 1.0}
                                    for series in env.panel.series}}


def test_initial_stock_and_pipeline_match_base_with_balanced_ages(panel, config):
    fresh = make_env(panel, config)
    base = InventoryEnvironment(panel, 140, 7, "fresh-test", config)
    np.testing.assert_array_equal(fresh.on_hand, base.on_hand)
    assert fresh.pending == base.pending
    for index, row in enumerate(fresh.batches):
        amounts = [next((batch.quantity for batch in row if batch.expiry_day == day), 0)
                   for day in range(140, 143)]
        assert sum(amounts) == base.on_hand[index]
        assert max(amounts) - min(amounts) <= 1


def test_fifo_sales_preserve_fresh_stock_and_expire_after_selling(panel, config):
    env = make_env(panel, config)
    set_stock(env, [[(3, 140), (5, 142)], [(2, 141)]])
    env.begin_day(140)
    outcome = env.end_day([4, 0], [2, 3])
    assert outcome["sales_by_series"] == [4, 0]
    assert outcome["spoilage_units"] == 0
    assert [(batch.quantity, batch.expiry_day) for batch in env.batches[0]] == [(4, 142)]
    env.begin_day(141)
    outcome = env.end_day([0, 1], [2, 3])
    assert outcome["age_expired_by_series"] == [0, 1]
    assert outcome["spoilage"] == 3
    np.testing.assert_array_equal(env.ledger, [4, 0])
    assert outcome["holding"] == 4 * 2 * config.solver.holding_rate


def test_daily_mass_balance_and_expiry_are_logged_as_movements(panel, config):
    env = make_env(panel, config)
    set_stock(env, [[(5, 140), (7, 142)], [(4, 140)]])
    env.begin_day(140)
    start = env.on_hand.copy()
    outcome = env.end_day([2, 1], [2, 3])
    np.testing.assert_allclose(start, np.asarray(outcome["sales_by_series"])
                               + np.asarray(outcome["spoilage_by_series"])
                               + env.on_hand)
    assert outcome["age_expired_units"] == 6
    assert outcome["spoilage"] == 15
    env.begin_day(141)
    snapshot = env.snapshot(10)
    assert snapshot.movement_volume == 3 + 6
    assert snapshot.expected_inventory == {series.series_id: env.on_hand[i]
                                           for i, series in enumerate(panel.series)}


def test_supplier_receipt_is_fresh_even_if_order_is_old(panel, config):
    env = make_env(panel, config)
    set_stock(env, [[], []])
    series = panel.series[0]
    env.pending = [Shipment("old-po", series.series_id, series.supplier, 8, 120, 140, False)]
    env.begin_day(140)
    assert env.batches[0] == [StockBatch(8, 142)]
    assert env.end_day([0, 0], [2, 2])["spoilage_units"] == 0
    env.begin_day(141)
    assert env.end_day([0, 0], [2, 2])["spoilage_units"] == 0
    env.begin_day(142)
    outcome = env.end_day([3, 0], [2, 2])
    assert outcome["sales"] == 3
    assert outcome["age_expired_units"] == 5
    assert outcome["holding"] == 0


def test_transfers_take_fifo_and_never_reset_age(panel, config):
    env = make_env(panel, config)
    set_stock(env, [[(3, 140), (4, 142)], []])
    env.begin_day(140)
    source, target = panel.series
    transfer = Transfer(item_id=source.item_id, source_series=source.series_id,
                        destination_series=target.series_id, quantity=5)
    env.execute(make_plan(env, transfers=[transfer]), make_problem(env), "move")
    assert env.transfer_batches["move:transfer:0"] == [StockBatch(3, 140), StockBatch(2, 142)]
    assert env.batches[0] == [StockBatch(2, 142)]
    outcome = env.end_day([0, 0], [2, 2])
    assert outcome["spoilage_units"] == 0  # shipment is physically in transit
    env.begin_day(141)
    assert env.received.tolist() == [0, 2]
    assert env.batches[1] == [StockBatch(2, 142)]
    outcome = env.end_day([0, 0], [2, 2])
    assert outcome["in_transit_expired_units"] == 3
    assert outcome["spoilage"] == 6
    assert outcome["received_units"] == 2
    assert outcome["arrived_units"] == 5
    assert "move:transfer:0" not in env.transfer_batches
    np.testing.assert_array_equal(env.ledger, [2, 2])


def test_storage_overflow_and_age_expiry_do_not_double_count(panel, config):
    config.solver.storage_per_location = 4
    env = make_env(panel, config)
    set_stock(env, [[(3, 140), (8, 142)], []])
    env.begin_day(140)
    outcome = env.end_day([1, 0], [2, 2])
    assert outcome["age_expired_units"] == 2
    assert outcome["capacity_overflow_units"] == 4
    assert outcome["spoilage_units"] == 6
    assert outcome["spoilage"] == 12
    assert outcome["on_hand"] == 4
    assert outcome["holding"] == 4 * 2 * config.solver.holding_rate
    env._assert_stock_balance()


def test_observed_stockout_history_is_past_only_and_simulation_flags_take_over(panel, config, tmp_path):
    path = tmp_path / "stockout.npy"
    flags = np.zeros_like(panel.sales)
    flags[0, 139] = 3  # partial-day stockout exposure
    flags[:, 140:] = 1
    np.save(path, flags)
    panel.provenance["source_observed_stockout_path"] = str(path)
    env = make_env(panel, config)
    flags[:, 140:] = 999  # future source values must not influence the snapshot
    np.save(path, flags)
    other = make_env(panel, config)
    assert env.snapshot(10).stockout_flags == other.snapshot(10).stockout_flags
    assert env.snapshot(10).stockout_flags[0][-1] is True
    set_stock(env, [[(5, 142)], [(5, 142)]])
    env.begin_day(140)
    env.end_day([0, 8], [2, 2])
    env.begin_day(141)
    assert env.snapshot(10).stockout_flags[0][-1] is False
    assert env.snapshot(10).stockout_flags[1][-1] is True


def test_supply_randomness_is_identical_to_base_and_independent_of_run_label(panel, config):
    fresh = make_env(panel, config)
    base = InventoryEnvironment(panel, 140, 7, "different-policy-label", config)
    fresh.begin_day(140)
    base.begin_day(140)
    orders = [Order(series_id=series.series_id, supplier=series.supplier, quantity=24)
              for series in panel.series]
    plan = make_plan(fresh, orders=orders)
    problem = make_problem(fresh)
    fresh_ids, fresh_costs = fresh.execute(plan, problem, "same-opportunity")
    base_ids, base_costs = base.execute(plan, problem, "same-opportunity")
    assert fresh_ids == base_ids
    assert fresh_costs == base_costs
    assert fresh.pending == base.pending


@pytest.mark.parametrize("shelf_life", [0, -1, True, 1.5])
def test_invalid_shelf_life_rejected(panel, config, shelf_life):
    panel.provenance["perishable_simulation"] = {"shelf_life_days": shelf_life}
    with pytest.raises(ValueError, match="positive integer"):
        make_env(panel, config)


def test_shelf_life_can_be_configured_without_changing_core_config(panel, config):
    panel.provenance["perishable_simulation"] = {"shelf_life_days": 1}
    env = make_env(panel, config)
    set_stock(env, [[(5, 140)], []])
    env.begin_day(140)
    outcome = env.end_day([2, 0], [2, 2])
    assert env.shelf_life_days == 1
    assert outcome["sales"] == 2
    assert outcome["age_expired_units"] == 3
    assert outcome["on_hand"] == 0


def test_run_one_writes_perishable_outcome_with_valid_evidence_chain(panel, config, model, monkeypatch, tmp_path):
    import ega.experiment as experiment
    from ega.store import ArtifactStore

    config.days = 2
    config.oracle = False
    monkeypatch.setattr(experiment, "InventoryEnvironment", PerishableInventoryEnvironment)
    summary = experiment.run_one(panel, config, "B1", "normal", 7, 0, model, tmp_path / "run")
    assert summary["chain_valid"] is True
    assert summary["trace_count"] == 2
    trace_index = json.loads((tmp_path / "run" / "trace_index.json").read_text())
    store = ArtifactStore(tmp_path / "run" / "artifacts")
    for row in trace_index:
        trace = store.get(row["trace_ref"])
        outcome = store.get(trace["references"]["outcome"])
        assert outcome["spoilage_units"] == pytest.approx(outcome["age_expired_units"]
                                                         + outcome["capacity_overflow_units"]
                                                         + outcome["in_transit_expired_units"])
        assert len(outcome["stock_batches_by_series"]) == panel.n
    store.close()
