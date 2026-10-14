"""Selective delegation: structured intake, language interpretation, policy routing and a hard gate."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'study_results/architecture_study_20261013'
BASE_PATH = ROOT / 'scripts/ollama_clean_study/core.py'
spec = importlib.util.spec_from_file_location('frozen_replenishment_core', BASE_PATH)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

ARMS = ['fixed_agents', 'selective_agents', 'structured_planner']
TABLE_HEADER = 'Supplier | Carton size | Minimum order | Delivery days | Daily dispatch limit'


def structured_intake(message):
    """Parse only the declared table format. Malformed declared tables request review.

    Reads the message itself; never copies values from the authenticated reference.
    Other prose goes to the language model. A recognised but broken table does not.
    """
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if TABLE_HEADER not in lines:
        return {'route': 'language', 'extracted': None, 'reason': 'unstructured_supplier_message'}
    header = lines.index(TABLE_HEADER)
    candidates = lines[header + 1:header + 4]
    if len(candidates) != 3:
        return {'route': 'review', 'extracted': None, 'reason': 'incomplete_supplier_table'}
    rows = []
    for line in candidates:
        match = re.fullmatch(r'(S[123])\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)', line)
        if not match:
            return {'route': 'review', 'extracted': None, 'reason': 'malformed_supplier_table'}
        supplier, pack, moq, lead, capacity = match.groups()
        rows.append(dict(supplier=supplier, pack=int(pack), moq=int(moq), lead_days=int(lead), capacity=int(capacity)))
    if {row['supplier'] for row in rows} != {'S1', 'S2', 'S3'}:
        return {'route': 'review', 'extracted': None, 'reason': 'duplicate_or_missing_supplier'}
    if any('|' in line for line in lines[header + 4:]):
        return {'route': 'review', 'extracted': None, 'reason': 'unexpected_table_rows'}
    budgets = re.findall(r'^The current daily spending budget is (\d+) cost-index units\. Each purchased unit costs one cost-index unit\.$', message, flags=re.M)
    if len(budgets) != 1:
        return {'route': 'review', 'extracted': None, 'reason': 'missing_or_duplicate_budget'}
    parsed = {'rules': rows, 'budget': int(budgets[0])}
    import jsonschema
    try:
        jsonschema.validate(parsed, base.SCHEMAS['supplier'])
    except jsonschema.ValidationError:
        return {'route': 'review', 'extracted': None, 'reason': 'table_schema_invalid'}
    return {'route': 'structured', 'extracted': parsed, 'reason': 'complete_declared_table'}


def policy_route(event):
    """Use an announced business event, never future demand or the experiment's score."""
    active = event.get('active_promotion') if isinstance(event, dict) else None
    if type(active) is not bool:
        return {'valid': False, 'priority': None, 'reason': 'promotion_status_unknown', 'review_required': True}
    return {'valid': True, 'priority': 'service_first' if active else 'balanced',
            'reason': 'declared_promotion_policy' if active else 'declared_routine_policy',
            'review_required': False}


def release_permitted(source_ok, route_ok, solver, action_failures, intake_review=False):
    """A model cannot override an unsuccessful source, route, solver or action check."""
    return bool(source_ok and route_ok and solver.get('feasible') is True and not action_failures and not intake_review)


class LiveClient(base.Ollama):
    """Same native model, prompts and generation settings as the existing workflow."""
    def ask(self, role, content, name):
        parsed = super().ask(role, content, name)
        file = self.output / f'{name}_{role}.json'
        self.records[-1]['path'] = str(file.relative_to(OUT))
        return parsed
