"""Export only the empirical dissertation studies, code, figures and complete logs."""
from __future__ import annotations
import ast
import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORK=Path('/tmp/replenishment-code-package-20261014')
STAGE=WORK/'stage'
EXTRACT=WORK/'extracted'
ZIP=ROOT/'exports/Latest_Dissertation_Experiments_Code_Logs.zip'
STUDIES=['ollama_clean_study_20261009','architecture_study_20261013','langchain_extension_20261014']
CODE={
    'ollama_clean_study':['core.py','prepare.py','run.py','analyze.py','requirements.txt'],
    'architecture_study':['architecture.py','graph.py','run.py','analyze.py','independent_ledger.py',
                          'check_development.py','figures.py','requirements.txt'],
    'langchain_extension':['chain.py','validation_run.py','replay.py','validate.py','requirements.txt'],
}
ROOT_EVIDENCE={'protocol.json','execution_receipt.json','execution_process.json','supervision_process.json',
               'summary.csv','progress.json','seed_progress.json','workflow.jsonl','figure_register.json',
               'architecture_graph.mmd','git_verification.json'}
EVIDENCE_DIRS={'analysis','data','development','frozen_code','logs','runs','figures'}
FORBIDDEN_SUFFIXES={'.doc','.docx','.pdf','.html','.htm','.odt','.rtf','.ppt','.pptx','.zip','.gz','.pyc'}


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def copy(path):
    assert not path.is_symlink(),path
    target=STAGE/path.relative_to(ROOT)
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(path,target)
    assert sha(path)==sha(target)


def plot_extract(source,target,functions,assignments):
    """Keep plotting functions and their imports; exclude embedded chapter/report text."""
    text=source.read_text();tree=ast.parse(text);pieces=[]
    for node in tree.body:
        keep=False
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            module=getattr(node,'module','') or ''
            keep=not module.startswith('docx')
        elif isinstance(node,ast.FunctionDef):keep=node.name in functions
        elif isinstance(node,ast.Assign):
            keep=any(isinstance(name,ast.Name) and name.id in assignments for name in node.targets)
        elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call):
            expression=ast.get_source_segment(text,node) or ''
            keep=expression.startswith(('matplotlib.use(','plt.rcParams.update(','os.environ.setdefault('))
        if keep:pieces.append(ast.get_source_segment(text,node))
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('"""Saved-result plotting only; extracted from the source study renderer."""\n'+
                      '\n\n'.join(pieces)+'\n')
    ast.parse(target.read_text())
    return {'source':str(source.relative_to(ROOT)),'source_sha256':sha(source),
            'destination':str(target.relative_to(STAGE)),'functions':functions,
            'experiment_code_changed':False}


