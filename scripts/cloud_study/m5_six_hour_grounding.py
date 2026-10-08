#!/usr/bin/env python3
"""Separate development check; expected labels never enter model requests."""
from pathlib import Path
import json
import time
from ega.config import load_config
from ega.data.panel import Panel
from ega.constraints import synthetic_contracts, render_templates, render_prose
from ega.agents.llm import LLMClient, Extraction, ModelUnavailable
from ega.agents.roles import FORMAT_CONVENTIONS
from ega.evaluation.grounding import signature
from ega.store import ArtifactStore
from ega.util import atomic_json

repo = Path('/workspace/MasterDissertation')
output = repo / 'results/six_hour_development_grounding'
output.mkdir(exist_ok=True)
identity = json.loads((repo / 'results/run_configs/six_hour_model_identity.json').read_text())
cfg = load_config(repo / 'results/run_configs/llm_prose_study_ollama.yaml')
cfg.llm.model = identity['model']
cfg.llm.model_revision = identity['digest']
cfg.llm.max_tokens = 1000
cfg.llm.timeout = 300
cfg.llm.retries = 0
cfg.llm.document_batch_size = 1
cfg.llm.spend_ledger = str(output / 'spend.json')
panel = Panel.load(repo / 'data/processed/m5')
assert panel.n == 30
rules = synthetic_contracts(panel.series, panel.price_at(1700).tolist(), panel.eligibility(1700),
                            1700, 4242, 'normal', False, cfg.solver.budget)[:2]
store = ArtifactStore(output / 'artifacts')
client = LLMClient(cfg.llm, store)
rows = []
try:
    for carrier, documents in [('template', render_templates(rules)), ('prose', render_prose(rules))]:
        for rule, document in zip(rules, documents):
            started = time.perf_counter()
            before = client.calls
            try:
                result = client.ask('supplier and constraint agent', {
                    'documents': [document.payload()], 'day': 1700,
                    'known_entities': [s.model_dump() for s in panel.series],
                    'task': 'Extract all active source rules. Preserve values and units exactly. Do not silently resolve conflicts.',
                    'format_conventions': FORMAT_CONVENTIONS}, Extraction)
                expected = {signature(rule.model_dump())}
                actual = {signature(c.model_dump()) for c in result.constraints}
                row = {'carrier': carrier, 'source_ref': document.ref, 'whole_set_exact_match': actual == expected,
                       'exact_rules': len(actual & expected), 'false_rules': len(actual - expected),
                       'omitted_rules': len(expected - actual), 'issues': result.issues}
            except ModelUnavailable as exc:
                row = {'carrier': carrier, 'source_ref': document.ref, 'whole_set_exact_match': False,
                       'error': str(exc), 'exact_rules': 0, 'omitted_rules': 1}
            row.update(elapsed_seconds=time.perf_counter()-started, calls=client.calls-before)
            rows.append(row)
            atomic_json(output / 'grounding_results.json', {
                'mode': 'real_llm', 'development_only': True, 'complete': len(rows) == 4,
                'series': 30, 'day': 1700, 'model': identity['model'], 'model_revision': identity['digest'],
                'document_batch_size': 1, 'cases': rows, 'llm_calls': client.calls, 'tokens': client.tokens,
                'llm_errors': client.errors, 'llm_seconds': client.seconds,
                'warning': 'Four controlled development cases with all 30 entities; not evaluation or general natural-language accuracy.'})
            print(json.dumps(row), flush=True)
finally:
    store.close()
