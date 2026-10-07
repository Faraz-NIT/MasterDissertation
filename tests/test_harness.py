import json

import pytest
from pydantic import ValidationError

from ega.cli import main
from ega.evaluation.faithfulness import replay
from ega.evaluation.harness import HarnessSuite, default_suite, load_suite, run_harness, summarize
from ega.store import ArtifactStore
from ega.util import atomic_json


def test_frozen_suite_detects_unsafe_permissions_and_replays(tmp_path):
    suite = default_suite()
    report = run_harness(suite, tmp_path / 'run')
    results = {(row['policy'], row['case_id']): row for row in report['cases']}
    summaries = {row['policy']: row for row in report['summary']}
    assert not report['passed']  # The ungated baseline must visibly fail safety expectations.
    assert summaries['D1']['passed'] == len(suite.cases)
    assert summaries['D1']['unsafe_executions'] == 0
    assert summaries['D1']['unnecessary_holds'] == 0
    assert summaries['D0']['unsafe_executions'] == 3
    assert summaries['D0']['permitted_constraint_violations'] == 1
    assert all(row['trace_valid'] and row['llm_calls'] == 0 for row in report['cases'])
    assert results['D0', 'stale_inventory']['actual_outcome'] == 'execute'
    assert results['D1', 'stale_inventory']['actual_outcome'] == 'hold'
    assert results['D1', 'infeasible_order']['actual_outcome'] == 'escalate'
    assert results['D1', 'infeasible_order']['constraint_violations'] == ['pack_integrality']
    assert results['D1', 'autonomy_cap']['constraint_violations'] == []
    assert results['D1', 'autonomy_cap']['actual_outcome'] == 'escalate'
    assert results['D1', 'valid_evidence']['proposed_order_units'] >= 2
    assert summaries['D1']['grounding_precision'] == 1

    clean = replay(tmp_path / 'run' / 'D1__valid_evidence')
    assert clean['action_matches'] and clean['problem_reconstruction_matches']
    held = replay(tmp_path / 'run' / 'D1__missing_forecast')
    assert held['held'] and held['action_matches']
    injected = replay(tmp_path / 'run' / 'D1__infeasible_order')
    assert injected['action_matches'] and injected['problem_reconstruction_matches']
    assert injected['independent_violations'] == ['pack_integrality']
    assert injected['action_source'].startswith('frozen harness proposal')

    run = tmp_path / 'run' / 'D1__valid_evidence'
    store = ArtifactStore(run / 'artifacts')
    try:
        row = results['D1', 'valid_evidence']
        trace = store.get(row['trace_ref'])
        documents = store.get(trace['references']['source_documents'])
        assert all('expected' not in document for document in documents)
        assert 'expected' not in store.get(trace['references']['observe'])
        assert trace['execution'] is None and trace['outcome'] is None
        assert store.db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0] == 0
    finally:
        store.close()


def test_frozen_suite_roundtrip_and_deterministic_decisions(tmp_path):
    suite = default_suite()
    atomic_json(tmp_path / 'suite.json', suite)
    loaded = load_suite(tmp_path / 'suite.json')
    first = run_harness(suite, tmp_path / 'first', policies=['D1'],
                        case_ids=['valid_evidence', 'infeasible_order'])
    second = run_harness(loaded, tmp_path / 'second', policies=['D1'],
                         case_ids=['valid_evidence', 'infeasible_order'])
    assert first['suite_hash'] == second['suite_hash']
    assert first['summary'] == second['summary']
    for one, two in zip(first['cases'], second['cases']):
        assert one['actual_outcome'] == two['actual_outcome']
        assert one['proposed_order_units'] == two['proposed_order_units']
        assert one['constraint_violations'] == two['constraint_violations']
    assert loaded == suite


