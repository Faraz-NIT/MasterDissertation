"""A contribution chapter that distinguishes architecture evidence from port validation."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
from datetime import datetime,timezone
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches,Pt,RGBColor

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'study_results/langchain_extension_20261014'
PRIOR = ROOT/'study_results/architecture_study_20261013'
DOCX = OUT/'LangChain_Agent_Contribution_Chapter.docx'


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def figures(validation):
    folder = OUT/'figures'; folder.mkdir(exist_ok=True)
    dot = '''digraph architecture {
      graph [rankdir=TB, newrank=true, bgcolor="white", nodesep=.45, ranksep=.42, dpi=180];
      node [shape=box, style="rounded,filled", fillcolor="#F4F8FA", color="#97A9B2", fontname="Arial", fontsize=12, margin=".18,.12"];
      edge [color="#97A9B2", arrowsize=.65];
      subgraph cluster_old { label="Previous fixed agent"; fontname="Arial"; fontsize=14; color="#D8E1E5"; style=rounded;
        a1 [label="Supplier reader (LLM)\\n+ source verification"];
        a2 [label="Priority coordinator (LLM)"];
        a3 [label="Shared numerical planner"];
        a4 [label="Critic (LLM) every day\\n+ hard release checks"];
        a1 -> a2 -> a3 -> a4;
      }
      subgraph cluster_new { label="Selective LangChain extension"; fontname="Arial"; fontsize=14; color="#D8E1E5"; style=rounded;
        b1 [label="Supplier intake\\nTable parser or LLM reader"];
        b2 [label="Source verification\\n+ explicit priority router"];
        b3 [label="Same numerical planner"];
        b4 [label="Checks pass: release\\nChecks fail: hold + LLM review"];
        b1 -> b2 -> b3 -> b4;
      }
      {rank=same; a1;b1;} {rank=same;a2;b2;} {rank=same;a3;b3;} {rank=same;a4;b4;}
    }'''
    (folder/'agent_extension.dot').write_text(dot)
    for extension in ['png','svg']:
        subprocess.run(['dot','-T'+extension,str(folder/'agent_extension.dot'),'-o',str(folder/('agent_extension.'+extension))],check=True)
    register = [{'key':'agent_extension','path':'figures/agent_extension.png','title':'Building on the previous replenishment agent',
                 'scope':'Architecture','caption':'The reader, numerical planner and hard release controls are retained. Delegation and priority selection change. LangChain implements the extension with conditional runnable branches and a planning tool.'}]
    originals = json.loads((PRIOR/'figure_register.json').read_text())['figures']
    for figure in originals[1:]:
        shutil.copyfile(PRIOR/figure['path'],OUT/figure['path'])
        figure = dict(figure)
        figure['caption'] = 'Completed 30-seed architecture study, executed with LangGraph. '+figure['caption']
        figure['source_sha256'] = sha(PRIOR/figure['path'])
        register.append(figure)
    diagnostics = {(r['dataset'],r['arm']):r for r in validation['diagnostics']}
    fig,axes = plt.subplots(1,2,figsize=(9,3.4),layout='constrained')
    for ax,dataset in zip(axes,['M5','RetailNet']):
        values = [diagnostics[(dataset,arm)]['mean_decision_seconds'] for arm in ['fixed_agents','selective_agents']]
        ax.bar(['Previous fixed agent','LangChain extension'],values,color=['#92A5AF','#397F9E'],width=.6)
        ax.set_title(dataset,fontsize=13); ax.set_ylabel('Mean decision time (seconds)')
        ax.set_ylim(0,max(values)*1.22); ax.spines[['top','right']].set_visible(False)
        ax.tick_params(axis='x',labelsize=9)
        for index,value in enumerate(values): ax.text(index,value+.04,f'{value:.2f} s',ha='center',fontsize=10)
    fig.savefig(folder/'fresh_langchain_validation.png',dpi=200); plt.close(fig)
    register.append({'key':'fresh_langchain_validation','path':'figures/fresh_langchain_validation.png',
                     'title':'Fresh LangChain execution check','scope':'M5 + RetailNet',
                     'caption':'Both workflows use LangChain in this fresh, one-seed validation. Thirty series per dataset, two weeks and three scenarios are covered. Times are descriptive; this small check supplies no new confidence intervals.'})
    (OUT/'figure_register.json').write_text(json.dumps({'figures':register,'primary_source':str(PRIOR.relative_to(ROOT))},indent=2)+'\n')
    return register


def draft(primary,validation,replay):
    diagnostics = {(r['dataset'],r['arm']):r for r in primary['diagnostics']}
    effects = {(r['dataset'],r['metric']):r for r in primary['paired_effects']
               if r['scenario']=='overall' and r['comparison']=='fixed_agents'}
    fresh = {(r['dataset'],r['arm']):r for r in validation['diagnostics']}
    tables = {
        'changes':{'title':'What changes and what is retained','headers':['Component','Previous agent','Selective extension'],'rows':[
            ['Supplier information','LLM reads every message','Parser for complete declared tables; LLM for prose'],
            ['Business priority','LLM selects the priority','Router applies the announced business policy'],
            ['Numerical planning','Constrained planning tool','Same tool, exposed as a LangChain StructuredTool'],
            ['Critic and release','LLM critic on every decision; hard checks retained','LLM review on failed checks; failed actions held'],
            ['Model and forecasts','Local pretrained model; past-only forecasts','Same model, prompts and forecasts'],
        ]},
        'results':{'title':'Completed architecture study: selective extension versus the previous fixed agent',
                   'headers':['Dataset','Declared-priority accuracy: previous / selective','Model-call reduction','Decision-time reduction','Inventory result'],'rows':[]},
        'hypotheses':{'title':'Architecture hypotheses in the completed 30-seed study',
                      'headers':['Hypothesis','M5','RetailNet'],'rows':[
            ['A1: At least 50% fewer model calls','Supported','Supported'],
            ['A2: Lower mean decision time','Supported','Supported'],
            ['A3: Preserved/improved priority accuracy and no released violations','Supported','Supported'],
            ['A4: Preserve service and cost within the stated study tolerances','Supported','Supported'],
        ]},
        'validation':{'title':'Fresh LangChain implementation validation; one new simulation seed',
                      'headers':['Dataset','Priority accuracy: previous / selective','Native calls: previous / selective','Released rule violations'],'rows':[]},
    }
    for dataset in ['M5','RetailNet']:
        old,new = diagnostics[(dataset,'fixed_agents')],diagnostics[(dataset,'selective_agents')]
        call_reduction = 100*(1-new['fresh_model_calls']/old['fresh_model_calls'])
        latency = 100*(1-new['mean_decision_seconds']/old['mean_decision_seconds'])
        inventory = ('Service and cost essentially unchanged' if dataset=='M5' else
                     f"Fill +{effects[(dataset,'fill_rate')]['mean']:.2f} pp; cost {effects[(dataset,'cost_per_demand')]['mean']:.2f}%")
        tables['results']['rows'].append([dataset,f"{100*old['priority_accuracy']:.2f}% / {100*new['priority_accuracy']:.2f}%",
                                          f'{call_reduction:.1f}%',f'{latency:.1f}%',inventory])
        old,new = fresh[(dataset,'fixed_agents')],fresh[(dataset,'selective_agents')]
        tables['validation']['rows'].append([dataset,f"{100*old['priority_accuracy']:.2f}% / {100*new['priority_accuracy']:.2f}%",
                                             f"{old['fresh_model_calls']} / {new['fresh_model_calls']}",str(new['violations'])])
    primary_m5 = effects[('M5','fill_rate')]['mean']
    retail_fill = effects[('RetailNet','fill_rate')]['mean']
    retail_cost = effects[('RetailNet','cost_per_demand')]['mean']
    retail_expiry = effects[('RetailNet','expiry_share')]['mean']
    text = f'''# Extending the Replenishment Agent: A LangChain Contribution

## 1. Building on the previous dissertation

The earlier chapters developed an agent-assisted replenishment system with three language-model roles: a supplier reader, a coordinator and a critic. The reader extracted supplier terms, the coordinator selected a business priority, and the critic reviewed a proposed order. A numerical planning tool calculated the quantities. This system provided the starting point for the extension presented here.

The previous study showed that these roles did not contribute equally. The model read the controlled supplier messages reliably, but it sometimes selected the wrong priority during promotions, particularly in RetailNet. At the same time, calling every role on every decision added processing time. These findings suggested a focused architectural improvement: retain the useful components and change how work is assigned between them.

My contribution is the design and evaluation of a selective-delegation extension to the replenishment agent. The extension decides when language interpretation is needed, applies known business policies consistently, and requests model review when checks fail. LangChain supplies the software components for this implementation. The contribution lies in their arrangement for replenishment and in the evidence about the resulting decisions.

The additional research question is: how far can selective delegation improve the reliability and efficiency of the existing LLM-agent replenishment system while preserving inventory performance? This question treats the earlier agent as the baseline and keeps the model, forecasts and numerical planner constant.

## 2. What the extension changes

The supplier reader remains available for prose messages. A complete table in the declared format can instead be read by a strict parser. The parser reads the message itself; it does not obtain missing values from the reference record. A malformed table requests review. Both routes retain the existing check against authenticated current supplier information.

The coordinator's business-priority decision becomes an explicit policy route. When an active promotion has been announced, the system uses the declared availability-focused policy. Otherwise, it uses the balanced policy. A missing or ambiguous promotion flag prevents automatic release. This is an instruction known before ordering, rather than information taken from future demand.

The numerical planner remains unchanged. It calculates feasible quantities under the budget, supplier capacity, carton-size and minimum-order rules. The extension also retains the existing hard release checks. It changes the critic's workload: valid routine decisions proceed after the checks, while failed or unknown conditions are held and referred to the LLM review role. An approving model response cannot release an order that fails those checks. Human resolution of review requests is outside the simulation.

[[TABLE:changes]]

[[FIGURE:agent_extension]]

The extension therefore builds directly on the previous agent. It assigns interpretation to the language model, declared priorities to a policy router, quantities to the numerical tool and release authority to explicit checks. Each responsibility can be examined separately when a decision is questioned.

## 3. Implementation with LangChain

The implementation uses LangChain's core library, version 1.6.10. Runnable sequences connect the stages, and conditional runnable branches select the supplier and review paths. The existing numerical planner is exposed as a StructuredTool. Each decision records the steps visited, the reason for delegation, the extracted fields, the selected priority and the proposed and released orders.

The original supplier, coordinator and critic prompts are retained. Local model calls use the same native interface and generation settings as before. This preserves the model comparison while adding explicit LangChain orchestration. Conversation memory, response caching, retries and external tracing are disabled. The three comparison workflows are all executed through the same LangChain chain during the fresh validation.

The model is Qwen2.5:1.5b, a pretrained language model in Q4_K_M quantisation, served locally with Ollama 0.40.0. It was used for inference and was not trained or fine-tuned on M5 or RetailNet. The cloud instance allocated four CPU cores and 32 GiB of memory, with no GPU. Python 3.12 and past-only LightGBM forecasts supported the experiment. Model settings used temperature zero, a fixed generation seed, a 4,096-token context and three inference threads.

## 4. Evaluation and evidence

The architecture evidence comes from the completed matched study: thirty selected series from each dataset, two seven-day windows, three operating situations and thirty simulation seeds. The situations are routine trading, supplier disruption and promotion. Three workflows produce 1,080 policy runs: the previous fixed agent, the selective extension and the same numerical planner with already structured supplier information. Opening stock, demand and supplier opportunities are matched within each case. The previous agent is rerun as the matched baseline using seeds 201–230, so its values can differ from those in the earlier dissertation experiment.

The full architecture comparison uses the LangGraph implementation. The LangChain version is assessed separately below, and the two sets of evidence are labelled throughout. All four architecture success conditions were stated before the main runs: fewer calls, faster decisions, preserved or improved policy accuracy without released violations, and preserved service and cost within the study's stated tolerances.

Two further checks establish the LangChain implementation. First, a recorded-response regression supplies archived model outputs to the new chain and reconstructs all {replay['portfolio_decisions']:,} earlier portfolio decisions. Orders, priorities, role paths and inventory outcomes match the earlier implementation throughout. This is a software consistency check and performs no new model inference.

Second, fresh local-model validation uses one new simulation seed, all thirty series per dataset, both windows and all three situations. It completes 36 matched policy runs and 252 portfolio decisions. Every native request and response is saved. This check confirms live execution of the LangChain implementation; its single seed does not support a fresh confidence-interval study. The completed 30-seed study remains the principal performance evidence.

Sixteen relevant engineering tests pass, covering delegation, malformed inputs, priority routing, planning-tool execution and guarded release. The fresh records also pass an independent inventory-ledger audit and checks of the native model requests, decision paths and released quantities.

## 5. Results in plain terms

### 5.1 Substantial gains in efficiency and policy reliability

In the completed architecture study, selective delegation reduced native model calls by 77.8% and mean decision time by about 55% in both datasets. These are substantial improvements in the amount of model processing needed for replenishment. Every supplier record was extracted correctly in the tested messages. The selective architecture applied the declared priority correctly on every decision, with no released rule violations.

RetailNet provides the clearest reliability improvement: declared-priority accuracy rose from 86.90% to 100%, a gain of 13.10 percentage points. During active promotions, it rose from 45% to 100%. M5 also reached 100%, although the previous agent was already close to that level. These scores measure adherence to the announced business instruction; inventory outcomes are assessed separately below.

[[TABLE:results]]

[[FIGURE:model_calls]]

[[FIGURE:decision_time]]

[[FIGURE:priority_accuracy]]

The important operational change is fewer opportunities for an unnecessary model decision. For a promotion whose priority has already been specified, the system applies that instruction directly. The model's contribution remains the interpretation of supplier prose and assistance with exceptional conditions.

### 5.2 M5: preserved inventory performance

For M5, selective delegation produced essentially the same service and cost performance as the previous fixed agent. The estimated fill-rate change was {primary_m5:+.3f} percentage points, and the paired intervals did not establish a service or cost improvement. The benefit was a simpler execution path with fewer model calls and faster decisions while retaining the planning outcome.

### 5.3 RetailNet: a small service and cost improvement

For RetailNet, the selective architecture improved fill rate by {retail_fill:.2f} percentage points and reduced the simulated operating-cost index by {abs(retail_cost):.2f}%. The paired intervals supported both improvements within the studied weeks. The change was associated with more consistent application of the announced promotion policy.

The improvement also involved a trade-off. Expiry share increased by {retail_expiry:.2f} percentage points overall, concentrated in promotions. More stock helped availability, but some additional stock expired in the hypothetical three-day shelf-life process. The cost index still fell because fewer missed sales outweighed the added expiry under the chosen weights.

[[FIGURE:inventory_effects]]

[[FIGURE:retailnet_expiry]]

The selective architecture matched the structured-information planner's orders throughout the main study. This shows that it connected the tested supplier messages to the reference planning behaviour. It does not establish an additional inventory advantage over a planner that already receives correct structured inputs.

### 5.4 What the LangChain validation confirms

The fresh LangChain check confirms the implementation on both datasets. Its supplier accuracy, priority accuracy, call counts and released-rule checks are shown separately below. These are observed execution results from one seed, rather than a replacement for the main study's estimates.

[[TABLE:validation]]

[[FIGURE:fresh_langchain_validation]]

All requests, responses, decisions, source fields and quantity checks are retained alongside the code. The recorded-response regression establishes that the framework change preserves the earlier decision logic when the model outputs are held constant. The fresh check establishes that the chain also runs with live local-model responses.

## 6. The contribution and its limits

The four architecture hypotheses were supported in the completed 30-seed study. Preservation of inventory performance used prospectively stated study tolerances: a fill-rate reduction below 0.10 percentage points and a cost increase below 0.5%, assessed through the paired interval bounds. These are study criteria and were not supplied by a retailer.

[[TABLE:hypotheses]]

The contribution is an evaluated extension of the existing agent, with a reusable LangChain implementation and a complete decision record. It improves computational efficiency and policy reliability. RetailNet also shows a small inventory benefit, while M5 retains its inventory performance. These specific findings define the scope of the contribution.

The historical windows were inspected during design and are not unseen holdouts. Seeds describe simulated demand and supply variation, not independent models. The evidence covers selected series and controlled supplier formats. Costs, supply and shelf lives are simulated, and RetailNet quantities are normalised sales proxies. Retailer profit and employee time are unmeasured.

Source verification needs reliable current supplier records. The main cases required no unresolved exceptions; hold behaviour was tested separately. Incomplete or contradictory real messages may need employee judgement and provide an important further test of the architecture.

## 7. Conclusion and future research

Building on the earlier agent produced a clear architectural improvement: fewer model calls, shorter processing time and more consistent application of the declared business policy. Inventory performance was preserved for M5 and improved modestly for RetailNet, with a small increase in expiry. LangChain makes the extension explicit and reproducible, and separate checks establish its consistency with the tested architecture.

Future research should test unfamiliar messages, new trading periods and longer shelf-life simulations. A pilot should measure employees' checking and review time. Retaining the same planner would help isolate the practical value of selective delegation in everyday retail work.
'''
    return text.strip()+'\n',tables


def build():
    primary = json.loads((PRIOR/'analysis/analysis_summary.json').read_text())
    validation = json.loads((OUT/'analysis/validation_summary.json').read_text())
    replay = json.loads((OUT/'development/recorded_response_replay.json').read_text())
    assert json.loads((PRIOR/'analysis/audit_receipt.json').read_text())['status']=='VERIFIED'
    assert json.loads((OUT/'analysis/audit_receipt.json').read_text())['status']=='VERIFIED'
    assert replay['status']=='PASS' and primary['all_registered_success_conditions_met']
    register = {f['key']:f for f in figures(validation)}
    manuscript,tables = draft(primary,validation,replay)
    (OUT/'chapter.md').write_text(manuscript)
    (OUT/'chapter_tables.json').write_text(json.dumps(tables,indent=2)+'\n')
    evidence = OUT/'primary_evidence'; evidence.mkdir(exist_ok=True)
    for name in ['analysis_summary.json','audit_receipt.json','paired_effects.csv','overall_seed_results.csv']:
        shutil.copyfile(PRIOR/'analysis'/name,evidence/name)
    sources = {'primary_protocol':PRIOR/'protocol.json','primary_audit':PRIOR/'analysis/audit_receipt.json',
               'primary_analysis':PRIOR/'analysis/analysis_summary.json','langchain_protocol':OUT/'protocol.json',
               'langchain_audit':OUT/'analysis/audit_receipt.json','recorded_response_regression':OUT/'development/recorded_response_replay.json'}
    (OUT/'evidence_map.json').write_text(json.dumps({name:{'path':str(path.relative_to(ROOT)),'sha256':sha(path)} for name,path in sources.items()},indent=2)+'\n')
    doc = Document(); section = doc.sections[0]
    section.page_width,section.page_height = Inches(8.2677),Inches(11.6929)
    section.top_margin=section.bottom_margin=section.left_margin=section.right_margin=Inches(1)
    section.header_distance=section.footer_distance=Inches(.45)
    for style in doc.styles:
        if style.type in [1,2]: style.font.name='Times New Roman'
    for fonts in doc.styles.element.iter(qn('w:rFonts')):
        for attr in list(fonts.attrib):
            if 'theme' in attr.lower(): del fonts.attrib[attr]
    normal=doc.styles['Normal'];normal.font.size=Pt(12)
    normal.paragraph_format.line_spacing=1.5;normal.paragraph_format.space_after=Pt(4)
    normal.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
    normal.paragraph_format.widow_control=True
    for name,size in [('Heading 1',16),('Heading 2',13),('Heading 3',12)]:
        style=doc.styles[name];style.font.size=Pt(size);style.font.bold=True
        style.font.color.rgb=RGBColor.from_string('20343D')
        style.paragraph_format.line_spacing=1.15;style.paragraph_format.keep_with_next=True
        style.paragraph_format.space_before=Pt(12);style.paragraph_format.space_after=Pt(7)
    caption=doc.styles['Caption'];caption.font.size=Pt(10.5);caption.font.bold=False
    caption.font.color.rgb=RGBColor.from_string('20343D')
    caption.paragraph_format.line_spacing=1.1;caption.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.LEFT
    section.header.paragraphs[0].text='AGENT ARCHITECTURE CONTRIBUTION | M5 AND RETAILNET'
    section.header.paragraphs[0].alignment=WD_ALIGN_PARAGRAPH.RIGHT
    for run in section.header.paragraphs[0].runs:run.font.size=Pt(9)
    footer=section.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run('Page ');field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    figure_count=table_count=0
    for line in manuscript.splitlines():
        if not line.strip():continue
        heading=re.match(r'^(#{1,3}) (.*)',line)
        if heading:doc.add_heading(heading[2],level=len(heading[1]))
        elif line.startswith('[[FIGURE:'):
            figure_count+=1;figure=register[line[9:-2]]
            p=doc.add_paragraph(style='Caption');p.paragraph_format.keep_with_next=True
            p.add_run(f"Figure {figure_count}. {figure['scope']}: {figure['title']}").bold=True
            p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.line_spacing=1;p.paragraph_format.keep_with_next=True
            p.add_run().add_picture(str(OUT/figure['path']),width=Inches(6.2))
            p=doc.add_paragraph(figure['caption'],style='Caption');p.paragraph_format.keep_together=True
        elif line.startswith('[[TABLE:'):
            table_count+=1;data=tables[line[8:-2]]
            p=doc.add_paragraph(style='Caption');p.paragraph_format.keep_with_next=True
            p.add_run(f"Table {table_count}. {data['title']}").bold=True
            table=doc.add_table(rows=0,cols=len(data['headers']));table.style='Table Grid'
            for i,row in enumerate([data['headers'],*data['rows']]):
                cells=table.add_row().cells;node=OxmlElement('w:cantSplit');table.rows[i]._tr.get_or_add_trPr().append(node)
                if i==0:
                    repeat=OxmlElement('w:tblHeader');table.rows[i]._tr.get_or_add_trPr().append(repeat)
                for cell,value in zip(cells,row):
                    cell.text=str(value)
                    for p in cell.paragraphs:
                        p.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.LEFT
                        p.paragraph_format.line_spacing=1.1;p.paragraph_format.space_after=Pt(4)
                        for run in p.runs:run.font.size=Pt(10);run.bold=i==0
            doc.add_paragraph().paragraph_format.space_after=Pt(0)
        else:doc.add_paragraph(line)
    doc.core_properties.title='Extending the Replenishment Agent: A LangChain Contribution'
    doc.core_properties.subject='One contribution chapter, separating full architecture evidence from LangChain validation'
    doc.core_properties.author=''
    doc.core_properties.modified=datetime.now(timezone.utc).replace(tzinfo=None)
    doc.save(DOCX)
    manifest={'status':'BUILT_PENDING_RENDER','scope':'One chapter extending the previous agent',
              'prose_words':len(re.findall(r"\b[\w’'-]+\b",'\n'.join(line for line in manuscript.splitlines() if not line.startswith(('#','[['))))),
              'figures':figure_count,'tables':table_count,'docx_sha256':sha(DOCX),'chapter_sha256':sha(OUT/'chapter.md'),
              'primary_performance_framework':'LangGraph','new_implementation_framework':'LangChain LCEL',
              'primary_runs':1080,'fresh_langchain_validation_runs':36,'recorded_regression_decisions':7560,
              'format':{'font':'Times New Roman','body_points':12,'line_spacing':1.5,'margins_inches':1}}
    (OUT/'build_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest))


if __name__=='__main__':build()
