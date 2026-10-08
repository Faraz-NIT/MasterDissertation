"""Frozen, bounded FreshRetailNet numerical and local-agent experiment owner."""
from __future__ import annotations
import argparse,fcntl,hashlib,json,multiprocessing as mp,os,pickle,shutil,subprocess,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from ega.config import ExperimentConfig,LLMConfig,ForecastConfig
from ega.data.panel import Panel
from ega.schemas import Series,Lineage
from ega.forecasting.core import build_forecaster
from ega.agents.grounding_v2 import GroundingV2Agent,render_hybrid_prose
from ega.agents.llm import LLMClient
from ega.constraints import synthetic_contracts
from ega.store import ArtifactStore
from ega.util import atomic_json,canonical,digest,environment

ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'results/freshretailnet';PROTOCOL=OUT/'protocol.json'
START='2026-10-08T09:19:34+00:00';CUTOFF='2026-10-08T13:25:00+00:00';DEADLINE='2026-10-08T14:19:34+00:00'
MODEL='ega-qwen2.5:1.5b-v2';MODEL_SHA='afc65fa44af0fb5f81dd6d0066bdf668521db7077c36a9635c09d13376fe4c90'
ARMS={'parser_no_recovery':('B4',False),'parser_recovery':('B4',True),'llm_no_recovery':('B10',False),'llm_recovery':('B10',True)}
MODELS={};PANEL=None

def now():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def audit(stage,payload):
    path=OUT/'workflow.jsonl';lock=OUT/'workflow.lock'
    with lock.open('a') as locked:
        fcntl.flock(locked,fcntl.LOCK_EX);previous='0'*64
        if path.exists():
            with path.open('rb') as f:
                f.seek(0,2);size=f.tell();f.seek(max(0,size-20000));lines=f.read().splitlines()
                if lines:previous=json.loads(lines[-1])['hash']
        row={'recorded_at_utc':now(),'stage':stage,'payload':payload,'previous_hash':previous};row['hash']=digest(row)
        with path.open('a') as f:f.write(canonical(row)+'\n');f.flush();os.fsync(f.fileno())
def guard():
    if datetime.now(timezone.utc)>=datetime.fromisoformat(CUTOFF):raise TimeoutError('Registered experiment cutoff reached; retain and report partial results')
    if shutil.disk_usage(ROOT).free<2*1024**3:raise RuntimeError('Disk reserve below2GiB')
def api(path):
    with urllib.request.urlopen('http://127.0.0.1:11434'+path,timeout=30) as r:return json.load(r)

def base_config(output,policies,scenarios,seeds,agent=False,recovery=False):
    return ExperimentConfig.model_validate({'dataset':str(ROOT/'data/processed/freshretailnet'),'output':str(output),'policies':policies,'scenarios':scenarios,'seeds':seeds,'start_day':90,'days':7,'warmup_days':14,'origins':1,'oracle':True,'document_carrier':'hybrid_prose' if agent else 'template','approval_mode':'hold','forecast':{'deep_epochs':10,'lgbm_estimators':150,'max_training_windows':12000},'solver':{'horizon':7,'scenarios':4,'time_limit':5,'mip_gap':.001,'unknown_arrival_rng':'v2_opportunity'},'quality':{'version':'FreshRetailNet-synthetic-faults-v1-NOT-calibrated','calibrated':False,'max_duration':5,'onset_rate':.025},'agent_v2':{'enabled':agent,'cache_enabled':True,'cache_path':str(OUT/'agent_verified_cache') if agent else None,'compact_output':True,'state_recovery':recovery,'expose_source_inventory':agent,'semantic_retries':1,'llm_recovery_selection':True,'llm_numeric_routing':False,'llm_critic':False},'llm':{'enabled':'B10' in policies,'provider':'openai_compatible','base_url':'http://127.0.0.1:11434/v1','model':MODEL,'model_revision':MODEL_SHA,'prompt_profile':'v2','max_tokens':2048,'timeout':240,'retries':0,'max_calls':1000,'document_batch_size':2,'temperature':0,'on_failure':'hold','use_memory':False,'spend_ledger':str(OUT/'evaluation_spend.json')}})

