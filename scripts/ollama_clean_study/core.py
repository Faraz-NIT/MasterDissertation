"""Small, fresh, no-repair replenishment experiment with three local LLM roles."""
from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "study_results/ollama_clean_study_20261009"
MODEL = "qwen2.5:1.5b"
ARMS = ["conventional", "structured_planner", "llm_agents"]
SCENARIOS = ["routine", "supplier_disruption", "promotion"]


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rng(seed, *parts):
    key = json.dumps([int(seed), *parts], separators=(",", ":"))
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier": {"type": "string", "enum": ["S1", "S2", "S3"]},
        "pack": {"type": "integer", "minimum": 1},
        "moq": {"type": "integer", "minimum": 1},
        "lead_days": {"type": "integer", "minimum": 1, "maximum": 7},
        "capacity": {"type": "integer", "minimum": 1},
    },
    "required": ["supplier", "pack", "moq", "lead_days", "capacity"],
    "additionalProperties": False,
}
SCHEMAS = {
    "supplier": {
        "type": "object",
        "properties": {
            "rules": {"type": "array", "items": RULE_SCHEMA, "minItems": 3, "maxItems": 3},
            "budget": {"type": "integer", "minimum": 1},
        },
        "required": ["rules", "budget"],
        "additionalProperties": False,
    },
    "planner": {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": ["constrained_order"]},
            "priority": {"type": "string", "enum": ["balanced", "service_first"]},
        },
        "required": ["tool", "priority"],
        "additionalProperties": False,
    },
    "critic": {
        "type": "object",
        "properties": {"verdict": {"type": "string", "enum": ["approve", "hold"]}},
        "required": ["verdict"],
        "additionalProperties": False,
    },
}
PROMPTS = {
    "supplier": (
        "You are the supplier-information agent. Read the current supplier message. "
        "Extract exactly one rule for each of S1, S2 and S3, and the daily budget. "
        "Copy every number exactly; pack is carton size, moq is minimum order, "
        "lead_days is delivery time, capacity is daily dispatch limit. "
        "Meaning matters, not the order of numbers in the sentence: a dispatch limit is capacity, "
        "and cartons of N means pack=N. Do not swap these fields. "
        "Use the current rules only. Return only the JSON object."
    ),
    "planner": (
        "You are the replenishment coordination agent. Numerical tools calculate quantities. "
        "Request constrained_order. Select balanced for routine trading and supplier disruption. "
        "Select service_first for an active announced promotion when availability is the priority. "
        "Do not estimate quantities yourself. Return only JSON."
    ),
    "critic": (
        "You are the independent review agent. Approve only when source verification, "
        "tool routing, solver feasibility, and every listed action check pass. "
        "Hold if any check fails or is unknown. Never override a failed check. Return only JSON."
    ),
}

EXAMPLES = {
    "supplier": [
        {"role":"user","content":"For S1, dispatch no more than 97 units today; allow 2 days for delivery. Minimum order 6 units; cartons of 3. For S2, cartons contain 4 units, minimum order 8, delivery 1 day, dispatch limit 88. S3 has dispatch limit 120, delivery 3 days, minimum order 12, carton size 6. Daily spending budget 250."},
        {"role":"assistant","content":json.dumps({"rules":[{"supplier":"S1","pack":3,"moq":6,"lead_days":2,"capacity":97},{"supplier":"S2","pack":4,"moq":8,"lead_days":1,"capacity":88},{"supplier":"S3","pack":6,"moq":12,"lead_days":3,"capacity":120}],"budget":250})},
    ],
    "critic": [
        {"role":"user","content":"{\"source_verification\":\"pass\",\"tool_routing\":\"pass\",\"solver_feasible\":true,\"action_checks\":{\"pack\":\"pass\",\"moq\":\"pass\",\"capacity\":\"pass\",\"budget\":\"fail\"}}"},
        {"role":"assistant","content":"{\"verdict\":\"hold\"}"},
        {"role":"user","content":"{\"source_verification\":\"pass\",\"tool_routing\":\"pass\",\"solver_feasible\":true,\"action_checks\":{\"pack\":\"pass\",\"moq\":\"pass\",\"capacity\":\"pass\",\"budget\":\"pass\"}}"},
        {"role":"assistant","content":"{\"verdict\":\"approve\"}"},
    ],
}


