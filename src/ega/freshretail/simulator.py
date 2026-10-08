"""A FIFO, perishable variant of the existing lost-sales inventory simulator.

Shelf life is a declared experimental assumption, not an observed field of
FreshRetailNet. Receipts have ``shelf_life_days`` usable daily selling periods;
stock received on day d expires *after* sales on d + shelf_life_days - 1.
Transfers retain their original expiry, including while in transit. Initial
stock is spread as evenly as possible over the remaining shelf-life buckets.
The existing five-day stock initialization, initial pipeline and keyed supply
draws are retained, so changing the simulator does not change those assumptions.

Age batches are evaluator-side physical state. The existing Snapshot schema
does not expose them to the planner, and the inherited optimizer does not become
age-aware merely because this simulator enforces physical expiry.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..simulator import InventoryEnvironment


@dataclass
class StockBatch:
    """A quantity with its last usable selling day, inclusive."""

    quantity: float
    expiry_day: int


class PerishableInventoryEnvironment(InventoryEnvironment):
    """Compatible with ``experiment.run_one`` and its evidence/ledger interface.

    Configure ``panel.provenance['perishable_simulation']['shelf_life_days']``
    or override ``SHELF_LIFE_DAYS`` on a subclass. The default is three days.
    Optional ``source_observed_stockout_path`` names an aligned .npy array;
    only columns strictly before the initial simulation day seed history flags.
    Positive source values mean observed stockout exposure, not verified latent
    demand. After initialization flags are generated from simulated lost sales.
    """

    SHELF_LIFE_DAYS = 3
    _TOLERANCE = 1e-8

    def __init__(self, panel, first_day, seed, run_id, config):
        assumptions = panel.provenance.get("perishable_simulation", {})
        shelf_life = assumptions.get("shelf_life_days", self.SHELF_LIFE_DAYS)
        if (isinstance(shelf_life, bool) or not isinstance(shelf_life, (int, np.integer))
                or shelf_life < 1):
            raise ValueError("shelf_life_days must be a positive integer")
        self.shelf_life_days = int(shelf_life)
        super().__init__(panel, first_day, seed, run_id, config)
        self.batches: list[list[StockBatch]] = []
        for quantity in self.on_hand:
            # Initial stock is integral in the base simulator. Put any remainder
            # into the fresher buckets so bucket sizes differ by at most one.
            base, remainder = divmod(int(quantity), self.shelf_life_days)
            row = []
            for offset in range(self.shelf_life_days):
                amount = base + int(offset >= self.shelf_life_days - remainder)
                if amount:
                    row.append(StockBatch(float(amount), first_day + offset))
            self.batches.append(row)
        self.transfer_batches: dict[str, list[StockBatch]] = {}
        self.last_spoilage = np.zeros(panel.n)
        self._received_expired = np.zeros(panel.n)
        self._today_transfers = np.zeros(panel.n)
        self._seed_observed_flags(first_day)
        self._assert_stock_balance()

    def _seed_observed_flags(self, first_day):
        path = self.panel.provenance.get("source_observed_stockout_path")
        if path is None:
            return
        values = np.load(Path(path), mmap_mode="r", allow_pickle=False)
        if values.shape != self.panel.sales.shape:
            raise ValueError("Source stockout flags must align with the canonical panel")
        historical = np.asarray(values[:, :first_day])
        if not np.issubdtype(historical.dtype, np.number) and historical.dtype != np.bool_:
            raise ValueError("Source stockout flags must be boolean or numeric")
        if not np.isfinite(historical).all() or (historical < 0).any():
            raise ValueError("Historical source stockout flags must be finite and nonnegative")
        self.flags = (historical > 0).tolist()

    def _assert_stock_balance(self):
        totals = np.asarray([sum(batch.quantity for batch in row) for row in self.batches])
        if (self.on_hand < -self._TOLERANCE).any():
            raise AssertionError("Physical inventory became negative")
        if not np.allclose(totals, self.on_hand, atol=self._TOLERANCE, rtol=0):
            raise AssertionError("FIFO batches disagree with physical inventory")
        if not np.allclose(self.ledger, self.on_hand, atol=self._TOLERANCE, rtol=0):
            raise AssertionError("Movement ledger disagrees with physical inventory")

    def _take_fifo(self, index, quantity):
        """Remove quantity from batches only; the caller updates stock/ledger."""
        remaining = float(quantity)
        removed = []
        survivors = []
        for batch in sorted(self.batches[index], key=lambda item: item.expiry_day):
            taken = min(batch.quantity, remaining)
            if taken > 0:
                removed.append(StockBatch(taken, batch.expiry_day))
                remaining -= taken
            leftover = batch.quantity - taken
            if leftover > self._TOLERANCE:
                survivors.append(StockBatch(leftover, batch.expiry_day))
        if remaining > self._TOLERANCE:
            raise AssertionError("Cannot remove more stock than the FIFO batches contain")
        self.batches[index] = survivors
        return removed

    def begin_day(self, day):
        self.day = day
        self.received = np.zeros(self.panel.n)
        self.received_ids = []
        self._received_expired = np.zeros(self.panel.n)
        self._today_transfers = np.zeros(self.panel.n)
        remaining = []
        for order in self.pending:
            if order.true_due_day > day:
                remaining.append(order)
                continue
            index = self.index[order.series_id]
            if order.kind == "transfer":
                incoming = self.transfer_batches.pop(order.order_id, None)
                if incoming is None:
                    raise AssertionError("Transfer receipt is missing its original age batches")
            else:
                incoming = [StockBatch(order.quantity, day + self.shelf_life_days - 1)]
            accepted = 0.0
            for batch in incoming:
                if batch.expiry_day < day:
                    self._received_expired[index] += batch.quantity
                elif batch.quantity > self._TOLERANCE:
                    self.batches[index].append(batch)
                    accepted += batch.quantity
            self.batches[index].sort(key=lambda item: item.expiry_day)
            self.on_hand[index] += accepted
            self.ledger[index] += accepted
            self.received[index] += accepted
            self.received_ids.append(order.order_id)
        self.pending = remaining
        self._assert_stock_balance()

    def snapshot(self, lookback, reveal_arrivals=False):
        snapshot = super().snapshot(lookback, reveal_arrivals)
        # Expiry is a real movement, including when zero sales occurred. This
        # avoids presenting a stock reduction as an unaccounted ledger error.
        snapshot.movement_volume += float(self.last_spoilage.sum() + self._received_expired.sum())
        return snapshot

    def execute(self, plan, problem, decision_id):
        self._assert_stock_balance()
        ids, costs = super().execute(plan, problem, decision_id)
        # The base implementation determines fulfilled transfer quantities and
        # all supplier randomness. Attach the corresponding FIFO ages afterward
        # without changing its random draws, supplier capacities or cost rules.
        shipments = {order.order_id: order for order in self.pending if order.kind == "transfer"}
        for position, move in enumerate(plan.transfers):
            order_id = f"{decision_id}:transfer:{position}"
            if order_id not in shipments:
                continue
            index = self.index[move.source_series]
            self.transfer_batches[order_id] = self._take_fifo(index, shipments[order_id].quantity)
        self._today_transfers += self.last_transfers
        self._assert_stock_balance()
        return ids, costs

    def end_day(self, demand, unit_costs):
        demand = np.asarray(demand, dtype=float)
        costs = np.asarray(unit_costs, dtype=float)
        if (demand.shape != (self.panel.n,) or costs.shape != (self.panel.n,)
                or not np.isfinite(demand).all() or not np.isfinite(costs).all()
                or (demand < 0).any() or (costs < 0).any()):
            raise ValueError("Demand and unit costs must be aligned, finite and nonnegative")
        self._assert_stock_balance()
        start = self.on_hand.copy()
        sold = np.minimum(self.on_hand, demand)
        lost = demand - sold
        for index, quantity in enumerate(sold):
            self._take_fifo(index, quantity)
        self.on_hand -= sold
        self.ledger -= sold
        expired = np.zeros(self.panel.n)
        for index, row in enumerate(self.batches):
            expired[index] = sum(batch.quantity for batch in row if batch.expiry_day <= self.day)
            self.batches[index] = [batch for batch in row if batch.expiry_day > self.day]
        self.on_hand -= expired
        self.ledger -= expired
        overflow = np.zeros(self.panel.n)
        for location in {series.location for series in self.panel.series}:
            indices = [i for i, series in enumerate(self.panel.series) if series.location == location]
            total = float(self.on_hand[indices].sum())
            capacity = self.config.solver.storage_per_location
            if total > capacity:
                overflow[indices] = self.on_hand[indices] * (total - capacity) / total
                for index in indices:
                    self._take_fifo(index, overflow[index])
                self.on_hand[indices] -= overflow[indices]
                self.ledger[indices] -= overflow[indices]
        spoiled = expired + overflow + self._received_expired
        self.last_sales = sold.copy()
        self.last_transfers = self._today_transfers.copy()
        self.last_spoilage = spoiled.copy()
        for index in range(self.panel.n):
            self.sales_history[index].append(float(sold[index]))
            self.flags[index].append(bool(lost[index] > 0))
        self.previous_start = start
        self._assert_stock_balance()
        return {
            "demand": float(demand.sum()), "sales": float(sold.sum()), "lost_sales": float(lost.sum()),
            "on_hand": float(self.on_hand.sum()), "stockout_pairs": int((lost > 0).sum()), "pairs": self.panel.n,
            "holding": float(np.sum(self.on_hand * costs * self.config.solver.holding_rate)),
            "shortage": float(np.sum(lost * costs * self.config.solver.shortage_multiplier)),
            "spoilage": float(np.sum(spoiled * costs)), "spoilage_units": float(spoiled.sum()),
            "age_expired_units": float(expired.sum()), "capacity_overflow_units": float(overflow.sum()),
            "in_transit_expired_units": float(self._received_expired.sum()),
            "received_units": float(self.received.sum()), "arrived_units": float(self.received.sum() + self._received_expired.sum()),
            "received_order_ids": self.received_ids,
            "sales_by_series": sold.tolist(), "lost_by_series": lost.tolist(), "on_hand_by_series": self.on_hand.tolist(),
            "age_expired_by_series": expired.tolist(), "capacity_overflow_by_series": overflow.tolist(),
            "in_transit_expired_by_series": self._received_expired.tolist(),
            "spoilage_by_series": spoiled.tolist(),
            "stock_batches_by_series": [[{"quantity": batch.quantity, "expiry_day": batch.expiry_day}
                                          for batch in row] for row in self.batches],
        }