@pytest.mark.parametrize('change', ['duplicate', 'unsafe_id', 'shape', 'future', 'nan', 'live', 'extra', 'truth'])
def test_invalid_suites_rejected_before_running(change):
    obj = default_suite().model_dump()
    if change == 'duplicate':
        obj['cases'].append(obj['cases'][0])
    elif change == 'unsafe_id':
        obj['cases'][0]['case_id'] = '../escape'
    elif change == 'shape':
        obj['cases'][0]['forecast']['samples'] = [[[1.]]]
    elif change == 'future':
        obj['cases'][0]['forecast']['training_end'] = 140
    elif change == 'nan':
        obj['cases'][0]['forecast']['samples'][0][0][0] = float('nan')
    elif change == 'live':
        obj['config']['llm']['enabled'] = True
        obj['config']['llm']['model'] = 'not-called'
    elif change == 'extra':
        obj['cases'][0]['expected']['unexpected_label'] = True
    elif change == 'truth':
        obj['cases'][0]['expected']['constraints'][0]['unit'] = 'USD'
    with pytest.raises(ValidationError):
        HarnessSuite.model_validate(obj)


def test_filters_and_output_protection(tmp_path):
    suite = default_suite()
    for options in [{'policies': ['B10']}, {'policies': []}, {'case_ids': ['unknown']},
                    {'case_ids': []}, {'policies': ['D1', 'D1']}]:
        with pytest.raises(ValueError):
            run_harness(suite, tmp_path / 'invalid', **options)
    assert not (tmp_path / 'invalid').exists()
    output = tmp_path / 'occupied'
    output.mkdir()
    (output / 'keep.txt').write_text('user data')
    with pytest.raises(FileExistsError):
        run_harness(suite, output)
    assert (output / 'keep.txt').read_text() == 'user data'


def test_cli_exports_suite_and_returns_failure_for_baseline(tmp_path):
    path = tmp_path / 'suite.json'
    assert main(['harness-suite', '--out', str(path)]) == 0
    assert main(['harness-suite', '--out', str(path)]) == 2
    assert main(['harness', '--suite', str(path), '--output', str(tmp_path / 'd1'),
                 '--policies', 'D1']) == 0
    assert main(['harness', '--output', str(tmp_path / 'd0'), '--policies', 'D0',
                 '--cases', 'infeasible_order']) == 1
    result = json.loads((tmp_path / 'd0' / 'results.json').read_text())
    assert result['summary'][0]['unsafe_executions'] == 1


def test_case_error_is_recorded_and_other_cases_continue(tmp_path, monkeypatch):
    from ega.agents.orchestrator import OrchestratorAutonomyAgent

    original = OrchestratorAutonomyAgent.run

    def fail_one(self, snapshot, documents, decision_id, seed):
        if decision_id.endswith('missing_forecast'):
            raise RuntimeError('Controlled tool failure')
        return original(self, snapshot, documents, decision_id, seed)

    monkeypatch.setattr(OrchestratorAutonomyAgent, 'run', fail_one)
    result = run_harness(default_suite(), tmp_path / 'run', policies=['D1'],
                         case_ids=['missing_forecast', 'infeasible_order'])
    rows = {row['case_id']: row for row in result['cases']}
    assert not result['passed']
    assert rows['missing_forecast']['actual_outcome'] == 'error'
    assert rows['infeasible_order']['passed']
    assert result['summary'][0]['runtime_errors'] == 1
    assert result['summary'][0]['unsafe_cases'] == 1
    store = ArtifactStore(tmp_path / 'run' / 'D1__missing_forecast' / 'artifacts')
    try:
        assert store.get(rows['missing_forecast']['error_ref'])['message'] == 'Controlled tool failure'
        assert store.verify_chain()
    finally:
        store.close()


def test_unsafe_rate_includes_violations_on_execute_labeled_cases():
    violating = {
        'policy': 'D0', 'passed': False, 'actual_outcome': 'execute',
        'expected_outcome': 'execute', 'unsafe_execution': True, 'unnecessary_hold': False,
        'constraint_violations': ['pack_integrality'], 'grounding': None,
        'trace_completeness': 1., 'trace_valid': True,
    }
    blocked = {**violating, 'passed': True, 'actual_outcome': 'hold',
               'expected_outcome': 'hold', 'unsafe_execution': False, 'constraint_violations': []}
    result = summarize([violating, violating, violating, blocked])[0]
    assert result['unsafe_executions'] == 3
    assert result['unsafe_execution_rate'] == 0.75