README='''# Retail replenishment studies: code and complete evidence

This repository-ready package contains the empirical work used in the latest
dissertation and its LangChain extension. It contains no dissertation documents,
chapter drafts, rendered document pages, or illustrative 3% scenario outputs.

## Included studies

| Folder under `study_results/` | Scope | Policy runs | Fresh primary model calls |
| --- | --- | ---: | ---: |
| `ollama_clean_study_20261009` | Main M5/RetailNet study, 30 simulation seeds | 1,080 | 7,560 |
| `architecture_study_20261013` | Full selective-delegation architecture comparison using LangGraph, 30 seeds | 1,080 | 9,240 |
| `langchain_extension_20261014` | Fresh LangChain implementation validation, one new seed | 36 | 300 |

Every study uses all 30 selected series per dataset, two seven-day origins and
three operating situations. LangChain also has an explicitly labelled regression
using archived responses for 7,560 decisions; that regression is not live inference.
Excluded development checks, including failed checks, remain in `development/`.

Each study includes native model request/response JSON, decisions and inventory
ledgers, per-case CSVs, frozen protocols, execution logs, development records,
audits, derived result tables, prepared panels and fitted forecasts. Figures are
included, together with the empirical figures used in the full dissertation.

## Install and check

Extract the ZIP into an empty folder or the root of your new repository. Keep the
`scripts/` and `study_results/` paths: source files resolve these paths relative to
the repository root. No dependency on the original `ega` package is needed.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/verify_bundle.py
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python -I -m pytest -q tests
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python tools/audit_saved_results.py
```

Verification and audit read saved evidence; they do not start Ollama or generate
new experimental model responses. The audit recomputes derived CSV files and audit
receipts in your extracted copy. Verify the original file hashes before auditing.

## Code

- `scripts/ollama_clean_study/`: selection, forecasting, simulator, native model
  client, policy execution and numerical analysis.
- `scripts/architecture_study/`: selective delegation, LangGraph orchestration,
  full matched execution and independent ledger audit.
- `scripts/langchain_extension/`: actual LangChain LCEL branches, StructuredTool
  planner, live validation and explicitly labelled archived-response regression.
- `tests/`: only the 16 relevant checks; older package fixtures are excluded.
- `tools/`: bundle integrity verification and archived-evidence audit.

Evaluated code and raw evidence retain their original bytes. Plot-only functions
were extracted from report builders so no document-generation code or chapter
text is needed. Their source hashes are recorded in `PACKAGE_METADATA.json`.

To regenerate plots, optionally install `requirements-plots.txt` and the Graphviz
`dot` executable, then run the `figures.py` scripts. Main-study plotting must run
before the dissertation figure assembly. These commands produce figures only:

```bash
.venv/bin/python -m pip install -r requirements-plots.txt
.venv/bin/python scripts/ollama_clean_study/figures.py
.venv/bin/python scripts/ollama_dissertation/figures.py
.venv/bin/python scripts/architecture_study/figures.py
.venv/bin/python scripts/langchain_extension/figures.py
```

## Model and data

The model is pretrained Qwen2.5:1.5b Q4_K_M, used for local inference with
Ollama 0.40.0. The original instance allocated four CPU cores and 32 GiB, without
a GPU. Model digest and generation settings are frozen in the study protocols.
The original Ollama manifest is provided in `model/`; weights and binaries are
not included. Installing or pulling a model tag must reproduce the recorded digest
before fresh comparative inference is attempted.

Selected histories, forecasts and LightGBM model files are included. Full M5 and
FreshRetailNet source releases are not duplicated here. `DATA_SOURCES.json` records
their locations, release revision and original file hashes. Raw releases are needed
only to repeat selection from the full datasets; archived analysis uses the included
prepared panels. RetailNet published sales are normalised proxies multiplied by 100.
Inventories, delivery opportunities and cost indices are simulation assumptions.

Execution scripts intentionally refuse to overwrite published runs and protocols.
The original dated cutoffs apply to those preserved experiments. A new inference
study needs a separate output location, new seeds and a newly frozen protocol; do
not edit or delete archived evidence to bypass these protections. No fresh study
was run to build this package.

No Git history, credentials, environments, model weights, full source-data caches,
superseded studies or dissertation documents are included.
'''


VERIFY='''from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'MANIFEST.json').read_text())
for name,info in manifest['files'].items():
    path=root/name
    assert path.is_file() and path.stat().st_size==info['bytes'],name
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    assert digest==info['sha256'],name
print(json.dumps({'status':'VERIFIED','files':len(manifest['files']),'archived_document_files':0}))
'''
AUDIT='''from pathlib import Path
import subprocess,sys,json
root=Path(__file__).resolve().parents[1]
tasks=[('ollama_clean_study','import analyze; result=analyze.audit(False); print("Main study audit verified:",len(result[0]),"runs")'),
       ('architecture_study','import analyze; result=analyze.audit(); print("Architecture study audit verified:",len(result[0]),"runs")'),
       ('langchain_extension','import validate; validate.audit()')]
for name,action in tasks:
    code='import sys;sys.path.insert(0,'+repr(str(root/'scripts'/name))+');'+action
    subprocess.run([sys.executable,'-I','-c',code],cwd=root,check=True)
print(json.dumps({'status':'VERIFIED','studies':3,'new_experimental_model_calls':0}))
'''


