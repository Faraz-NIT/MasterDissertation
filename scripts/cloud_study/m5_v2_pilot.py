"""Bounded local development benchmark and separately frozen replenishment pilot."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

import pandas as pd
from ega.agents.grounding_v2 import GroundingV2Agent, public_source_proof, render_hybrid_prose
from ega.agents.llm import LLMClient
from ega.config import ExperimentConfig, LLMConfig
from ega.constraints import synthetic_contracts
from ega.data.panel import Panel
from ega.experiment import run_one, summarize_study
from ega.forecasting.core import build_forecaster
from ega.schemas import Lineage
from ega.store import ArtifactStore
from ega.util import atomic_json, canonical, digest, environment


ROOT=Path('/workspace/MasterDissertation')
OUT=ROOT/'results/v2_pilot'
PROTOCOL=OUT/'protocol.json'
START=datetime.fromisoformat('2026-10-07T22:47:14+00:00')
BASES={'qwen15':'qwen2.5:1.5b','llama3':'llama3.2:3b'}
MODEL_NAMES={'qwen15':'ega-qwen2.5:1.5b-v2','llama3':'ega-llama3.2:3b-v2'}
ARMS={'parser_no_recovery':('B4',False),'parser_recovery':('B4',True),
      'llm_v2_no_recovery':('B10',False),'llm_v2_recovery':('B10',True)}


def now():return datetime.now(timezone.utc).isoformat()


def audit(stage,payload):
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'work_log.jsonl'
    previous='0'*64
    if path.exists():
        lines=path.read_text().splitlines()
        if lines:previous=json.loads(lines[-1])['hash']
    row={'recorded_at_utc':now(),'stage':stage,'payload':payload,'previous_hash':previous}
    row['hash']=digest(row)
    with path.open('a') as f:f.write(canonical(row)+'\n');f.flush();os.fsync(f.fileno())


def api(path,body=None):
    req=urllib.request.Request('http://127.0.0.1:11434'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=300) as r:return json.load(r)


def guard():
    if datetime.now(timezone.utc)>=START+timedelta(hours=5,minutes=30):
        raise TimeoutError('Registered experiment cutoff reached; preserve partial artifacts and report them honestly')
    if shutil.disk_usage(ROOT).free<2*1024**3:raise RuntimeError('Disk reserve below2GiB')


def prepare():
    if PROTOCOL.exists():raise FileExistsError('Existing v2 protocol must not be overwritten')
    OUT.mkdir(parents=True,exist_ok=True)
    frozen={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT/'src').rglob('*.py')}
    before={'root_checkout':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'source_sha256':frozen,'environment':environment(), 'ollama_version':api('/api/version'),
            'model_tags_before':api('/api/tags')}
    atomic_json(OUT/'initial_environment.json',before)
    protocol={'schema_version':'m5-agent-v2-pilot-protocol-v1','status':'development',
        'requested_at_utc':START.isoformat(),'report_deadline_utc':(START+timedelta(hours=6)).isoformat(),
        'experiment_cutoff_utc':(START+timedelta(hours=5,minutes=30)).isoformat(),
        'user_timezone':'Europe/Paris','dataset':'data/processed/m5','series':30,
        'development':{'day':1700,'seed':4242,'variants':[0,1],
            'candidate_models':MODEL_NAMES,'semantic_retries':1,'transport_retries':0,
            'selection_rule':'Most fully proved complete-case successes, then fewer semantic correction attempts, then lower total measured elapsed seconds. No evaluation outcomes used.',
            'cache_demonstration':'One additional repeated development case with verified cache; never part of accuracy selection.'},
        'evaluation':{'start_day':1858,'warmup_days':14,'days':14,'origins':1,
            'seeds':[13,29],'scenarios':['normal','derived_field_collapse','feed_gap','capacity_cut'],
            'arms':{k:{'policy':v[0],'recovery':v[1],'root':str(OUT/k)} for k,v in ARMS.items()},
            'expected_runs':32,'expected_decisions':448,'carrier':'hybrid_prose',
            'same_trained_forecaster':True,'same_source_information':True,
            'shared_source_inventory_observation':True,'approval_mode':'hold',
            'deterministic_critic_all_arms':True,'llm_numeric_routing':False},
        'limits':{'API_dollar_cost':0,'new_model_downloads':False,'inference_parallelism':1,
            'CPU_threads_for_model':3,'max_recorded_requests':1000,'minimum_disk_reserve_gib':2},
        'interpretation':[
            'A small exploratory pilot, not a new full dissertation or powered confirmatory study.',
            'All30series simulated; public grammars parsed locally and only two bounded supplier/portfolio clauses require live extraction.',
            'The strongest deterministic parser also covers hybrid source-slot grammars, so model success cannot establish superiority over that parser.',
            'Raw source_quantity is an explicitly added simulated current observation, exposed before corruption equally to every arm.',
            'Recovery tool independently verifies source/ledger agreement; no clean state, hidden evaluator problem, realized future demand or oracle reaches the agents.',
            'Two-day version1 study is historical failure context, not a matched cost/service comparator.',
            'Caching creates reused evidence, not new independent model accuracy trials.',
            'Supplier clauses and operational state/faults simulated; observed M5 sales used as a demand proxy.',
            'Hold and purchase expenditure are not savings; terminal inventory lacks salvage credit.'
        ]}
    atomic_json(PROTOCOL,protocol)
    audit('protocol_created',{'protocol':str(PROTOCOL),'sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()})
    profiles={}
    for label,base in BASES.items():
        request={'model':MODEL_NAMES[label],'from':base,'stream':False,
                 'parameters':{'num_ctx':8192,'num_thread':3,'temperature':0,'seed':42}}
        response=api('/api/create',request)
        tags={x['name']:x for x in api('/api/tags')['models']}
        profile={'request':request,'response':response,'identity':tags[MODEL_NAMES[label]],
                 'show':api('/api/show',{'model':MODEL_NAMES[label]})}
        profiles[label]=profile
        audit('local_model_profile_created',{'label':label,'request':request,'response':response,
                                             'model_digest':profile['identity']['digest']})
    atomic_json(OUT/'candidate_model_profiles.json',profiles)
    print(json.dumps({'phase':'prepared','protocol':str(PROTOCOL)}),flush=True)


def benchmark(round_no=1,compact=False):
    profiles=json.loads((OUT/'candidate_model_profiles.json').read_text())
    panel=Panel.load(ROOT/'data/processed/m5');day=1728 if compact else 1700;seed=4050 if compact else 4242
    if compact:
        protocol=json.loads(PROTOCOL.read_text())
        protocol['development']['additional_round']={'round':round_no,'day':day,'seed':seed,
            'compact_output':True,'registered_at_utc':now(),
            'reason':'Both candidates failed original full-tuple development; reduce output to model-interpreted value/unit with exact short evidence span. Trusted source tools supply and validate structural metadata.',
            'selection_rule':protocol['development']['selection_rule'],'evaluation_started':False}
        atomic_json(PROTOCOL,protocol)
        audit('compact_development_round_registered',protocol['development']['additional_round'])
    rules=synthetic_contracts(panel.series,panel.price_at(day).tolist(),panel.eligibility(day),
                              day,seed,'normal',False,3000)
    report=[]
    for label in BASES:
        guard();identity=profiles[label]['identity'];labelroot=OUT/'development'/(label if round_no==1 else f'{label}_round{round_no}')
        if (labelroot/'summary.json').exists():raise FileExistsError(labelroot)
        store=ArtifactStore(labelroot/'artifacts')
        client=LLMClient(LLMConfig(enabled=True,model=identity['name'],model_revision=identity['digest'],
            prompt_profile='v2',max_tokens=2048,timeout=240,retries=0,document_batch_size=2,
            max_calls=50,use_memory=False,spend_ledger=str(labelroot/'spend.json')),store)
        cases=[];cache={};total_started=time.perf_counter()
        for variant in [0,1]:
            guard();case_id=f'{label}-development-variant{variant}';client.audit_decision_id=case_id
            docs=render_hybrid_prose(rules,variant)
            # Full30-series coverage; only2bounded clauses are unresolved.
            agent=GroundingV2Agent(cache=cache,model_revision=identity['digest'],
                context_version=f'v2-development-round{round_no}-separate-from-evaluation',
                semantic_retries=1,compact_output=compact)
            def record(stage,obj,inputs=()):
                ref=store.put(obj);store.event(case_id,stage,{'inputs':list(inputs),'output':ref});return ref
            lineage=Lineage(snapshot_version=f'development{variant}',run_id=case_id,day=day)
            calls_before=client.calls;tokens_before=client.tokens;started=time.perf_counter()
            result=agent.run(docs,lineage,panel.series,day,client=client,record=record)
            row={'case_id':case_id,'variant':variant,'complete_proved_success':not result.issues,
                 'elapsed_seconds':time.perf_counter()-started,'calls':client.calls-calls_before,
                 'tokens':client.tokens-tokens_before,'issues':result.issues,'stats':dict(agent.last_stats),
                 'source_ref':store.put([d.payload() for d in docs]),'result_ref':store.put(result)}
            cases.append(row);audit('development_case_completed',row)
            print(json.dumps({'phase':'development',**row}),flush=True)
        summary={'label':label,'round':round_no,'compact_output':compact,'model':identity,'cases':cases,'calls':client.calls,'tokens':client.tokens,
                 'client_errors':client.errors,'seconds':time.perf_counter()-total_started,
                 'complete_successes':sum(c['complete_proved_success'] for c in cases),
                 'semantic_retries':sum(c['stats']['semantic_retries'] for c in cases),
                 'chain_valid':store.verify_chain()}
        assert summary['chain_valid'];atomic_json(labelroot/'summary.json',summary)
        if compact and summary['complete_successes']==2:
            case_id=f'{label}-development-round{round_no}-cache-probe';client.audit_decision_id=case_id
            calls_before=client.calls
            repeated=agent.run(render_hybrid_prose(rules,1),
                Lineage(snapshot_version='cache-probe',run_id=case_id,day=day),panel.series,day,
                client=client,record=record)
            probe={'issues':repeated.issues,'new_calls':client.calls-calls_before,'stats':agent.last_stats,
                   'chain_valid':store.verify_chain(),'selection_accuracy_case':False}
            assert not probe['issues'] and probe['new_calls']==0 and probe['stats']['cache_hits']==157
            atomic_json(labelroot/'cache_probe.json',probe);audit('development_cache_probe',{'label':label,**probe})
        store.close();report.append(summary)
    report.sort(key=lambda x:(-x['complete_successes'],x['semantic_retries'],x['seconds']))
    selected=report[0]
    # Clean-case gate: do not launch inventory exposure while extraction cannot produce all mandatory evidence.
    eligible=selected['complete_successes']==2 and selected['client_errors']==0
    result={'candidates':report,'selected_label':selected['label'],'selected_model':selected['model'],
            'inventory_pilot_eligible':eligible,'selection_used_evaluation_outcomes':False,
            'selected_at_utc':now()}
    result.update(round=round_no,compact_output=compact,development_day=day,development_seed=seed)
    selection_path=OUT/('development_selection.json' if round_no==1 else f'development_selection_round{round_no}.json')
    atomic_json(selection_path,result)
    atomic_json(OUT/'development_current_selection.json',{'source':str(selection_path),**result})
    audit('development_selection_frozen',result)
    print(json.dumps({'phase':'development_selection','eligible':eligible,'selected':selected['label']}),flush=True)
    return eligible


def freeze():
    selection=json.loads((OUT/'development_current_selection.json').read_text())
    if not selection['inventory_pilot_eligible']:raise RuntimeError('Clean-case evidence gate failed; no inventory pilot may be launched')
    protocol=json.loads(PROTOCOL.read_text())
    if protocol['status']=='frozen':raise FileExistsError('Pilot already frozen; use run phase')
    model=selection['selected_model'];configs={}
    for label,(policy,recovery) in ARMS.items():
        config=ExperimentConfig.model_validate({'dataset':str(ROOT/'data/processed/m5'),'output':str(OUT/label),
            'policies':[policy],'scenarios':['normal','derived_field_collapse','feed_gap','capacity_cut'],'seeds':[13,29],
            'start_day':1858,'days':14,'origins':1,'origin_stride':28,'warmup_days':14,
            'document_carrier':'hybrid_prose','approval_mode':'hold','oracle':True,
            'forecast':{'deep_epochs':10,'lgbm_estimators':150,'max_training_windows':12000},
            'solver':{'horizon':7,'scenarios':4,'time_limit':5,'mip_gap':.001,'risk_weight':.1,'cvar_alpha':.95},
            'quality':{'version':'synthetic-v2-pilot-NOT-calibrated','calibrated':False,
                       'onset_rate':.025,'min_duration':1,'max_duration':5},
            'agent_v2':{'enabled':True,'cache_enabled':True,'cache_path':str(OUT/'evaluation_verified_cache'),
                        'compact_output':selection.get('compact_output',False),
                        'semantic_retries':1,'state_recovery':recovery,'expose_source_inventory':True,
                        'llm_recovery_selection':True,'llm_numeric_routing':False,'llm_critic':False},
            'llm':{'enabled':policy=='B10','base_url':'http://localhost:11434/v1','provider':'openai_compatible',
                   'model':model['name'],'model_revision':model['digest'],'prompt_profile':'v2',
                   'max_tokens':2048,'timeout':240,'retries':0,'document_batch_size':2,
                   'max_calls':1000,'json_mode':'schema','temperature':0,'on_failure':'hold','use_memory':False,
                   'spend_ledger':str(OUT/'evaluation_spend.json')}})
        path=OUT/'configs'/f'{label}.json';atomic_json(path,config)
        configs[label]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    source={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ['src','tests'] for p in (ROOT/folder).rglob('*.py')}
    protocol.update(status='frozen',frozen_at_utc=now(),selected_model=model,configs=configs,
                    frozen_source_sha256=source,
                    base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    protocol['evaluation'].update(scenarios=['normal','derived_field_collapse','feed_gap','capacity_cut'],
                                  expected_runs=32,expected_decisions=448)
    protocol['evaluation']['capacity_cut_registration']={
        'registered_at_utc':now(),'evaluation_started':False,
        'reason':'Exercise changed numerical supplier capacity, absent from constant-capacity clean development cases. Added before evaluation with no evaluation outcomes observed.'}
    protocol['frozen_prepared_data_sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in (ROOT/'data/processed/m5').iterdir() if p.is_file()}
    protocol['frozen_helper_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path('/workspace/tools/m5_v2_pilot.py'),Path('/workspace/tools/m5_v2_supervisor.py')]}
    protocol['code_version_note']='Explicitly authorized version2 coding task. Original version1 artifacts are unchanged. Pre-freeze additions include compact source-grounding, independent recovery, stable arrival-opportunity sampling, and request-before-transport audit logging.'
    atomic_json(PROTOCOL,protocol)
    diff=subprocess.check_output(['git','diff','--binary'],cwd=ROOT)
    (OUT/'tracked_code_changes.patch').write_bytes(diff)
    for name,sha256 in source.items():
        target=OUT/'frozen_code'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
        assert hashlib.sha256(target.read_bytes()).hexdigest()==sha256
    atomic_json(OUT/'frozen_source_inventory.json',source)
    audit('evaluation_protocol_frozen',{'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
                                       'model_digest':model['digest'],'configs':configs})
    print(json.dumps({'phase':'frozen','model':model['name']}),flush=True)


def run():
    protocol=json.loads(PROTOCOL.read_text());assert protocol['status']=='frozen'
    for path,expected in protocol['frozen_source_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected, f'Source changed after freeze: {path}'
    for path,expected in protocol['frozen_prepared_data_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected, f'Data changed after freeze: {path}'
    for path,expected in protocol['frozen_helper_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected, f'Helper changed after freeze: {path}'
    tags={x['name']:x for x in api('/api/tags')['models']}
    selected=protocol['selected_model'];assert tags[selected['name']]['digest']==selected['digest']
    panel=Panel.load(ROOT/'data/processed/m5');assert panel.n==30
    first_cfg=ExperimentConfig.model_validate(json.loads(Path(protocol['configs']['parser_no_recovery']['path']).read_text()))
    guard();audit('shared_forecast_training_started',{'train_end_exclusive':1844})
    model=build_forecaster('deep',first_cfg.forecast).fit(panel,1844)
    shared=OUT/'shared';shared.mkdir(exist_ok=True);model.save(shared/'model_deep_origin0.pt')
    model_sha=hashlib.sha256((shared/'model_deep_origin0.pt').read_bytes()).hexdigest()
    atomic_json(shared/'model_identity.json',{'path':str(shared/'model_deep_origin0.pt'),'sha256':model_sha,
        'training_end':model.training_end,'forecast_config':first_cfg.forecast.model_dump(),
        'source_inventory':protocol['frozen_source_sha256']})
    audit('shared_forecast_training_completed',{'model_sha256':model_sha,'training_end':model.training_end})
    for label in ARMS:
        guard();entry=protocol['configs'][label];path=Path(entry['path'])
        assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
        cfg=ExperimentConfig.model_validate(json.loads(path.read_text()));stage=Path(cfg.output)
        if stage.exists():raise FileExistsError(f'Rerun refused: {stage}')
        stage.mkdir();atomic_json(stage/'resolved_config.json',cfg);atomic_json(stage/'environment.json',environment())
        rows=[];atomic_json(stage/'shared_model_reference.json',{'path':str(shared/'model_deep_origin0.pt'),'sha256':model_sha})
        for scenario in cfg.scenarios:
            for seed in cfg.seeds:
                guard();runroot=stage/f'{cfg.policies[0]}__{scenario}__seed{seed}__origin0'
                audit('run_started',{'arm':label,'scenario':scenario,'seed':seed,'path':str(runroot)})
                print(json.dumps({'phase':'run_started','arm':label,'scenario':scenario,'seed':seed}),flush=True)
                row=run_one(panel,cfg,cfg.policies[0],scenario,seed,0,model,runroot)
                rows.append(row);pd.DataFrame(rows).to_csv(stage/'summary.csv',index=False)
                assert row['chain_valid'];audit('run_completed',{'arm':label,**row})
                print(json.dumps({'phase':'run_completed','arm':label,**row}),flush=True)
        summarize_study(stage,cfg)
        audit('arm_completed',{'arm':label,'runs':len(rows)})
    final={'status':'COMPLETE','completed_at_utc':now(),'runs':32,'decisions':448,
           'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
           'model_identity':api('/api/tags'),'API_usage':json.loads((OUT/'evaluation_spend.json').read_text())
           if (OUT/'evaluation_spend.json').exists() else {'calls':0,'usd':0},
           'no_forecast_retraining_between_arms':True}
    atomic_json(OUT/'execution_complete.json',final);audit('evaluation_completed',final)
    print(json.dumps({'phase':'COMPLETE','runs':32,'decisions':448}),flush=True)


if __name__=='__main__':
    os.chdir(ROOT)
    args=argparse.ArgumentParser();args.add_argument('phase',choices=['prepare','benchmark','benchmark-compact','freeze','run'])
    phase=args.parse_args().phase
    try:
        if phase=='prepare':prepare()
        elif phase=='benchmark':benchmark()
        elif phase=='benchmark-compact':benchmark(round_no=2,compact=True)
        elif phase=='freeze':freeze()
        else:run()
    except BaseException as exc:
        audit('phase_failure',{'phase':phase,'type':type(exc).__name__,'message':str(exc)})
        raise
