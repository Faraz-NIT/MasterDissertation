"""Dataset-labelled empirical figures and simple conceptual diagrams for the rewrite."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
os.environ.setdefault('MPLCONFIGDIR','/tmp/ollama-dissertation-matplotlib')
os.environ.setdefault('XDG_CACHE_HOME','/tmp/ollama-dissertation-cache')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from config import ROOT,OUT,STUDY,read,sha

REGISTER=[]


def diagram(key,title,caption,body):
    folder=OUT/'figures';folder.mkdir(exist_ok=True)
    source='digraph Thesis { graph [rankdir=LR,bgcolor="white",pad=.2,nodesep=.3,ranksep=.4,label="M5 + RetailNet — '+title+'",labelloc=t,fontname="Arial",fontsize=18]; node [shape=box,style="rounded,filled",fontname="Arial",fontsize=14,color="#BDCBD4",fillcolor="#F2F6F9",margin=".15,.12"]; edge [color="#8194A2",arrowsize=.7]; '+body+' }'
    path=folder/(key+'.dot');path.write_text(source)
    for suffix in ['png','svg']:
        subprocess.run(['dot','-T'+suffix,'-Gdpi=180',str(path),'-o',str(folder/(key+'.'+suffix))],check=True,capture_output=True)
    REGISTER.append({'key':key,'dataset':'M5 + RetailNet','title':title,'caption':caption,'kind':'conceptual illustration; not an empirical outcome','path':'figures/'+key+'.png','sha256':sha(folder/(key+'.png'))})


def main():
    if read(STUDY/'analysis/audit_receipt.json')['status']!='VERIFIED':raise RuntimeError('Completed evidence must be verified')
    diagrams=[
        ('decision_cycle','From information to an order','Conceptual retail decision process used to explain the business problem; applies to both datasets.',
         'a [label="Current information"]; b [label="Expected sales"]; c [label="Order calculation"]; d [label="Release checks"]; e [label="Stock and service"]; a -> b -> c -> d -> e;'),
        ('evidence_layers','What is observed and what is modelled','Conceptual evidence categories. Retail sales are released observations; forecasts are fitted outputs; inventories, supplier events and costs are simulation assumptions.',
         'a [label="Observed\nReleased retail sales",fillcolor="#E8F0F6"]; b [label="Predicted\nPast-only sales forecast"]; c [label="Assumed\nStock, suppliers and costs",fillcolor="#F7F0E8"]; d [label="Measured in simulation\nService, index and expiry",fillcolor="#EAF4EF"]; a -> b; b -> d; c -> d;'),
        ('shared_components','The comparison that isolates the LLM layer','Conceptual comparison: both routes share the numerical planning capability. Already-structured inputs are an idealised reference; staff preparation time is not measured.',
         'a [label="Structured current inputs"]; b [label="Supplier text + LLM roles",fillcolor="#F3EDF7"]; c [label="Same numerical planner"]; d [label="Common execution limits"]; a -> c; b -> c; c -> d;'),
        ('study_map','The completed study design','Design schematic from the frozen protocol. Thirty series are used jointly in every dataset portfolio decision; model-call count applies only to the agent policy.',
         'a [label="M5\n30 selected series",fillcolor="#E7EFF7"]; b [label="RetailNet\n30 selected series",fillcolor="#E8F4EE"]; c [label="2 weeks × 3 situations\n× 30 seeds"]; d [label="3 policies\n1,080 runs"]; e [label="7,560 fresh\nOllama calls"]; a -> c; b -> c; c -> d -> e;'),
        ('adoption_path','A proposed adoption path','Managerial recommendation, not a completed deployment: move between stages only after measuring interpretation quality, review effort and operational consequences.',
         'a [label="Shadow recommendations\nCompare with current work"]; b [label="Reviewed pilot\nMeasure exceptions and effort"]; c [label="Bounded routine release\nRetain limits and monitoring",fillcolor="#E8F4EE"]; a -> b -> c;')]
    for args in diagrams:diagram(*args)
    original=read(STUDY/'figure_register.json')['figures']
    mapping={
        '01_agent_workflow':('agent_workflow','Three language-model roles with numerical planning and release checks'),
        '02_dataset_profiles':('dataset_profiles','Recorded sales and the shared forecast in the two test weeks'),
        '03_fill_rate':('m5_fill','Customer-demand fulfilment by operating situation'),
        '04_fill_rate':('retailnet_fill','Customer-demand fulfilment by operating situation'),
        '05_operating_cost':('m5_cost','Inventory operating cost by operating situation'),
        '06_operating_cost':('retailnet_cost','Inventory operating cost by operating situation'),
        '07_daily_service':('m5_daily','Service through each simulated week'),
        '08_daily_service':('retailnet_daily','Service through each simulated week'),
        '09_retailnet_expiry':('retailnet_expiry','Fresh-stock expiry by operating situation'),
        '10_cost_components':('cost_components','Components of the inventory operating-cost index'),
        '11_source_accuracy':('source_accuracy','Supplier-reading accuracy across the controlled formats'),
        '12_model_latency':('model_latency','Local model-call latency by role'),
        '13_paired_effects':('paired_service','Paired effects on demand fulfilment'),
        '14_paired_effects':('paired_cost','Paired effects on the operating-cost index'),
        '15_holds':('holds','Held decisions in the completed study')}
    for f in original:
        key,title=mapping[f['name']];source=STUDY/f['path']
        if sha(source)!=f['sha256']:raise RuntimeError('Source figure changed')
        target=OUT/'figures'/(key+'.png');shutil.copyfile(source,target)
        REGISTER.append({'key':key,'dataset':f['dataset'],'title':title,'caption':f['caption'],
            'kind':'empirical study figure' if key!='agent_workflow' else 'evaluated architecture',
            'path':str(target.relative_to(OUT)),'sha256':sha(target),'source':str(source.relative_to(ROOT)),'source_sha256':f['sha256']})
    days=pd.read_csv(STUDY/'analysis/daily_results.csv');agents=days[days.arm=='llm_agents'];values=[]
    for dataset in ['M5','RetailNet']:
        group=agents[agents.dataset==dataset];active=group[(group.scenario=='promotion')&(group.day>=2)]
        values.append({'dataset':dataset,'all_days':len(group),'all_correct':int(group.priority_correct.sum()),
            'active_days':len(active),'active_correct':int(active.priority_correct.sum())})
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':14,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(9.4,4.5));x=np.arange(2)
    for i,r in enumerate(values):
        ax.bar(x+(i-.5)*.32,[100*r['all_correct']/r['all_days'],100*r['active_correct']/r['active_days']],.32,
            color=['#24548A','#27775D'][i],label=r['dataset'])
    ax.set_xticks(x,['All trading days','Active-promotion days']);ax.set_ylabel('Expected priority selected (%)');ax.set_ylim(0,105)
    ax.set_title('M5 + RetailNet — selecting the business priority',fontweight='bold');ax.legend(frameon=False);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    path=OUT/'figures/priority_accuracy.png';fig.savefig(path,dpi=180,bbox_inches='tight',facecolor='white');plt.close(fig)
    REGISTER.append({'key':'priority_accuracy','dataset':'M5 + RetailNet','title':'Correct selection of the declared business priority',
        'caption':'Complete audited agent decisions: 1,260 total days and 300 active-promotion days per dataset. Overall accuracy is 98.97% for M5 and 87.46% for RetailNet; active-promotion accuracy is 96.33% and 47.33%, respectively. The difference exposes policy-selection errors despite accurate supplier reading.',
        'kind':'additional empirical summary of audited decisions','path':str(path.relative_to(OUT)),'sha256':sha(path),'plotted_values':values})
    input_paths=[STUDY/'protocol.json',STUDY/'execution_receipt.json',STUDY/'analysis/audit_receipt.json',STUDY/'data/preparation_receipt.json',STUDY/'figure_register.json']
    input_paths.extend((STUDY/'analysis').glob('*.csv'));input_paths.append(STUDY/'analysis/overall_effects.json')
    register={'figures':REGISTER,'inputs':{str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in input_paths}}
    (OUT/'figure_register.json').write_text(json.dumps(register,indent=2)+'\n')
    print(json.dumps({'figures':len(REGISTER),'additional_priority_values':values}))


if __name__=='__main__':main()
