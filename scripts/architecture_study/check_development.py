"""Reproducible tests and excluded invented-panel LangGraph integrations before freezing."""
from pathlib import Path
import json
import re
import subprocess
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run
from architecture import OUT, ROOT, base

folder = OUT / 'development'
if (folder / 'langgraph_integration_receipt.json').exists():
    raise FileExistsError('Preserve existing development receipts; use a fresh experiment folder')
command = [sys.executable,'-m','pytest','-q','tests/test_selective_architecture.py','tests/test_ollama_clean_study.py']
result = subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
(folder/'numerical_tests.log').write_text(result.stdout)
if result.returncode:
    raise RuntimeError(result.stdout)
match = re.search(r'(\d+) passed',result.stdout)
base.dump(folder/'numerical_tests.json',{'status':'PASS','checks':int(match[1]),'command':command,
                                      'at_utc':run.now(),'compiled_langgraph_checks':True})
summaries = []
for dataset,origin in [('M5',1927),('RetailNet',83)]:
    data = run.load(dataset,origin)
    toy = dict(data)
    toy['historical_mean'] = np.ones(30)*2
    toy['residual_sd'] = np.zeros(30)
    toy['forecast'] = np.ones((30,14))*2
    toy['sales'] = np.ones_like(data['sales'])*2
    original_out = run.OUT
    run.OUT = OUT/'development/langgraph_integration'
    try:
        local = run.run_case(toy,'promotion',903)
    finally:
        run.OUT = original_out
    assert all(r['actual_violations']==0 and r['held']==0 for r in local)
    assert next(r for r in local if r['arm']=='selective_agents')['priority_correct']==7
    summaries.extend(local)
base.dump(folder/'langgraph_integration_receipt.json',{'status':'PASS','at_utc':run.now(),
          'note':'Invented constant-demand panels; no primary evaluation outcomes','summaries':summaries})
(OUT/'architecture_graph.mmd').write_text(run.GRAPH.get_graph().draw_mermaid()+'\n')
print(json.dumps({'status':'PASS','numerical_checks':int(match[1]),'invented_panel_policy_runs':len(summaries)}))
