#!/usr/bin/env python3
"""Compare one/four-document serving batches before any Qwen1.5 evaluation."""
from pathlib import Path
import json
import time
from ega.config import load_config
from ega.data.panel import Panel
from ega.constraints import synthetic_contracts, render_templates, render_prose
from ega.agents.llm import LLMClient, Extraction, ModelUnavailable
from ega.agents.roles import FORMAT_CONVENTIONS
FORMAT_CONVENTIONS += " " + json.loads(Path("/workspace/tools/six_hour_prompt_profile.json").read_text())["additional_conventions"]
from ega.evaluation.grounding import signature
from ega.store import ArtifactStore
from ega.util import atomic_json

repo = Path('/workspace/MasterDissertation')
output = repo / 'results/six_hour_qwen15_documented_format_development'
output.mkdir(exist_ok=True)
identity = json.loads((repo / 'results/run_configs/six_hour_model_identity.json').read_text())
assert identity['model'] == 'ega-qwen2.5:1.5b-sixhour'
cfg = load_config(repo / 'results/run_configs/llm_prose_study_ollama.yaml')
cfg.llm.model, cfg.llm.model_revision = identity['model'], identity['digest']
cfg.llm.max_tokens, cfg.llm.timeout, cfg.llm.retries = 4000, 300, 0
cfg.llm.spend_ledger = str(output / 'spend.json')
panel = Panel.load(repo / 'data/processed/m5')
assert panel.n == 30
rules = synthetic_contracts(panel.series, panel.price_at(1700).tolist(), panel.eligibility(1700),
                            1700, 4242, 'normal', False, cfg.solver.budget)[:4]
store = ArtifactStore(output / 'artifacts')
client = LLMClient(cfg.llm, store)
rows = []
try:
    for batch_size in (4,):
        for carrier, renderer in [('template', render_templates), ('prose', render_prose)]:
            chosen = rules[:batch_size]
            documents = renderer(chosen)
            started, before = time.perf_counter(), client.calls
            try:
                result = client.ask('supplier and constraint agent', {
                    'documents': [document.payload() for document in documents], 'day': 1700,
                    'known_entities': [s.model_dump() for s in panel.series],
                    'task': 'Extract all active source rules. Preserve values and units exactly. Do not silently resolve conflicts.',
                    'format_conventions': FORMAT_CONVENTIONS}, Extraction)
                expected = {signature(rule.model_dump()) for rule in chosen}
                actual = {signature(c.model_dump()) for c in result.constraints}
                row = {'carrier': carrier, 'expected_rules': len(expected), 'whole_set_exact_match': actual == expected,
                       'exact_rules': len(actual & expected), 'false_rules': len(actual - expected),
                       'omitted_rules': len(expected - actual), 'issues': result.issues}
            except ModelUnavailable as exc:
                row = {'carrier': carrier, 'expected_rules': len(chosen), 'whole_set_exact_match': False,
                       'error': str(exc), 'exact_rules': 0, 'omitted_rules': len(chosen)}
            row.update(batch_size=batch_size, elapsed_seconds=time.perf_counter()-started,
                       calls=client.calls-before, source_refs=[d.ref for d in documents])
            rows.append(row)
            atomic_json(output / 'grounding_results.json', {
                'mode': 'real_llm', 'development_only': True, 'complete': len(rows) == 2,
                'series': 30, 'day': 1700, 'model': identity['model'], 'model_revision': identity['digest'],
                'cases': rows, 'llm_calls': client.calls, 'tokens': client.tokens,
                'llm_errors': client.errors, 'llm_seconds': client.seconds,
                'warning': 'Four controlled development cases; serving batch selection only. Expected labels are excluded from all requests.'})
            print(json.dumps(row), flush=True)
finally:
    store.close()
