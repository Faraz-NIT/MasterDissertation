"""Package completed shortened-study evidence without modifying experiment outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/workspace/MasterDissertation')
OUT = ROOT / 'results/report'
TOOLS = Path('/workspace/tools')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    data = json.loads((OUT / 'M5_six_hour_study_report_data.json').read_text())
    protocol = json.loads((ROOT / 'results/run_configs/six_hour_protocol.json').read_text())
    rows = list(csv.DictReader((OUT / 'M5_six_hour_results.csv').open()))
    expected_groups = {'numerical_7_days': 360, 'prose_feasibility_2_days': 8,
                       'structured_reference_2_days': 4}
    assert Counter(r['comparison_group'] for r in rows) == expected_groups
    identities = [(r['comparison_group'], r['policy'], r['scenario'], r['seed'], r['origin']) for r in rows]
    assert len(set(identities)) == len(rows) == 372
    assert {int(r['m5_series']) for r in rows} == {30}
    totals = {key: sum(int(float(r[key])) for r in rows)
              for key in ['trace_count', 'llm_calls', 'tokens']}
    assert totals == {'trace_count': 2544, 'llm_calls': 30, 'tokens': 112739}
    assert all(r['chain_valid'].lower() == 'true' for r in rows)
    assert data['overall_status'] == 'COMPLETE' and data['final_snapshot']
    assert data['display_timezone'] == 'UTC' and data['warnings'] == []
    assert data['final_numeric_audit']['valid']
    for stage in data['stages']:
        if stage.get('required'):
            assert stage['status'] == 'COMPLETE' and stage['completed'] == stage['expected']
            assert stage['invalid_chains'] == 0 and not stage['packing_errors']
    now = datetime.now(timezone.utc)
    deadline = datetime.fromisoformat(protocol['report_deadline_utc'])
    start = datetime.fromisoformat(protocol['requested_at_utc'])
    assert now <= deadline
    tracked = subprocess.check_output(['git', 'status', '--short', '--untracked-files=no'],
                                      cwd=ROOT, text=True).strip()
    assert not tracked

    files: dict[str, Path] = {}

    def add(path: Path, archive_path: str | None = None) -> None:
        assert path.is_file() and not path.is_symlink(), path
        name = archive_path or path.relative_to(ROOT).as_posix()
        assert not name.startswith('/') and '..' not in Path(name).parts
        assert name not in files or files[name] == path
        files[name] = path

    report_files = [OUT / ('M5_six_hour_study_report' + suffix)
                    for suffix in ['.pdf', '.html', '.md', '_data.json', '_input_hashes.json']]
    for p in report_files:
        add(p)
    for p in OUT.glob('M5_six_hour_study_report_*.png'):
        # Only graphs actually regenerated for the final report, not older snapshots.
        if p.stat().st_mtime >= report_files[0].stat().st_mtime - 60:
            add(p)
    for name in ['M5_six_hour_results.csv', 'M5_six_hour_evidence_README.md',
                 'generate_report.py', 'six_hour_live_grounding_assessment.json',
                 'six_hour_trace_validation.json']:
        add(OUT / name)
    add(OUT / 'source/dissertation_revised_business_school.html')
    for name in ['six_hour_protocol.json', 'six_hour_numeric.yaml',
                 'six_hour_numeric_extension.yaml', 'six_hour_agentic_prose.yaml',
                 'six_hour_structured_controls.yaml', 'six_hour_model_identity.json',
                 'six_hour_numeric_extension_owner.json']:
        add(ROOT / 'results/run_configs' / name)
    for p in (ROOT / 'data/processed/m5').iterdir():
        if p.is_file():
            add(p)
    for stage in ['six_hour_numeric', 'six_hour_numeric_extension',
                  'six_hour_numeric_30seeds', 'six_hour_agentic_prose',
                  'six_hour_structured_controls']:
        p = ROOT / 'results' / stage
        for name in ['summary.csv', 'study_summary.json', 'resolved_config.json',
                     'environment.json', 'merge_manifest.json', 'analytical_manifest.json',
                     'training_equivalence.json', 'paired_comparisons.csv']:
            if (p / name).is_file():
                add(p / name)
        for run in p.glob('*__*__seed*__origin*'):
            for name in ['summary.json', 'daily.csv', 'detection.csv', 'trace_index.json',
                         'run_manifest.json', 'packing_manifest.json']:
                if (run / name).is_file():
                    add(run / name)

    # Selected complete object archives support the reported live-model and replay cases.
    selected_runs = []
    for stage in ['six_hour_agentic_prose', 'six_hour_structured_controls']:
        selected_runs.extend(sorted((ROOT / 'results' / stage).glob('*__*__seed*__origin*')))
    selected_runs.extend(ROOT / 'results/six_hour_numeric' / f'{p}__feed_gap__seed0__origin0'
                         for p in ['B3', 'B4'])
    assert len(selected_runs) == 14
    for run in selected_runs:
        assert (run / 'artifacts/audit.sqlite').is_file()
        assert (run / 'artifacts/objects.zip').is_file()
        for p in (run / 'artifacts').rglob('*'):
            if p.is_file() and p.suffix in ['.sqlite', '.zip', '.json']:
                add(p)
    for name in ['m5_live_grounding_assess.py', 'm5_live_grounding_assess.md',
                 'm5_live_grounding_assess_validation.json', 'm5_training_equivalence.py',
                 'm5_training_equivalence_validation.json', 'm5_final_numeric_audit.json',
                 'm5_pack_artifacts.py', 'm5_pack_artifacts.md', 'm5_shortened_export.py']:
        add(TOOLS / name, 'helpers/' + name)

    completion = {
        'format': 'm5-shortened-study-final-completion-v1',
        'recorded_at_utc': now.isoformat(), 'requested_at_utc': start.isoformat(),
        'report_deadline_utc': deadline.isoformat(),
        'elapsed_hours_to_export': (now - start).total_seconds() / 3600,
        'within_six_hour_deadline': True, 'status': 'COMPLETE',
        'scope': 'shortened_six_hour', 'full_dissertation_complete': False,
        'report_snapshot_utc': data['generated_at'], 'series': 30,
        'comparison_group_runs': expected_groups, 'unique_runs': len(rows), **totals,
        'tracked_checkout_changes': False, 'checkout_sha': data['checkout_sha'],
        'source_grid_audit_valid': True, 'all_required_stages_complete': True,
        'report_warnings': [],
        'report_refresh_repair': 'The extension owner recorded a report-reader error after successful numerical completion. The report-only reader was corrected and the final UTC snapshot generated without resimulation or changes to experiment outputs.',
        'selected_complete_audit_cases': [p.relative_to(ROOT).as_posix() for p in selected_runs],
        'export_scope': 'Report, CSV, prepared panel, frozen configuration, original run summaries and 14 selected complete audit cases. Full numerical object archives and model weights remain outside this partial evidence export.',
        'findings': {'feed_gap_committed_plan_violations_B3': 63,
                     'feed_gap_committed_plan_violations_B4': 0,
                     'live_llm_executed_decisions': 0,
                     'live_llm_held_decisions': 8,
                     'llm_replenishment_benefit_established': False},
        'important_output_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in report_files},
    }
    cp = OUT / 'six_hour_final_completion.json'
    cp.write_text(json.dumps(completion, indent=2, sort_keys=True) + '\n')
    add(cp)
    inventory = {'format': 'm5-evidence-export-sha256-v1',
                 'created_at_utc': now.isoformat(),
                 'files': [{'path': name, 'size_bytes': p.stat().st_size, 'sha256': sha(p)}
                           for name, p in sorted(files.items())]}
    ip = OUT / 'M5_six_hour_evidence_inventory.json'
    ip.write_text(json.dumps(inventory, indent=2, sort_keys=True) + '\n')
    target = OUT / 'M5_six_hour_results_and_evidence.zip'
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, p in sorted(files.items()):
            z.write(p, name)
        z.write(ip, ip.relative_to(ROOT).as_posix())
    # Verify every exported byte against the recorded original file hashes.
    with zipfile.ZipFile(target) as z:
        assert len(z.namelist()) == len(files) + 1
        for row in inventory['files']:
            contents = z.read(row['path'])
            assert len(contents) == row['size_bytes']
            assert hashlib.sha256(contents).hexdigest() == row['sha256']
        assert z.read(ip.relative_to(ROOT).as_posix()) == ip.read_bytes()
    checksum = OUT / 'M5_six_hour_results_and_evidence.zip.sha256'
    checksum.write_text(sha(target) + '  ' + target.name + '\n')
    print(json.dumps({'status': 'verified', 'members': len(files) + 1,
                      'archive_bytes': target.stat().st_size, 'archive_sha256': sha(target),
                      'elapsed_hours': completion['elapsed_hours_to_export'],
                      'pdf_sha256': sha(report_files[0]), 'archive': str(target)}))


if __name__ == '__main__':
    main()
