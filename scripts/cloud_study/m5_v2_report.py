#!/usr/bin/env python3
"""Independent, read-only evidence audit and report for the opt-in M5 v2 pilot.

No live model requests are made. Source runs and earlier study reports are never
modified. COMPLETE is assigned only to exact configured grids with hash-verified
objects, complete trace/daily records and valid SQLite audit chains.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
import hashlib
import html
import itertools
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import zipfile

import numpy as np
import pandas as pd

REPO = Path('/workspace/MasterDissertation')
FORBIDDEN_CONTEXT_KEYS = {'true_problem', 'truth_constraints', 'oracle_ref', 'realized_future_demand', 'evaluation_ref'}
MATCH_FIELDS = ['dataset', 'start_day', 'days', 'warmup_days', 'origin_stride', 'origins', 'seeds', 'scenarios', 'forecast_override', 'forecast', 'solver', 'gate', 'quality', 'document_carrier', 'approval_mode', 'approval_delay', 'harmful_abs_tolerance', 'harmful_rel_tolerance', 'escalation_cost', 'harmful_cost', 'oracle']
NUMERIC_FIELDS = ['cost', 'fill_rate', 'hard_violations', 'violation_executions', 'reference_deviations', 'held_decisions', 'executed_actions', 'mean_inventory', 'llm_calls', 'tokens', 'llm_errors', 'trace_count']


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(canonical(value), encoding='utf8'); temp.replace(path)


def finite(value, default=None):
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError):
        return default


def bool_value(value):
    if isinstance(value, bool): return value
    if isinstance(value, str) and value.lower() in {'true', 'false'}: return value.lower() == 'true'
    if value in (0, 1): return bool(value)
    raise ValueError(f'Unrecognized boolean: {value!r}')


def discover_keys(value, keys=FORBIDDEN_CONTEXT_KEYS, path='payload'):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f'{path}.{key}'
            if key in keys: found.append(here)
            found.extend(discover_keys(item, keys, here))
    elif isinstance(value, list):
        for i, item in enumerate(value): found.extend(discover_keys(item, keys, f'{path}[{i}]'))
    return found


class VerifiedReader:
    """Verify original objects, including retained storage archives, without restore."""
    def __init__(self, run, inventory):
        self.run = Path(run); self.inventory = inventory; self.cache = {}
        self.archive = self.run/'artifacts/objects.zip'
        self.records = {}; self.packed = (self.run/'packing_manifest.json').exists()
        if self.packed:
            manifest = self.read_file(self.run/'packing_manifest.json')
            records = manifest['original_objects']
            if len(records) != manifest['original_object_count'] or digest(records) != manifest['original_object_inventory_sha256']:
                raise ValueError('Packed original object inventory differs')
            if sha(self.archive) != manifest['archive_sha256'] or self.archive.stat().st_size != manifest['archive_bytes']:
                raise ValueError('Packed artifact archive SHA/size differs')
            self.inventory[str(self.archive)] = {'sha256': sha(self.archive), 'bytes': self.archive.stat().st_size}
            with zipfile.ZipFile(self.archive) as archive:
                info = archive.infolist()
                names = [entry.filename for entry in info]
                if len(names) != len(set(names)) or set(names) != {'objects/'+name for name in records}:
                    raise ValueError('Packed archive original member set differs')
                for entry in info:
                    if entry.is_dir() or entry.flag_bits & 1 or entry.file_size != records[entry.filename.removeprefix('objects/')]['bytes']:
                        raise ValueError('Packed archive member size/type differs')
            for key, filename in [('summary_sha256','summary.json'), ('run_manifest_sha256','run_manifest.json'), ('trace_index_sha256','trace_index.json')]:
                if sha(self.run/filename) != manifest['provenance'][key]: raise ValueError('Packed source provenance differs')
            self.records = records
        self.names = set(self.records) | {p.name for p in (self.run/'artifacts/objects').glob('*.json')}
        for name in self.names:
            if not re.fullmatch(r'[0-9a-f]{64}\.json', name): raise ValueError('Unexpected artifact object name')

    def read_file(self, path):
        path = Path(path); self.inventory[str(path)] = {'sha256': sha(path), 'bytes': path.stat().st_size}
        return load_json(path)

    def load(self, ref):
        if not isinstance(ref,str) or not re.fullmatch(r'[0-9a-f]{64}',ref): raise ValueError('Invalid content-addressed reference')
        if ref in self.cache: return self.cache[ref]
        name = ref+'.json'; loose = self.run/'artifacts/objects'/name
        if loose.exists():
            content = loose.read_bytes(); source = str(loose)
        elif name in self.records:
            with zipfile.ZipFile(self.archive) as archive: content = archive.read('objects/'+name)
            source = str(self.archive)+'::objects/'+name
        else: raise FileNotFoundError(f'Absent artifact {ref}')
        value = json.loads(content)
        if hashlib.sha256(content).hexdigest() != ref or digest(value) != ref: raise ValueError(f'Content hash differs: {ref}')
        if name in self.records and len(content) != self.records[name]['bytes']: raise ValueError('Original artifact byte length differs')
        self.inventory[source] = {'sha256':ref,'bytes':len(content)}; self.cache[ref] = value
        return value

    def verify_all(self):
        for name in sorted(self.names): self.load(name[:-5])
        return len(self.names)


def verify_chain(db_path):
    path = Path(db_path).resolve()
    connection = sqlite3.connect(f'file:{path}?mode=ro',uri=True)
    prev = '0'*64; events=[]
    try:
        for seq, decision, stage, payload, previous, current in connection.execute('SELECT seq,decision_id,stage,payload,previous_hash,event_hash FROM events ORDER BY seq'):
            value=json.loads(payload)
            if previous != prev or digest({'decision_id':decision,'stage':stage,'payload':value,'previous_hash':previous}) != current:
                raise ValueError(f'Audit event chain differs at sequence {seq}')
            events.append({'seq':seq,'decision_id':decision,'stage':stage,'payload':value,'previous_hash':previous,'event_hash':current}); prev=current
        receipts={key:json.loads(payload) for key,payload in connection.execute('SELECT idempotency_key,payload FROM receipts')}
    finally: connection.close()
    return events,receipts,prev


def expected_grid(config):
    return set(itertools.product(config['policies'],config['scenarios'],map(int,config['seeds']),range(int(config['origins']))))


def row_identity(row):
    return str(row['policy']),str(row['scenario']),int(row['seed']),int(row['origin'])


def request_payloads(request):
    result=[]
    for message in request.get('messages',[]):
        if message.get('role')!='user':continue
        try: value=json.loads(message.get('content',''))
        except (ValueError,TypeError):continue
        if isinstance(value,dict): result.append(value)
    return result



def audit_attempt_pairs(artifacts,events,decision_id,expected_attempts,required=False):
    starts=[(ref,obj) for ref,obj in artifacts if obj.get('kind')=='llm_request_started']
    if required and len(starts)!=expected_attempts:raise ValueError('Recorded pre-HTTP starts differ from model attempt count')
    sequences={e['payload'].get('output'):e['seq'] for e in events if e['decision_id']==decision_id and e['stage'] in {'llm_request_started','llm_request_response','llm_request_error'}}
    pairs=[]
    def identity(obj):return (obj.get('role'),obj.get('started_at_utc'),obj.get('attempt'),digest(obj.get('request',{})))
    keys=[identity(obj) for ref,obj in starts]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate pre-HTTP model attempt identities')
    for ref,obj in artifacts:
        if obj.get('kind') not in {'llm_call','llm_error'}:continue
        matches=[(start_ref,start) for start_ref,start in starts if identity(start)==identity(obj)]
        if required and len(matches)!=1:raise ValueError('Model response/error has no unique matching persisted request start')
        if matches:
            start_ref,start=matches[0]
            if start_ref not in sequences or ref not in sequences or sequences[start_ref]>=sequences[ref]:raise ValueError('Model response/error precedes persisted request in the audit chain')
            pairs.append({'started_ref':start_ref,'result_ref':ref,'result_kind':obj['kind'],'start_seq':sequences[start_ref],'result_seq':sequences[ref]})
    if required:
        result_starts={pair['started_ref'] for pair in pairs}
        if result_starts!={ref for ref,obj in starts}:raise ValueError('Completed decision has an unanswered persisted model request')
    return {'pre_http_starts':len(starts),'paired_results':len(pairs),'pairs':pairs}

def audit_run(label, root, row, config, inventory):
    path = Path(row.get('path') or root/f"{row['policy']}__{row['scenario']}__seed{row['seed']}__origin{row['origin']}")
    if not path.is_absolute(): path = (REPO/path).resolve()
    reader=VerifiedReader(path,inventory)
    manifest=reader.read_file(path/'run_manifest.json'); source=reader.read_file(path/'summary.json')
    if row_identity(source)!=row_identity(row): raise ValueError('Summary identity differs from original per-run result')
    for field in NUMERIC_FIELDS:
        if field in row and field in source and finite(row[field]) != finite(source[field]): raise ValueError(f'Summary CSV/source {field} differs')
    source_differences=config_differences(manifest['config'],config)
    if any(x['field'] != 'output' for x in source_differences): raise ValueError(f'Run manifest and resolved configuration differ beyond original worker output path: {source_differences}')
    if not bool_value(source['chain_valid']):raise ValueError('Original run reports invalid audit chain')
    inventory[str(path/'daily.csv')]={'sha256':sha(path/'daily.csv'),'bytes':(path/'daily.csv').stat().st_size}
    daily=pd.read_csv(path/'daily.csv'); index=reader.read_file(path/'trace_index.json')
    expected_days=list(range(int(config['start_day'])+int(source['origin'])*int(config['origin_stride']),int(config['start_day'])+int(source['origin'])*int(config['origin_stride'])+int(config['days'])))
    if sorted(daily.day.astype(int))!=expected_days or sorted(int(x['day']) for x in index)!=expected_days or len(index)!=int(source['trace_count']):raise ValueError('Daily/index trace grid differs')
    db=path/'artifacts/audit.sqlite'; events,receipts,last_hash=verify_chain(db)
    inventory[str(db)]={'sha256':sha(db),'bytes':db.stat().st_size}
    object_count=reader.verify_all(); call_rows=[];trace_rows=[]; v2_events=[]
    event_stage_counts=Counter(e['stage'] for e in events)
    for e in events:
        if 'v2' in e['stage'] or e['stage'] in {'llm_request_started','llm_request_response','llm_request_error','recovery_status','recovery_selection','recovery_selection_failure','recover_state','recovery','source_cache','repair','validate_extraction'}:
            output_ref=e['payload'].get('output')
            artifact=reader.load(output_ref) if output_ref else None
            mechanism=re.sub(r'^v2_[0-9]+_', '', e['stage'])
            origin_kind=None
            if mechanism=='grounding_v2_cache_hit' and artifact and artifact.get('origin_ref'):
                origin=reader.load(artifact['origin_ref'])
                origin_kind='model_numeric_terms' if origin.get('accepted') is True and origin.get('llm_refs') else 'parser' if origin.get('grammar') else 'unclassified'
            v2_events.append({'arm':label,'run':path.name,'mechanism':mechanism,**e,'artifact':artifact,'derived_cache_origin_kind':origin_kind})
    for entry in index:
        trace=reader.load(entry['trace_ref']); refs=trace['references']
        if trace['decision_id']!=entry['decision_id'] or int(trace['day'])!=int(entry['day']): raise ValueError('Trace index identity differs')
        receipt=reader.load(trace.get('execution') or refs['receipt'])
        if receipts.get(entry['decision_id'])!=receipt:raise ValueError('Trace execution and SQLite receipt differ')
        plan=reader.load(refs['propose']); available=reader.load(refs['source_documents'])
        by_ref={d['source_ref']:d for d in available}; trace_calls=[]
        for ref in trace.get('llm',{}).get('artifacts',[]):
            obj=reader.load(ref)
            if obj.get('kind') not in {'llm_request_started','llm_call','llm_error'}:continue
            payloads=request_payloads(obj.get('request',{})); leakage=[];documents=[]
            for payload in payloads:
                leakage.extend(discover_keys(payload)); docs=payload.get('documents',[])
                if isinstance(docs,list):documents.extend(docs)
            for doc in documents:
                if doc.get('source_ref') not in by_ref or doc!=by_ref[doc['source_ref']]:raise ValueError('Model submitted document differs from decision source evidence')
            if leakage:raise ValueError(f'Forbidden evaluator keys in model context: {leakage}')
            if obj.get('kind')!='llm_call':continue
            response=obj.get('response') or {}; usage=response.get('usage') or {}
            token_count=int(usage.get('total_tokens') or sum(int(usage.get(k) or 0) for k in ['input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens']))
            choice=(response.get('choices') or [{}])[0]
            call={'arm':label,'run':path.name,'policy':source['policy'],'scenario':source['scenario'],'seed':source['seed'],'origin':source['origin'],'day':entry['day'],'decision_id':entry['decision_id'],'artifact_ref':ref,'role':obj.get('role','unknown'),'attempt':obj.get('attempt'), 'model_revision':obj.get('model_revision'),'served_model':obj.get('served_model') or response.get('model'),'started_at_utc':obj.get('started_at_utc'),'elapsed_seconds':finite(obj.get('elapsed_seconds')),'tokens':token_count,'prompt_tokens':int(usage.get('prompt_tokens') or usage.get('input_tokens') or 0),'completion_tokens':int(usage.get('completion_tokens') or usage.get('output_tokens') or 0),'submitted_documents':len(documents),'finish_reason':choice.get('finish_reason') or response.get('stop_reason'),'forbidden_context_keys':len(leakage),'request_sha256':digest(obj.get('request',{})),'response_sha256':digest(response),'repair_labeled':any('repair' in str(obj.get('role','')).lower() or 'correction_task' in p or 'validation_errors' in p for p in payloads)}
            call_rows.append(call); trace_calls.append(call)
            if not any(e.get('artifact',{}).get('kind')=='llm_call' and e.get('payload',{}).get('output')==ref for e in v2_events):
                v2_events.append({'arm':label,'run':path.name,'decision_id':entry['decision_id'],'mechanism':'captured_model_call','stage':'captured_model_call','payload':{'output':ref},'artifact':obj})
        decision_v2_events=[e for e in v2_events if e['decision_id']==entry['decision_id']]
        final_events=[e for e in decision_v2_events if e['mechanism']=='grounding_v2_final']
        grounding_final=final_events[-1]['artifact'] if final_events else {}
        grounding_stats=grounding_final.get('stats',{})
        if grounding_final:
            if int(grounding_stats.get('source_documents',-1))!=len(available):raise ValueError('Grounding source count differs from observed source documents')
            proved=grounding_final.get('proved_source_refs')
            if proved is not None:
                if len(proved)!=len(set(proved)) or not set(proved)<=set(by_ref) or int(grounding_stats.get('verified_documents',-1))!=len(proved):raise ValueError('Grounding proved source identities differ from coverage statistics')
                if not grounding_final.get('result',{}).get('issues') and set(proved)!=set(by_ref):raise ValueError('Issue-free grounding omitted available source documents')
        recovery=trace.get('recovery') or {}
        recovery_selection_events=[e for e in decision_v2_events if e['mechanism']=='recovery_selection']
        recovery_selection=recovery_selection_events[-1]['artifact'] if recovery_selection_events else {}
        reported=trace.get('llm',{})
        attempt_proof=audit_attempt_pairs([(ref,reader.load(ref)) for ref in reported.get('artifacts',[])],events,entry['decision_id'],int(reported.get('calls',0)),required=bool(config.get('agent_v2',{}).get('enabled')))
        # Failed HTTP attempts may have error records without a successful llm_call.
        error_refs=[r for r in reported.get('artifacts',[]) if reader.load(r).get('kind')=='llm_error']
        if len(trace_calls)>int(reported.get('calls',0)):raise ValueError('Captured successful calls exceed trace call count')
        actual=daily[daily.day.astype(int)==int(entry['day'])].iloc[0]
        held=receipt['status']=='held'
        if held!=bool_value(actual.held):raise ValueError('Receipt and daily hold indicator differ')
        evaluation=reader.load(trace['evaluation'])
        if len(evaluation.get('violations',[]))!=int(actual.hard_violations):raise ValueError('Post-decision evaluation and daily hard violations differ')
        solver=plan.get('solver',{})
        trace_rows.append({'arm':label,'run':path.name,'policy':source['policy'],'scenario':source['scenario'],'seed':source['seed'],'origin':source['origin'],'day':entry['day'],'decision_id':entry['decision_id'],'trace_ref':entry['trace_ref'],'receipt_status':receipt['status'],'held':held,'executed_nonzero_action':bool_value(actual.executed_action),'cost':finite(actual.cost),'demand':finite(actual.demand),'sales':finite(actual.sales),'on_hand':finite(actual.on_hand),'hard_violations':int(actual.hard_violations),'reference_deviation':bool_value(actual.reference_deviation),'llm_calls':int(reported.get('calls',0)),'llm_tokens':int(reported.get('tokens',0)),'llm_errors':int(reported.get('errors',0)),'captured_successful_calls':len(trace_calls),'captured_error_artifacts':len(error_refs),'pre_http_attempt_proof':attempt_proof,'source_documents':len(available),'submitted_document_exposures':sum(x['submitted_documents'] for x in trace_calls),'optimizer_reached':'problem' in refs,'solver_method':plan.get('method'),'solver_feasible':solver.get('feasible'),'solver_status':solver.get('status'),'solver_gap':finite(solver.get('gap') if 'gap' in solver else solver.get('mip_gap')),'solver_optimal':solver.get('optimal'),'latency_seconds':finite(actual.latency_seconds),'errors':trace.get('errors',[]),'v2_config':trace.get('agent_v2_config',{}),'grounding_stats':grounding_stats,'grounding_issues':grounding_final.get('result',{}).get('issues',[]),'grounding_complete':not grounding_final.get('result',{}).get('issues',[]) if grounding_final else None,'recovery_status':recovery.get('status'),'recovery_applied':recovery.get('applied',False),'recovery_changed_fields':len(recovery.get('changed_fields',[])),'recovery_hard_fail_before':recovery.get('hard_fail_before'),'recovery_hard_fail_after':recovery.get('hard_fail_after'),'recovery_tool_selected':recovery_selection.get('requested_tool'),'recovery_selector_source':recovery_selection.get('source','live_model' if recovery_selection_events else None)})
    if sum(x['llm_calls'] for x in trace_rows)!=int(source.get('llm_calls',0)) or sum(x['llm_tokens'] for x in trace_rows)!=int(source.get('tokens',0)):
        raise ValueError('Per-trace model usage differs from run summary')
    clean={key:(finite(source.get(key)) if key in NUMERIC_FIELDS else source.get(key)) for key in source}
    clean.update(arm=label,source_result_root=str(root),source_run_path=str(path),configured_days=int(config['days']),series_count=int(manifest.get('data',{}).get('series')) if isinstance(manifest.get('data',{}).get('series'),int) else len(manifest.get('data',{}).get('series',[])) or None)
    proof={'arm':label,'run':path.name,'path':str(path),'identity':list(row_identity(source)),'chain_valid':True,'chain_event_count':len(events),'chain_final_hash':last_hash,'object_count':object_count,'trace_count':len(index),'manifest_sha256':sha(path/'run_manifest.json'),'summary_sha256':sha(path/'summary.json'),'daily_sha256':sha(path/'daily.csv'),'trace_index_sha256':sha(path/'trace_index.json'),'event_stages':dict(event_stage_counts),'source_data_provenance':manifest.get('data',{}),'source_config_output_path_difference':source_differences}
    return clean,trace_rows,call_rows,v2_events,proof


def audit_stage(label, root, inventory, allow_partial=False):
    root=Path(root).resolve(); config_path=root/'resolved_config.json'; config=load_json(config_path)
    inventory[str(config_path)]={'sha256':sha(config_path),'bytes':config_path.stat().st_size}
    if not (root/'summary.csv').exists():return {'label':label,'root':str(root),'config':config,'status':'UNRUN','expected_runs':len(expected_grid(config)),'completed_runs':0,'missing_grid':[list(i) for i in sorted(expected_grid(config))]},[],[],[],[],[]
    summary_path=root/'summary.csv'; inventory[str(summary_path)]={'sha256':sha(summary_path),'bytes':summary_path.stat().st_size}
    with summary_path.open(newline='') as stream: source_rows=list(csv.DictReader(stream))
    identities=[row_identity(r) for r in source_rows]
    if len(set(identities))!=len(identities):raise ValueError('Duplicate configured run identities')
    expected=expected_grid(config); unexpected=set(identities)-expected
    if unexpected:raise ValueError(f'Unconfigured run identities: {unexpected}')
    missing=expected-set(identities); status='COMPLETE' if not missing else 'PARTIAL'
    if missing and not allow_partial:raise ValueError(f'{label}: incomplete grid ({len(missing)} missing); pass --allow-partial for explicitly labeled snapshot')
    rows=[];traces=[];calls=[];v2=[];proofs=[]
    for row in source_rows:
        result=audit_run(label,root,row,config,inventory)
        for collection,part in zip([rows,traces,calls,v2,proofs],result):
            if isinstance(part,list):collection.extend(part)
            else:collection.append(part)
    calendar_path=(REPO/config['dataset']/'calendar.csv').resolve() if not Path(config['dataset']).is_absolute() else Path(config['dataset'])/'calendar.csv'
    date_mapping=[]
    if calendar_path.exists():
        calendar=pd.read_csv(calendar_path)
        inventory[str(calendar_path)]={'sha256':sha(calendar_path),'bytes':calendar_path.stat().st_size}
        for origin in range(int(config['origins'])):
            start=int(config['start_day'])+origin*int(config['origin_stride']); end=start+int(config['days'])-1; train_last=start-int(config['warmup_days'])-1
            date_mapping.append({'origin':origin,'start_index':start,'end_index':end,'training_last_included_index':train_last,'start_date':str(calendar.iloc[start].get('date')),'end_date':str(calendar.iloc[end].get('date')),'training_last_included_date':str(calendar.iloc[train_last].get('date'))})
    details={'label':label,'root':str(root),'config':config,'status':status,'expected_runs':len(expected),'completed_runs':len(rows),'missing_grid':[list(i) for i in sorted(missing)],'configured_days':config['days'],'seeds':config['seeds'],'scenarios':config['scenarios'],'policies':config['policies'],'origins':config['origins'],'start_day':config['start_day'],'model':config.get('llm',{}),'agent_v2':config.get('agent_v2',{}),'historical_date_mapping':date_mapping}
    return details,rows,traces,calls,v2,proofs


def aggregate(rows,traces,calls):
    out=[]
    for (arm,policy,scenario),group in itertools.groupby(sorted(rows,key=lambda x:(x['arm'],x['policy'],x['scenario'])),key=lambda x:(x['arm'],x['policy'],x['scenario'])):
        group=list(group); ts=[t for t in traces if (t['arm'],t['policy'],t['scenario'])==(arm,policy,scenario)];cs=[c for c in calls if (c['arm'],c['policy'],c['scenario'])==(arm,policy,scenario)]
        def avg(key):
            values=[finite(x.get(key)) for x in group];values=[x for x in values if x is not None]
            return sum(values)/len(values) if values else None
        entry={'arm':arm,'policy':policy,'scenario':scenario,'runs':len(group),'seeds':sorted(set(int(x['seed']) for x in group)),'decision_days_per_run':sorted(set(x['configured_days'] for x in group)), 'decisions':len(ts),'mean_cost':avg('cost'),'mean_fill_rate':avg('fill_rate'),'mean_inventory':avg('mean_inventory')}
        for key in ['held_decisions','executed_actions','hard_violations','violation_executions','reference_deviations','llm_calls','llm_errors','tokens']:
            entry[key]=int(sum(finite(x.get(key),0) for x in group))
        latencies=[x['latency_seconds'] for x in ts if x['latency_seconds'] is not None]
        entry.update(optimizer_decisions=sum(x['optimizer_reached'] for x in ts),feasible_plans=sum(x['solver_feasible'] is True for x in ts),mean_decision_latency_seconds=float(np.mean(latencies)) if latencies else None,p95_decision_latency_seconds=float(np.quantile(latencies,.95)) if latencies else None,captured_successful_calls=len(cs),model_call_seconds=sum(x['elapsed_seconds'] or 0 for x in cs),submitted_document_exposures=sum(x['submitted_documents'] for x in cs),available_document_exposures=sum(x['source_documents'] for x in ts),repair_labeled_calls=sum(x['repair_labeled'] for x in cs))
        out.append(entry)
    return out



def mechanism_aggregate(traces,events):
    result=[]
    for arm in sorted({t['arm'] for t in traces}):
        ts=[t for t in traces if t['arm']==arm]; es=[e for e in events if e['arm']==arm]
        row={'arm':arm,'decisions':len(ts),'grounding_attempted_decisions':sum(bool(t.get('grounding_stats')) for t in ts),'grounding_complete_decisions':sum(t.get('grounding_complete') is True for t in ts),'recovery_applied_decisions':sum(t.get('recovery_applied',False) for t in ts),'recovery_changed_inventory_fields':sum(t.get('recovery_changed_fields',0) for t in ts),'recovery_remaining_hard_fail_decisions':sum(bool(t.get('recovery_applied')) and t.get('recovery_hard_fail_after') is True for t in ts)}
        for key in ['source_documents','parsed_documents','model_documents','cache_hits','cache_misses','model_attempts','semantic_retries','verified_documents','submitted_document_exposures','model_documents_attempted','compact_model_numeric_terms','tool_derived_metadata_rules']:
            row[key]=sum(int(t.get('grounding_stats',{}).get(key) or 0) for t in ts)
        row['model_share_of_source_exposures']=row['model_documents']/row['source_documents'] if row['source_documents'] else None
        row['grounding_document_coverage']=row['verified_documents']/row['source_documents'] if row['source_documents'] else None
        validations=[e['artifact'] for e in es if e['mechanism']=='grounding_v2_validation']
        row['semantic_validation_batches']=len(validations)
        row['accepted_initial_batches']=sum(v.get('accepted') is True and int(v.get('attempt',0))==0 for v in validations)
        row['accepted_repair_batches']=sum(v.get('accepted') is True and int(v.get('attempt',0))>0 for v in validations)
        row['rejected_validation_batches']=sum(v.get('accepted') is False for v in validations)
        row['source_exposures_skipped_by_state_gate']=sum(int(t['source_documents']) for t in ts if not t.get('grounding_stats'))
        row['cache_rejected_events']=sum(e['mechanism']=='grounding_v2_cache_rejected' for e in es)
        row['cached_model_term_documents']=sum(e.get('derived_cache_origin_kind')=='model_numeric_terms' for e in es)
        row['cached_parser_documents']=sum(e.get('derived_cache_origin_kind')=='parser' for e in es)
        row['unclassified_cache_documents']=sum(e.get('derived_cache_origin_kind')=='unclassified' for e in es)
        row['cache_write_events']=sum(e['mechanism']=='grounding_v2_cache_write' for e in es)
        result.append(row)
    return result


def paired_descriptive(rows):
    contrasts=[('llm_v2_no_recovery','parser_no_recovery','LLM minus parser / no recovery'),('llm_v2_recovery','parser_recovery','LLM minus parser / recovery'),('parser_recovery','parser_no_recovery','Recovery minus no recovery / parser'),('llm_v2_recovery','llm_v2_no_recovery','Recovery minus no recovery / LLM')]
    result=[]
    for treatment,reference,description in contrasts:
        scenarios=sorted({r['scenario'] for r in rows if r['arm'] in {treatment,reference}})
        for scenario in scenarios:
            left={(int(r['seed']),int(r['origin'])):r for r in rows if r['arm']==treatment and r['scenario']==scenario};right={(int(r['seed']),int(r['origin'])):r for r in rows if r['arm']==reference and r['scenario']==scenario}
            shared=set(left)&set(right)
            if not shared:continue
            by_seed=defaultdict(list)
            for key in sorted(shared):
                a,b=left[key],right[key]
                if a['configured_days']!=b['configured_days']:raise ValueError('Paired descriptive contrast crosses decision horizons')
                by_seed[key[0]].append((a,b))
            seed_pairs=[]
            for seed,pairs in sorted(by_seed.items()):
                seed_pairs.append({'seed':seed,'origins':len(pairs),'treatment_cost':float(np.mean([finite(a['cost']) for a,b in pairs])),'reference_cost':float(np.mean([finite(b['cost']) for a,b in pairs])),'treatment_fill':float(np.mean([finite(a['fill_rate']) for a,b in pairs])),'reference_fill':float(np.mean([finite(b['fill_rate']) for a,b in pairs]))})
            tc=float(np.mean([p['treatment_cost'] for p in seed_pairs]));rc=float(np.mean([p['reference_cost'] for p in seed_pairs]));tf=float(np.mean([p['treatment_fill'] for p in seed_pairs]));rf=float(np.mean([p['reference_fill'] for p in seed_pairs]))
            result.append({'contrast':description,'treatment_arm':treatment,'reference_arm':reference,'scenario':scenario,'n_paired_seeds':len(seed_pairs),'mean_paired_cost_difference':tc-rc,'cost_difference_pct_reference':100*(tc-rc)/rc if rc else None,'fill_difference_percentage_points':100*(tf-rf),'treatment_mean_cost':tc,'reference_mean_cost':rc,'treatment_mean_fill':tf,'reference_mean_fill':rf,'seed_pairs':seed_pairs,'interpretation':'Descriptive matched simulation-seed contrast only; no significance or power inference. Recovery availability is separated from LLM versus parser extraction.'})
    return result

def config_differences(a,b,path=''):
    if isinstance(a,dict) and isinstance(b,dict):
        result=[]
        for key in sorted(set(a)|set(b)):
            here=f'{path}.{key}' if path else key
            if key not in a or key not in b:result.append({'field':here,'left':a.get(key),'right':b.get(key)})
            else:result.extend(config_differences(a[key],b[key],here))
        return result
    return [] if a==b else [{'field':path,'left':a,'right':b}]


def fairness(stages):
    result=[]
    for left,right in itertools.combinations(stages,2):
        differences=[{'field':key,'left':left['config'].get(key),'right':right['config'].get(key)} for key in MATCH_FIELDS if left['config'].get(key)!=right['config'].get(key)]
        result.append({'left':left['label'],'right':right['label'],'matched_registered_core_fields':not differences,'unmatched_core_fields':differences,'all_config_differences':config_differences(left['config'],right['config'])})
    return result



def auxiliary_development(protocol_path,inventory):
    root=Path(protocol_path).resolve().parent
    selection_paths=sorted(root.glob('development_selection*.json'),key=lambda p:p.name)
    if not selection_paths:return {}
    current_path=root/'development_current_selection.json'
    current=load_json(current_path) if current_path.exists() else load_json(selection_paths[-1])
    if current_path.exists():inventory[str(current_path)]={'sha256':sha(current_path),'bytes':current_path.stat().st_size}
    rounds=[];candidates=[];proofs=[];captured_artifacts=[];cache_probes=[]
    for selection_path in selection_paths:
        selected=load_json(selection_path);inventory[str(selection_path)]={'sha256':sha(selection_path),'bytes':selection_path.stat().st_size}
        round_no=int(selected.get('round') or (int(re.search(r'round([0-9]+)',selection_path.name).group(1)) if re.search(r'round([0-9]+)',selection_path.name) else 1))
        rounds.append({'round':round_no,'compact_output':selected.get('compact_output',False),'inventory_pilot_eligible':selected['inventory_pilot_eligible'],'selected_label':selected['selected_label'],'selected_at_utc':selected['selected_at_utc'],'source':str(selection_path),'development_day':selected.get('development_day',1700),'development_seed':selected.get('development_seed',4242)})
        for candidate in selected.get('candidates',[]):
            label=candidate['label']; path=root/'development'/(label if round_no==1 else f'{label}_round{round_no}')
            reader=VerifiedReader(path,inventory);summary=reader.read_file(path/'summary.json')
            if summary!=candidate:raise ValueError('Development candidate summary differs from frozen selection')
            events,receipts,last=verify_chain(path/'artifacts/audit.sqlite')
            inventory[str(path/'artifacts/audit.sqlite')]={'sha256':sha(path/'artifacts/audit.sqlite'),'bytes':(path/'artifacts/audit.sqlite').stat().st_size}
            objects=reader.verify_all();captured=[];source_documents={}
            for event in events:
                ref=event['payload'].get('output');obj=reader.load(ref) if ref else {}
                if event['stage']=='grounding_v2_sources':source_documents[event['decision_id']]={d['source_ref']:d for d in obj['documents']}
                if event['stage'] in {'llm_request_started','llm_request_response','llm_request_error'}:
                    for payload in request_payloads(obj.get('request',{})):
                        if discover_keys(payload):raise ValueError('Forbidden evaluator keys in development model context')
                        for doc in payload.get('documents',[]):
                            available=source_documents.get(event['decision_id'],{})
                            if available.get(doc['source_ref'])!=doc:raise ValueError('Development model source differs from captured case source')
                    if obj.get('kind')=='llm_call':
                        captured.append(ref);captured_artifacts.append({'development_round':round_no,'candidate':label,'artifact_ref':ref,'artifact':obj})
            if len(captured)!=int(summary['calls']) or len(captured)!=len(set(captured)):raise ValueError('Development fresh captured-call count differs')
            selected_current=label==current.get('selected_label') and round_no==int(current.get('round') or 1)
            candidates.append({'round':round_no,'compact_output':summary.get('compact_output',False),'label':label,'model':summary['model']['name'],'digest':summary['model']['digest'],'complete_case_successes':summary['complete_successes'],'cases':len(summary['cases']),'semantic_retries':summary['semantic_retries'],'client_errors':summary['client_errors'],'calls':summary['calls'],'tokens':summary['tokens'],'elapsed_seconds':summary['seconds'],'selected_for_evaluation':selected_current,'case_issues':[{'variant':c['variant'],'issues':c['issues'],'stats':c['stats']} for c in summary['cases']]})
            proofs.append({'round':round_no,'candidate':label,'chain_events':len(events),'chain_final_hash':last,'objects':objects,'summary_sha256':sha(path/'summary.json')})
            probe_path=path/'cache_probe.json'
            if probe_path.exists():
                probe=reader.read_file(probe_path);cache_probes.append({'round':round_no,'candidate':label,**probe})
    work_log=root/'work_log.jsonl';work_proof={}
    if work_log.exists():
        previous='0'*64;count=0
        for line in work_log.read_text().splitlines():
            obj=json.loads(line);claimed=obj.pop('hash')
            if obj.get('previous_hash')!=previous or digest(obj)!=claimed:raise ValueError('Global pilot work-log chain differs')
            previous=claimed;count+=1
        work_proof={'events':count,'final_hash':previous,'sha256':sha(work_log)}
        inventory[str(work_log)]={'sha256':sha(work_log),'bytes':work_log.stat().st_size}
    return {'selection':current,'rounds':rounds,'candidates':candidates,'candidate_audit_proofs':proofs,'development_captured_model_artifacts':captured_artifacts,'cache_probes':cache_probes,'global_work_log_proof':work_proof,'separate_from_inventory_run_counts':True}


def selected_true_checks(traces,proofs,inventory):
    """Check two trace plans against post-decision truth, without model input."""
    from ega.schemas import Plan
    from ega.optimization import check_plan
    by_run={(p['arm'],p['run']):p for p in proofs}
    selected=[]
    normal=[t for t in traces if t['arm'].startswith('llm') and t['scenario']=='normal' and t['executed_nonzero_action']]
    recovered=[t for t in traces if t['arm'].startswith('llm') and t.get('recovery_applied') and t['executed_nonzero_action']]
    if normal:selected.append(('First actual normal model-enabled replenishment',normal[0]))
    if recovered:selected.append(('First actual replenishment after model-selected deterministic recovery',recovered[0]))
    elif any(t.get('recovery_applied') for t in traces):selected.append(('First recorded deterministic recovery (no model-recovery execution case available)',next(t for t in traces if t.get('recovery_applied'))))
    if len(selected)<2:
        used={(t['arm'],t['decision_id']) for reason,t in selected}
        other=[t for t in traces if (t['arm'],t['decision_id']) not in used and t['optimizer_reached']]
        if other:selected.append(('First additional optimizer trace',other[0]))
    result=[]
    for reason,row in selected[:2]:
        proof=by_run[(row['arm'],row['run'])];reader=VerifiedReader(proof['path'],inventory)
        trace=reader.load(row['trace_ref']);plan_ref=trace['references']['propose'];plan=Plan.model_validate(reader.load(plan_ref))
        evaluation_ref=trace['evaluation'];evaluation=reader.load(evaluation_ref);true_problem=evaluation['true_problem']
        raw=check_plan(plan,true_problem)
        comparison={**true_problem,'lineage':plan.lineage.model_dump()}
        aligned=check_plan(plan,comparison)
        relevant=row['receipt_status']=='executed' and row['executed_nonzero_action']
        if relevant and aligned!=evaluation['violations']:raise ValueError('Selected independently recomputed committed-plan violations differ from original evaluator')
        result.append({'selection_reason':reason,'arm':row['arm'],'run':row['run'],'day':row['day'],'decision_id':row['decision_id'],'trace_ref':row['trace_ref'],'plan_ref':plan_ref,'evaluation_ref':evaluation_ref,'receipt_status':row['receipt_status'],'executed_nonzero_action':row['executed_nonzero_action'],'raw_true_problem_checks':raw,'metadata_aligned_true_problem_checks':aligned,'recorded_evaluation_violations':evaluation['violations'],'recomputed_metric_matches_evaluator':aligned==evaluation['violations'] if relevant else None,'alignment':'Only problem.lineage is set to the immutable plan.lineage, matching the registered evaluator comparison. Physical/economic state, sources, constraints, quantities and forecast values are unchanged. Evaluation truth remains post-decision and is never model context.'})
    return result


def write_csv(path,rows):
    path=Path(path);fields=list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w',newline='',encoding='utf8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({key:json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else value for key,value in row.items()})


def number(value, digits=3):
    if value is None:return 'Not measured'
    if isinstance(value,(list,dict)):return canonical(value)
    if isinstance(value,(bool,str)):return str(value)
    if int(value)==value:return str(int(value))
    return f'{value:.{digits}f}'


def markdown_table(headers,rows):
    def cell(value):return number(value).replace('|','\\|').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+['| '+' | '.join(cell(v) for v in row)+' |' for row in rows])


def graphs(out,data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':145})
    rows=data['aggregates']
    if not rows:return []
    scenarios=list(dict.fromkeys(scenario for stage in data['stages'] for scenario in stage['config']['scenarios']))
    arms=[stage['label'] for stage in data['stages']]
    colors=['#246f9e','#df8b35','#2b9679','#92549a','#b84c5a','#646d7a']
    aliases={'parser_no_recovery':'Parser / no recovery','parser_recovery':'Parser / recovery','llm_v2_no_recovery':'LLM / no recovery','llm_v2_recovery':'LLM / recovery'}
    def label(arm):return aliases.get(arm,arm)
    costs=[];timelines=[]
    for scenario in scenarios:
        chosen=[r for r in rows if r['scenario']==scenario]
        fig,axes=plt.subplots(1,2,figsize=(9.2,3.5))
        for ax,key,title in zip(axes,['mean_cost','mean_fill_rate'],['Mean simulated cost (USD)','Mean fill rate']):
            values=[r[key] for r in chosen]
            ax.bar(range(len(chosen)),values,color=[colors[arms.index(r['arm'])%len(colors)] for r in chosen])
            ax.set_xticks(range(len(chosen)),[label(r['arm']) for r in chosen],rotation=22,ha='right',fontsize=8)
            ax.set_title(title)
            if key=='mean_fill_rate':ax.set_ylim(0,1.08)
            elif values:ax.set_ylim(0,max(values)*1.17 if max(values)>0 else 1)
            for x,value in enumerate(values):
                if value is not None:ax.text(x,value,f'{value:.3f}',ha='center',va='bottom',fontsize=8)
        fig.suptitle(scenario.replace('_',' ').capitalize()+' — matched 14-day pilot',fontsize=12)
        fig.tight_layout(rect=(0,0,1,.94));path=out/f'M5_v2_cost_service_{scenario}.png';fig.savefig(path,bbox_inches='tight');plt.close(fig);costs.append(path)
        fig,axes=plt.subplots(1,2,figsize=(9.2,3.8))
        for arm_index,arm in enumerate(arms):
            ts=[t for t in data['traces'] if t['arm']==arm and t['scenario']==scenario]
            if not ts:continue
            by_day=defaultdict(list)
            for t in ts:by_day[t['day']].append(t)
            days=sorted(by_day);x=list(range(1,len(days)+1))
            axes[0].plot(x,[np.mean([t['on_hand'] for t in by_day[d]]) for d in days],marker='.',label=label(arm),color=colors[arm_index%len(colors)])
            axes[1].plot(x,[np.mean([t['latency_seconds'] for t in by_day[d]]) for d in days],marker='.',label=label(arm),color=colors[arm_index%len(colors)])
        axes[0].set_title('End-of-day inventory');axes[0].set_ylabel('Mean units');axes[1].set_title('Agent decision latency');axes[1].set_ylabel('Mean seconds')
        for ax in axes:ax.set_xlabel('Decision day');ax.set_xticks([1,4,7,10,14]);ax.grid(alpha=.2)
        handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=2,fontsize=8)
        fig.suptitle(scenario.replace('_',' ').capitalize()+' — inventory and latency',fontsize=12);fig.tight_layout(rect=(0,.12,1,.94));path=out/f'M5_v2_inventory_latency_{scenario}.png';fig.savefig(path,bbox_inches='tight');plt.close(fig);timelines.append(path)
    fig,axes=plt.subplots(1,3,figsize=(10.5,4.5));group_width=.8;bar_width=group_width/max(len(arms),1)
    for ax,key,title in zip(axes,['held_decisions','hard_violations','optimizer_decisions'],['Held decisions','Committed-plan violations','Decisions reaching optimizer']):
        for i,arm in enumerate(arms):
            values=[sum(r[key] for r in rows if r['arm']==arm and r['scenario']==scenario) for scenario in scenarios]
            xs=np.arange(len(scenarios))-group_width/2+bar_width*(i+.5)
            ax.bar(xs,values,width=bar_width*.94,color=colors[i%len(colors)],label=label(arm))
        ax.set_xticks(range(len(scenarios)),[s.replace('_','\n') for s in scenarios],fontsize=8);ax.set_title(title,fontsize=10);ax.set_ylabel('Total decisions / checks');ax.set_ylim(bottom=0)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=2,fontsize=8);fig.tight_layout(rect=(0,.12,1,1));safety=out/'M5_v2_execution_safety.png';fig.savefig(safety,bbox_inches='tight');plt.close(fig)
    # Stable primary positions plus every separate scenario chart in the appendix.
    return [costs[0],safety,timelines[0],*costs[1:],*timelines[1:]]



def assessment_items(data):
    assessment=data.get('assessment',{})
    if not assessment:return ['No separate independent source/recovery assessment has been supplied. Its accuracy is not measured by the run-count audit.']
    rows=assessment.get('aggregates',[])
    source=data.get('assessment_source') or {}
    items=[assessment.get('method','Independent post-decision assessment.'),
        {'table':(['Arm','Grounded days','State-gated days','Exact active sets','Rule precision','Rule recall','False rules','Omitted rules'],[[r['arm'],r.get('grounding_decisions',0),r.get('state_gated_unattempted_decisions',0),r.get('whole_active_set_exact_decisions',0),r.get('active_rule_precision'),r.get('active_rule_recall'),r.get('false_active_rules',0),r.get('omitted_active_rules',0)] for r in rows])},
        {'table':(['Arm','Fresh extraction calls','Submitted terms','Exact terms','False terms','Omissions','Term precision','Term recall'],[[r['arm'],r.get('physical_extraction_calls',0),r.get('submitted_terms',0),r.get('exact_numeric_terms',0),r.get('false_numeric_terms',0),r.get('omitted_terms',0),r.get('model_numeric_term_precision'),r.get('model_numeric_term_recall')] for r in rows])},
        {'table':(['Arm','Tool calls','Recoveries applied','Changed quantities','Recovery audit problems'],[[r['arm'],r.get('recovery_tool_invocations',0),r.get('recovery_applied',0),r.get('recovery_derived_quantities_changed',0),r.get('recovery_audit_problem_cases',0)] for r in rows])},
        {'table':(['Arm','Fresh model selector calls','Instruction-compliant choices','Semantic choice errors'],[[r['arm'],r.get('physical_selector_calls',0),r.get('instruction_compliant_selector_calls',0),r.get('selector_semantic_error_calls',0)] for r in rows])},
        'Rule precision/recall compare recorded active constraint sets with an independent source inverse and precedence resolver; they concern the complete hybrid pipeline. Compact model term accuracy concerns only value/unit/exact span from fresh current model responses. Metadata fields, parsed rules, state-gated days and cache reuses have separate attribution and denominators.',
        'Recovery selection is a separate language-model task. Correct extraction values and zero HTTP/schema errors do not establish correct tool choice. Instruction compliance requires both named recovery anomalies, complete current feeds and allowlisted anomaly citations. Independent tool preconditions and the autonomy gate can preserve safety despite a semantically wrong model request.',
        'Full independent assessment: '+str(source.get('path','machine-readable assessment JSON'))+'; SHA-256 '+str(source.get('sha256','unrecorded'))+'. Exhaustive source-by-source cases and recovery rows remain in that file, outside the report narrative.'
    ]
    numeric=assessment.get('physical_extraction_calls',[])[:1]
    if numeric:
        representative=numeric[0]
        items.append({'json':{key:representative.get(key) for key in ['arm','run','day','artifact_ref','semantic_attempt','compact_model_fields','tool_metadata_fields','submitted_terms','exact_numeric_terms','pipeline_validation_accepted','checks']}})
    applied=next((r for r in assessment.get('recovery_cases',[]) if r.get('applied')),None)
    if applied:
        brief={key:applied.get(key) for key in ['arm','run','day','status','applied','problems','only_permitted_fields_changed','changed_quantities','all_sources_match_ledgers','certification_recomputed_exact','hard_fail_before','hard_fail_after','truth_access']}
        brief['sample_changed_rows']=[r for r in applied.get('rows',[]) if r.get('changed')][:3]
        items.append({'json':brief})
    items.extend(assessment.get('limitations',[]))
    return items

def posthoc_items(data):
    """Display measured replay/integrity outcomes, not exhaustive file pins."""
    evidence=data.get('posthoc_evidence',{})
    sources=data.get('posthoc_sources',{})
    if not evidence:return ['No separate cached replay/counterfactual or completion-integrity assessment has been supplied.']
    items=[]
    for label,proof in evidence.items():
        if not isinstance(proof,dict):
            items.append(str(label)+': exhaustive evidence supplied in machine-readable JSON.')
            continue
        cases=proof.get('cases',[])
        if cases and any('replay' in case for case in cases):
            items.extend([proof.get('mode','Selected cached software replay.'),proof.get('scope','Selected decisions only.'),
                {'table':(['Arm / scenario','Day','Certificate match','Action match','Held','Forecast deletion blocked','Original bytes unchanged','Assessment error'],[[str(case.get('arm'))+' / '+str(case.get('scenario')),case.get('day'),case.get('replay',{}).get('state_certificate_matches'),case.get('replay',{}).get('action_matches'),case.get('replay',{}).get('held'),case.get('required_forecast_deletion',{}).get('reconstruction_blocked'),case.get('original_source_bytes_unchanged'),case.get('assessment_error','')] for case in cases])}])
            counters=[]
            for case in cases:
                for counter in case.get('deterministic_tool_counterfactuals',[]):
                    counters.append([str(case.get('arm'))+' / '+str(case.get('scenario')),case.get('day'),counter.get('factor'),counter.get('multiplier'),counter.get('action_changed'),len(counter.get('violations',[])),counter.get('violations',[])])
            if counters:items.append({'table':(['Arm / scenario','Day','Optimizer factor','Multiplier','Action changed','Violation count','Violations'],counters)})
            items.append('These copied-store checks use recorded model output and rerun deterministic tools; they make no fresh model requests. A held case has no forecast deletion test. Structural forecast deletion blocks reconstruction; it does not measure semantic model context use. Large synthetic budget/capacity interventions test optimizer sensitivity, and a nonbinding factor may leave the action unchanged.')
        elif 'selections' in proof and 'incorrect_stale_feed_choices' in proof:
            items.extend([proof.get('scope','All fresh recovery selections.'),
                {'table':(['Model recovery selector outcome','Count'],[['Fresh selections',proof.get('selections')],['Instruction-compliant choices',proof.get('instruction_compliant')],['Incorrect stale-feed choices',proof.get('incorrect_stale_feed_choices')],['Bad choices blocked before execution',proof.get('bad_choices_blocked_before_execution')]])},
                proof.get('interpretation','')])
        elif 'frozen_inputs' in proof and 'arms' in proof:
            groups=Counter(row.get('group','unspecified') for row in proof.get('frozen_inputs',[]))
            items.extend([
                'Completion-integrity status: '+str(proof.get('status'))+'. Frozen source, tests, prepared data and execution helper pins were checked against the frozen protocol. Protected original dissertation and version-1 report pins were also checked.',
                {'table':(['Integrity item','Recorded outcome'],[['Status',proof.get('status')],['Audited at UTC',proof.get('audited_at_utc')],['Exact completion totals',proof.get('totals',{})],['Frozen input groups',dict(groups)],['Workflow records',proof.get('workflow_audit',{}).get('records')],['Workflow final chain hash',proof.get('workflow_audit',{}).get('final_hash')],['Protected original files',len(proof.get('protected_originals',[]))],['Shared forecast identities',len({arm.get('shared_forecast_sha256') for arm in proof.get('arms',[])})],['Selected model digest',proof.get('selected_model',{}).get('digest')],['Before registered cutoff',proof.get('completed_before_cutoff')],['Request to completion minutes',proof.get('elapsed_request_to_evaluation_completion_minutes')]])},
                {'table':(['Arm','Runs','Days','Calls','Tokens','Errors','Hard violations','Holds'],[[arm.get('arm'),arm.get('runs'),arm.get('decision_days'),arm.get('calls'),arm.get('tokens'),arm.get('errors'),arm.get('committed_plan_violations'),arm.get('held_days')] for arm in proof.get('arms',[])])},
                proof.get('code_state','')])
        else:
            items.append({'json':{key:value for key,value in proof.items() if key in ['status','scope','mode','totals','originals_preserved','completed_before_cutoff','summary','results']}})
        filename=sources.get(label)
        if filename:
            items.append(str(label)+': full JSON '+str(filename)+'; SHA-256 '+sha(filename)+'.')
    return items


def make_sections(data,figure_paths):
    totals=data['totals'];aggregates=data['aggregates'];status=data['status'];sections=[]
    sections.append(('M5 replenishment agent version-2 pilot',[
        f"Execution status: {status}. Report generated {data['generated_at_local']} (Europe/Paris). This report describes measured simulator outputs and captured requests, not supplier field deployment.",
        f"The audited current pilot contains {totals['runs']} completed runs, {totals['decisions']} decision traces, {totals['model_calls']} recorded model attempts and {totals['tokens']} recorded tokens. Captured successful HTTP model responses: {totals['captured_successful_calls']}. Completed deterministic parser runs are not LLM runs.",
        ('The registered clean-case development gate failed, so inventory evaluation was not launched. Zero completed inventory runs are a blocked pilot, not evidence of replenishment performance.' if status=='BLOCKED' else 'The inventory evaluation has not been launched; planned runs are not results.' if status=='UNRUN' else 'The pilot evaluates extraction, bounded repair, source-version caching and evidence-based state recovery before making replenishment claims.'),
        "Every measurement below retains its original arm, scenario, seed, origin and decision window."]))
    llm_arms={stage['label'] for stage in data['stages'] if stage['config'].get('llm',{}).get('enabled')}
    live=[row for row in aggregates if row['arm'] in llm_arms]
    if live:
        sections[0][1].append(f"Current model-enabled arms reached the optimizer on {sum(r['optimizer_decisions'] for r in live)} decisions, executed {sum(r['executed_actions'] for r in live)} nonzero replenishment actions and held {sum(r['held_decisions'] for r in live)} decisions. Their committed-plan hard-violation count is {sum(r['hard_violations'] for r in live)}. Recovery, trusted metadata binding and a capable parser control determine how these outcomes should be attributed.")
    if status=='COMPLETE':
        contrasts=data.get('paired_descriptive',[])
        llm_differences=[r for r in contrasts if r['contrast'].startswith('LLM minus parser')]
        if llm_differences and all(r['mean_paired_cost_difference']==0 and r['fill_difference_percentage_points']==0 for r in llm_differences):
            sections[0][1].append('The LLM and capable parser arms produced identical cost and fill results at both recovery settings in every matched scenario. This controlled-corpus pilot measured no additional operational advantage from the language model.')
        recovered=next((r for r in contrasts if r['treatment_arm']=='llm_v2_recovery' and r['reference_arm']=='llm_v2_no_recovery' and r['scenario']=='derived_field_collapse'),None)
        if recovered:
            sections[0][1].append(f"For derived-field collapse, adding observable-evidence recovery changed mean simulated cost from {recovered['reference_mean_cost']:.2f} to {recovered['treatment_mean_cost']:.2f} USD ({recovered['cost_difference_pct_reference']:+.2f}%) and fill from {recovered['reference_mean_fill']*100:.1f}% to {recovered['treatment_mean_fill']*100:.1f}% ({recovered['fill_difference_percentage_points']:+.1f} percentage points). The same recovery effect appears in the parser control; this benefit belongs to the recovery architecture.")
        selector_rows=data.get('assessment',{}).get('physical_selector_calls',[])
        if selector_rows:
            compliant=sum(row['instruction_compliant'] for row in selector_rows);stale_errors=sum(not row['instruction_compliant'] and not row['required_source_stages_current'] for row in selector_rows)
            sections[0][1].append(f"The recovery selector followed its instructions on {compliant}/{len(selector_rows)} fresh choices. It requested recovery on {stale_errors} stale-feed decisions that required a hold. The independent recovery tool did not apply those repairs and the gate held the decisions. This is a semantic tool-selection failure despite zero client errors; exact numeric extraction does not establish reliable tool selection.")
    if data['status']=='COMPLETE' and data.get('paired_descriptive'):
        sections[0][1].append('The following matched contrasts separate LLM versus capable parser performance from the effect of recovery. Each scenario has two paired simulation seeds, with repeated days retained within the same run. Cost percentages use the reference arm mean; fill differences are percentage points. These are descriptive engineering comparisons, without significance or power claims.')
        sections[0][1].append({'table':(['Matched contrast','Scenario','Paired seeds','Cost change %','Fill change pp'],[[r['contrast'],r['scenario'],r['n_paired_seeds'],r['cost_difference_pct_reference'],r['fill_difference_percentage_points']] for r in data['paired_descriptive']])})
    main_rows=[[r['arm']+' / '+r['policy'],r['scenario'],r['runs'],r['mean_cost'],r['mean_fill_rate'],r['held_decisions'],r['executed_actions'],r['hard_violations']] for r in aggregates]
    sections.append(('Observed replenishment results',[{'table':(['Arm / policy','Scenario','Runs','Mean cost','Mean fill','Holds','Nonzero execution','Hard violations'],main_rows)},
        "Cost includes purchase, fixed order, transfer, holding, shortage and spoilage within the configured window. Purchases are charged when ordered. Terminal stock has no salvage credit. Inventory, lead times, available constraints and future service must be considered together; held orders can appear cheap until initial inventory is depleted.",
        "Actual hard violations concern committed plans checked against the post-decision evaluator specification. Clean-reference action deviations are a separate comparator metric. The physical simulator can cap transfers and supplier fulfilment, so plan violations do not assert negative physical inventory.",{'image':str(figure_paths[0])} if figure_paths else "No completed results were available for a graph."]))
    stage_rows=[[s['label'],s['status'],s['completed_runs'],s['expected_runs'],s['configured_days'],s['seeds'],s['scenarios'],s['policies']] for s in data['stages']]
    sections.append(('Registered design and completion',[{'table':(['Arm','Status','Completed','Configured','Days','Seeds','Scenarios','Policies'],stage_rows)},
        "Each configured run identity is a policy × scenario × independent simulation seed × rolling origin. Store-item series and repeated days are not independent replications. This pilot supplies descriptive findings; it makes no confirmatory significance, power or full-dissertation claims.",
        "The M5 panel contains thirty selected FOODS item-store series: three items across ten stores. It is not a random or department-balanced M5 sample. Observed M5 sales are used as a demand proxy. Inventory, supplier rules, wholesale costs, contracts, disturbances and approvals are simulated.",
        "Supplier text is controlled synthetic prose generated from public rendering grammars. More natural-looking language is not a validated real supplier corpus. A capable deterministic parser is therefore a necessary control. Findings about parsing these grammars cannot be generalized to heterogeneous commercial contracts.",
        {'table':(['Arm','Origin','Historical evaluation dates','Last included training date'],[[s['label'],m['origin'],m['start_date']+' through '+m['end_date'],m['training_last_included_date']] for s in data['stages'] for m in s.get('historical_date_mapping',[])])},
        'Historical M5 dates describe the evaluated data window; report and inference timestamps describe current cloud execution. Frozen training cutoffs precede the evaluation and warmup window.',
        {'json':{'schema_version':data['protocol'].get('schema_version'),'status':data['protocol'].get('status'),'requested_at_utc':data['protocol'].get('requested_at_utc'),'frozen_at_utc':data['protocol'].get('frozen_at_utc'),'experiment_cutoff_utc':data['protocol'].get('experiment_cutoff_utc'),'report_deadline_utc':data['protocol'].get('report_deadline_utc'),'selected_model':{key:data['protocol'].get('selected_model',{}).get(key) for key in ['name','digest','size','details']},'evaluation':data['protocol'].get('evaluation'),'limits':data['protocol'].get('limits'),'code_version_note':data['protocol'].get('code_version_note')}},
        'The complete frozen protocol, source/test/data hashes, configurations and model profiles are preserved in the downloadable evidence files.'
    ]))
    fair_rows=[[x['left'],x['right'],x['matched_registered_core_fields'],[d['field'] for d in x['unmatched_core_fields']]] for x in data['fairness']]
    sections.append(('Fair comparisons and development boundaries',[{'table':(['Left arm','Right arm','Matched registered core fields','Unmatched fields'],fair_rows)},
        "The core comparison checks identical dataset, historical start and duration, seeds/origins, warmup, carrier, forecast, solver, gate, disturbances, accounting and approval configuration. Model, parser, repair and caching settings are separately disclosed in the full input inventory and report data. Shared verified caching can reuse identical contracts across registered seeds and scenarios within a configuration; cache hit and inference latency results therefore depend on run order and are not independent model-accuracy trials. Fresh physical calls come only from current trace records, not imported cached model-response objects. A policy difference or different recovery capability is a treatment difference, not a silent matched control.",
        "The previous version-1 report is historical context only: four live model runs covered two decision days each, all eight days were held, with thirty recorded calls. Its strict conditional grounding assessment found 88 exact tuples, seven false tuples and 24 omissions from 112 submitted documents. Only sixteen of 157 available documents were submitted on each of seven extraction days. Version-1 cost and service are not pooled with this longer version-2 window and are not used as a savings baseline.",
        "A favorable result requires actual model calls when labeled LLM, complete relevant mandatory evidence, current-state feasible decisions and adequate service. Parser fallbacks and cache hits must retain their provenance. Cache coverage alone does not establish LLM reasoning or independent validation."]))
    development=data.get('development',{})
    if development:
        sections.append(('Pre-evaluation model selection',[
            {'table':(['Round / head','Model','Complete cases','Repairs','Errors','Calls','Tokens','Measured seconds','Selected'],[[str(c['round'])+' / '+('numeric term' if c['compact_output'] else 'full tuple'),c['model'],str(c['complete_case_successes'])+'/'+str(c['cases']),c['semantic_retries'],c['client_errors'],c['calls'],c['tokens'],c['elapsed_seconds'],c['selected_for_evaluation']] for c in development.get('candidates',[])])},
            'Candidate models were compared on separate development days and seeds with two controlled wording variants per round. Both local candidates failed every full-tuple case in round 1. Before inventory evaluation, the extraction head was reduced to model-proposed value, unit and a short exact source quote. IDs, entity, scope, parameter, conversion, aggregation, dates and precedence are then supplied by a disclosed trusted source-slot tool. Those structural fields are not LLM extraction accuracy. Round 2 uses fresh development cases; this is adaptive engineering development, not an untouched confirmatory test. Selection uses complete source-proved case successes, then correction count, then measured elapsed time. These two cases are a development benchmark, not an independent test set, proof of broad model quality, or part of the inventory-run totals.',
            'The inventory pilot starts only after the registered clean-case gate passes. The selected model identity and source code are frozen before evaluation. Development cache reuse is a separate efficiency check; it never creates additional independent accuracy trials. In the repeated 157-document cases, most cached rules originate from deterministic parsing and only two from accepted model numeric terms. Cache hits must not be equated with the number of avoided model requests.',
            {'table':(['Candidate','Fresh requests in repeat','Complete repeated case','Cache hits','Accuracy selection case'],[[p['candidate'],p.get('new_calls'),not p.get('issues'),p.get('stats',{}).get('cache_hits'),p.get('selection_accuracy_case')] for p in development.get('cache_probes',[])])},
            {'json':development.get('candidate_audit_proofs',[])}]))
    usage_rows=[[r['arm']+' / '+r['policy'],r['scenario'],r['llm_calls'],r['tokens'],r['llm_errors'],r['optimizer_decisions'],r['feasible_plans'],r['mean_decision_latency_seconds'],r['p95_decision_latency_seconds']] for r in aggregates]
    sections.append(('Model use, optimization and latency',[{'table':(['Arm / policy','Scenario','Calls','Tokens','Errors','Optimizer decisions','Feasible plans','Mean sec','p95 sec'],usage_rows)},
        "Model-call attempts, successful response artifacts and validation outcomes have different denominators. Transport or structured-output errors are not automatically semantic failures. A schema-valid response does not prove that source values, units, entities or validity are correct.",
        "Every comparison uses the same single trained GRU forecaster, frozen before the evaluation and warmup window. This pilot does not benchmark DeepAR, TFT or foundation forecasters. The optimizer supplies numeric orders; the language model is not allowed to invent final order quantities. A solver feasible incumbent is not necessarily optimal. Any optimal flag is interpreted under the configured MIP tolerance and time limit.",
        "Latency is measured for the agent decision, including live model work, validation, gates and relevant recovery. It excludes the evaluator reference solve. Local endpoint API token charges can be zero while infrastructure cost remains unmeasured.",{'image':str(figure_paths[2])} if len(figure_paths)>2 else '']))
    kinds=Counter(x['mechanism'] for x in data['v2_events'])
    sections.append(('Extraction, repair, cache and recovery evidence',[{'table':(['Arm','Attempted sources','Parser rules','Accepted model terms','Cache hits','Fully grounded days','Repair requests','Repair success','Recovery applied'],[[r['arm'],r['source_documents'],r['parsed_documents'],r['model_documents'],r['cache_hits'],r['grounding_complete_decisions'],r['semantic_retries'],r['accepted_repair_batches'],r['recovery_applied_decisions']] for r in data['mechanism_aggregates']])},
        {'table':(['Arm','Cached parser rules','Cached model terms','Cache rejections','Model numeric terms','Tool-bound metadata','Sources skipped by state gate'],[[r['arm'],r['cached_parser_documents'],r['cached_model_term_documents'],r['cache_rejected_events'],r['compact_model_numeric_terms'],r['tool_derived_metadata_rules'],r['source_exposures_skipped_by_state_gate']] for r in data['mechanism_aggregates']])},
        {'table':(['Recorded version-2 event stage','Events'],sorted(kinds.items()))},
        "In the hybrid carrier, common clauses use deterministic public-grammar parsing. At most one supplier clause and one portfolio clause per day use the language-model path. This enables an actual model-dependent decision while retaining complete source coverage across all thirty simulated series; it is not thirty-series LLM extraction coverage. The capable full-parser control recognizes those same hybrid clauses independently. Every supported version-2 mechanism must be substantiated by its recorded artifact references. A compact output credits the model only for value/unit and its literal numeric-term quote. Trusted source-slot metadata binding supplies the rest of the rule and verifies the model term; it does not replace an invalid or omitted model term. A repair can repeat the original source and exact validation feedback; it cannot receive hidden expected answers. Repairs are bounded, and failed corrections remain holds. Verified cache entries require unchanged authenticated source identity, version and validity context. Unseen or changed sources must not become cache hits.",
        "State recovery must come from authorized observable feeds or documented reconciliation, followed by fresh certification. The post-decision evaluator state and future realized sales are never eligible recovery inputs. Parser and LLM comparison arms should receive the same recovery capability; otherwise its effect remains confounded with language-model extraction.",
        *assessment_items(data),
        "If an optional grounding/recovery assessment is absent, its accuracy is not measured by this generator. The raw version-2 event ledger is exported as JSON Lines and is available for independent source-by-source inspection. Submitted document exposures count retries, so they must not be treated as unique pipeline coverage without a strict coverage assessment."]))
    sections.append(('Execution, inventory and service safeguards',[
        {'image':str(figure_paths[1])} if len(figure_paths)>1 else '',
        "Held decisions, executed receipts and nonzero replenishment actions are reported separately. An executed zero-order receipt does not demonstrate successful replenishment. Longer windows help reveal shortages after initial stock is consumed, but a small pilot still cannot establish steady-state costs or retailer ROI.",
        "Quality gates reduce exposure to suspect inputs and can also delay replenishment. Repair and recovery must improve valid coverage and service without weakening those checks. A strong parser control may perform equally well or better on this controlled corpus; that result is informative and must be reported."]))
    sections.append(('Alignment with the revised dissertation',[
        {'table':(['Research question','Evidence provided by this pilot','Remaining dissertation evidence'],[
            ['RQ1: replenishment performance','Matched parser/LLM optimizer outcomes on the same 14-day window; separate recovery effects','Full multi-origin, severity and independent-seed design; broader forecast families and measured retailer outcomes'],
            ['RQ2: evidence quality','Observed feed-gap and derived-field-collapse faults, source/ledger recovery and recertification','Full quality taxonomy, telemetry calibration and field reliability'],
            ['RQ3: constraint grounding','Controlled synthetic clauses; compact numeric value/unit/source-span model checks; full-source metadata bound by trusted tools; capacity cut','Validated naturally occurring contracts, model interpretation of complete tuple metadata and unit conversions'],
            ['RQ4: architecture and ablations','Capable parser controls and recovery/no-recovery factorial comparisons','LLM-only, fixed-autonomy, role, actionable-memory and critic ablations'],
            ['RQ5: reliability','Actual committed-plan violations, solver/gate/receipt logs and complete configured traces','Powered robustness studies, external supplier systems and deployment incidents'],
            ['RQ6: trace faithfulness','Selected copied-store cached replay and deterministic budget/capacity sensitivity when supplied','Free-form versus typed-agent comparison, model-internal faithfulness and semantic context-deletion experiments'],
            ['RQ7: human audit','Auditable source records and evidence exports','Human participants, approved study protocol and measured reviewer outcomes']
        ])},
        'This version-2 engineering pilot does not establish the full H1–H8 dissertation claims. It supplies a narrower, reproducible test of a safer hybrid extraction/recovery design. Deterministic numeric-tool sensitivity is not a new live LLM experiment. Deleting a forecast artifact tests a structural reconstruction requirement; it is not semantic context deletion or evidence that the model used a source faithfully.',
        'Cached replay demonstrates that recorded software inputs reproduce the selected action/state hashes. It does not reveal internal model reasoning or replace a human audit.'
    ]))
    if len(figure_paths)>3:
        sections.append(('Additional scenario graphs',[{'image':str(path)} for path in figure_paths[3:]]))
    sections.append(('Audit integrity and limits',[
        f"Audited {totals['objects']} original content-addressed objects and {totals['events']} SQLite chain events across {totals['runs']} completed runs. Each original summary, daily CSV, trace index, run manifest and resolved configuration is independently hashed. All discovered object contents match their original SHA-256 references. SQLite chains and receipt identities were checked read-only.",
        "All current pilot model attempts were persisted before HTTP transport and paired with their later response/error by role, start timestamp, attempt number and exact request hash; their SQLite sequence order was checked. Request-start objects and imported cached calls are not additional physical calls. Every captured successful model request was checked for exact submitted-source equality and explicitly forbidden evaluator fields. The audit can detect those recorded leakage patterns; it is not a proof against every possible information channel. Evaluation objects are retained after decisions for assessment and are not model context.",
        "SHA-256 and local chains detect modification and preserve reproducibility; they are not signatures, external timestamps or WORM storage. Logs contain actual prompts, supplier source evidence, full model responses, validations, solver artifacts, gates, receipts and simulator outcomes. Credentials and authorization headers are not exported.",
        "There are no human participants, ERP deployment, measured organizational ROI, validated naturally occurring supplier contracts, complete rolling-origin/severity matrix or independently powered full dissertation tests. The main outcome is a reproducible engineering pilot with descriptive operational evidence.",
        {'json':data['selected_true_problem_checks']},
        {'json':data['shared_forecast_artifacts']},
        *posthoc_items(data),
        {'table':(['Evidence item','Count'],[['Completed runs',totals['runs']],['Daily decisions',totals['decisions']],['Original objects',totals['objects']],['Hash-chain events',totals['events']],['Recorded model attempts',totals['model_calls']],['Captured successful responses',totals['captured_successful_calls']],['Captured model tokens',totals['tokens']],['Forbidden-context key findings',totals['forbidden_context_keys']]])}]))
    return sections


def render_outputs(out,data,figure_paths):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak,Preformatted
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import matplotlib
    font_dir=Path(matplotlib.get_data_path())/'fonts/ttf'
    for family,file in [('V2Sans','DejaVuSans.ttf'),('V2SansBold','DejaVuSans-Bold.ttf'),('V2SansOblique','DejaVuSans-Oblique.ttf'),('V2SansBoldOblique','DejaVuSans-BoldOblique.ttf')]:pdfmetrics.registerFont(TTFont(family,str(font_dir/file)))
    pdfmetrics.registerFontFamily('V2Sans',normal='V2Sans',bold='V2SansBold',italic='V2SansOblique',boldItalic='V2SansBoldOblique')
    styles=getSampleStyleSheet()
    for key in ['Normal','BodyText','Title','Heading1','Heading2']:
        styles[key].fontName='V2SansBold' if key in ['Title','Heading1','Heading2'] else 'V2Sans'
    styles['BodyText'].fontSize=9;styles['BodyText'].leading=13;styles['BodyText'].spaceAfter=9
    styles['Title'].fontSize=21;styles['Title'].leading=27
    styles.add(ParagraphStyle(name='V2Table',fontName='V2Sans',fontSize=7,leading=10))
    styles.add(ParagraphStyle(name='V2Mono',fontName='V2Sans',fontSize=7,leading=10,wordWrap='CJK'))
    sections=make_sections(data,figure_paths);story=[];md=[];html_parts=[]
    width=A4[0]-76
    for section_i,(title,items) in enumerate(sections):
        if section_i:story.append(PageBreak())
        story.append(Paragraph(html.escape(title),styles['Title'] if section_i==0 else styles['Heading1']));story.append(Spacer(1,10));md.append(('# ' if section_i==0 else '## ')+title);html_parts.append(f'<h{1 if section_i==0 else 2}>{html.escape(title)}</h{1 if section_i==0 else 2}>')
        for item in items:
            if isinstance(item,str):
                if not item:continue
                story.append(Paragraph(html.escape(item),styles['BodyText']));md.append(item);html_parts.append('<p>'+html.escape(item)+'</p>')
            elif 'table' in item:
                headers,rows=item['table'];md.append(markdown_table(headers,rows));html_parts.append('<table><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(number(v))+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table>')
                table_rows=[[Paragraph(html.escape(str(c)),styles['V2Table']) for c in headers]]+[[Paragraph(html.escape(number(c)),styles['V2Table']) for c in row] for row in rows]
                table=Table(table_rows,colWidths=[width/len(headers)]*len(headers),repeatRows=1,hAlign='LEFT')
                table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e3eef5')),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.25,colors.HexColor('#c5d0d8')),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]));story.extend([table,Spacer(1,12)])
            elif 'image' in item:
                path=Path(item['image']);from PIL import Image as PILImage
                with PILImage.open(path) as im:w,h=im.size
                display_width=width;display_height=display_width*h/w
                if display_height>450:display_height=450;display_width=display_height*w/h
                story.extend([Image(str(path),width=display_width,height=display_height),Spacer(1,12)]);md.append(f'![{path.stem}]({path.name})');html_parts.append(f'<img src="{html.escape(path.name)}" alt="{html.escape(path.stem)}">')
            elif 'json' in item:
                value=item['json'];md.append('```json\n'+json.dumps(value,indent=2,ensure_ascii=False)+'\n```');html_parts.append('<pre>'+html.escape(json.dumps(value,indent=2,ensure_ascii=False))+'</pre>')
                # The complete machine-readable structure is exported; keep PDF readable.
                if value:
                    brief=json.dumps(value,indent=2,ensure_ascii=False)
                    if len(brief)>8000:brief=brief[:8000]+'\n[Full structure is in the accompanying JSON evidence.]'
                    for line in brief.splitlines():story.append(Paragraph(html.escape(line),styles['V2Mono']))
                    story.append(Spacer(1,12))
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('V2Sans',7);canvas.setFillColor(colors.HexColor('#566570'));canvas.drawString(38,25,'M5 v2 simulator pilot | '+data['status']+' | '+data['generated_at_local']);canvas.drawRightString(A4[0]-38,25,str(doc.page));canvas.restoreState()
    pdf=out/'M5_v2_pilot_report.pdf';doc=SimpleDocTemplate(str(pdf),pagesize=A4,rightMargin=38,leftMargin=38,topMargin=40,bottomMargin=40,title='M5 replenishment agent version-2 pilot — '+data['status'],author='M5 experiment evidence',pageCompression=1);doc.build(story,onFirstPage=footer,onLaterPages=footer)
    (out/'M5_v2_pilot_report.md').write_text('\n\n'.join(md)+'\n',encoding='utf8')
    css='body{font-family:system-ui,sans-serif;max-width:1180px;margin:40px auto;padding:0 24px;line-height:1.5;color:#1d2933}h1,h2{color:#16496a}table{border-collapse:collapse;width:100%;margin:20px 0;font-size:13px}td,th{border:1px solid #c5d0d8;padding:7px;text-align:left;vertical-align:top}th{background:#e3eef5}img{max-width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f5;padding:14px;font-size:12px}'
    (out/'M5_v2_pilot_report.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>M5 v2 pilot report</title><style>'+css+'</style></head><body>'+''.join(html_parts)+'</body></html>',encoding='utf8')
    return pdf


def evidence_zip(out,data,inventory):
    destination=out/'M5_v2_results_and_evidence.zip'; members={}
    # Reports and machine-readable metrics are compact; originals are retained in source roots.
    for path in out.iterdir():
        if path.is_file() and path.name not in {destination.name,'M5_v2_export_inventory.json','M5_v2_report_generation.json'} and path.suffix in {'.pdf','.html','.md','.json','.csv','.jsonl','.png'}:members['report/'+path.name]=path
    assessment_source=data.get('assessment_source')
    if assessment_source:
        path=Path(assessment_source['path']);members['assessment/'+path.name]=path
    protocol_path=data.get('protocol_path')
    if protocol_path:members['protocol/'+Path(protocol_path).name]=Path(protocol_path)
    members['helpers/m5_v2_report.py']=Path(__file__).resolve()
    for name in ['m5_v2_report_validate.py','m5_v2_report_validation.json','m5_v2_assess.py','m5_v2_assess_validate.py','m5_v2_assess_validation.json']:
        path=Path(__file__).resolve().parent/name
        if path.exists():members['helpers/'+name]=path
    for label,filename in data.get('posthoc_sources',{}).items():
        path=Path(filename);members['posthoc/'+path.name]=path
    for proof in data.get('execution_helper_proofs',[]):
        path=Path(proof['path']);members['helpers/'+path.name]=path
    for proof in data.get('prepared_data_proofs',[]):
        path=REPO/proof['path'];members['prepared_panel/'+path.name]=path
    for model in data.get('shared_forecast_artifacts',[])[:1]:
        path=Path(model['path'])
        identity=path.parent/'model_identity.json'
        if identity.exists():members['forecast/model_identity.json']=identity
    pilot_root=Path(data['protocol_path']).parent
    for name in ['development_selection.json','development_selection_round2.json','development_current_selection.json','candidate_model_profiles.json','initial_environment.json','frozen_source_inventory.json','tracked_code_changes.patch','work_log.jsonl','execution_complete.json','pre_freeze_corrected_tests_validation.json','full_tests_final_validation.json','integration_recovery_validation.json','integration_compact_validation.json','selected_cached_replay.json','final_audit.json']:
        path=pilot_root/name
        if path.exists():members['pilot/'+name]=path
    for path in (pilot_root/'frozen_code').rglob('*.py'):
        members['pilot/frozen_code/'+path.relative_to(pilot_root/'frozen_code').as_posix()]=path
    for path in (pilot_root/'development').glob('*/*.json'):
        members['pilot/development/'+path.parent.name+'/'+path.name]=path
    for stage in data['stages']:
        root=Path(stage['root']);label=re.sub(r'[^a-zA-Z0-9_-]','_',stage['label'])
        for name in ['resolved_config.json','environment.json','summary.csv','study_summary.json','paired_comparisons.csv']:
            path=root/name
            if path.exists():members[f'original/{label}/{name}']=path
        for proof in [p for p in data['run_proofs'] if p['arm']==stage['label']]:
            path=Path(proof['path'])
            for name in ['run_manifest.json','summary.json','daily.csv','detection.csv','trace_index.json','packing_manifest.json']:
                source=path/name
                if source.exists():members[f'original/{label}/{path.name}/{name}']=source
    records={name:{'sha256':sha(path),'bytes':path.stat().st_size} for name,path in members.items()}
    export={'format':'m5-v2-compact-evidence-v1','generated_at_local':data['generated_at_local'],'scope':'Report, all metrics, per-run provenance and full audit proofs. Full content-addressed objects and SQLite histories remain at original cloud run paths; this compact export is not a standalone runnable environment or full artifact archive.','members':records,'member_inventory_sha256':digest(records)}
    atomic_json(out/'M5_v2_export_inventory.json',export)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(members.items()):archive.write(path,name)
        archive.write(out/'M5_v2_export_inventory.json','M5_v2_export_inventory.json')
    with zipfile.ZipFile(destination) as archive:
        for name,record in records.items():
            content=archive.read(name)
            if len(content)!=record['bytes'] or hashlib.sha256(content).hexdigest()!=record['sha256']:raise ValueError('Export member verification failed')
    return destination


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',required=True,type=Path)
    parser.add_argument('--stage',action='append',default=[],help='Unique arm label=original result root')
    parser.add_argument('--output',type=Path,default=REPO/'results/v2_report')
    parser.add_argument('--assessment',type=Path)
    parser.add_argument('--posthoc',action='append',default=[],help='Evidence label=read-only replay/counterfactual JSON')
    parser.add_argument('--allow-partial',action='store_true')
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--no-zip',action='store_true')
    args=parser.parse_args(argv);out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR',str(out/'.matplotlib-cache'))
    protocol=load_json(args.protocol);inventory={str(args.protocol.resolve()):{'sha256':sha(args.protocol),'bytes':args.protocol.stat().st_size}}
    inventory[str(Path(__file__).resolve())]={'sha256':sha(__file__),'bytes':Path(__file__).stat().st_size}
    historical_evidence_paths=[REPO/'results/report/M5_six_hour_study_report.md',REPO/'results/report/six_hour_live_grounding_assessment.json',REPO/'results/report/source/dissertation_revised_business_school.html']
    for path in historical_evidence_paths:
        if path.exists():inventory[str(path)]={'sha256':sha(path),'bytes':path.stat().st_size}
    stages=[];rows=[];traces=[];calls=[];v2=[];proofs=[]
    for item in args.stage:
        label,separator,path=item.partition('=')
        if not separator or not label or label in {s['label'] for s in stages}:parser.error('Stages must have unique label=path values')
        result=audit_stage(label,Path(path),inventory,args.allow_partial)
        stages.append(result[0])
        for collection,part in zip([rows,traces,calls,v2,proofs],result[1:]):collection.extend(part)
    if len({c['artifact_ref'] for c in calls})!=len(calls):raise ValueError('A physical successful model response is counted more than once across current arms')
    development=auxiliary_development(args.protocol,inventory)
    registered_arms=protocol.get('evaluation',{}).get('arms',{})
    missing_arms=sorted(set(registered_arms)-{s['label'] for s in stages}) if stages else sorted(registered_arms)
    unexpected_arms=sorted({s['label'] for s in stages}-set(registered_arms)) if registered_arms else []
    if unexpected_arms:raise ValueError(f'Unregistered pilot arm labels: {unexpected_arms}')
    if stages and missing_arms and not args.allow_partial:raise ValueError(f'Registered arms missing from report: {missing_arms}')
    frozen_source_proofs=[]
    for relative,expected_sha in protocol.get('frozen_source_sha256',{}).items():
        frozen_path=Path(args.protocol).resolve().parent/'frozen_code'/relative
        if not frozen_path.exists() or sha(frozen_path)!=expected_sha:raise ValueError('Frozen source snapshot is absent or changed')
        if sha(REPO/relative)!=expected_sha:raise ValueError('Current source differs from frozen snapshot; refuse current-code truth checking')
        inventory[str(frozen_path)]={'sha256':expected_sha,'bytes':frozen_path.stat().st_size}
        frozen_source_proofs.append({'path':relative,'sha256':expected_sha})
    prepared_data_proofs=[]
    for relative,expected_sha in protocol.get('frozen_prepared_data_sha256',{}).items():
        path=REPO/relative
        if sha(path)!=expected_sha:raise ValueError('Prepared M5 data differ from registered frozen bytes')
        inventory[str(path)]={'sha256':expected_sha,'bytes':path.stat().st_size}
        prepared_data_proofs.append({'path':relative,'sha256':expected_sha,'bytes':path.stat().st_size})
    execution_helper_proofs=[]
    for filename,expected_sha in protocol.get('frozen_helper_sha256',{}).items():
        path=Path(filename)
        if sha(path)!=expected_sha:raise ValueError('Execution helper differs from registered frozen bytes')
        inventory[str(path)]={'sha256':expected_sha,'bytes':path.stat().st_size}
        execution_helper_proofs.append({'path':filename,'sha256':expected_sha})
    shared_models=[]
    for stage in stages:
        registered_config=protocol.get('configs',{}).get(stage['label'])
        if registered_config:
            source_path=Path(registered_config['path'])
            if sha(source_path)!=registered_config['sha256'] or load_json(source_path)!=stage['config']:raise ValueError('Registered frozen configuration changed')
            inventory[str(source_path)]={'sha256':sha(source_path),'bytes':source_path.stat().st_size}
        model_ref_path=Path(stage['root'])/'shared_model_reference.json'
        if model_ref_path.exists():
            ref=load_json(model_ref_path);model_path=Path(ref['path'])
            if sha(model_path)!=ref['sha256']:raise ValueError('Shared forecast artifact SHA differs')
            inventory[str(model_path)]={'sha256':sha(model_path),'bytes':model_path.stat().st_size}
            inventory[str(model_ref_path)]={'sha256':sha(model_ref_path),'bytes':model_ref_path.stat().st_size}
            shared_models.append({'arm':stage['label'],**ref})
    if shared_models and len({x['sha256'] for x in shared_models})!=1:raise ValueError('Pilot arms use different trained forecast artifact bytes')
    overall='COMPLETE' if stages and not missing_arms and all(s['status']=='COMPLETE' for s in stages) else 'PARTIAL' if stages else 'BLOCKED' if development.get('selection',{}).get('inventory_pilot_eligible') is False else 'UNRUN'
    assessment=load_json(args.assessment) if args.assessment else {}
    posthoc_evidence={};posthoc_sources={}
    for item in args.posthoc:
        label,separator,filename=item.partition('=')
        if not separator:parser.error('Post-hoc evidence must have label=JSON path')
        path=Path(filename).resolve();posthoc_evidence[label]=load_json(path);posthoc_sources[label]=str(path)
        inventory[str(path)]={'sha256':sha(path),'bytes':path.stat().st_size}
    for name in ['selected_cached_replay.json','trace_validation.json','counterfactual_results.json','final_audit.json','core_integrity_proof.json','tool_selector_assessment.json']:
        path=Path(args.protocol).resolve().parent/name
        if path.exists():
            posthoc_evidence[name]=load_json(path);posthoc_sources[name]=str(path)
            inventory[str(path)]={'sha256':sha(path),'bytes':path.stat().st_size}
    if args.assessment:inventory[str(args.assessment.resolve())]={'sha256':sha(args.assessment),'bytes':args.assessment.stat().st_size}
    generated=datetime.now(ZoneInfo('Europe/Paris')).isoformat(timespec='seconds')
    totals={'runs':len(rows),'decisions':len(traces),'objects':sum(p['object_count'] for p in proofs),'events':sum(p['chain_event_count'] for p in proofs),'model_calls':sum(int(r.get('llm_calls') or 0) for r in rows),'captured_successful_calls':len(calls),'tokens':sum(int(r.get('tokens') or 0) for r in rows),'forbidden_context_keys':sum(c['forbidden_context_keys'] for c in calls)}
    if overall=='COMPLETE':
        expected_runs=protocol.get('evaluation',{}).get('expected_runs')
        expected_decisions=protocol.get('evaluation',{}).get('expected_decisions')
        if expected_runs is not None and totals['runs']!=int(expected_runs):raise ValueError('Complete report differs from registered total run count')
        if expected_decisions is not None and totals['decisions']!=int(expected_decisions):raise ValueError('Complete report differs from registered total decision count')
    data={'format':'m5-v2-pilot-evidence-v1','status':overall,'generated_at_local':generated,'timezone':'Europe/Paris','protocol_path':str(args.protocol.resolve()),'protocol':protocol,'missing_registered_arms':missing_arms,'shared_forecast_artifacts':shared_models,'frozen_source_proofs':frozen_source_proofs,'prepared_data_proofs':prepared_data_proofs,'execution_helper_proofs':execution_helper_proofs,'development':development,'stages':stages,'totals':totals,'aggregates':aggregate(rows,traces,calls),'paired_descriptive':paired_descriptive(rows),'fairness':fairness(stages),'run_proofs':proofs,'runs':rows,'traces':traces,'calls':calls,'v2_events':v2,'assessment':assessment,'assessment_source':{'path':str(args.assessment.resolve()),'sha256':sha(args.assessment)} if args.assessment else None,'posthoc_evidence':posthoc_evidence,'posthoc_sources':posthoc_sources,'mechanism_aggregates':mechanism_aggregate(traces,v2),'selected_true_problem_checks':selected_true_checks(traces,proofs,inventory) if traces else [],'source_integrity':'all original runs audited read-only; no historical report overwritten'}
    atomic_json(out/'M5_v2_pilot_report_data.json',data);atomic_json(out/'M5_v2_pilot_input_hashes.json',{'format':'m5-v2-input-inventory-v1','generated_at_local':generated,'files_and_archive_members':inventory,'inventory_sha256':digest(inventory)})
    atomic_json(out/'M5_v2_selected_true_checks.json',data['selected_true_problem_checks']);write_csv(out/'M5_v2_paired_descriptive.csv',data['paired_descriptive']);write_csv(out/'M5_v2_mechanisms.csv',data['mechanism_aggregates']);write_csv(out/'M5_v2_results.csv',rows);write_csv(out/'M5_v2_decisions.csv',traces);write_csv(out/'M5_v2_model_calls.csv',calls)
    (out/'M5_v2_development_model_artifacts.jsonl').write_text(''.join(canonical(e)+'\n' for e in development.get('development_captured_model_artifacts',[])),encoding='utf8')
    (out/'M5_v2_event_ledger.jsonl').write_text(''.join(canonical(e)+'\n' for e in v2),encoding='utf8')
    (out/'M5_v2_evidence_README.md').write_text('# M5 v2 pilot evidence\n\nThis export preserves current registered arms separately and does not pool the historical version-1 study. Every original run identity, manifest, daily row, trace, model request/response and SQLite receipt was audited read-only. Hash inventory and run proofs document verified original bytes.\n\nThe compact ZIP includes reports, scientific figures, CSV metrics, event ledger, frozen protocol/configurations and per-run provenance. Full JSON object archives and SQLite histories remain at source_result_root/source_run_path in the cloud workspace. The export does not include model weights, full raw M5 files, a runnable environment, credentials or unperformed experiments.\n\nCosts and service must be compared only across matched windows and information. Cache hits, repaired outputs, parser results and actual model calls retain distinct provenance. Controlled supplier prose is synthetic; M5 sales are a demand proxy. No human study, field deployment, confirmatory power or general LLM superiority is claimed.\n',encoding='utf8')
    result={'status':overall,'totals':totals,'output':str(out),'validation_only':args.validate_only}
    if not args.validate_only:
        figures=graphs(out,data);pdf=render_outputs(out,data,figures);result.update(pdf=str(pdf),pdf_sha256=sha(pdf),pdf_bytes=pdf.stat().st_size)
        if not args.no_zip:
            archive=evidence_zip(out,data,inventory);result.update(zip=str(archive),zip_sha256=sha(archive),zip_bytes=archive.stat().st_size)
    atomic_json(out/'M5_v2_report_generation.json',result);print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':main()
