"""Copy verified reports into the Git delivery tree; retain full evidence separately."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'results/freshretailnet'
OUT = ROOT / 'study_results/freshretailnet'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_verified(source, destination):
    if source.is_symlink():
        raise ValueError(f'Symlink refused: {source}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and digest(destination) != digest(source):
        raise FileExistsError(f'Preserve different existing delivery: {destination}')
    if not destination.exists():
        shutil.copy2(source, destination)
    if digest(destination) != digest(source):
        raise AssertionError(f'Delivery bytes changed: {destination}')


def main():
    main_audit = read(SOURCE / 'audit/audit.json')
    follow_audit = read(SOURCE / 'gate_transfer/audit_independent/audit.json')
    report = read(SOURCE / 'report/report_manifest.json')
    integrity = read(SOURCE / 'report/document_integrity_receipt.json')
    assert main_audit['status'] == follow_audit['status'] == 'VERIFIED_COMPLETE'
    assert report['status'] == integrity['status'] == 'VERIFIED'
    assert integrity['docx_sha256'] == digest(SOURCE / 'report/Dual_Benchmark_Dissertation_Final.docx')
    for check in integrity['pdf_checks']:
        assert digest(SOURCE / 'report' / Path(check['file']).name) == check['sha256']
    for entry in report['outputs']:
        path = SOURCE / 'report' / entry['path']
        assert path.stat().st_size == entry['bytes'] and digest(path) == entry['sha256'], path
    OUT.mkdir(parents=True, exist_ok=True)
    for path in sorted((SOURCE / 'report').rglob('*')):
        if path.is_file() and path.suffix != '.log':
            copy_verified(path, OUT / path.relative_to(SOURCE / 'report'))
    for relative in [
        'protocol.json', 'numerical/execution_complete.json', 'agents/execution_complete.json',
        'audit/audit.json', 'forecast/independent_audit.json',
        'policy_sensitivity/audit.json', 'development/policy_sensitivity_independent_audit.json',
        'gate_transfer/protocol.json', 'gate_transfer/execution_complete.json',
        'gate_transfer/audit.json', 'gate_transfer/audit_independent/audit.json',
        'gate_transfer/calibration/selection_receipt.json',
        'data/selected_series.csv', 'data/selection.json', 'data/train_validation.json',
        'data/eval_validation.json', 'setup/download_receipt.json',
    ]:
        copy_verified(SOURCE / relative, OUT / 'receipts' / relative)
    owner = read(SOURCE / 'gate_transfer/audit.json')
    primary = main_audit['totals']
    assert primary['runs'] == 392 and owner['runs'] == 480 and owner['decisions'] == 3360
    with (SOURCE / 'report/FreshRetailNet_agent_all_runs.csv').open() as stream:
        primary_agent_violations = sum(int(float(r['hard_violations'])) for r in csv.DictReader(stream))
    with (SOURCE / 'gate_transfer/descriptive_means.csv').open() as stream:
        means = list(csv.DictReader(stream))
    field = {r['arm']: r for r in means if r['scenario'] == 'derived_field_collapse'}
    baseline = field['llm_no_recovery']; recovered = field['llm_recovery']
    cost_change = 100 * (float(recovered['cost']) / float(baseline['cost']) - 1)
    fill_change = 100 * (float(recovered['fill_rate']) - float(baseline['fill_rate']))
    readme = f'''# FreshRetailNet study and dual-benchmark dissertation

Download the [full Word dissertation](Dual_Benchmark_Dissertation_Final.docx),
the [dissertation PDF](Dual_Benchmark_Dissertation_Final.pdf), or the
[detailed FreshRetailNet report](FreshRetailNet_study_report.pdf).
The [report download ZIP](FreshRetailNet_report_download.zip) contains both PDFs,
the Word file, result tables and all new figures. On GitHub, select **Download raw file**.

The study validated the complete pinned FreshRetailNet release: 4,850,000 daily rows,
50,000 store–product series, 898 stores, 18 cities and 865 product IDs. Replenishment
experiments use a training-selected panel of **30 series**, or **0.06%** of the release.
Every main simulation run uses all 30 series. This is a bounded study, rather than an
evaluation of replenishment performance across all 50,000 series.

## Completed evidence

- Primary study: **360** conventional numerical runs and **32** matched parser/LLM
  runs, with seven simulated days per run. The numerical grid has 30 simulation seeds;
  the primary live-agent pilot has two seeds.
- Separately registered exploratory gate-transfer follow-up: **480** runs, four
  configurations, four scenarios and 30 simulation seeds, with **3,360** decisions.
- Independent policy analysis: **1,080** perishability/demand/calculator sensitivity
  runs and **60** valid-stockout gate ablations. These calculators use different units
  and supply assumptions and are not pooled with the main MILP study.
- Protected forecasting and artificial-mask recovery tests, including four rolling
  validation folds and the publisher's seven-day evaluation period.

This yields **2,012 completed simulation runs** and **14,084 run-days**, excluding the
separate training-only calibration and forecasting fits. An independent audit verifies
the primary and follow-up grid, source objects, event chains, physical stock balances,
cost arithmetic, grounding and physical model requests/responses. The receipts are in
[receipts/](receipts/); complete raw logs and source data are in the evidence archive.

## What the evidence supports

Raw LightGBM achieved **38.84% WAPE** on fully stocked evaluation days, versus
**42.84%** for seasonal naïve. Recovered forecasts did not beat raw LightGBM on that
target. Artificial masking identifies recovery error where sales are observed; naturally
lost demand during real stockouts remains unobserved.

The unmodified M5 spending cap held every normal, inventory-field-fault and feed-gap
day in the primary agent pilot. That transfer failure remains in the report. A separately
registered follow-up selected a cap of **1,850** from training-only proposals. Its
evaluation reuses the official holdout after the primary results were seen and is
explicitly **exploratory**. In its inventory-field-fault scenario, verified repair changed
LLM-arm mean simulated cost by **{cost_change:+.2f}%** and fill by **{fill_change:+.2f}
percentage points**. The parser receives the same verified repair. The matched outcomes below distinguish
any shared architectural benefit from an additional return from the language model.

The primary LLM/parser outcomes match in **{primary['parser_llm_pairs_primary_metrics_equal']}/
{primary['parser_llm_matched_pairs']}** pairs. The exploratory follow-up matches in
**{owner['llm_parser_equal_run_pairs']}/{owner['llm_parser_pairs']}** pairs. Primary agent
configurations have **{primary_agent_violations}** actual committed-action constraint
violations; follow-up configurations have **{owner['hard_violations']}**.
The conventional MILP also has zero actual violations in the primary study, so the
LLM cannot receive unique safety credit. Wrong recovery requests are retained and
independent tools refuse stale evidence. Cached grounding is not a fresh semantic trial
for each simulation seed.

Sales are globally normalized amounts. Inventory, procurement, suppliers, lead times,
expiry, lost demand assumptions and costs are simulated. Main costs are an index,
not USD, CNY or retailer profit. The inherited MILP is age-unaware despite physical
FIFO expiry; the separate policy calculators examine age handling. The M5 comparison
is descriptive and uses within-dataset changes because horizons, products and economics
differ. No human participant study or production ROI was measured.

## Source attribution and reproduction

Data: **Dingdong-Inc/FreshRetailNet-50K**, CC BY 4.0,
https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K
at revision `08c1fab7f9257bc73679d415d65d644165d351d4`.
Publisher methods and counting discrepancies are recorded in the source receipts.
The locally hosted model is `ega-qwen2.5:1.5b-v2`; there were no paid API calls.
CPU, installation and human oversight costs are not monetized.

The complete pinned train/evaluation Parquet files, selected panel, saved forecast
tensors, requests/responses, content-addressed decision objects, SQLite logs, failed
development checks, protocols, audits and report sources are preserved byte for byte.
[archives.json](archives.json) records archive-part hashes and order;
[file_inventory.json.gz](file_inventory.json.gz) records every original path.
Parts are at most **48 MiB**, stored in ordinary Git without Git LFS.

After cloning the repository, reassemble and restore using Python 3.11 or later:

```bash
python scripts/freshretailnet_delivery.py --restore /tmp/freshretailnet-restored
```

Every part, joined archive and restored file is verified by SHA-256. Restoration
refuses to overwrite different existing bytes. Recorded absolute cloud paths remain
in provenance; restoration alone does not install dependencies or restart experiments.
For a compact read-only restoration, add `--link-identical`: all original paths are
restored, but identical files share hardlinks. Edits to one such file affect its aliases;
the default restoration writes separate copies.
Local model weights, runtime binaries, virtual environments and authentication are
excluded. Do not rerun the immutable primary protocol over existing evidence folders.
All original M5 delivery archives remain unchanged.
'''
    (OUT / 'README.md').write_text(readme)
    selected = [p for p in OUT.rglob('*') if p.is_file() and
                (p.suffix in {'.pdf', '.docx', '.csv'} or
                 ('figures' in p.parts and p.suffix == '.png') or p == OUT / 'README.md') and
                'receipts' not in p.parts]
    with zipfile.ZipFile(OUT / 'FreshRetailNet_report_download.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(selected):
            archive.write(path, path.relative_to(OUT))
    with zipfile.ZipFile(OUT / 'FreshRetailNet_report_download.zip') as archive:
        assert len(archive.infolist()) == len(selected)
        for path in selected:
            with archive.open(path.relative_to(OUT).as_posix()) as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            assert checksum == digest(path), f'Download ZIP bytes changed: {path}'
    records = [{'path':str(p.relative_to(OUT)), 'bytes':p.stat().st_size,
                'sha256':digest(p)} for p in sorted(OUT.rglob('*'))
               if p.is_file() and 'archive_parts' not in p.parts]
    receipt = {'status':'VERIFIED', 'files':records,
               'report_manifest_sha256':digest(OUT / 'report_manifest.json')}
    (OUT / 'direct_delivery_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status':'VERIFIED', 'direct_files':len(records),
                      'download_zip_bytes':(OUT / 'FreshRetailNet_report_download.zip').stat().st_size}))


if __name__ == '__main__':
    main()
