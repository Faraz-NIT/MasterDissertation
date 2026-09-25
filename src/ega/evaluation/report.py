"""Standalone local HTML reports; no CDN, API key, network request or hosted service."""
from __future__ import annotations
import html
import json
from pathlib import Path
import pandas as pd
from ..store import ArtifactStore

CSS="""
body{font:15px/1.55 system-ui,sans-serif;background:#f4f6f7;color:#14252d;margin:0;padding:36px}
main{max-width:1250px;margin:auto}h1{font-size:36px;line-height:1.15;margin:0 0 12px}.eyebrow{letter-spacing:.15em;text-transform:uppercase;font-size:12px;color:#396a73}
.card{background:white;border:1px solid #d8e2e5;border-radius:12px;padding:24px;margin:20px 0;overflow:auto}
.notice{background:#fff8e5;border-left:4px solid #d4a026;padding:16px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid #e3e8eb}th{background:#eef4f5}
pre{white-space:pre-wrap;word-break:break-word;background:#f1f5f6;padding:16px;font-size:12px}summary{cursor:pointer;font-weight:650;padding:12px 0}.subtle{color:#63767e}footer{margin-top:35px;color:#63767e}
"""

def render_report(root,output=None):
    root=Path(root);output=Path(output) if output else root/'report.html'
    df=pd.read_csv(root/'summary.csv');study=json.loads((root/'study_summary.json').read_text())
    synthetic=False;traces=[]
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder/'trace_index.json').exists():continue
        manifest=json.loads((folder/'run_manifest.json').read_text());synthetic|=manifest['data'].get('synthetic',False)
        index=json.loads((folder/'trace_index.json').read_text());store=ArtifactStore(folder/'artifacts')
        for entry in index[:3]:
            trace=store.get(entry['trace_ref']);cert=store.get(trace['references']['certify_state']);plan=store.get(trace['references']['propose'])
            fields={'lineage':trace['lineage'],'state_quality':cert['quality'],'failed_checks':[c for c in cert['checks'] if c['outcome']!='pass'],
                    'autonomy':trace['autonomy'],'orders':plan['orders'],'transfers':plan['transfers'],'solver':plan['solver'],
                    'fallback':trace['fallback'],'errors':trace['errors'],'trace_ref':entry['trace_ref']}
            label=html.escape(f"{trace['policy']} · {manifest['scenario']} · day {trace['day']} · quality {cert['quality']:.2f}")
            traces.append(f'<details><summary>{label}</summary><pre>{html.escape(json.dumps(fields,indent=2))}</pre></details>')
        store.close()
    table=pd.DataFrame(study['results']).round(4).to_html(index=False,escape=True,border=0)
    warning='SYNTHETIC SOFTWARE DEMONSTRATION — not M5 results and not dissertation evidence.' if synthetic else 'M5-based simulation. Inventory, supply and constraints are synthetic; check calibration and replication counts.'
    page=f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evidence-gated replenishment — experiment report</title><style>{CSS}</style><main>
<p class="eyebrow">Evidence-gated autonomy / research workbench</p><h1>Replenishment experiment & audit report</h1>
<p class="subtle">A decision is only as reliable as the evidence it uses.</p><div class="notice">{html.escape(warning)}</div>
<section class="card"><h2>Study outcomes</h2><p>{len(df)} policy/scenario/seed/origin runs. Costs, service and safety must be read together.</p>{table}</section>
<section class="card"><h2>Lineage-first decision inspection</h2><p>First three decisions per run. Complete trace indexes and artifacts are stored alongside this report.</p>{''.join(traces)}</section>
<footer>Simulator-only execution. Local content hashes are tamper-evident, not cryptographic proof of trusted authorship. No model reasoning transcript is claimed.</footer></main></html>"""
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(page,encoding='utf8');return output