def register():
    if PROTOCOL.exists():raise FileExistsError('Do not overwrite a registered protocol')
    p={'schema_version':'freshretailnet-bounded-v1','status':'development','requested_at_utc':START,'experiment_cutoff_utc':CUTOFF,'report_and_push_deadline_utc':DEADLINE,'timezone':'Europe/Paris','source_revision':'08c1fab7f9257bc73679d415d65d644165d351d4','source_license':'CC-BY-4.0','release_validation':'All4.85milliondailyrows; source hashes, keys, hourly totals and flag alignment','computational_panel':json.loads((OUT/'data/selection.json').read_text()),'official_holdout':{'train_days':90,'eval_days':7,'origin':90,'eval_targets_opened_before_freeze':False},'forecast_study':{'fold_train_end_exclusive':[62,69,76,83],'horizon':7,'features':'historical sales lags, hour/day-of-week/series identity; no future actual sales, stockout masks, weather or promotions','mask_lengths':[2,4,8],'candidate_recovery':['raw_zero','profile','gbm'],'candidate_forecasts':['seasonal_naive_raw','lightgbm_raw','lightgbm_profile_recovered','lightgbm_gbm_recovered'],'selection':'training-validation metrics only, selected receipt before final eval load','natural_lost_demand_ground_truth':False},'numerical':{'policies':['B1','B2','B3','B4'],'scenarios':['normal','derived_field_collapse','feed_gap'],'seeds':list(range(30)),'days':7,'expected_runs':360,'expected_decisions':2520,'maximum_workers':2},'agent_factorial':{'arms':{k:{'policy':v[0],'inventory_state_recovery':v[1]} for k,v in ARMS.items()},'scenarios':['normal','derived_field_collapse','feed_gap','capacity_cut'],'seeds':[13,29],'days':7,'expected_runs':32,'expected_decisions':224,'forecast':'identical saved nativeGRU-NB, training through day89','constraints':'same synthetic supplier sources; strong parser covers same grammar; LLM extracts bounded numerical clauses and selects recovery tool','critics':'deterministic independent verification equallyallarms'},'policy_sensitivity':{'forecast_views':['raw','validation_selected_recovered'],'calculators':['order_up_to','age_aware'],'shelf_life_days':[1,3,7],'assumed_demand_multipliers':[1,1.25,1.5],'seeds':list(range(30)),'expected_runs':1080,'gate_ablation_runs':60,'demand_world':'same observed eval sales proxy times scenario multiplier for every competing policy; not recovered natural ground truth'},'simulator':{'core_shelf_life_days':3,'FIFO':True,'opening_stock_and_pipeline':'same per paired comparison, uncharged initial state; warmup14days for core','normalized_quantity_scale':100,'economic_unit':'cost index; legacy USD tags retained only for core compatibility','supplier_and_inventory':'simulated, not publisher-observed','terminal_inventory_salvage_primary':False,'simulator_results':'conditional counterfactual evidence, not retailer profits'},'model':{'name':MODEL,'digest':MODEL_SHA,'context':8192,'threads':3,'temperature':0,'seed':42,'local_API_USD':0,'new_model_download':False},'limits':{'hard_cutoff':True,'report_reserve_minutes':54,'minimum_free_gib':2},'interpretation':['30series cover0.06% of50K; no full-population claim','Artificial-mask known truth differs from naturally censored unknown demand','Statistical demand recovery differs from inventory record reconciliation','Forecastrecovery benefits not attributed to LLM','Two-seed liveagent factorial exploratory;30seednumericalcontrols do not create30seedLLM evidence','M5 comparison descriptive; unequalhistoricalhorizons/economics prohibitabsoluteprofitcomparison','No formal human study, actualsuppliercorpus or ERP execution','No model changes after final holdout; retain faileddevelopment/errors and partialruns']}
    atomic_json(PROTOCOL,p);audit('protocol_registered',{'sha256':sha(PROTOCOL),'protocol':p});print(json.dumps({'phase':'registered'}),flush=True)

