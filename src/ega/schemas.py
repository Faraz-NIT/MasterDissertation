"""Typed blackboard artifacts. Corrupt observations are allowed; actions are not."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .util import digest

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)

class Lineage(Record):
    snapshot_version: str
    run_id: str
    day: int
    certificate_hash: str = ""

class Series(Record):
    series_id: str
    item_id: str
    department: str
    family: str
    location: str
    cluster: str
    supplier: str
    currency: str = "USD"
    attributes_complete: bool = True

class InventoryRow(Record):
    series_id: str
    quantity: float
    source_quantity: float | None = None
    unit: str = "unit"

class PurchaseOrder(Record):
    order_id: str
    series_id: str
    supplier: str | None
    quantity: float
    ordered_day: int | None
    due_day: int | None
    source: Literal["supplier", "transfer"] = "supplier"
    stock_line: bool = True

class SalesLine(Record):
    key: str
    quantity: float
    unit_price: float
    line_total: float
    currency: str
    series_id: str

class Snapshot(Record):
    lineage: Lineage
    series: list[Series]
    inventory: list[InventoryRow]
    open_orders: list[PurchaseOrder]
    history: list[list[float | None]]
    history_days: list[int]
    stockout_flags: list[list[bool]]
    prices: list[float]
    sales_lines: list[SalesLine]
    stage_days: dict[str,int]
    source_locations: list[str]
    loaded_locations: list[str]
    source_row_count: int
    expected_inventory: dict[str,float]
    previous_inventory: dict[str,float]
    previous_inventory_hash: str
    movement_volume: float
    history_revision: float = 0
    operator_notes: list[str] = Field(default_factory=list)
    aliases: dict[str,str] = Field(default_factory=dict)
    @model_validator(mode="after")
    def dimensions(self):
        n = len(self.series); h = len(self.history_days)
        if len(self.history) != n or len(self.prices) != n or len(self.stockout_flags) != n:
            raise ValueError("Snapshot arrays must align with the series catalog")
        if any(len(x) != h for x in self.history + self.stockout_flags):
            raise ValueError("Every history/stockout row must align with history_days")
        if any(d >= self.lineage.day for d in self.history_days):
            raise ValueError("Look-ahead leakage: history must end before the decision day")
        return self
    def observed_quantities(self) -> list[float]:
        # Deliberately do not 'repair' corrupted duplicate rows behind the baseline's back.
        totals = {s.series_id: 0.0 for s in self.series}
        for row in self.inventory:
            if row.series_id in totals:
                totals[row.series_id] += row.quantity
        return [totals[s.series_id] for s in self.series]

class Check(Record):
    name: str
    family: str
    outcome: Literal["pass", "warn", "hard_fail"]
    evidence: dict
    weight: float = 0.1

class Certificate(Record):
    lineage: Lineage
    quality: float = Field(ge=0, le=1)
    checks: list[Check]
    hypotheses: list[dict] = Field(default_factory=list)
    @property
    def hard_fail(self) -> bool:
        return any(c.outcome == "hard_fail" for c in self.checks)

class Constraint(Record):
    constraint_id: str
    entity: str
    scope: Literal["series", "item", "supplier", "portfolio", "cluster"]
    parameter: Literal["pack", "moq", "aggregate_moq", "capacity", "lead_time", "unit_cost", "fixed_cost", "budget", "eligibility", "conversion", "storage"]
    value: float
    unit: str
    conversion: float | None = None
    aggregation: Literal["line", "supplier_order", "location", "portfolio"]
    valid_from: int
    valid_to: int
    precedence: int
    source_ref: str
    confidence: float = Field(ge=0, le=1)
    provenance: Literal["authenticated_source", "system_default"] = "authenticated_source"
    @model_validator(mode="after")
    def valid(self):
        if self.valid_to < self.valid_from:
            raise ValueError("Reversed validity window")
        return self

class ConstraintSet(Record):
    lineage: Lineage
    constraints: list[Constraint]
    issues: list[str] = Field(default_factory=list)
    @property
    def confidence(self) -> float:
        return min((c.confidence for c in self.constraints), default=0)

class Forecast(Record):
    lineage: Lineage
    model: str
    model_version: str
    training_end: int
    samples: list[list[list[float]]]
    quantiles: dict[str,list[list[float]]]
    diagnostics: dict
    censor_adjusted: bool
    seed: int

class Order(Record):
    series_id: str
    supplier: str
    quantity: int = Field(ge=0)

class Transfer(Record):
    item_id: str
    source_series: str
    destination_series: str
    quantity: int = Field(ge=0)

class Plan(Record):
    lineage: Lineage
    method: str
    orders: list[Order]
    transfers: list[Transfer]
    objective: float | None
    components: dict[str,float]
    solver: dict
    active_constraints: list[str]
    diagnostics: list[str] = Field(default_factory=list)
    def action_hash(self) -> str:
        return digest({"orders": sorted([x.model_dump() for x in self.orders], key=lambda x:x["series_id"]),
                       "transfers": sorted([x.model_dump() for x in self.transfers], key=lambda x:(x["source_series"],x["destination_series"]))})

class Verdict(Record):
    lineage: Lineage
    decision: Literal["pass", "veto", "escalate"]
    checks: list[Check]

class Autonomy(Record):
    level: Literal["advisory", "approval", "bounded", "full"]
    permitted: bool
    reasons: list[str]
    inputs: dict
    urgent: bool = False
    required_approvals: int = 0

class Receipt(Record):
    decision_id: str
    idempotency_key: str
    action_hash: str
    status: Literal["executed", "held", "rejected", "cancelled"]
    order_ids: list[str]
    environment: Literal["simulator"] = "simulator"


def assert_lineage(*records: Record) -> None:
    keys = {(r.lineage.snapshot_version, r.lineage.run_id, r.lineage.day, r.lineage.certificate_hash) for r in records}
    if len(keys) != 1:
        raise ValueError("Mixed-lineage artifacts cannot be combined; reconcile explicitly")
