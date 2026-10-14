"""Fresh, bounded LangChain implementation validation, separate from the full study.

The frozen matched-case executor is reused, with its graph dependency replaced
by the actual LCEL chain. Only the trace field is renamed in the saved records.
No earlier model responses enter this live validation.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain import CHAIN, ROOT, base
import importlib.util

SOURCE = ROOT / 'scripts/architecture_study/run.py'
spec = importlib.util.spec_from_file_location('previous_matched_executor', SOURCE)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)

OUT = ROOT / 'study_results/langchain_extension_20261014'
PRIOR = ROOT / 'study_results/architecture_study_20261013'


def now():
    return datetime.now(timezone.utc).isoformat()


def event(stage, **fields):
    row = {'at_utc':now(),'stage':stage,**fields}
    with (OUT/'workflow.jsonl').open('a') as stream:
        stream.write(json.dumps(row)+'\n')
    print(json.dumps(row),flush=True)


class LiveClient(base.Ollama):
    def ask(self, role, content, name):
        answer = super().ask(role,content,name)
        self.records[-1]['path'] = str((self.output/f'{name}_{role}.json').relative_to(OUT))
        return answer


def freeze():
    if (OUT/'protocol.json').exists():
        raise FileExistsError('Preserve the frozen protocol')
    tests = json.loads((OUT/'development/tests.json').read_text())
    assert tests['status'] == 'PASS' and tests['passed'] == 16
    prior = json.loads((PRIOR/'protocol.json').read_text())
    assert json.loads((PRIOR/'analysis/audit_receipt.json').read_text())['status'] == 'VERIFIED'
    for name,digest in prior['code_sha256'].items():
        assert base.sha(ROOT/name) == digest
    shutil.copytree(PRIOR/'data',OUT/'data',dirs_exist_ok=True)
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=10) as stream:
        model = next(m for m in json.load(stream)['models'] if m['name'] == base.MODEL)
    assert model['digest'] == prior['model']['digest']
    protocol = copy.deepcopy(prior)
    protocol.update({
        'schema':'langchain-extension-validation-v1','status':'FROZEN','frozen_at_utc':now(),
        'purpose':'Fresh implementation validation; not a new 30-seed performance study',
        'question':'Does the LangChain implementation retain the selective architecture and its guarded planning behaviour?',
        'framework':{'langchain-core':version('langchain-core'),'LCEL':True,'StructuredTool':True,
                     'compiled_langgraph_invoked':False,'external_tracing':False},
        'orchestration':{'framework':'LangChain LCEL','langchain_core_version':version('langchain-core'),
                         'compiled_langgraph_invoked':False,'per_decision_step_traces':True,
                         'external_tracing_service':False,'checkpoint_or_response_cache':False},
        'inference':'No fresh inferential estimates: single-seed implementation validation only',
        'success_rule':'Complete execution, fresh native responses, correct paths and independent safety/ledger audit',
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'arms':{'fixed_agents':'Previous three-role fixed agent, executed with LangChain',
                'selective_agents':'Selective extension, executed with LangChain',
                'structured_planner':'Same structured-input numerical reference, executed with LangChain'},
        'simulation_seeds':[233],'expected_cases':12,'expected_runs':36,
        'expected_portfolio_days':252,'expected_fixed_agent_days':84,'expected_selective_agent_days':84,
        'expected_fixed_fresh_calls':252,'expected_selective_supplier_calls_if_no_failures':48,
        'expected_table_decisions':36,'fresh_model_response_reuse':False,
        'native_llm_response_cache':False,'llm_retries':0,
        'primary_architecture_study_protocol_sha256':base.sha(PRIOR/'protocol.json'),
        'primary_architecture_study_folder':str(PRIOR.relative_to(ROOT)),
        'hypotheses':{},'inferential_analysis':'None: one seed is an implementation check, not a fresh confidence-interval study',
        'success_checks':['All 36 matched runs complete','Native model responses are fresh and logged',
                          'Every path follows LangChain delegation and release rules',
                          'No released budget, capacity, carton or minimum-order violations',
                          'Independent physical-ledger audit passes'],
        'historical_periods_are_unseen_holdouts':False,
    })
    protocol.pop('experiment_cutoff_utc',None)
    sources = [ROOT/'scripts/langchain_extension'/name for name in
               ['chain.py','validation_run.py','validate.py','replay.py','requirements.txt']]
    sources += [ROOT/'tests/test_langchain_extension.py', SOURCE,
                ROOT/'scripts/architecture_study/graph.py',ROOT/'scripts/architecture_study/architecture.py',
                ROOT/'scripts/architecture_study/analyze.py',ROOT/'scripts/architecture_study/independent_ledger.py',
                ROOT/'scripts/ollama_clean_study/core.py']
    protocol['code_sha256'] = {str(path.relative_to(ROOT)):base.sha(path) for path in sources}
    for dataset,info in protocol['datasets'].items():
        for name,digest in info['file_sha256'].items():
            assert base.sha(OUT/'data'/dataset/name) == digest
    base.dump(OUT/'protocol.json',protocol)
    event('validation_frozen',expected_runs=36,simulation_seeds=[233])


def execute():
    protocol = json.loads((OUT/'protocol.json').read_text())
    if (OUT/'execution_receipt.json').exists() or list((OUT/'runs').glob('*')):
        raise FileExistsError('Never overwrite or resume a fresh validation')
    for name,digest in protocol['code_sha256'].items():
        assert base.sha(ROOT/name) == digest
    shared.OUT,shared.GRAPH,shared.LiveClient = OUT,CHAIN,LiveClient
    results = []
    started = time.perf_counter()
    event('validation_started',protocol_sha256=base.sha(OUT/'protocol.json'))
    for scenario in protocol['scenarios']:
        for dataset,info in protocol['datasets'].items():
            for origin in info['origins']:
                seed = protocol['simulation_seeds'][0]
                event('case_started',dataset=dataset,origin=origin,scenario=scenario,runs_complete=len(results))
                results.extend(shared.run_case(shared.load(dataset,origin),scenario,seed))
                case = f'{dataset}__{scenario}__seed{seed}__origin{origin}'
                path = OUT/'runs'/case/'decisions.jsonl'
                records = [json.loads(line) for line in path.read_text().splitlines()]
                for record in records:
                    record['langchain_step_trace'] = record.pop('langgraph_node_trace')
                    record['orchestration_framework'] = 'LangChain LCEL'
                path.write_text(''.join(json.dumps(record,allow_nan=False)+'\n' for record in records))
                pd.DataFrame(results).to_csv(OUT/'summary.csv',index=False)
                event('case_finished',dataset=dataset,origin=origin,scenario=scenario,
                      runs_complete=len(results),fresh_calls=int(sum(r['model_calls'] for r in results)))
    receipt = {'status':'COMPLETE','at_utc':now(),'runs':len(results),'portfolio_days':len(results)*7,
               'fresh_primary_model_calls':int(sum(r['model_calls'] for r in results)),
               'elapsed_seconds':time.perf_counter()-started,'balanced_seeds_complete':[233],
               'scope':'Implementation validation, not the full 30-seed study',
               'protocol_sha256':base.sha(OUT/'protocol.json')}
    assert receipt['runs'] == protocol['expected_runs']
    base.dump(OUT/'execution_receipt.json',receipt)
    event('validation_finished',**receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase',choices=['freeze','run'])
    args = parser.parse_args()
    (freeze if args.phase == 'freeze' else execute)()
