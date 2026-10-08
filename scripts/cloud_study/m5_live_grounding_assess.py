#!/usr/bin/env python3
"""Read-only, hash-verified post-hoc grounding assessment of captured requests.

Truth is reconstructed only for documents actually submitted to an Extraction
request. The inverse must exactly re-render both public prose phrasings and
reproduce the original text digest. Later unprocessed documents are coverage
gaps, never conditional extraction omissions. No model is called or recalled.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

from ega.agents.llm import Extraction
from ega.config import ExperimentConfig
from ega.constraints import render_prose
from ega.evaluation.grounding import FIELDS, signature
from ega.schemas import Constraint
from ega.util import atomic_json, digest

REPO = Path('/workspace/MasterDissertation')
GENERATOR = REPO / 'results/report/generate_report.py'
DEFAULT_STAGE = REPO / 'results/six_hour_agentic_prose'
DEFAULT_OUTPUT = REPO / 'results/report/six_hour_live_grounding_assessment.json'
NUMBER = r'[^\s]+'
V0 = re.compile(r'^Contract clause (?P<cid>.+?) \(precedence (?P<precedence>-?\d+), aggregation (?P<aggregation>\w+)\): (?P<entity>.+?) must comply with (?P<parameter>\w+) = (?P<value>\S+) (?P<unit>\S+) at (?P<scope>\w+) scope, valid from day (?P<start>-?\d+) to day (?P<end>-?\d+) inclusive; conversion (?P<conversion>\S+)\.$')
V1 = re.compile(r'^Rule (?P<cid>.+?)\. For entity (?P<entity>.+?), scope (?P<scope>\w+), (?P<parameter>\w+) is (?P<value>\S+) (?P<unit>\S+)\. Aggregation level: (?P<aggregation>\w+)\. Effective from day (?P<start>-?\d+) to day (?P<end>-?\d+), both inclusive\. Precedence (?P<precedence>-?\d+)\. Conversion: (?P<conversion>\S+)\.$')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strict_inverse(document, available=None):
    """Assign a typed rule only after full grammar, source and hash roundtrip."""
    required = {'source_ref', 'text', 'authenticated', 'sha256'}
    if set(document) != required or not isinstance(document['text'], str):
        raise ValueError('Submitted source payload is outside the public four-field document schema')
    if document['authenticated'] is not True:
        raise ValueError('Submitted source is not authenticated')
    if not isinstance(document['source_ref'], str) or not document['source_ref']:
        raise ValueError('Submitted source reference is absent')
    if digest(document['text']) != document['sha256']:
        raise ValueError('Submitted source text digest differs from payload')
    if available is not None and available.get(document['source_ref']) != document:
        raise ValueError('Submitted source payload differs from the captured available document')
    matches = [(variant, pattern.fullmatch(document['text'])) for variant, pattern in [(0, V0), (1, V1)]]
    matches = [(variant, match) for variant, match in matches if match]
    if len(matches) != 1:
        raise ValueError('Submitted source has no unique exact public render_prose grammar match')
    variant, match = matches[0]
    fields = match.groupdict()
    value = float(fields['value'])
    conversion = None if fields['conversion'] == 'none' else float(fields['conversion'])
    if not math.isfinite(value) or conversion is not None and not math.isfinite(conversion):
        raise ValueError('Nonfinite numeric source cannot be assigned an exact tuple')
    rule = Constraint(constraint_id=fields['cid'], entity=fields['entity'], scope=fields['scope'],
                      parameter=fields['parameter'], value=value, unit=fields['unit'], conversion=conversion,
                      aggregation=fields['aggregation'], valid_from=int(fields['start']), valid_to=int(fields['end']),
                      precedence=int(fields['precedence']), source_ref=document['source_ref'],
                      confidence=1., provenance='authenticated_source')
    reproduced = render_prose([rule], variant=variant)[0].payload()
    if reproduced != document:
        raise ValueError('Inverse rule does not exactly reproduce source text, reference, authentication and digest')
    return rule, variant


def extraction_payload(request):
    candidates = []
    for message in request.get('messages', []):
        if message.get('role') != 'user':
            continue
        try:
            value = json.loads(message['content'])
        except (ValueError, TypeError, KeyError):
            continue
        if isinstance(value, dict) and isinstance(value.get('documents'), list):
            candidates.append(value)
    if len(candidates) != 1:
        raise ValueError('No unique captured document payload in the extraction request')
    return candidates[0]


def score_response(documents, response, available=None):
    expected_rules, exclusions = [], []
    for index, document in enumerate(documents):
        try:
            rule, variant = strict_inverse(document, available)
            expected_rules.append(rule)
        except (ValueError, TypeError, KeyError) as exc:
            exclusions.append({'document_index': index, 'source_ref': document.get('source_ref') if isinstance(document, dict) else None, 'reason': str(exc)})
    expected = {signature(rule.model_dump()) for rule in expected_rules}
    expected_by_ref = {rule.source_ref: rule for rule in expected_rules}
    excluded_refs = {item['source_ref'] for item in exclusions}
    parsed, response_error = None, None
    try:
        choice = response['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise ValueError('Response was explicitly truncated')
        if choice.get('message', {}).get('refusal'):
            raise ValueError('Response explicitly refused extraction')
        parsed = Extraction.model_validate(json.loads(choice['message']['content']))
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        response_error = str(exc)
    result = {'submitted_document_exposures': len(documents), 'truth_proven_document_exposures': len(expected_rules),
              'excluded_unproven_document_exposures': len(exclusions), 'truth_exclusions': exclusions,
              'expected_unique_tuples': len(expected), 'duplicate_input_tuples': len(expected_rules) - len(expected),
              'schema_valid_response': parsed is not None, 'response_exclusion_reason': response_error,
              'comparison_fields': FIELDS, 'source_inverse_roundtrip_exact': not exclusions,
              'returned_rules': None, 'returned_unique_tuples': None, 'exact_tuples': None,
              'false_tuples': None, 'omitted_submitted_tuples': None, 'tuple_precision': None, 'tuple_recall': None}
    if parsed is None:
        result['expected_tuples_excluded_due_to_invalid_response'] = len(expected)
        return result
    # Truth-unproven source rules are excluded rather than declared false. A
    # genuinely extra source reference remains an unsupported false tuple.
    eligible_actual = [rule for rule in parsed.constraints if rule.source_ref not in excluded_refs]
    counts = Counter(signature(rule.model_dump()) for rule in eligible_actual)
    actual = set(counts)
    exact, false, omitted = expected & actual, actual - expected, expected - actual
    mismatches = Counter()
    mismatch_rows = []
    unknown_sources = []
    actual_by_ref = Counter(rule.source_ref for rule in eligible_actual)
    for rule in eligible_actual:
        original = expected_by_ref.get(rule.source_ref)
        if original is None:
            unknown_sources.append(rule.model_dump(mode='json'))
            continue
        wrong = [field for field in FIELDS if getattr(rule, field) != getattr(original, field)]
        if wrong:
            mismatches.update(wrong)
            mismatch_rows.append({'source_ref': rule.source_ref, 'mismatched_fields': wrong,
                                  'expected_fields': {field: getattr(original, field) for field in wrong},
                                  'actual_fields': {field: getattr(rule, field) for field in wrong}})
    result.update(returned_rules=len(parsed.constraints), eligible_returned_rule_occurrences=len(eligible_actual),
                  returned_rules_excluded_due_to_unproven_source=len(parsed.constraints) - len(eligible_actual),
                  returned_unique_tuples=len(actual), exact_tuples=len(exact), false_tuples=len(false),
                  omitted_submitted_tuples=len(omitted), tuple_precision=len(exact) / len(actual) if actual else None,
                  tuple_recall=len(exact) / len(expected) if expected else None,
                  whole_submitted_set_exact=actual == expected,
                  duplicate_returned_rule_occurrences=sum(count - 1 for count in counts.values()),
                  unknown_extra_source_rule_occurrences=len(unknown_sources),
                  unknown_extra_source_rules=unknown_sources,
                  additional_rules_for_known_sources=sum(max(0, count - 1) for ref, count in actual_by_ref.items() if ref in expected_by_ref),
                  field_mismatch_counts={field: mismatches[field] for field in FIELDS}, field_mismatches=mismatch_rows,
                  model_issues=parsed.issues)
    return result


def report_reader():
    spec = importlib.util.spec_from_file_location('m5_grounding_verified_report_reader', GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # __main__ is intentionally never invoked.
    return module


def verify_chain(run, expected_packing):
    database = run / 'artifacts/audit.sqlite'
    wal = database.with_name(database.name + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Completed run has a nonempty SQLite WAL; read-only chain proof is unavailable')
    previous, count = '0' * 64, 0
    with sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        for decision, stage, payload, recorded_previous, recorded_hash in connection.execute(
                'SELECT decision_id,stage,payload,previous_hash,event_hash FROM events ORDER BY seq'):
            event = {'decision_id': decision, 'stage': stage, 'payload': json.loads(payload), 'previous_hash': previous}
            if recorded_previous != previous or digest(event) != recorded_hash:
                raise ValueError('Actual SQLite audit chain failed')
            previous, count = recorded_hash, count + 1
    if expected_packing:
        if previous != expected_packing['chain_terminal_hash'] or count != expected_packing['event_count']:
            raise ValueError('Current SQLite chain differs from verified packing provenance')
    return {'valid': True, 'events': count, 'terminal_hash': previous, 'audit_sqlite_sha256': sha(database)}


def assess(stage):
    module = report_reader()
    cfg = ExperimentConfig.model_validate(json.loads((stage / 'resolved_config.json').read_text()))
    merged = json.loads((stage / 'merge_manifest.json').read_text())
    expected = {(p, s, seed, origin) for p in cfg.policies for s in cfg.scenarios for seed in cfg.seeds for origin in range(cfg.origins)}
    if not merged.get('complete') or merged.get('config_sha256') != digest(cfg) or merged.get('runs_expected') != len(expected):
        raise ValueError('Complete frozen merge/configuration proof is absent or inconsistent')
    from m5_parallel import validate_run
    cases, calls, errors, run_proofs = [], [], [], []
    found, all_attempts = set(), {}
    for run in sorted(stage.glob('*__*__seed*__origin*')):
        manifest = json.loads((run / 'run_manifest.json').read_text())
        run_cfg = ExperimentConfig.model_validate(manifest['config'])
        a, b = run_cfg.model_dump(mode='json'), cfg.model_dump(mode='json')
        for key in ('output', 'seeds'):
            a.pop(key); b.pop(key)
        if a != b or not set(run_cfg.seeds) <= set(cfg.seeds):
            raise ValueError('Run configuration is outside the frozen merged study')
        identity, summary = validate_run(run, run_cfg)
        if identity not in expected or identity in found:
            raise ValueError('Unexpected or duplicate completed run identity')
        found.add(identity)
        reader = module.PackedArtifactReader(run)
        index = json.loads((run / 'trace_index.json').read_text())
        chain = verify_chain(run, reader.manifest.get('provenance') if reader.manifest else None)
        run_proofs.append({'run': str(run), 'identity': list(identity), 'trace_count': len(index),
                           'packing': reader.summary(), 'chain': chain,
                           'summary_sha256': sha(run / 'summary.json'), 'run_manifest_sha256': sha(run / 'run_manifest.json'),
                           'trace_index_sha256': sha(run / 'trace_index.json')})
        for entry in index:
            trace = reader.load(entry['trace_ref'])
            references = trace.get('llm', {}).get('artifacts', [])
            if not references and identity[0] not in ('B9', 'B10'):
                continue
            available_documents = reader.load(trace['references']['source_documents'])
            available = {document['source_ref']: document for document in available_documents}
            if len(available) != len(available_documents):
                raise ValueError('Available source references are duplicated')
            attempted_refs, day_calls = set(), []
            for reference in references:
                artifact = reader.load(reference)
                kind = artifact.get('kind')
                if kind not in ('llm_call', 'llm_error'):
                    raise ValueError('LLM trace references an unrecognized call artifact')
                attempt_key = (str(run), entry['day'], artifact.get('role'), artifact.get('started_at_utc'),
                               artifact.get('attempt'), digest(artifact.get('request', {})))
                prior = all_attempts.setdefault(attempt_key, {'records': [], 'artifacts': [], 'role': artifact.get('role')})
                prior['records'].append(artifact); prior['artifacts'].append(reference)
                if kind == 'llm_error':
                    errors.append({'run': run.name, 'day': entry['day'], 'reference': reference,
                                   'role': artifact.get('role'), 'error': artifact.get('error')})
                # Score one captured request per actual attempt; a paired error
                # artifact must not double-count the same request/response.
                schema_name = artifact.get('request', {}).get('response_format', {}).get('json_schema', {}).get('name')
                if artifact.get('role') != 'supplier and constraint agent' or schema_name != 'Extraction':
                    continue
                if any(row['attempt_key'] == list(attempt_key) for row in day_calls):
                    continue
                payload = extraction_payload(artifact['request'])
                if len(payload.get('known_entities', [])) != 30:
                    raise ValueError('Captured extraction request does not contain the full 30-series catalog')
                documents = payload['documents']
                attempted_refs.update(document.get('source_ref') for document in documents)
                result = score_response(documents, artifact.get('response') or {}, available)
                result.update(attempt_key=list(attempt_key), artifact_ref=reference,
                              request_sha256=digest(artifact['request']), role=artifact['role'],
                              elapsed_seconds=artifact.get('elapsed_seconds'), actual_usage=(artifact.get('response') or {}).get('usage', {}),
                              source_refs=[document.get('source_ref') for document in documents],
                              known_entity_catalog_size=len(payload['known_entities']))
                calls.append(result); day_calls.append(result)
            if identity[0] in ('B9', 'B10'):
                unknown = attempted_refs - set(available)
                if unknown:
                    raise ValueError('Requested documents have references absent from captured available sources')
                reasons = trace.get('autonomy', {}).get('reasons', [])
                dimensional = [reason for reason in reasons if 'dimensional mismatch' in str(reason)]
                cases.append({'run': run.name, 'policy': identity[0], 'scenario': identity[1], 'seed': identity[2],
                              'origin': identity[3], 'day': entry['day'], 'available_source_documents': len(available),
                              'distinct_source_documents_submitted': len(attempted_refs),
                              'unprocessed_source_documents': len(set(available) - attempted_refs),
                              'attempted_document_coverage': len(attempted_refs) / len(available) if available else None,
                              'extraction_requests': len(day_calls), 'supplier_request_rows': day_calls,
                              'trace_ref': entry['trace_ref'], 'autonomy_level': trace.get('autonomy', {}).get('level'),
                              'permitted': trace.get('autonomy', {}).get('permitted'),
                              'recorded_dimensional_mismatch_reasons': dimensional,
                              'conditional_accuracy_status': 'captured_requests_scored' if day_calls else 'no_extraction_request; no conditional score',
                              'gate_quality': trace.get('autonomy', {}).get('inputs', {}).get('quality')})
    if found != expected or merged.get('runs_merged') != len(found):
        raise ValueError('Completed run grid differs from the frozen expected identities')
    requests, roles, usage_total, elapsed_total = [], Counter(), Counter(), 0.
    for attempt_key, item in all_attempts.items():
        complete = next((record for record in item['records'] if record.get('kind') == 'llm_call'), item['records'][0])
        response = complete.get('response') or {}
        usage = response.get('usage') or {}
        roles[item['role']] += 1
        for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            usage_total[field] += int(usage.get(field) or 0)
        elapsed_total += float(complete.get('elapsed_seconds') or 0)
        requests.append({'run': Path(attempt_key[0]).name, 'day': attempt_key[1], 'role': item['role'],
                         'artifact_refs': item['artifacts'], 'actual_usage': usage,
                         'elapsed_seconds': complete.get('elapsed_seconds'),
                         'has_error_record': any(record.get('kind') == 'llm_error' for record in item['records'])})
    eligible = [row for row in calls if row['schema_valid_response']]
    totals = Counter()
    for row in calls:
        for key in ('submitted_document_exposures', 'truth_proven_document_exposures', 'excluded_unproven_document_exposures'):
            totals[key] += row[key]
    for row in eligible:
        for key in ('expected_unique_tuples', 'returned_rules', 'returned_unique_tuples', 'exact_tuples', 'false_tuples',
                    'omitted_submitted_tuples', 'duplicate_returned_rule_occurrences', 'unknown_extra_source_rule_occurrences',
                    'additional_rules_for_known_sources'):
            totals[key] += row.get(key) or 0
    field_counts = Counter()
    for row in eligible:
        field_counts.update(row['field_mismatch_counts'])
    extraction_days = [case for case in cases if case['extraction_requests']]
    scores = dict(totals)
    scores.update(tuple_precision=totals['exact_tuples'] / totals['returned_unique_tuples'] if totals['returned_unique_tuples'] else None,
                  tuple_recall=totals['exact_tuples'] / totals['expected_unique_tuples'] if totals['expected_unique_tuples'] else None,
                  valid_response_requests=len(eligible), invalid_response_requests=len(calls) - len(eligible),
                  expected_tuples_excluded_due_to_invalid_response=sum(row.get('expected_tuples_excluded_due_to_invalid_response', 0) for row in calls),
                  field_mismatch_counts={field: field_counts[field] for field in FIELDS})
    return {'schema_version': 'm5-live-grounding-assessment-v1', 'complete': True, 'assessed_at_utc': datetime.now(timezone.utc).isoformat(),
            'stage': str(stage), 'model': cfg.llm.model, 'model_revision': cfg.llm.model_revision,
            'document_batch_size': cfg.llm.document_batch_size,
            'stage_validation': {'expected_runs': len(expected), 'validated_runs': len(found), 'exact_grid': True,
                                 'decision_days': len(expected) * cfg.days, 'all_selected_artifacts_hash_verified': True,
                                 'all_actual_sqlite_chains_valid': True, 'config_sha256': digest(cfg),
                                 'merge_manifest_sha256': sha(stage / 'merge_manifest.json')},
            'role_counts': dict(roles), 'llm_requests': len(requests), 'supplier_extraction_requests': len(calls),
            'llm_error_records': len(errors), 'actual_usage_totals': dict(usage_total), 'llm_elapsed_seconds': elapsed_total,
            'conditional_grounding': scores,
            'coverage': {'llm_decision_days': len(cases), 'extraction_decision_days': len(extraction_days),
                         'days_without_extraction_requests': len(cases) - len(extraction_days),
                         'available_document_exposures_on_extraction_days': sum(case['available_source_documents'] for case in extraction_days),
                         'distinct_submitted_document_exposures_on_extraction_days': sum(case['distinct_source_documents_submitted'] for case in extraction_days),
                         'unprocessed_document_exposures_on_extraction_days': sum(case['unprocessed_source_documents'] for case in extraction_days)},
            'decision_cases': cases, 'requests': requests, 'llm_errors': errors, 'run_integrity_proofs': run_proofs,
            'method': {'reader': str(GENERATOR) + ':PackedArtifactReader', 'reader_sha256': sha(GENERATOR),
                       'assessor_sha256': sha(__file__), 'comparison_fields': FIELDS,
                       'truth_rule': 'Captured documents only; strict inverse of public render_prose variants0/1, authenticated source, exact available-payload equality and exact re-render/text digest required.',
                       'tuple_rule': 'Original grounding.signature; excludes confidence, constraint_id and provenance. Unique tuple sets per actual request; duplicates separately counted.',
                       'field_pairing': 'Field mismatch comparison uses the identical submitted source_ref; extra source references are separate unsupported-source errors, not guessed field matches.',
                       'accuracy_denominator': 'Only hash/roundtrip-proven submitted documents with schema-valid responses. Unproven source labels and invalid responses are excluded with explicit counts.',
                       'coverage_rule': 'Later unprocessed documents are coverage gaps, not conditional extraction omissions.',
                       'limitations': ['Descriptive repeated request exposures; no independence, general natural-language accuracy, confidence interval, model recall or policy-benefit inference.',
                                       'Read-only post-hoc evaluator; no expected labels are sent to any model, no experiments or applications are modified.']}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, default=DEFAULT_STAGE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = assess(args.stage.resolve())
    atomic_json(args.output.resolve(), result)
    print(json.dumps({key: result[key] for key in ['complete', 'llm_requests', 'supplier_extraction_requests',
                                                  'role_counts', 'actual_usage_totals', 'conditional_grounding', 'coverage']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