def development():
    guard();d=pd.read_parquet(OUT/'data/selected_train.parquet');ids=sorted(d.series_id.unique());rows=d.groupby('series_id').first();series=[]
    for sid in ids:
        r=rows.loc[sid];series.append(Series(series_id=sid,item_id=f'FRN_{int(r.product_id):04d}',department=f'MG_{int(r.management_group_id)}',family=f'CAT_{int(r.first_category_id)}',location=f'S{int(r.store_id):04d}',cluster=f'C{int(r.city_id):02d}',supplier=f'SYNTHETIC_MG_{int(r.management_group_id)}'))
    contracts=synthetic_contracts(series,[1.]*30,[True]*30,62,4242,'normal',False,3000);docs=render_hybrid_prose(contracts,0)
    store=ArtifactStore(OUT/'development/llm_smoke/artifacts');cfg=LLMConfig(enabled=True,base_url='http://127.0.0.1:11434/v1',model=MODEL,model_revision=MODEL_SHA,prompt_profile='v2',max_tokens=2048,timeout=240,retries=0,max_calls=30,use_memory=False,spend_ledger=str(OUT/'development/development_spend.json'))
    client=LLMClient(cfg,store);client.audit_decision_id='frn-development-day62';agent=GroundingV2Agent(model_revision=MODEL_SHA,context_version='fresh-development-separate-evaluation',semantic_retries=1,compact_output=True)
    def record(stage,obj,inputs=()):
        ref=store.put(obj);store.event(client.audit_decision_id,stage,{'inputs':list(inputs),'output':ref});return ref
    started=time.perf_counter();result=agent.run(docs,Lineage(snapshot_version='fresh-dev62',run_id=client.audit_decision_id,day=62),series,62,client=client,record=record)
    receipt={'status':'PASS' if not result.issues else 'FAIL','issues':result.issues,'stats':agent.last_stats,'calls':client.calls,'tokens':client.tokens,'client_errors':client.errors,'seconds':time.perf_counter()-started,'chain_valid':store.verify_chain(),'clauses':len(contracts),'training_only':True,'model':api('/api/tags')}
    atomic_json(OUT/'development/llm_smoke/receipt.json',receipt);audit('local_llm_development_checked',receipt);store.close();print(json.dumps(receipt),flush=True)
    if result.issues:raise RuntimeError('Development source-grounding failed; evaluation gated')

def freeze():
    p=json.loads(PROTOCOL.read_text());assert p['status']=='development'
    assert json.loads((OUT/'development/llm_smoke/receipt.json').read_text())['status']=='PASS'
    assert json.loads((OUT/'development/test_receipt.json').read_text())['status']=='PASS'
    tags={x['name']:x for x in api('/api/tags')['models']};assert tags[MODEL]['digest']==MODEL_SHA
    source={str(x.relative_to(ROOT)):sha(x) for folder in ['src','tests','scripts/freshretailnet'] for x in (ROOT/folder).rglob('*.py') if x.name not in {'build_report.py','audit_study.py'}}
    configs={};numeric=base_config(OUT/'numerical',['B1','B2','B3','B4'],p['numerical']['scenarios'],p['numerical']['seeds'])
    atomic_json(OUT/'configs/numerical.json',numeric);configs['numerical']={'path':str(OUT/'configs/numerical.json'),'sha256':sha(OUT/'configs/numerical.json')}
    for arm,(policy,recovery) in ARMS.items():
        cfg=base_config(OUT/'agents'/arm,[policy],p['agent_factorial']['scenarios'],[13,29],True,recovery)
        atomic_json(OUT/f'configs/{arm}.json',cfg);configs[arm]={'path':str(OUT/f'configs/{arm}.json'),'sha256':sha(OUT/f'configs/{arm}.json')}
    p.update(status='frozen',frozen_at_utc=now(),configs=configs,source_sha256=source,source_base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),selection_sha256=sha(OUT/'data/selected_series.csv'),source_train_sha256=sha(ROOT/'data/raw/freshretailnet/train.parquet'),source_eval_sha256=sha(ROOT/'data/raw/freshretailnet/eval.parquet'),prepared_train_sha256=sha(OUT/'data/selected_train.parquet'))
    for name,checksum in source.items():
        destination=OUT/'frozen_code'/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,destination);assert sha(destination)==checksum
    atomic_json(PROTOCOL,p);audit('protocol_frozen',{'sha256':sha(PROTOCOL),'code_files':len(source),'frozen_at_utc':p['frozen_at_utc']});print(json.dumps({'phase':'frozen','sha256':sha(PROTOCOL)}),flush=True)