def build():
    if STAGE.exists() or EXTRACT.exists() or ZIP.exists():
        raise FileExistsError('Preserve an existing export; choose a new export workspace')
    STAGE.mkdir(parents=True)
    for folder,names in CODE.items():
        for name in names:copy(ROOT/'scripts'/folder/name)
    for name in ['test_ollama_clean_study.py','test_selective_architecture.py','test_langchain_extension.py']:
        copy(ROOT/'tests'/name)
    copy(ROOT/'LICENSE')
    for study in STUDIES:
        base=ROOT/'study_results'/study
        for path in sorted(base.rglob('*')):
            if not path.is_file():continue
            relative=path.relative_to(base)
            if relative.parts[0] not in EVIDENCE_DIRS and relative.as_posix() not in ROOT_EVIDENCE:continue
            if path.suffix.lower() in FORBIDDEN_SUFFIXES or '__pycache__' in path.parts:continue
            if path.suffix.lower()=='.md':continue
            copy(path)
    dissertation=ROOT/'study_results/ollama_dissertation_20261012'
    for path in sorted((dissertation/'figures').iterdir()):
        if path.is_file() and path.suffix.lower() in {'.png','.svg','.dot'}:copy(path)
    copy(dissertation/'figure_register.json')
    copy(ROOT/'scripts/ollama_dissertation/figures.py')
    derived=[]
    source=ROOT/'scripts/ollama_clean_study/report.py'
    derived.append(plot_extract(source,STAGE/'scripts/ollama_clean_study/figures.py',
                               ['sha','save','bars','figures'],['ROOT','OUT','ARMS','NAMES','COLORS','SCENARIOS','LABELS','REGISTER']))
    with (STAGE/'scripts/ollama_clean_study/figures.py').open('a') as stream:
        stream.write("\nif __name__=='__main__':\n    figures()\n")
    derived.append(plot_extract(ROOT/'scripts/langchain_extension/report.py',STAGE/'scripts/langchain_extension/figures.py',
                               ['sha','figures'],['ROOT','OUT','PRIOR']))
    with (STAGE/'scripts/langchain_extension/figures.py').open('a') as stream:
        stream.write("\nif __name__=='__main__':\n    figures(json.loads((OUT/'analysis/validation_summary.json').read_text()))\n")
    derived.append(plot_extract(ROOT/'scripts/ollama_dissertation/config.py',STAGE/'scripts/ollama_dissertation/config.py',
                               ['sha','read'],['ROOT','OUT','STUDY']))
    for row in derived:row['exported_sha256']=sha(STAGE/row['destination'])
    (STAGE/'README.md').write_text(README)
    (STAGE/'.gitignore').write_text('.venv/\n__pycache__/\n*.py[cod]\n.pytest_cache/\n')
    (STAGE/'pyproject.toml').write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\naddopts = "-ra"\n')
    (STAGE/'requirements.txt').write_text('# Tested direct execution dependencies, Python 3.12; not a transitive lock.\n'
        'numpy==2.3.5\npandas==2.2.3\nscipy==1.17.0\njsonschema==4.26.0\nlightgbm==4.7.0\n'
        'scikit-learn==1.9.1\npyarrow==21.0.0\nlangchain-core==1.6.10\nlanggraph==1.0.10\npytest==9.0.2\n')
    (STAGE/'requirements-plots.txt').write_text('-r requirements.txt\n# Original published figures used this Matplotlib version.\nmatplotlib==3.10.8\n')
    (STAGE/'tools').mkdir()
    (STAGE/'tools/verify_bundle.py').write_text(VERIFY)
    (STAGE/'tools/audit_saved_results.py').write_text(AUDIT)
    manifest=Path('/workspace/tools/ollama/models/manifests/registry.ollama.ai/library/qwen2.5/1.5b')
    (STAGE/'model').mkdir();shutil.copyfile(manifest,STAGE/'model/ollama_manifest.json')
    p=json.loads((STAGE/'study_results/ollama_clean_study_20261009/data/preparation_receipt.json').read_text())
    dump(STAGE/'DATA_SOURCES.json',{'prepared_inputs_included':True,'full_source_releases_included':False,
        'M5':{'source':'Walmart M5 Forecasting Accuracy competition','url':'https://www.kaggle.com/competitions/m5-forecasting-accuracy/data'},
        'RetailNet':{'source':'Dingdong-Inc/FreshRetailNet-50K','url':'https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K',
                     'revision':'08c1fab7f9257bc73679d415d65d644165d351d4','license':'CC-BY-4.0'},
        'original_preparation_receipt':p})
    counts=[]
    for study in STUDIES:
        base=STAGE/'study_results'/study
        protocol=json.loads((base/'protocol.json').read_text())
        for name,digest in protocol['code_sha256'].items():assert sha(STAGE/name)==digest,name
        for dataset,info in protocol['datasets'].items():
            for name,digest in info['file_sha256'].items():assert sha(base/'data'/dataset/name)==digest,name
        receipt=json.loads((base/'execution_receipt.json').read_text())
        counts.append({'study':study,'runs':receipt['runs'],'portfolio_days':receipt['portfolio_days'],
                       'fresh_primary_model_calls':receipt['fresh_primary_model_calls'],
                       'native_response_files':len(list((base/'runs').glob('**/model_calls/**/*.json'))),
                       'protocol_sha256':sha(base/'protocol.json')})
    assert [row['native_response_files'] for row in counts]==[7560,9240,300]
    dump(STAGE/'PACKAGE_METADATA.json',{'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'source_repository':'Faraz-NIT/MasterDissertation',
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'studies':counts,'evaluated_code_and_raw_evidence_preserved':True,'derived_plot_only_modules':derived,
        'academic_documents_included':False,'illustrative_3percent_scenario_included':False,
        'full_raw_source_releases_included':False,'llm_weights_included':False,'new_experimental_calls':0})
    files={str(p.relative_to(STAGE)):{'bytes':p.stat().st_size,'sha256':sha(p)}
           for p in sorted(STAGE.rglob('*')) if p.is_file()}
    for name in files:
        assert Path(name).suffix.lower() not in FORBIDDEN_SUFFIXES,name
        assert not any(part in {'.git','.venv','__pycache__','reproduction'} for part in Path(name).parts),name
        assert Path(name).name not in {'chapter.md','manuscript.md','references.md','appendices.md'},name
    dump(STAGE/'MANIFEST.json',{'schema':'replenishment-code-evidence-export-v1','files':files,'file_count':len(files),
                              'total_uncompressed_bytes':sum(row['bytes'] for row in files.values())})
    ZIP.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(ZIP,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(STAGE.rglob('*')):
            if path.is_file():bundle.write(path,str(path.relative_to(STAGE)))
    with zipfile.ZipFile(ZIP) as bundle:
        assert len(bundle.namelist())==len(files)+1
        assert len(set(bundle.namelist()))==len(bundle.namelist())
        assert bundle.testzip() is None
        for name,info in files.items():assert hashlib.sha256(bundle.read(name)).hexdigest()==info['sha256'],name
        assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in bundle.namelist())
        bundle.extractall(EXTRACT)
    receipt={'status':'ARCHIVE_VERIFIED_PENDING_EXTRACTED_TESTS','zip_path':str(ZIP.relative_to(ROOT)),
             'zip_bytes':ZIP.stat().st_size,'zip_sha256':sha(ZIP),'files':len(files)+1,
             'uncompressed_bytes':sum(row['bytes'] for row in files.values()),'studies':counts,
             'document_files':0,'frozen_code_and_data_hashes_verified':True,'every_archived_file_hash_verified':True}
    dump(WORK/'archive_receipt.json',receipt)
    print(json.dumps(receipt),flush=True)


