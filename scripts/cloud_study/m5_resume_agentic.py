#!/usr/bin/env python3
"""Prepare the real local model, freeze its digest, then resume M5 agentic studies."""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path('/workspace/MasterDissertation')
PY = ROOT / '.venv/bin/python'
OLLAMA = Path('/workspace/tools/ollama/bin/ollama')
sys.path.insert(0, '/workspace/tools')
from m5_parallel import status
import yaml


def run(command, log):
    log = ROOT / 'results/logs' / log
    with log.open('a') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, env=dict(os.environ),
                       stdout=stream, stderr=subprocess.STDOUT, check=True)


def api(path):
    with urllib.request.urlopen('http://127.0.0.1:11434' + path, timeout=15) as response:
        return json.load(response)


def main():
    os.chdir(ROOT)
    os.environ['OLLAMA_HOST'] = '127.0.0.1:11434'
    stages = ['llm_architectures_ollama', 'llm_prose_study_ollama']
    try:
        api('/api/version')
        tags = api('/api/tags')['models']
        if not any(m['name'] == 'llama3.2:3b' for m in tags):
            run([OLLAMA, 'pull', 'llama3.2:3b'], 'ollama_model_pull.log')
        if not any(m['name'] == 'ega-llama3.2:3b' for m in tags):
            run([OLLAMA, 'create', 'ega-llama3.2:3b', '-f', 'configs/Modelfile.llama'],
                'ollama_model_create.log')
        model = next(m for m in api('/api/tags')['models'] if m['name'] == 'ega-llama3.2:3b')
        revision = model['digest']
        for stage in stages:
            path = ROOT / 'results/run_configs' / (stage + '.yaml')
            cfg = yaml.safe_load(path.read_text())
            previous = cfg['llm']['model_revision']
            if previous not in ['PENDING_LOCAL_MODEL_DOWNLOAD', revision]:
                raise RuntimeError('Local model digest changed; keep frozen study or choose new outputs')
            cfg['llm']['model_revision'] = revision
            path.write_text(yaml.safe_dump(cfg))
            status(stage, state='prepared', status='prepared', blocker=None, model_revision=revision)
        protocol_path = ROOT / 'results/run_configs/execution_protocol.json'
        protocol = json.loads(protocol_path.read_text())
        previous = protocol['model_revision']
        if previous != 'pending download; freeze before evaluation' and previous != revision:
            raise RuntimeError('Frozen protocol model digest changed')
        protocol['model_revision'] = revision
        protocol_path.write_text(json.dumps(protocol, indent=2))
        # A structured functional request must succeed before expensive studies start.
        request = urllib.request.Request('http://127.0.0.1:11434/v1/chat/completions',
            data=json.dumps({'model': model['name'], 'messages': [{'role':'user',
                'content':'Return the integer value 2 in the requested schema.'}],
                'temperature':0, 'max_tokens':128, 'response_format':{'type':'json_schema',
                'json_schema':{'name':'readiness','strict':True,'schema':{'type':'object',
                'properties':{'value':{'type':'integer'}},'required':['value'],
                'additionalProperties':False}}}}).encode(),
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request, timeout=300) as response:
            answer=json.load(response)
        assert json.loads(answer['choices'][0]['message']['content']) == {'value':2}, 'Model readiness response failed'
        (ROOT/'results/logs/ollama_functional_readiness.json').write_text(json.dumps(answer,indent=2))
        grounding = ROOT/'results/grounding_prose_ollama'
        if not grounding.exists():
            run([PY, 'scripts/grounding_benchmark.py', '--corpus','examples/grounding_prose.jsonl',
                 '--llm-config','results/run_configs/llm_prose_study_ollama.yaml',
                 '--output',str(grounding)],'grounding_prose_ollama.log')
        # Local inference is serialized; extra seed workers would add queue time.
        for stage in stages:
            run([PY,'/workspace/tools/m5_parallel.py','--config',
                 'results/run_configs/'+stage+'.yaml','--workers','1','--stage',stage],
                stage+'_driver.log')
        return 0
    except Exception as exc:
        for stage in stages:
            status(stage, state='blocked', status='blocked', blocker=str(exc))
        print('Local agentic execution blocked:',exc,file=sys.stderr)
        print('Check results/logs/ollama_model_pull.log and apply required model download domains in environment settings.',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
