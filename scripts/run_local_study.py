"""Frozen, resumable local synthetic experiment; no remote model calls."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yaml
import httpx

from ega.config import ExperimentConfig, load_config
from ega.data.synthetic import make_demo
from ega.evaluation.faithfulness import replay, trace_audit, deletion_test
from ega.evaluation.grounding import make_corpus, evaluate_corpus
from ega.evaluation.metrics import paired_bootstrap, holm
from ega.evaluation.report import render_report
from ega.experiment import run_experiment, run_one, summarize_study
from ega.data.panel import Panel
from ega.forecasting.core import SeasonalForecaster
from ega.util import atomic_json, digest, environment


def operational_run(task):
    raw, policy, scenario, seed, origin = task
    cfg = ExperimentConfig.model_validate(raw)
    run = Path(cfg.output)/f'{policy}__{scenario}__seed{seed}__origin{origin}'
    if (run/'summary.json').exists():
        return json.loads((run/'summary.json').read_text())
    # Partial folders are handled by the existing sequential runner on resume.
    # run_one uses idempotent artifact insertion, but unfinished receipts must
    # never be reused for a new simulation.
    if run.exists():
        import shutil
        resolved = run.resolve()
        if resolved.parent != Path(cfg.output).resolve():
            raise ValueError('Partial run is outside the study directory')
        shutil.rmtree(resolved)
    panel = Panel.load(cfg.dataset)
    model = SeasonalForecaster(cfg.forecast).fit(
        panel, cfg.start_day + origin * cfg.origin_stride - cfg.warmup_days)
    return run_one(panel, cfg, policy, scenario, seed, origin, model, run)


def parallel_operations(cfg, workers):
    out = Path(cfg.output)
    out.mkdir(parents=True, exist_ok=True)
    wire = cfg.model_dump(mode='json')
    pinned = out/'resolved_config.json'
    if pinned.exists() and json.loads(pinned.read_text()) != wire:
        raise ValueError('Cannot resume changed operational settings')
    if not pinned.exists():
        atomic_json(pinned, wire)
    atomic_json(out/'environment.json', environment())
    tasks = [(wire, p, s, seed, origin) for origin in range(cfg.origins)
             for p in cfg.policies for s in cfg.scenarios for seed in cfg.seeds]
    rows = []
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(operational_run, task) for task in tasks]
        for future in as_completed(futures):
            rows.append(future.result())
            pd.DataFrame(rows).to_csv(out/'summary.csv', index=False)
            if len(rows) % 30 == 0:
                print(f'{out.name}: {len(rows)}/{len(tasks)} runs complete', flush=True)
    summarize_study(out, cfg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='results/local_redesign_v1')
    parser.add_argument('--skip-tests', action='store_true')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    if args.report_only:
        finalize(root, json.loads((root/'protocol.json').read_text()))
        return
    local = load_config('configs/llm_study.ollama.yaml')
    if local.llm.base_url != 'http://localhost:11434/v1':
        raise ValueError('This protocol permits only the local Ollama endpoint')
    protocol = {
        'version': 'local-redesign-v1', 'synthetic': True,
        'data_seed': 20261006, 'items': 2, 'stores': 2, 'data_days': 260,
        'primary_seeds': list(range(30)), 'origins': [160, 188], 'days': 14,
        'scenarios': ['normal', 'feed_gap', 'derived_field_collapse',
                      'foreign_unit_moq', 'capacity_cut', 'promotion_spike'],
        'forecast': 'seasonal_naive', 'gate': local.gate.model_dump(),
        'solver': {'horizon': 6, 'scenarios': 4, 'time_limit': 10},
        'primary_contrast': 'D1 minus D0; gate and deterministic critic together',
        'secondary_contrast': 'D1 delayed simulated approval minus D1 hold',
        'grounding': 'all six controlled prose cases; template and prose parser controls',
        'llm_integration': {'policies': ['B9', 'B10'], 'seeds': [7, 29],
                            'scenarios': ['normal', 'derived_field_collapse'], 'days': 3,
                            'carrier': 'prose', 'forecast_override': 'seasonal_naive'},
        'llm': local.llm.model_dump(),
        'limits': 'Primary inference is conditional on one synthetic panel. LLM closed-loop '
                  'runs are integration checks, not a powered LLM policy study. '
                  'No human participants, M5, remote APIs or GRU reproduction.',
    }
    frozen = root / 'protocol.json'
    if frozen.exists() and json.loads(frozen.read_text()) != protocol:
        raise ValueError('Protocol changed; choose a new output directory')
    if frozen.exists():
        protocol = json.loads(frozen.read_text())
    else:
        atomic_json(frozen, protocol)
    atomic_json(root / 'protocol_hash.json', {'sha256': digest(protocol)})
    tags = httpx.get('http://localhost:11434/api/tags', timeout=30).json()
    matches = [m for m in tags['models'] if m['name'] == local.llm.model]
    if len(matches) != 1 or matches[0]['digest'] != local.llm.model_revision:
        raise ValueError('Installed local model digest does not match the frozen revision')
    atomic_json(root/'local_model.json', matches[0])
    if not args.skip_tests:
        with (root / 'tests.log').open('w') as log:
            subprocess.run([sys.executable, '-m', 'pytest', '-q'], stdout=log,
                           stderr=subprocess.STDOUT, check=True)
    dataset = root / 'panel'
    if not (dataset / 'manifest.json').exists():
        make_demo(dataset, items=2, stores=2, days=260, seed=20261006)
    common = dict(dataset=str(dataset), policies=['D0', 'D1', 'B1'],
                  scenarios=protocol['scenarios'], seeds=list(range(30)), start_day=160,
                  warmup_days=7, days=14, origins=2, origin_stride=28,
                  solver=protocol['solver'], approval_mode='oracle', approval_delay=1)
    for name, changes in [('operations', {}),
                          ('hold_ablation', {'policies': ['D1'], 'approval_mode': 'hold'})]:
        cfg = ExperimentConfig.model_validate({**common, **changes, 'output': str(root/name)})
        (root / f'{name}.yaml').write_text(yaml.safe_dump(cfg.model_dump()), encoding='utf8')
        parallel_operations(cfg, args.workers)
        render_report(cfg.output)
    for carrier in ['templates', 'prose']:
        corpus = root / f'{carrier}.jsonl'
        make_corpus(corpus, prose_only=carrier == 'prose')
        out = root / f'grounding_{carrier}_parser'
        if not (out/'grounding_results.json').exists():
            evaluate_corpus(corpus, out)
    out = root / 'grounding_prose_llama'
    if not (out/'grounding_results.json').exists():
        evaluate_corpus(root/'prose.jsonl', out, local.llm)
    cfg = local.model_copy(deep=True)
    cfg.dataset = str(dataset)
    cfg.output = str(root/'llm_integration')
    cfg.policies = ['B9', 'B10']
    cfg.scenarios = ['normal', 'derived_field_collapse']
    cfg.seeds = [7, 29]
    cfg.start_day = 160
    cfg.days = 3
    cfg.warmup_days = 7
    cfg.document_carrier = 'prose'
    cfg.llm.spend_ledger = str(root/'local_spend.json')
    (root/'llm_integration.yaml').write_text(yaml.safe_dump(cfg.model_dump()), encoding='utf8')
    run_experiment(cfg, resume=True)
    render_report(cfg.output)
    finalize(root, protocol)


def finalize(root, protocol):
    comparisons = []
    operations = pd.read_csv(root/'operations'/'summary.csv')
    ablation = pd.read_csv(root/'hold_ablation'/'summary.csv')
    for scenario in protocol['scenarios']:
        for label, left, right in [
            ('gate_and_critic', operations[operations.policy == 'D1'], operations[operations.policy == 'D0']),
            ('approval', operations[operations.policy == 'D1'], ablation),
        ]:
            for metric in ['cost', 'fill_rate', 'hard_violations', 'reference_deviations', 'held_decisions']:
                a = left[left.scenario == scenario].groupby('seed')[metric].mean()
                b = right[right.scenario == scenario].groupby('seed')[metric].mean()
                if not a.index.equals(b.index) or len(a) != 30:
                    raise ValueError('Incomplete paired seed coverage')
                comparisons.append({'contrast': label, 'scenario': scenario, 'metric': metric,
                                    **paired_bootstrap(a.to_numpy(), b.to_numpy())})
    for row, adjusted in zip(comparisons, holm([r['wilcoxon_p'] for r in comparisons])):
        row['holm_p'] = adjusted
    pd.DataFrame(comparisons).to_csv(root/'planned_comparisons.csv', index=False)
    audit_path = root/'audits.json'
    if audit_path.exists():
        audits = json.loads(audit_path.read_text())
    else:
        audits = []
        for study in ['operations', 'hold_ablation', 'llm_integration']:
            for run in sorted((root/study).glob('*__*')):
                entries = json.loads((run/'trace_index.json').read_text())
                day = entries[0]['day']
                audits.append({'run': str(run), 'replay': replay(run, day),
                               'trace': trace_audit(run, day), 'deletion': deletion_test(run, day)})
        atomic_json(audit_path, audits)
    frames = {s: pd.read_csv(root/s/'summary.csv') for s in
              ['operations', 'hold_ablation', 'llm_integration']}
    expected = {'operations': 1080, 'hold_ablation': 360, 'llm_integration': 8}
    for study, frame in frames.items():
        if len(frame) != expected[study] or frame.duplicated(['policy','scenario','seed','origin']).any():
            raise ValueError(f'Incomplete or duplicate runs in {study}')
    denominators = []
    for study in frames:
        for run in (root/study).glob('*__*'):
            daily = pd.read_csv(run/'daily.csv', usecols=[
                'policy', 'scenario', 'reference_available', 'executed_action', 'hard_violations'])
            denominators.append({'study': study, 'policy': daily.policy.iloc[0],
                'scenario': daily.scenario.iloc[0], 'decisions': len(daily),
                'reference_available': int(daily.reference_available.sum()),
                'executed_actions': int(daily.executed_action.sum()),
                'hard_violations': int(daily.hard_violations.sum())})
    denominator_table = pd.DataFrame(denominators).groupby(
        ['study','policy','scenario']).sum(numeric_only=True).reset_index()
    denominator_table.to_csv(root/'endpoint_denominators.csv', index=False)
    grounding = []
    for name in ['templates_parser', 'prose_parser', 'prose_llama']:
        result = json.loads((root/f'grounding_{name}'/'grounding_results.json').read_text())
        if len(result['cases']) != 6:
            raise ValueError('Incomplete grounding corpus coverage')
        grounding.extend({'reader': name, **case} for case in result['cases'])
    atomic_json(root/'completion.json', {
        'complete': True, 'protocol_hash': digest(protocol),
        'runs': {s: len(f) for s, f in frames.items()},
        'decisions': sum(int(f.trace_count.sum()) for f in frames.values()),
        'all_chains_valid': all(bool(f.chain_valid.all()) for f in frames.values()),
        'all_audited_artifacts_verified': all(a['trace']['artifacts_hash_verified'] for a in audits),
        'replay_action_matches': sum(a['replay']['action_matches'] for a in audits),
        'replay_count': len(audits),
        'llm_errors': int(frames['llm_integration'].llm_errors.sum()),
        'fallback_decisions': int(frames['llm_integration'].fallback_decisions.sum()),
        'grounding_exact_cases': sum(c['whole_set_exact_match'] for c in grounding
                                    if c['reader'] == 'prose_llama'),
        'grounding_total_cases': 6,
        'limits': protocol['limits'],
    })
    tables = ''.join(f'<h2>{name}</h2>'+frame.groupby(['scenario','policy'])[
        ['cost','fill_rate','held_decisions','hard_violations','reference_deviations']
    ].mean().round(4).to_html() for name, frame in frames.items())
    figure_html = ''
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        comparison_frame = pd.DataFrame(comparisons)
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout='constrained')
        for axis, metric, scale, label in zip(axes, ['cost','fill_rate'], [1,100],
                ['Simulated cost difference', 'Fill-rate difference (percentage points)']):
            sub = comparison_frame[(comparison_frame.contrast == 'gate_and_critic') &
                                   (comparison_frame.metric == metric)].set_index('scenario').loc[
                                       protocol['scenarios']]
            center = sub.mean_difference.to_numpy()*scale
            axis.errorbar(center, range(len(sub)),
                xerr=[(sub.mean_difference-sub.ci_low).to_numpy()*scale,
                      (sub.ci_high-sub.mean_difference).to_numpy()*scale],
                fmt='o', color='#13777c', capsize=4)
            axis.axvline(0, color='#777777', linestyle='--', linewidth=1)
            axis.set_yticks(range(len(sub)), [s.replace('_',' ') for s in sub.index])
            axis.invert_yaxis()
            axis.set_xlabel(label+' (D1 minus D0)')
            axis.grid(axis='x', alpha=0.2)
        fig.suptitle('Gate and deterministic critic versus ungated MILP\n'
                     'Marginal 95% paired bootstrap intervals; 30 seeds; origins averaged within seed')
        fig.savefig(root/'primary_comparison.png', dpi=200)
        fig.savefig(root/'primary_comparison.pdf')
        plt.close(fig)
        figure_html = ('<h2>Primary comparison with uncertainty</h2><img '
            'src="primary_comparison.png" style="max-width:100%" '
            'alt="Paired confidence intervals for simulated cost and service differences">')
    except ModuleNotFoundError:
        print('Matplotlib absent: numerical results remain available.', flush=True)
    (root/'report.html').write_text('<!doctype html><meta charset="utf-8">'
        '<title>Local redesigned experiment</title><style>body{font:15px system-ui;'
        'margin:40px}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ddd}</style>'
        '<h1>Completed local synthetic experiment</h1><p>'+protocol['limits']+'</p>'+figure_html+tables+
        '<p>Schema and dimensional validity do not establish factual entailment of prose '
        'values. Grounding exact-match scores use labels withheld from model requests.</p>'+
        '<h2>Endpoint coverage and denominators</h2>'+denominator_table.to_html(index=False)+
        '<h2>Grounding accuracy</h2>'+pd.DataFrame(grounding)[[
            'reader','case_id','whole_set_exact_match','field_tuple_precision','field_tuple_recall',
            'false_constraints','omitted_constraints','escalated','residual_errors_eligible_for_solver'
        ]].round(4).to_html(index=False)+
        '<h2>Planned paired comparisons</h2>'+pd.DataFrame(comparisons).round(5).to_html(index=False),
        encoding='utf8')
    print(f'Completed: {root / "report.html"}', flush=True)


if __name__ == '__main__':
    main()