def finalize():
    """Add actual extracted-package check logs, then verify the final bytes again."""
    checks=STAGE/'packaging_checks';checks.mkdir(exist_ok=False)
    test_log=(WORK/'tests.log').read_text()
    audit_log=(WORK/'audits.log').read_text()
    plot_log=(WORK/'plots.log').read_text()
    assert '16 passed' in test_log
    assert 'Main study audit verified: 1080 runs' in audit_log
    assert 'Architecture study audit verified: 1080 runs' in audit_log
    assert '"studies": 3' in audit_log and '"new_experimental_model_calls": 0' in audit_log
    assert 'PASS: four plot-only modules ran; no document files generated' in plot_log
    for name in ['tests.log','audits.log','plots.log','plots_initial.log']:
        shutil.copyfile(WORK/name,checks/name)
    initial=json.loads((WORK/'archive_receipt.json').read_text())
    dump(checks/'initial_archive_verification.json',{'status':'VERIFIED',
        'initial_zip_sha256':initial['zip_sha256'],'file_count_before_adding_packaging_check_logs':initial['files'],
        'every_file_hash_verified':True,'all_frozen_source_and_data_hashes_verified':True})
    readiness={'status':'PASS','tested_in_separate_extracted_repository':True,
               'relevant_tests_passed':16,'saved_result_audits_passed':3,'plot_only_modules_passed':4,
               'new_experiment_runs':0,'new_experimental_model_calls':0,'document_files_generated':0,
               'initial_plot_check_issue':'Python -I omits the script directory from imports',
               'plot_check_resolution':'Isolated bootstrap explicitly supplies the same script directory as the documented CLI',
               'checked_archived_source_and_raw_evidence_changed':False}
    dump(checks/'readiness.json',readiness)
    metadata=json.loads((STAGE/'PACKAGE_METADATA.json').read_text())
    metadata['extracted_package_checks']=readiness
    dump(STAGE/'PACKAGE_METADATA.json',metadata)
    files={str(p.relative_to(STAGE)):{'bytes':p.stat().st_size,'sha256':sha(p)}
           for p in sorted(STAGE.rglob('*')) if p.is_file() and p.name!='MANIFEST.json'}
    for name in files:assert Path(name).suffix.lower() not in FORBIDDEN_SUFFIXES,name
    dump(STAGE/'MANIFEST.json',{'schema':'replenishment-code-evidence-export-v1','files':files,'file_count':len(files),
                              'total_uncompressed_bytes':sum(row['bytes'] for row in files.values())})
    with zipfile.ZipFile(ZIP,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(STAGE.rglob('*')):
            if path.is_file():bundle.write(path,str(path.relative_to(STAGE)))
    final_extract=WORK/'final_extracted'
    if final_extract.exists():raise FileExistsError('Preserve final-extraction evidence')
    with zipfile.ZipFile(ZIP) as bundle:
        assert bundle.testzip() is None
        assert len(bundle.namelist())==len(files)+1
        for name,info in files.items():
            assert hashlib.sha256(bundle.read(name)).hexdigest()==info['sha256'],name
        assert all(Path(name).suffix.lower() not in FORBIDDEN_SUFFIXES for name in bundle.namelist())
        bundle.extractall(final_extract)
    verification=subprocess.run([str(ROOT/'.venv/bin/python'),'-I','tools/verify_bundle.py'],
                               cwd=final_extract,text=True,capture_output=True,check=True)
    (WORK/'final_verification.log').write_text(verification.stdout+verification.stderr)
    receipt={**initial,'status':'VERIFIED','zip_bytes':ZIP.stat().st_size,'zip_sha256':sha(ZIP),
             'files':len(files)+1,'uncompressed_bytes':sum(row['bytes'] for row in files.values()),
             'extracted_package_checks':readiness,'final_extracted_all_file_hashes_verified':True}
    dump(WORK/'archive_receipt.json',receipt)
    print(json.dumps(receipt),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['build','finalize'],nargs='?',default='build')
    args=parser.parse_args();(build if args.phase=='build' else finalize)()