def verify():
    p=json.loads(PROTOCOL.read_text());assert p['status']=='frozen'
    for name,checksum in p['source_sha256'].items():assert sha(ROOT/name)==checksum,f'Frozen code changed:{name}'
    for entry in p['configs'].values():assert sha(entry['path'])==entry['sha256']
    return p

def train():
    verify();guard();panel=Panel.load(ROOT/'data/processed/freshretailnet');cfg=ExperimentConfig.model_validate(json.loads((OUT/'configs/numerical.json').read_text()));shared=OUT/'shared';shared.mkdir(exist_ok=False)
    identities={}
    for name in ['seasonal_naive','lightgbm','deep']:
        audit('shared_forecast_training_started',{'name':name,'train_end_exclusive':90});model=build_forecaster(name,cfg.forecast).fit(panel,90)
        path=shared/f'{name}.pkl' if name!='deep' else shared/'deep.pt'
        if name=='deep':
            model.save(path);atomic_json(shared/'deep_training.json',{'losses':model.losses,'training_end':model.training_end,'config':cfg.forecast.model_dump()})
        else:
            with path.open('wb') as f:pickle.dump(model,f)
        identities[name]={'path':str(path),'sha256':sha(path),'training_end':model.training_end};audit('shared_forecast_training_completed',identities[name])
    atomic_json(shared/'model_identities.json',identities)
    from ega.freshretail.simulator import PerishableInventoryEnvironment
    restored=load_models()['deep'];snapshot=PerishableInventoryEnvironment(panel,90,4242,'model-restoration-check',cfg).snapshot(cfg.forecast.lookback)
    original_prediction=model.predict(snapshot,7,4,4242);restored_prediction=restored.predict(snapshot,7,4,4242)
    assert original_prediction.samples==restored_prediction.samples
    atomic_json(shared/'restoration_check.json',{'status':'PASS','saved_tensor_sha256':identities['deep']['sha256'],'identical_seeded_forecast_samples':True,'additional_training':False,'future_targets_consulted':False})
    audit('saved_forecast_restoration_verified',{'identical_seeded_forecast_samples':True,'additional_training':False})
    print(json.dumps({'phase':'shared_models_saved','models':identities}),flush=True)

def load_models():
    from ega.forecasting.deep import DeepNegativeBinomial
    import torch
    cfg=ExperimentConfig.model_validate(json.loads((OUT/'configs/numerical.json').read_text()));result={}
    for name in ['seasonal_naive','lightgbm']:
        with (OUT/f'shared/{name}.pkl').open('rb') as f:result[name]=pickle.load(f)
    # Reconstruct architecture without training; all arms consume the saved tensors.
    from torch import nn
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    class SavedNetwork(nn.Module):
        def __init__(self):
            super().__init__();self.gru=nn.GRU(3,cfg.forecast.hidden_size,batch_first=True);self.head=nn.Linear(cfg.forecast.hidden_size,2)
        def forward(self,x,h=None):
            z,h=self.gru(x,h);return torch.nn.functional.softplus(self.head(z))+1e-4,h
    deep=DeepNegativeBinomial(cfg.forecast);deep.net=SavedNetwork();saved=torch.load(OUT/'shared/deep.pt',weights_only=False)
    deep.net.load_state_dict(saved['state_dict']);deep.config=cfg.forecast;deep.training_end=saved['training_end'];deep.losses=json.loads((OUT/'shared/deep_training.json').read_text())['losses'];deep.net.eval();result['deep']=deep
    return result

