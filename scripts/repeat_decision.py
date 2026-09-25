"""Real-LLM fixed-evidence decision dispersion. No fake stochastic agent substitute."""
import argparse,json,copy
from pathlib import Path
import numpy as np
from ega.config import load_config,ExperimentConfig
from ega.schemas import Snapshot,ConstraintSet,Forecast
from ega.evaluation.faithfulness import load_trace
from ega.constraints import SourceDocument
from ega.agents.orchestrator import OrchestratorAutonomyAgent
from ega.store import ArtifactStore
from ega.util import atomic_json
p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--config',required=True)
p.add_argument('--day',type=int);p.add_argument('--replications',type=int,default=30);p.add_argument('--out',default='results/fixed_evidence')
a=p.parse_args();cfg=load_config(a.config)
if not cfg.llm.enabled:raise SystemExit('Enable a real LLM explicitly; this script makes external calls.')
if a.replications<2:raise SystemExit('At least two repetitions are required.')
store,trace,manifest=load_trace(a.run_dir,a.day)
try:
    snap=Snapshot.model_validate(store.get(trace['references']['observe']))
    fc=Forecast.model_validate(store.get(trace['references']['forecast']))
    docs=[SourceDocument(ref=d['source_ref'],text=d['text'],authenticated=d['authenticated']) for d in store.get(trace['references']['source_documents'])]
finally:store.close()
class FixedForecast:
    name='cached_fixed_forecast'
    def predict(self,snapshot,horizon,scenarios,seed):
        obj=fc.model_copy(deep=True);obj.lineage=snapshot.lineage
        if np.asarray(obj.samples).shape!=(scenarios,len(snapshot.series),horizon):raise ValueError('Use the source run horizon and scenario count')
        return obj
rows=[]
for i in range(a.replications):
    config=cfg.model_copy(deep=True);config.llm.seed=cfg.llm.seed+i
    s=ArtifactStore(Path(a.out)/f'repeat_{i:03}');agent=OrchestratorAutonomyAgent('B10',FixedForecast(),config,s)
    d=agent.run(snap.model_copy(deep=True),docs,f'fixed-evidence-{i}',manifest['seed'])
    rows.append({'replication':i,'proposed_units':sum(o.quantity for o in d.plan.orders),'permitted':d.autonomy.permitted,
                 'action_hash':d.plan.action_hash(),'trace_ref':s.put(d.trace),'tokens':d.trace['llm']['tokens']})
    s.close()
atomic_json(Path(a.out)/'reliability.json',{'replications':rows,'proposed_units_variance':float(np.var([x['proposed_units'] for x in rows],ddof=1)),
    'distinct_action_hashes':len({x['action_hash'] for x in rows}),'warning':'Fixed evidence and demand forecast; no order is executed. Seeds may be ignored by providers. Constant-demand bullwhip ratio is undefined; report absolute action dispersion.'})
