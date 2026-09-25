"""Blinded, counterbalanced packet export. Does not recruit or simulate human participants."""
from __future__ import annotations
import csv
import html
import json
from pathlib import Path
import numpy as np
from ..store import ArtifactStore
from ..util import atomic_json,digest
from .report import CSS

ARMS=['narrative','structured_without_lineage','full_lineage']

def export_packets(results,output,participants=3,max_cases=12,seed=42):
    results=Path(results);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if participants<1:raise ValueError('participants must be positive')
    cases=[]
    for index_path in sorted(results.glob('*/trace_index.json')):
        run=index_path.parent;store=ArtifactStore(run/'artifacts')
        for entry in json.loads(index_path.read_text()):
            trace=store.get(entry['trace_ref']);plan=store.get(trace['references']['propose'])
            if not plan['orders'] and not plan['transfers']:continue
            if not trace.get('evaluation') or store.get(trace['execution'])['status']!='executed':continue
            eval_obj=store.get(trace['evaluation']);cert=store.get(trace['references']['certify_state'])
            if eval_obj.get('oracle_ref') is None:continue
            case_id='case-'+digest([trace['decision_id'],seed])[:10]
            constraints=store.get(trace['references'].get('ground_constraints',trace['references'].get('fallback_constraints'))) if ('ground_constraints' in trace['references'] or 'fallback_constraints' in trace['references']) else {}
            cases.append({'case_id':case_id,'trace':trace,'plan':plan,'certificate':cert,'constraints':constraints,
                          'correct_accept':not bool(eval_obj['harmful_execution'] or eval_obj['violations']),
                          'degraded_state':bool(cert['quality']<1),'source_run':run.name})
        store.close()
    rng=np.random.default_rng(seed);rng.shuffle(cases);cases=cases[:max_cases]
    if not cases:raise ValueError('No executed/proposed nonzero decisions with reference labels were found')
    assignments=[];answer_key=[]
    for case in cases:answer_key.append({k:case[k] for k in ['case_id','correct_accept','degraded_state','source_run']})
    for participant in range(participants):
        pdir=output/f'participant_{participant+1:03}';pdir.mkdir(exist_ok=True);links=[]
        order=rng.permutation(len(cases))
        for pos,case_index in enumerate(order):
            case=cases[case_index];arm=ARMS[(participant+int(case_index))%3];plan=case['plan'];cid=case['case_id']
            action={'orders':plan['orders'],'transfers':plan['transfers']}
            if arm=='narrative':
                content='<p>The system proposes the following replenishment plan based on demand projections and available stock. Review whether it should be accepted or overridden.</p>'
                content+='<pre>'+html.escape(json.dumps(action,indent=2))+'</pre>'
            else:
                fields={'action':action,'constraints':case['constraints'].get('constraints',[]),'solver':plan['solver']}
                # Remove lineage nested inside any structured object in the no-lineage arm.
                if arm=='full_lineage':fields={'lineage':case['trace']['lineage'],'state_certificate':case['certificate'],**fields}
                content='<pre>'+html.escape(json.dumps(fields,indent=2))+'</pre>'
            file=pdir/f'{pos+1:02}_{cid}.html'
            file.write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Audit {cid}</title><style>{CSS}</style><main><h1>Decision audit</h1><p>Case {cid}. Decide accept or override, record confidence 0–100 and elapsed seconds. Study materials only; no real orders.</p><section class="card">{content}</section></main></html>',encoding='utf8')
            links.append(f'<p><a href="{file.name}">Case {pos+1}</a></p>')
            assignments.append({'participant_id':participant+1,'case_id':cid,'arm':arm,'order':pos+1})
        (pdir/'index.html').write_text('<html><meta charset="utf-8"><title>Audit cases</title>'+''.join(links)+'</html>')
    atomic_json(output/'RESEARCHER_ONLY_answer_key.json',answer_key)
    atomic_json(output/'RESEARCHER_ONLY_assignments.json',assignments)
    with (output/'responses_template.csv').open('w',newline='') as f:
        csv.writer(f).writerow(['participant_id','case_id','decision_accept','confidence_probability','elapsed_seconds','workload_0_100'])
    atomic_json(output/'study_manifest.json',{'arms':ARMS,'cases':len(cases),'participants_planned':participants,
          'approval_required':True,'warning':'Obtain institutional approval/consent before recruitment. Reference labels require expert review. Narrative arm is a deterministic summary, not a measured LLM rationale.'})
    return len(cases)

def score_responses(study_dir,responses_csv):
    import pandas as pd
    root=Path(study_dir)
    response=pd.read_csv(responses_csv)
    if response.empty:raise ValueError('No actual responses supplied; no human-study findings can be generated')
    key=pd.DataFrame(json.loads((root/'RESEARCHER_ONLY_answer_key.json').read_text()))
    assignment=pd.DataFrame(json.loads((root/'RESEARCHER_ONLY_assignments.json').read_text()))
    if response.duplicated(['participant_id','case_id']).any():raise ValueError('Duplicate participant/case responses')
    for col in ['decision_accept','confidence_probability','elapsed_seconds']:
        response[col]=pd.to_numeric(response[col],errors='raise')
    if not response.decision_accept.isin([0,1]).all():raise ValueError('decision_accept must be 0 or 1')
    if not response.confidence_probability.between(0,1).all() or (response.elapsed_seconds<0).any():raise ValueError('Invalid confidence or time')
    data=response.merge(assignment,on=['participant_id','case_id'],validate='one_to_one').merge(key,on='case_id',validate='many_to_one')
    if len(data)!=len(response):raise ValueError('Unassigned responses found')
    data['correct']=(data.decision_accept==data.correct_accept.astype(int)).astype(int)
    data['confidence_brier']=(data.confidence_probability-data['correct'])**2
    return data.groupby('arm').agg(n=('correct','size'),accuracy=('correct','mean'),mean_seconds=('elapsed_seconds','mean'),mean_confidence_brier=('confidence_brier','mean')).reset_index()
