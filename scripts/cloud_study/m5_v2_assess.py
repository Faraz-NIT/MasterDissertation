#!/usr/bin/env python3
"""Independent post-decision source and recovery assessment of frozen v2 traces.

Read-only; never calls a model, repairs a run or feeds expected answers to agents.
The grammar inverse below is independent of production GroundingV2Agent. It
proves only the registered controlled corpus, not arbitrary supplier language.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime
import importlib.util
import json,math,re
from pathlib import Path
from zoneinfo import ZoneInfo

spec=importlib.util.spec_from_file_location('v2report','/workspace/tools/m5_v2_report.py');report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)
FIELDS=['constraint_id','entity','scope','parameter','value','unit','conversion','aggregation','valid_from','valid_to','precedence','source_ref']
TOKEN=r'[^\s|]+'
NUM=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
PATTERNS=[
 ('public0',re.compile(r'^Contract clause (?P<constraint_id>.+?) \(precedence (?P<precedence>-?\d+), aggregation (?P<aggregation>\w+)\): (?P<entity>.+?) must comply with (?P<parameter>\w+) = (?P<value>\S+) (?P<unit>\S+) at (?P<scope>\w+) scope, valid from day (?P<valid_from>-?\d+) to day (?P<valid_to>-?\d+) inclusive; conversion (?P<conversion>\S+)\.$')),
 ('public1',re.compile(r'^Rule (?P<constraint_id>.+?)\. For entity (?P<entity>.+?), scope (?P<scope>\w+), (?P<parameter>\w+) is (?P<value>\S+) (?P<unit>\S+)\. Aggregation level: (?P<aggregation>\w+)\. Effective from day (?P<valid_from>-?\d+) to day (?P<valid_to>-?\d+), both inclusive\. Precedence (?P<precedence>-?\d+)\. Conversion: (?P<conversion>\S+)\.$')),
 ('hybrid_supplier0',re.compile(rf'^Agreement (?P<constraint_id>{TOKEN}): (?P<entity>{TOKEN}) has a (?P<parameter_words>.+?) term of (?P<value>{NUM}) (?P<unit>{TOKEN})\. Coverage: (?P<scope>{TOKEN}); accounting group: (?P<aggregation>{TOKEN}); effective days (?P<valid_from>-?\d+) to (?P<valid_to>-?\d+) inclusive\. Priority is (?P<precedence>-?\d+); conversion factor is (?P<conversion>none|{NUM})\.$')),
 ('hybrid_portfolio0',re.compile(rf'^The (?P<scope>{TOKEN}) agreement (?P<constraint_id>{TOKEN}) sets (?P<parameter_words>.+?) at (?P<value>{NUM}) (?P<unit>{TOKEN}) for (?P<entity>{TOKEN})\. Its accounting group is (?P<aggregation>{TOKEN})\. Priority (?P<precedence>-?\d+) applies throughout days (?P<valid_from>-?\d+) to (?P<valid_to>-?\d+) inclusive, with conversion (?P<conversion>none|{NUM})\.$')),
 ('hybrid_supplier1',re.compile(rf'^Between day (?P<valid_from>-?\d+) and day (?P<valid_to>-?\d+) inclusive, (?P<entity>{TOKEN})\x27s (?P<scope>{TOKEN}) agreement (?P<constraint_id>{TOKEN}) allows (?P<parameter_words>.+?) of (?P<value>{NUM}) (?P<unit>{TOKEN})\. Book the term at (?P<aggregation>{TOKEN}); apply precedence (?P<precedence>-?\d+) and conversion (?P<conversion>none|{NUM})\.$')),
 ('hybrid_portfolio1',re.compile(rf'^For (?P<entity>{TOKEN}), (?P<scope>{TOKEN}) agreement (?P<constraint_id>{TOKEN}) specifies (?P<value>{NUM}) (?P<unit>{TOKEN}) for (?P<parameter_words>.+?)\. The rule lasts from day (?P<valid_from>-?\d+) through day (?P<valid_to>-?\d+) inclusive\. Its priority is (?P<precedence>-?\d+), accounting group (?P<aggregation>{TOKEN}), and conversion factor (?P<conversion>none|{NUM})\.$')),
]
PARAMETERS={'pack','moq','aggregate_moq','capacity','lead_time','unit_cost','fixed_cost','budget','eligibility','conversion','storage'}


def inverse(document):
    if set(document)!={'source_ref','text','authenticated','sha256'} or document['authenticated'] is not True or report.digest(document['text'])!=document['sha256']:raise ValueError('Observed source authentication/schema/text digest mismatch')
    matches=[(name,match) for name,pattern in PATTERNS if (match:=pattern.fullmatch(document['text']))]
    if len(matches)!=1:raise ValueError('No unique independent registered grammar inverse')
    name,match=matches[0];raw=match.groupdict();word=raw.pop('parameter_words',None)
    if word is not None:raw['parameter']=word.replace(' ','_')
    if raw['parameter'] not in PARAMETERS:raise ValueError('Source parameter is outside registered corpus')
    literal_span=raw['value']+' '+raw['unit']
    raw['value']=float(raw['value']);raw['conversion']=None if raw['conversion']=='none' else float(raw['conversion'])
    for field in ['valid_from','valid_to','precedence']:raw[field]=int(raw[field])
    if not math.isfinite(raw['value']) or raw['conversion'] is not None and not math.isfinite(raw['conversion']):raise ValueError('Nonfinite source numeric field')
    raw['source_ref']=document['source_ref']
    # The known public grammar spells source scope and accounting fields directly.
    if 'supplier' in name and raw['scope']!='supplier' or 'portfolio' in name and raw['scope']!='portfolio':raise ValueError('Hybrid grammar form/scope mismatch')
    return {field:raw[field] for field in FIELDS},name,literal_span


def signature(rule):return report.canonical({field:rule[field] for field in FIELDS})


def active_rules(rules,day):
    chosen={};conflicts=[]
    for rule in rules:
        if not rule['valid_from']<=day<=rule['valid_to']:continue
        key=(rule['entity'],rule['parameter']);prior=chosen.get(key)
        if prior is None or rule['precedence']>prior['precedence']:chosen[key]=rule
        elif rule['precedence']==prior['precedence'] and any(rule[field]!=prior[field] for field in ['value','unit','conversion']):conflicts.append({'key':list(key),'left':prior,'right':rule})
    return list(chosen.values()),conflicts


def score_numeric_call(call,documents,semantic_attempt):
    request_payload=next(p for p in report.request_payloads(call['request']) if 'documents' in p)
    submitted=request_payload['documents'];expected={d['source_ref']:inverse(d) for d in submitted}
    try:
        choice=call['response']['choices'][0]
        if choice.get('finish_reason')=='length':raise ValueError('Truncated model output')
        raw=json.loads(choice['message']['content'])
        if not isinstance(raw,dict) or not isinstance(raw.get('constraints'),list):raise ValueError('Invalid structured extraction response')
    except (ValueError,KeyError,IndexError,TypeError) as exc:
        return {'semantic_attempt':semantic_attempt,'submitted_terms':len(submitted),'returned_terms':0,'exact_numeric_terms':0,'false_numeric_terms':0,'omitted_terms':len(expected),'omitted_source_refs':sorted(expected),'complete_exact_numeric_batch':False,'response_invalid':True,'response_error':str(exc),'checks':[]}
    rows=raw['constraints']
    counter=Counter(row.get('source_ref') for row in rows);checks=[]
    for row in rows:
        source_ref=row.get('source_ref');source=expected.get(source_ref);errors=[]
        if source is None:errors.append('unknown_source_ref')
        else:
            truth,grammar,span=source
            if row.get('value')!=truth['value']:errors.append('value')
            if row.get('unit')!=truth['unit']:errors.append('unit')
            if row.get('value_quote')!=span or span not in documents[source_ref]['text']:errors.append('value_quote')
        if counter[source_ref]>1:errors.append('duplicate_source_ref')
        checks.append({'source_ref':source_ref,'exact_numeric_term':not errors,'errors':errors,'returned_value':row.get('value'),'returned_unit':row.get('unit'),'returned_quote':row.get('value_quote'),'source_numeric_term':({'value':source[0]['value'],'unit':source[0]['unit'],'literal_span':source[2]} if source else None)})
    omitted=sorted(set(expected)-set(counter));exact=sum(c['exact_numeric_term'] for c in checks)
    valid_batch=not raw.get('issues') and not omitted and len(checks)==len(expected) and exact==len(expected)
    return {'semantic_attempt':semantic_attempt,'compact_model_fields':['source_ref','value','unit','value_quote'],'tool_metadata_fields':[f for f in FIELDS if f not in {'source_ref','value','unit'}],'submitted_terms':len(submitted),'returned_terms':len(rows),'exact_numeric_terms':exact,'false_numeric_terms':len(rows)-exact,'omitted_terms':len(omitted),'omitted_source_refs':omitted,'complete_exact_numeric_batch':valid_batch,'model_issues':raw.get('issues',[]),'checks':checks}


def score_recovery_selection(call):
    """Score model tool choice from its recorded observable request only."""
    payload=next(p for p in report.request_payloads(call['request']) if 'allowed_tools' in p)
    required={'stock_movement_balance','inventory_distribution_shift'}
    failures={a['name'] for a in payload['anomalies'] if a.get('outcome')=='hard_fail'}
    day=payload['decision_day'];stages=payload['stage_days']
    complete=payload.get('source_inventory_complete') is True
    current=all(stages.get(stage)==day for stage in ['inventory','sales','products'])
    anomalies_present=required<=failures
    expected='reconcile_current_inventory' if anomalies_present and complete and current else 'hold'
    errors=[];raw={}
    try:
        choice=call['response']['choices'][0]
        if choice.get('finish_reason')=='length':raise ValueError('Truncated response')
        raw=json.loads(choice['message']['content'])
        if not isinstance(raw,dict) or not isinstance(raw.get('evidence_refs'),list):raise ValueError('Invalid selector schema')
    except (ValueError,KeyError,IndexError,TypeError):errors.append('invalid_structured_response')
    requested=raw.get('requested_tool');refs=raw.get('evidence_refs',[])
    if requested!=expected:errors.append('requested_tool_does_not_follow_observable_conditions')
    if not refs or any(not isinstance(ref,str) or ref not in failures for ref in refs):errors.append('missing_or_unallowlisted_anomaly_evidence')
    if requested=='reconcile_current_inventory' and not required<=set(ref for ref in refs if isinstance(ref,str)):errors.append('both_required_anomalies_not_cited')
    return {'expected_tool':expected,'requested_tool':requested,'evidence_refs':refs,'observed_hard_fail_checks':sorted(failures),'both_required_anomalies_present':anomalies_present,'source_inventory_complete':complete,'required_source_stages_current':current,'source_stage_dates':stages,'decision_day':day,'instruction_compliant':not errors,'semantic_errors':errors,'denominator':'Fresh physical selector responses; distinct from extraction terms and client/schema errors.','truth_access':'Recorded observable request fields only; no evaluator or clean state.'}


def verify_recovery(trace,reader,gate):
    recovery=trace.get('recovery')
    if not recovery:return None
    from ega.config import GateConfig
    from ega.schemas import Snapshot
    from ega.quality import certify
    observed=reader.load(trace['references']['observe']);revised=reader.load(trace['references']['reconciled_snapshot'])
    before={r['series_id']:r for r in observed['inventory']};after={r['series_id']:r for r in revised['inventory']};day=observed['lineage']['day']
    problems=[];rows=[]
    if set(before)!=set(after) or len(before)!=len(observed['inventory']) or len(after)!=len(revised['inventory']):problems.append('inventory_identity_changed_or_duplicate')
    for sid,row in before.items():
        final=after[sid];source=row.get('source_quantity');ledger=observed['expected_inventory'].get(sid)
        agreed=source is not None and ledger is not None and math.isfinite(source) and math.isfinite(ledger) and abs(source-ledger)<=1e-8
        rows.append({'series_id':sid,'quantity_before':row['quantity'],'quantity_after':final['quantity'],'source_quantity':source,'ledger_expected':ledger,'source_ledger_agreement':agreed,'changed':row['quantity']!=final['quantity']})
        if recovery.get('applied') and (not agreed or final['quantity']!=source):problems.append('quantity_not_proved_by_source_and_ledger:'+sid)
    cleaned_before=json.loads(report.canonical(observed));cleaned_after=json.loads(report.canonical(revised))
    if recovery.get('applied'):
        for value in [cleaned_before,cleaned_after]:
            value['lineage'].pop('certificate_hash',None);value['lineage'].pop('snapshot_version',None)
            for row in value['inventory']:row.pop('quantity',None)
        if cleaned_before!=cleaned_after:problems.append('fields_other_than_derived_quantity_and_lineage_changed')
        if any(observed['stage_days'].get(stage)!=day for stage in ['inventory','sales','products']):problems.append('required_source_stage_not_current')
    elif observed!=revised:problems.append('refused_or_inapplicable_recovery_changed_observation')
    before_cert=certify(Snapshot.model_validate(observed),GateConfig.model_validate(gate)).model_dump(mode='json')
    after_cert=certify(Snapshot.model_validate(revised),GateConfig.model_validate(gate)).model_dump(mode='json')
    if before_cert!=recovery['certificate_before']:problems.append('recorded_before_certificate_not_recomputed')
    if after_cert!=recovery['certificate_after'] or after_cert!=reader.load(trace['references']['certify_state']):problems.append('recorded_after_certificate_not_recomputed')
    if report.digest(observed)!=recovery['before_snapshot_hash'] or report.digest(revised)!=recovery['after_snapshot_hash']:problems.append('recovery_snapshot_hashes_differ')
    if recovery.get('applied'):
        checks={c['name']:c['outcome'] for c in before_cert['checks']}
        if any(checks.get(name)!='hard_fail' for name in ['stock_movement_balance','inventory_distribution_shift']):problems.append('required_observable_recovery_anomalies_absent')
    return {'status':recovery['status'],'applied':recovery['applied'],'problems':sorted(set(problems)),'only_permitted_fields_changed':not any('fields_other_than' in x for x in problems),'changed_quantities':sum(r['changed'] for r in rows),'all_sources_match_ledgers':all(r['source_ledger_agreement'] for r in rows),'certification_recomputed_exact':not any('certificate_not_recomputed' in x for x in problems),'hard_fail_before':any(c['outcome']=='hard_fail' for c in before_cert['checks']),'hard_fail_after':any(c['outcome']=='hard_fail' for c in after_cert['checks']),'source_stage_dates':observed['stage_days'],'decision_day':day,'rows':rows,'truth_access':'Observed input, recorded reconciliation output and recertification only. No clean snapshot, post-decision true problem or oracle enters this recovery assessment.'}


def assess(data_path,output):
    data=report.load_json(data_path);inventory={str(Path(data_path).resolve()):{'sha256':report.sha(data_path),'bytes':Path(data_path).stat().st_size}}
    protocol=data['protocol'];proof_by_run={(p['arm'],p['run']):p for p in data['run_proofs']};config_by_arm={s['label']:s['config'] for s in data['stages']}
    cases=[];physical_calls=[];selector_calls=[];recoveries=[];seen_calls=set();counts=defaultdict(Counter)
    events_by_decision=defaultdict(list)
    for event in data['v2_events']:events_by_decision[(event['arm'],event['decision_id'])].append(event)
    for row in data['traces']:
        arm=row['arm'];reader=report.VerifiedReader(proof_by_run[(arm,row['run'])]['path'],inventory);trace=reader.load(row['trace_ref'])
        documents=reader.load(trace['references']['source_documents']);docs={d['source_ref']:d for d in documents}
        inverses=[inverse(d) for d in documents];expected,source_conflicts=active_rules([item[0] for item in inverses],row['day']);expected_set={signature(c) for c in expected}
        actual_ref=trace['references'].get('ground_constraints');counts[arm]['decisions']+=1;counts[arm]['available_source_exposures']+=len(documents)
        if actual_ref:
            actual=reader.load(actual_ref);observed_list=[signature(c) for c in actual['constraints']];actual_set=set(observed_list);exact=expected_set&actual_set;false=actual_set-expected_set;omitted=expected_set-actual_set
            scored={'arm':arm,'run':row['run'],'day':row['day'],'trace_ref':row['trace_ref'],'sources':len(documents),'independently_parsed_sources':len(inverses),'expected_active_rules':len(expected_set),'recorded_active_rules':len(actual_set),'exact_active_rules':len(exact),'false_active_rules':len(false),'omitted_active_rules':len(omitted),'duplicate_recorded_rules':len(observed_list)-len(actual_set),'whole_active_set_exact':expected_set==actual_set and len(observed_list)==len(actual_set),'source_equal_precedence_conflicts':source_conflicts,'pipeline_issues':actual['issues'],'eligible_complete_source_set':not actual['issues'] and expected_set==actual_set and not source_conflicts,'tuple_fields':FIELDS,'expected_active_rule_refs':sorted(c['source_ref'] for c in expected),'actual_active_rule_refs':sorted(c['source_ref'] for c in actual['constraints'])}
            cases.append(scored)
            for key in ['sources','expected_active_rules','recorded_active_rules','exact_active_rules','false_active_rules','omitted_active_rules','duplicate_recorded_rules']:counts[arm][key]+=scored[key]
            counts[arm]['grounding_decisions']+=1;counts[arm]['whole_active_set_exact_decisions']+=scored['whole_active_set_exact'];counts[arm]['eligible_complete_source_set_decisions']+=scored['eligible_complete_source_set']
        else:counts[arm]['state_gated_unattempted_decisions']+=1;counts[arm]['state_gated_unattempted_source_exposures']+=len(documents)
        validations={ref:e for e in events_by_decision[(arm,row['decision_id'])] if e['mechanism']=='grounding_v2_validation' for ref in e['artifact'].get('llm_refs',[])}
        for ref in trace['llm']['artifacts']:
            call=reader.load(ref)
            if call.get('kind')!='llm_call':continue
            selector_payloads=[p for p in report.request_payloads(call['request']) if 'allowed_tools' in p]
            if selector_payloads:
                if ref in seen_calls:raise ValueError('Physical selector call duplicated across traces')
                seen_calls.add(ref);selection=score_recovery_selection(call)
                selector_calls.append({'arm':arm,'run':row['run'],'day':row['day'],'artifact_ref':ref,**selection})
                counts[arm]['physical_selector_calls']+=1;counts[arm]['instruction_compliant_selector_calls']+=selection['instruction_compliant'];counts[arm]['selector_semantic_error_calls']+=not selection['instruction_compliant']
                continue
            payloads=[p for p in report.request_payloads(call['request']) if p.get('documents')]
            if not payloads:continue  # Recovery selector is a different measured task.
            if ref in seen_calls:raise ValueError('Physical extraction call duplicated across traces')
            seen_calls.add(ref);payload=payloads[0]
            semantic_attempt='repair' if 'validation_errors' in payload or 'correction_task' in payload else 'initial'
            score=score_numeric_call(call,docs,semantic_attempt);validation=validations.get(ref);accepted=validation['artifact']['accepted'] if validation else None
            if accepted is True and not score['complete_exact_numeric_batch']:raise ValueError('Production accepted a numerically incorrect model batch')
            physical_calls.append({'arm':arm,'run':row['run'],'day':row['day'],'artifact_ref':ref,'request_sha256':report.digest(call['request']),'response_sha256':report.digest(call['response']),'pipeline_validation_accepted':accepted,**score})
            for key in ['submitted_terms','returned_terms','exact_numeric_terms','false_numeric_terms','omitted_terms']:counts[arm][key]+=score[key]
            counts[arm]['physical_extraction_calls']+=1;counts[arm][semantic_attempt+'_extraction_calls']+=1
            counts[arm][semantic_attempt+'_exact_batches']+=score['complete_exact_numeric_batch']
        recovery=verify_recovery(trace,reader,config_by_arm[arm]['gate'])
        if recovery:
            recoveries.append({'arm':arm,'run':row['run'],'day':row['day'],'trace_ref':row['trace_ref'],**recovery});counts[arm]['recovery_tool_invocations']+=1;counts[arm]['recovery_applied']+=recovery['applied'];counts[arm]['recovery_audit_problem_cases']+=bool(recovery['problems']);counts[arm]['recovery_derived_quantities_changed']+=recovery['changed_quantities']
    aggregate=[]
    for arm,count in counts.items():
        r={'arm':arm,**dict(count)}
        r['active_rule_precision']=count['exact_active_rules']/count['recorded_active_rules'] if count['recorded_active_rules'] else None
        r['active_rule_recall']=count['exact_active_rules']/count['expected_active_rules'] if count['expected_active_rules'] else None
        r['model_numeric_term_precision']=count['exact_numeric_terms']/count['returned_terms'] if count['returned_terms'] else None
        r['model_numeric_term_recall']=count['exact_numeric_terms']/count['submitted_terms'] if count['submitted_terms'] else None
        aggregate.append(r)
    result={'format':'m5-v2-post-decision-independent-assessment-v2','generated_at_local':datetime.now(ZoneInfo('Europe/Paris')).isoformat(timespec='seconds'),'source_report_data_sha256':report.sha(data_path),'helper_sha256':report.sha(__file__),'scope_status':data['status'],'method':'Independent literal regex inverse for two public and four hybrid renderings; explicit validity/precedence resolver; twelve-field recorded active-rule comparison. Model-only accuracy uses unique current physical extraction responses and four compact head fields; trusted metadata and cached reuses are not new model trials. Selector instruction compliance is assessed separately from both required observable anomalies, complete current feeds and allowlisted citations. Recovery uses only recorded observable inputs and recertification.','limitations':['Controlled grammars are fully disclosed and also recognized by the capable parser. This is not natural-language corpus validation or evidence of broad semantic understanding.','Day/document exposures, wording variants and cache hits are correlated; no significance or power claim.','Recovery source/ledger values are simulated observed evidence; freshness uses table dates rather than separately authenticated row timestamps.'], 'aggregates':aggregate,'grounding_cases':cases,'physical_extraction_calls':physical_calls,'physical_selector_calls':selector_calls,'recovery_cases':recoveries,'input_hashes':inventory}
    report.atomic_json(output,result);print(json.dumps({'output':str(output),'aggregates':aggregate,'physical_extraction_calls':len(physical_calls),'physical_selector_calls':len(selector_calls),'grounding_cases':len(cases),'recovery_cases':len(recoveries)},indent=2));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',required=True,type=Path);p.add_argument('--output',required=True,type=Path);args=p.parse_args();assess(args.data,args.output)