class Ollama:
    def __init__(self, output, timeout=90):
        self.output = Path(output)
        self.timeout = timeout
        self.records = []

    def ask(self, role, content, name):
        path = self.output / f"{name}_{role}.json"
        if path.exists():
            raise FileExistsError("Never overwrite a model request: "+str(path))
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": PROMPTS[role]},
                *EXAMPLES.get(role, []),
                {"role": "user", "content": content},
            ],
            "stream": False,
            "format": SCHEMAS[role],
            "options": {"temperature": 0, "seed": 20261009, "num_ctx": 4096, "num_thread": 3, "num_predict": 512},
            "keep_alive": "2h",
        }
        started = time.perf_counter()
        record = {"role": role, "name": name, "request": payload}
        parsed = None
        try:
            request = urllib.request.Request(
                "http://127.0.0.1:11434/api/chat",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
            record["response"] = result
            parsed = json.loads(result["message"]["content"])
            import jsonschema
            jsonschema.validate(parsed, SCHEMAS[role])
            record["schema_valid"] = True
        except Exception as exc:
            record["error"] = {"type": type(exc).__name__, "message": str(exc)}
            record["schema_valid"] = False
            parsed = None
        record["seconds"] = time.perf_counter() - started
        record["parsed"] = parsed
        dump(path, record)
        self.records.append({
            "role": role, "seconds": record["seconds"], "schema_valid": record["schema_valid"],
            "input_tokens": record.get("response", {}).get("prompt_eval_count", 0),
            "output_tokens": record.get("response", {}).get("eval_count", 0),
            "path": str(path.relative_to(OUT)) if path.is_relative_to(OUT) else str(path),
            "sha256": sha(path),
        })
        return parsed


def contracts(data, scenario, seed, day):
    mu = data["historical_mean"]
    groups = data["groups"]
    pack = [2, 4, 6]
    lead = [1, 2, 2]
    rules = []
    for group in range(3):
        capacity = max(12, int(math.ceil(mu[groups == group].sum() * 2.8)))
        capacity = max(12, int(capacity * rng(seed, "capacity", day, group).uniform(.92, 1.08)))
        carton = pack[group]
        delivery = lead[group]
        if scenario == "supplier_disruption" and day >= 2:
            carton *= 2
            delivery += 1
            capacity = max(carton * 2, int(capacity * .7))
        rules.append({"supplier": f"S{group+1}", "pack": carton, "moq": carton * 2,
                      "lead_days": delivery, "capacity": capacity})
    budget = max(36, int(math.ceil(mu.sum() * 2.8) * rng(seed, "budget", day).uniform(.92, 1.08)))
    return {"rules": rules, "budget": budget}


def supplier_message(rules, day, style):
    lines = [f"Current supplier agreement for decision day {day}. All quantities are study units."]
    if style == 2:
        lines.append("Supplier | Carton size | Minimum order | Delivery days | Daily dispatch limit")
    for row in rules["rules"]:
        s, p, m, l, c = (row[k] for k in ("supplier", "pack", "moq", "lead_days", "capacity"))
        if style == 0:
            lines.append(f"{s} sells cartons of {p} units. The minimum order is {m} units. Delivery takes {l} days. Daily dispatch is limited to {c} units.")
        elif style == 1:
            lines.append(f"For {s}, dispatch no more than {c} units today; allow {l} days for delivery. The order must contain at least {m} units, supplied in cartons of {p}.")
        else:
            lines.append(f"{s} | {p} | {m} | {l} | {c}")
    lines.append(f"The current daily spending budget is {rules['budget']} cost-index units. Each purchased unit costs one cost-index unit.")
    return "\n".join(lines)


def verify_source(extracted, authoritative):
    """Validate against the current authenticated contract record, not future demand."""
    if not isinstance(extracted, dict):
        return False, 0, ["missing_source_extraction"]
    rows = extracted.get("rules", [])
    found = {r.get("supplier"): r for r in rows if isinstance(r, dict)}
    correct = int(extracted.get("budget") == authoritative["budget"])
    failures = []
    if len(rows) != 3 or set(found) != {"S1", "S2", "S3"}:
        failures.append("supplier_coverage")
    for expected in authoritative["rules"]:
        row = found.get(expected["supplier"], {})
        for key in ("pack", "moq", "lead_days", "capacity"):
            same = row.get(key) == expected[key]
            correct += int(same)
            if not same:
                failures.append(expected["supplier"] + "." + key)
    if extracted.get("budget") != authoritative["budget"]:
        failures.append("budget_source")
    return not failures, correct, failures


def rule_arrays(rules, groups):
    found = {r["supplier"]: r for r in rules["rules"]}
    return {key: np.array([found[f"S{g+1}"][key] for g in groups], dtype=float)
            for key in ("pack", "moq", "lead_days", "capacity")}


def checks(orders, rules, groups):
    quantities = np.asarray(orders, dtype=float)
    a = rule_arrays(rules, groups)
    failures = []
    if not np.isfinite(quantities).all() or (quantities < 0).any():
        failures.append("nonnegative_quantities")
    if not np.allclose(quantities / a["pack"], np.rint(quantities / a["pack"]), atol=1e-7):
        failures.append("pack_size")
    if ((quantities > 0) & (quantities + 1e-7 < a["moq"])).any():
        failures.append("minimum_order")
    if quantities.sum() > rules["budget"] + 1e-7:
        failures.append("budget")
    for group in range(3):
        if quantities[groups == group].sum() > a["capacity"][groups == group][0] + 1e-7:
            failures.append(f"capacity_S{group+1}")
    return failures


def conventional_order(target, rules, groups):
    a = rule_arrays(rules, groups)
    desired = np.ceil(np.maximum(0, target) / a["pack"]) * a["pack"]
    desired[(desired > 0) & (desired < a["moq"])] = a["moq"][(desired > 0) & (desired < a["moq"])]
    for group in range(3):
        mask = groups == group
        total = desired[mask].sum()
        cap = a["capacity"][mask][0]
        if total > cap:
            desired[mask] *= cap / total
    if desired.sum() > rules["budget"]:
        desired *= rules["budget"] / desired.sum()
    q = np.floor(desired / a["pack"]) * a["pack"]
    q[(q > 0) & (q < a["moq"])] = 0
    assert not checks(q, rules, groups)
    return q, {"feasible": True, "tool": "proportional_order_up_to"}


def constrained_order(target, urgency, rules, groups):
    a = rule_arrays(rules, groups)
    n = len(groups)
    maximum = np.ceil(np.maximum(np.maximum(0, target), a["moq"]) / a["pack"])
    maximum[target <= 0] = 0
    c = np.r_[a["pack"], np.zeros(n), 5 * urgency]
    integrality = np.r_[np.ones(2*n), np.zeros(n)]
    lower = np.zeros(3*n)
    upper = np.r_[maximum, np.ones(n), np.full(n, np.inf)]
    matrix, lo, hi = [], [], []
    for i in range(n):
        row = np.zeros(3*n); row[i] = a["pack"][i]; row[n+i] = -a["moq"][i]
        matrix.append(row); lo.append(0); hi.append(np.inf)
        row = np.zeros(3*n); row[i] = 1; row[n+i] = -maximum[i]
        matrix.append(row); lo.append(-np.inf); hi.append(0)
        row = np.zeros(3*n); row[i] = a["pack"][i]; row[2*n+i] = 1
        matrix.append(row); lo.append(max(0, target[i])); hi.append(np.inf)
    row = np.zeros(3*n); row[:n] = a["pack"]
    matrix.append(row); lo.append(-np.inf); hi.append(rules["budget"])
    for group in range(3):
        row = np.zeros(3*n); row[:n] = a["pack"] * (groups == group)
        matrix.append(row); lo.append(-np.inf); hi.append(a["capacity"][groups == group][0])
    result = milp(c, integrality=integrality, bounds=Bounds(lower, upper),
                  constraints=LinearConstraint(np.asarray(matrix), lo, hi),
                  options={"time_limit": 1, "mip_rel_gap": .001, "presolve": True})
    if result.x is None:
        return np.zeros(n), {"feasible": False, "status": int(result.status), "message": result.message}
    q = np.rint(result.x[:n]) * a["pack"]
    failed = checks(q, rules, groups)
    return q, {"feasible": not failed, "tool": "constrained_order", "status": int(result.status),
               "objective": float(result.fun), "checks": failed}


class Inventory:
    def __init__(self, data, seed):
        self.n = len(data["series_ids"])
        self.seed = seed
        self.shelf = 3 if data["dataset"] == "RetailNet" else 10000
        quantity = np.ceil(data["historical_mean"] * 3)
        self.batches = [[] for _ in range(self.n)]
        for i, value in enumerate(quantity):
            if self.shelf == 3:
                base, rest = divmod(int(value), 3)
                self.batches[i] = [[float(base + int(j >= 3-rest)), j] for j in range(3) if base + int(j >= 3-rest)]
            elif value:
                self.batches[i] = [[float(value), self.shelf]]
        self.pending = []
        self.total_receipts = 0.0
        self.initial_units = float(quantity.sum())
        self.received_today = 0.0

    def stock(self):
        return np.array([sum(b[0] for b in rows) for rows in self.batches])

    def begin(self, day):
        self.received_today = 0.0
        remaining = []
        for row in self.pending:
            if row["due"] <= day:
                self.batches[row["series"]].append([row["quantity"], day + self.shelf - 1])
                self.received_today += row["quantity"]
            else:
                remaining.append(row)
        self.pending = remaining
        self.total_receipts += self.received_today

    def execute(self, day, q, rules, groups):
        a = rule_arrays(rules, groups)
        purchase = 0.0
        for i, quantity in enumerate(q):
            if not quantity:
                continue
            draw = rng(self.seed, "supply", day, i)
            cancelled = draw.random() < .02
            fill = draw.choice([.8, 1.0], p=[.1, .9])
            amount = 0.0 if cancelled else float(np.floor(quantity * fill))
            delay = int(draw.choice([0, 1], p=[.9, .1]))
            if amount:
                self.pending.append({"series": i, "quantity": amount,
                                     "due": day + int(a["lead_days"][i]) + delay, "ordered": day})
                purchase += amount
        return purchase

    def end(self, day, demand):
        before = self.stock()
        sold = np.minimum(before, demand)
        expired = np.zeros(self.n)
        for i, rows in enumerate(self.batches):
            amount = sold[i]
            new = []
            for quantity, expiry in sorted(rows, key=lambda r: r[1]):
                used = min(quantity, amount); quantity -= used; amount -= used
                if expiry <= day:
                    expired[i] += quantity
                elif quantity > 1e-9:
                    new.append([quantity, expiry])
            self.batches[i] = new
        lost = demand - sold
        stock = self.stock()
        assert np.allclose(before - sold - expired, stock, atol=1e-6)
        holding = float(stock.sum() * .02)
        shortage = float(lost.sum() * 5)
        waste = float(expired.sum())
        return {"demand": float(demand.sum()), "sales": float(sold.sum()), "lost": float(lost.sum()),
                "expiry_units": waste, "stock": float(stock.sum()), "holding_cost": holding,
                "shortage_cost": shortage, "expiry_cost": waste,
                "operating_cost": holding + shortage + waste,
                "sales_by_series": sold.tolist(), "demand_by_series": demand.tolist(),
                "lost_by_series": lost.tolist(), "expiry_by_series": expired.tolist(),
                "stock_by_series": stock.tolist(), "received_units": self.received_today}

    def target(self, forecast, residual_sd, day, rules, groups, priority, age_aware):
        a = rule_arrays(rules, groups)
        z = 1.65 if priority == "service_first" else 1.28
        desired = np.zeros(self.n)
        urgency = np.ones(self.n)
        current = self.stock()
        for i in range(self.n):
            lead = int(a["lead_days"][i])
            mean = np.asarray(forecast[i, day:day+lead+1])
            safety = z * residual_sd[i] * np.sqrt(lead+1)
            if not age_aware:
                pipeline = sum(p["quantity"] for p in self.pending if p["series"] == i and p["due"] <= day+lead)
                desired[i] = max(0, mean.sum() + safety - current[i] - pipeline)
            else:
                batches = [b.copy() for b in self.batches[i]]
                for offset in range(lead+1):
                    when = day+offset
                    if offset:
                        batches += [[p["quantity"], when+self.shelf-1] for p in self.pending if p["series"] == i and p["due"] == when]
                    if offset == lead:
                        available = sum(q for q, expiry in batches if expiry >= when)
                        desired[i] = max(0, mean[-1] + safety - available)
                        break
                    need = mean[offset]
                    new = []
                    for q, expiry in sorted(batches, key=lambda b: b[1]):
                        taken = min(q, need); q -= taken; need -= taken
                        if expiry > when and q > 1e-9:
                            new.append([q, expiry])
                    batches = new
            urgency[i] = 1 + min(2, max(0, mean.sum() - current[i]) / max(mean.sum(), 1))
        return desired, urgency