def one(task):
    from ega import experiment
    from ega.freshretail.simulator import PerishableInventoryEnvironment
    experiment.InventoryEnvironment=PerishableInventoryEnvironment
    policy,scenario,seed=task;guard();cfg=ExperimentConfig.model_validate(json.loads((OUT/'configs/numerical.json').read_text()));root=OUT/'numerical'/f'{policy}__{scenario}__seed{seed}__origin0'
    if root.exists():raise FileExistsError(root)
    name='seasonal_naive' if policy=='B1' else 'lightgbm' if policy=='B2' else 'deep'
    return experiment.run_one(PANEL,cfg,policy,scenario,seed,0,MODELS[name],root)

def numerical():
    global MODELS,PANEL
    p=verify();MODELS=load_models();PANEL=Panel.load(ROOT/'data/processed/freshretailnet');output=OUT/'numerical';output.mkdir(exist_ok=False)
    cfg=json.loads((OUT/'configs/numerical.json').read_text());atomic_json(output/'resolved_config.json',cfg);tasks=[(pol,sc,seed) for pol in p['numerical']['policies'] for sc in p['numerical']['scenarios'] for seed in p['numerical']['seeds']];rows=[]
    audit('numerical_execution_started',{'tasks':len(tasks),'workers':2})
    with mp.get_context('fork').Pool(2) as pool:
        for row in pool.imap_unordered(one,tasks,chunksize=1):
            rows.append(row);pd.DataFrame(rows).to_csv(output/'summary.csv',index=False);audit('numerical_run_completed',row);print(json.dumps({'completed_runs':len(rows),'policy':row['policy'],'scenario':row['scenario'],'seed':row['seed']}),flush=True)
    atomic_json(output/'execution_complete.json',{'status':'COMPLETE','runs':len(rows),'decisions':sum(r['trace_count'] for r in rows),'completed_at_utc':now()});audit('numerical_execution_completed',{'runs':len(rows)});print('COMPLETE numerical',flush=True)

def agents():
    from ega import experiment
    from ega.freshretail.simulator import PerishableInventoryEnvironment
    experiment.InventoryEnvironment=PerishableInventoryEnvironment
    verify();models=load_models();panel=Panel.load(ROOT/'data/processed/freshretailnet');count=0
    tags={x['name']:x for x in api('/api/tags')['models']};assert tags[MODEL]['digest']==MODEL_SHA
    for arm in ARMS:
        cfg=ExperimentConfig.model_validate(json.loads((OUT/f'configs/{arm}.json').read_text()));stage=Path(cfg.output);stage.mkdir(parents=True,exist_ok=False);atomic_json(stage/'resolved_config.json',cfg);rows=[]
        for sc in cfg.scenarios:
            for seed in cfg.seeds:
                guard();root=stage/f'{cfg.policies[0]}__{sc}__seed{seed}__origin0';audit('agent_run_started',{'arm':arm,'scenario':sc,'seed':seed});print(json.dumps({'phase':'agent_run_started','arm':arm,'scenario':sc,'seed':seed}),flush=True)
                row=experiment.run_one(panel,cfg,cfg.policies[0],sc,seed,0,models['deep'],root);rows.append(row);count+=1;pd.DataFrame(rows).to_csv(stage/'summary.csv',index=False);audit('agent_run_completed',{'arm':arm,**row});print(json.dumps({'phase':'agent_run_completed','arm':arm,'completed_runs':count,**row}),flush=True)
    complete={'status':'COMPLETE','runs':count,'decisions':count*7,'completed_at_utc':now(),'API_usage':json.loads((OUT/'evaluation_spend.json').read_text()) if (OUT/'evaluation_spend.json').exists() else {}}
    atomic_json(OUT/'agents/execution_complete.json',complete);audit('agent_factorial_completed',complete);print('COMPLETE agents',flush=True)

if __name__=='__main__':
    os.chdir(ROOT);arg=argparse.ArgumentParser();arg.add_argument('phase',choices=['register','development','freeze','train','numerical','agents']);args=arg.parse_args()
    try:globals()[args.phase]()
    except BaseException as exc:audit('phase_failed',{'phase':args.phase,'type':type(exc).__name__,'message':str(exc)});raise
