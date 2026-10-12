"""Readable tables derived only from the completed, independently audited study."""
from __future__ import annotations
import pandas as pd
from config import OUT,STUDY,read

ARMS=['conventional','structured_planner','llm_agents']
LABELS={'conventional':'Conventional ordering','structured_planner':'Structured-data planner','llm_agents':'Ollama agents'}


def overall():
    seeds=pd.read_csv(STUDY/'analysis/seed_results.csv')
    byseed=seeds.groupby(['dataset','arm','seed'])[['fill_rate','cost_per_demand','expiry_share']].mean()
    return byseed.groupby(['dataset','arm']).mean()


def get_refs():return [line.strip() for line in (OUT/'references.md').read_text().split('\n\n') if line.strip()]


def tables():
    p=read(STUDY/'protocol.json');means=overall();effects=read(STUDY/'analysis/overall_effects.json')
    forecast=pd.read_csv(STUDY/'analysis/shared_forecast_context.csv')
    headline=[]
    for dataset in ['M5','RetailNet']:
        for arm in ARMS:
            r=means.loc[(dataset,arm)]
            headline.append([dataset,LABELS[arm],f'{100*r.fill_rate:.2f}%',f'{r.cost_per_demand:.3f}',f'{100*r.expiry_share:.2f}%' if dataset=='RetailNet' else 'No expiry in horizon'])
    intervals=[]
    for r in effects:
        service=r['fill_effect_pp'];cost=r['cost_effect_pct']
        intervals.append([r['dataset'],LABELS[r['comparison']],f"{service['mean']:+.2f} [{service['ci_low']:+.2f}, {service['ci_high']:+.2f}]",f"{cost['mean']:+.2f}% [{cost['ci_low']:+.2f}%, {cost['ci_high']:+.2f}%]"])
    return {
        'study_scope':('M5 + RetailNet: completed experimental scope',['Element','Completed design'],[
            ['Selected panels','30 store–product series per dataset'],['Weekly episodes','Two separate seven-day origins per dataset'],
            ['Business situations','Routine trading; supplier disruption; promotion'],['Simulation variation','30 matched seeds'],
            ['Policies','Conventional; structured-data planner; Ollama agents'],['Completed policy episodes','1,080'],
            ['Portfolio / series-days','7,560 / 226,800'],['Fresh primary model calls','7,560 across 2,520 agent portfolio days']]),
        'dataset_panels':('M5 and RetailNet: source and selected-panel context',['Characteristic','M5','RetailNet'],[
            ['Quantity convention','Published unit sales','Published normalized sales × 100'],['Selected series','30','30'],
            ['Products / stores in panel','30 / 10','29 / 29'],['Selection basis','Training-only sales-volume strata','Training-only sales-volume strata'],
            ['Test period','9–22 May 2016','19 June–2 July 2024'],['Expiry assumption','None within the weekly horizon','Hypothetical three-day FIFO']]),
        'policy_comparison':('M5 + RetailNet: responsibilities of the three policies',['Policy','Information and planning responsibility'],[
            [LABELS['conventional'],'Current structured rules; order-up-to targets; proportionate limit allocation; aggregate inventory position'],
            [LABELS['structured_planner'],'Current structured rules; shared constrained tool; age projection; direct scenario-priority mapping'],
            [LABELS['llm_agents'],'Three Qwen calls for source reading, coordination and review; same numerical tool; source verification and release gate']]),
        'scenarios':('M5 + RetailNet: declared operating situations',['Situation','Change from the third simulated day'],[
            ['Routine trading','No event change; announced daily variation in limits'],
            ['Supplier disruption','Cartons and minimum orders double; delivery +1 day; capacity −30%'],
            ['Promotion','Announced +30% sales-proxy and forecast uplift; expected service-first tool priority']]),
        'model_environment':('M5 + RetailNet: model, training and computing environment',['Component','Actual setting'],[
            ['Computer','Linux; four allocated CPU cores; 32 GiB memory; no GPU'],
            ['Language model','Pretrained Qwen2.5 1.5B, served locally through Ollama'],['Retail fine-tuning','None; language-model inference only'],
            ['Forecast family','LightGBM; four primary fits using earlier retail history'],['Fitting / inference threads','One for numerical fitting; three for Qwen calls'],
            ['Live evaluation duration','2.66 hours; development and reporting additional'],['Costs not monetised','Compute, integration, staff review and production support']]),
        'headline_results':('M5 and RetailNet: overall measured policy outcomes',['Dataset','Policy','Demand fulfilled','Operating index / demand','Expired share'],headline),
        'technical_settings':('M5 + RetailNet: selected technical settings',['Item','Frozen setting'],[
            ['Model tag / representation',p['model']['tag']+' / '+p['model']['details']['quantization_level']],
            ['Ollama version',p['model']['ollama']['version']],['Working context / output limit','4,096 / 512 tokens'],
            ['Generation','Temperature 0; seed 20261009; three CPU threads'],['Response treatment','Native structured JSON; no retries or answer cache'],
            ['Forecast fit','LightGBM 150 trees; maximum depth 5; at most 365 historical days'],['Primary fitted windows','M5 origins 1927, 1934; RetailNet origins 83, 90'],
            ['Cost coefficients','0.02 holding; 5 unmet demand; 1 expired unit'],['Starting inventory','Rounded-up three historical average days; no initial pipeline'],
            ['Synthetic supply','2% cancellations; 10% partial fill at 80%; 10% extra-day delay'],['Main numerical packages','NumPy 2.3.5; pandas 2.2.3; SciPy 1.17.0; LightGBM 4.7.0'],
            ['Inference scope','One fixed pretrained model; three task-specific roles']]),
        'paired_intervals':('M5 and RetailNet: overall paired effects with 95% intervals',['Dataset','Comparator','Service change (points)','Cost change (%)'],intervals),
        'forecast_context':('M5 and RetailNet: the shared LightGBM forecast context',['Dataset','Weekly origin','WAPE','MAE'],[
            [r.dataset,str(r.origin),f'{r.wape_pct:.2f}%',f'{r.mae:.3f}'] for r in forecast.itertuples()]),
        'evidence_locations':('M5 + RetailNet: where to inspect the saved evidence',['Evidence','Location within the completed study folder'],[
            ['Prospective settings and code','protocol.json; frozen_code/'],['Selected panels and four primary fits','data/M5/origin_*/; data/RetailNet/origin_*/'],
            ['Raw model calls and physical decisions','runs/'],['Run, daily and seed tables; paired effects','analysis/'],
            ['Independent replay and numerical audit','analysis/audit_receipt.json'],['Complete primary execution','execution_receipt.json; logs/'],
            ['Verified experiment download','Fresh_Ollama_Study_download.zip'],['Study folder','study_results/ollama_clean_study_20261009/']])}
