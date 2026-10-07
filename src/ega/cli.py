from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import pandas as pd
from .config import ExperimentConfig,load_config
from .util import atomic_json,environment

def main(argv=None):
    parser=argparse.ArgumentParser(prog='ega',description='Evidence-gated replenishment research repository. Simulator-only execution.')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('doctor',help='Show installed versions and optional capabilities')
    p=sub.add_parser('prepare',help='Map user-provided M5 CSVs to a canonical dataset')
    p.add_argument('--raw',default='data/raw/m5');p.add_argument('--out',default='data/processed/m5');p.add_argument('--items',type=int,default=3)
    p.add_argument('--all-items',action='store_true');p.add_argument('--stores',nargs='+');p.add_argument('--materialize-facts',action='store_true')
    p=sub.add_parser('demo-data');p.add_argument('--out',default='data/processed/demo');p.add_argument('--items',type=int,default=2);p.add_argument('--stores',type=int,default=2)
    p=sub.add_parser('demo',help='Run synthetic, non-LLM software demonstration')
    p.add_argument('--output',default='results/demo');p.add_argument('--days',type=int,default=6)
    p=sub.add_parser('run');p.add_argument('--config',required=True);p.add_argument('--output');p.add_argument('--policies',nargs='+');p.add_argument('--seeds',nargs='+',type=int);p.add_argument('--days',type=int);p.add_argument('--resume',action='store_true',help='Keep completed runs in --output and re-run the rest')
    p=sub.add_parser('forecast-backtest');p.add_argument('--config',required=True);p.add_argument('--model',choices=['seasonal_naive','croston_sba','lightgbm','deep','chronos'],required=True);p.add_argument('--origins',nargs='+',type=int,required=True);p.add_argument('--horizon',type=int,default=28);p.add_argument('--out',default='results/forecast_scores.json')
    p=sub.add_parser('report');p.add_argument('--results',required=True);p.add_argument('--out')
    for name in ['replay','trace-audit','counterfactual','delete-evidence']:
        p=sub.add_parser(name);p.add_argument('--run-dir',required=True);p.add_argument('--day',type=int);p.add_argument('--out')
        if name=='counterfactual':p.add_argument('--factor',default='budget',choices=['budget','capacity','lead_time','forecast','eligibility','quality']);p.add_argument('--multiplier',type=float,default=0.5)
        if name=='delete-evidence':p.add_argument('--artifact',default='forecast')
    p=sub.add_parser('audit-packets');p.add_argument('--results',required=True);p.add_argument('--out',required=True);p.add_argument('--participants',type=int,default=3);p.add_argument('--max-cases',type=int,default=12)
    p=sub.add_parser('audit-score');p.add_argument('--study-dir',required=True);p.add_argument('--responses',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('calibrate');p.add_argument('--incidents',required=True);p.add_argument('--exposure-days',type=int,required=True);p.add_argument('--provenance',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('read-workbook');p.add_argument('path');p.add_argument('--out',required=True)
    p=sub.add_parser('harness',help='Evaluate frozen synthetic decision cases with offline D0/D1 policies')
    p.add_argument('--suite',help='Validated harness-v1 JSON; defaults to the built-in synthetic suite')
    p.add_argument('--output',default='results/harness');p.add_argument('--policies',nargs='+',choices=['D0','D1'])
    p.add_argument('--cases',nargs='+',help='Run only these case IDs')
    p=sub.add_parser('harness-suite',help='Export the built-in frozen synthetic evaluation suite')
    p.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='doctor':
            print(json.dumps(environment(),indent=2));print('No API key is inspected or printed. LLM connectivity is checked only by an explicitly selected live run.');return 0
        if args.command=='harness-suite':
            from .evaluation.harness import default_suite
            target=Path(args.out)
            if target.exists():raise FileExistsError(f'Suite already exists: {target}')
            atomic_json(target,default_suite());print(target);return 0
        if args.command=='harness':
            from .evaluation.harness import default_suite,load_suite,run_harness
            suite=load_suite(args.suite) if args.suite else default_suite()
            result=run_harness(suite,args.output,args.policies,args.cases,progress=lambda message: print(message,flush=True))
            print(pd.DataFrame(result['summary'])[['policy','cases','passed','failed','unsafe_executions',
                'unnecessary_holds','permitted_constraint_violations','runtime_errors','invalid_traces']].to_string(index=False))
            print(f'Decision permission only; no orders committed. Results: {Path(args.output)/"results.json"}')
            return 0 if result['passed'] else 1
        if args.command=='prepare':
            from .data.m5 import prepare_m5
            panel=prepare_m5(args.raw,args.out,None if args.all_items else args.items,args.stores,args.materialize_facts)
            print(f'Prepared {panel.n} series × {panel.days} days in {args.out}');return 0
        if args.command=='demo-data':
            from .data.synthetic import make_demo
            panel=make_demo(args.out,args.items,args.stores);print(f'SYNTHETIC demonstration dataset: {panel.n} series in {args.out}');return 0
        if args.command in {'demo','run'}:
            from .experiment import run_experiment
            if args.command=='demo':
                from .data.synthetic import make_demo
                dataset=Path(args.output)/'synthetic_data';make_demo(dataset,items=1,stores=2)
                config=ExperimentConfig.model_validate({'dataset':str(dataset),'output':args.output,'policies':['B1','D0','D1'],
                    'scenarios':['normal','feed_gap','derived_field_collapse'],'seeds':[7,29],'days':args.days,'warmup_days':4,
                    'solver':{'horizon':6,'scenarios':4,'time_limit':10}})
            else:
                raw=load_config(args.config).model_dump()
                for key in ['output','policies','seeds','days']:
                    value=getattr(args,key,None)
                    if value is not None:raw[key]=value
                config=ExperimentConfig.model_validate(raw)
            results=run_experiment(config,resume=getattr(args,'resume',False))
            from .evaluation.report import render_report
            report=render_report(config.output)
            print(results[['policy','scenario','seed','cost','fill_rate','held_decisions','harmful_executions']].to_string(index=False))
            print(f'Report: {report}');return 0
        if args.command=='forecast-backtest':
            from .data.panel import Panel
            from .evaluation.forecasting import forecast_backtest
            config=load_config(args.config);rows=forecast_backtest(Panel.load(config.dataset),config,args.model,args.origins,args.horizon)
            atomic_json(Path(args.out),rows);print(json.dumps(rows,indent=2));return 0
        if args.command=='report':
            from .evaluation.report import render_report
            print(render_report(args.results,args.out));return 0
        if args.command in {'replay','trace-audit','counterfactual','delete-evidence'}:
            from .evaluation.faithfulness import replay,trace_audit,counterfactual,deletion_test
            if args.command=='replay':result=replay(args.run_dir,args.day)
            elif args.command=='trace-audit':result=trace_audit(args.run_dir,args.day)
            elif args.command=='counterfactual':result=counterfactual(args.run_dir,args.day,args.factor,args.multiplier)
            else:result=deletion_test(args.run_dir,args.day,args.artifact)
            if args.out:atomic_json(Path(args.out),result)
            print(json.dumps(result,indent=2));return 0
        if args.command=='audit-packets':
            from .evaluation.human_audit import export_packets
            n=export_packets(args.results,args.out,args.participants,args.max_cases);print(f'Exported {n} blinded cases. Researcher-only files must not be distributed to participants.');return 0
        if args.command=='audit-score':
            from .evaluation.human_audit import score_responses
            df=score_responses(args.study_dir,args.responses);Path(args.out).parent.mkdir(parents=True,exist_ok=True);df.to_csv(args.out,index=False);print(df.to_string(index=False));return 0
        if args.command=='calibrate':
            from .calibration import calibrate
            print(json.dumps(calibrate(args.incidents,args.exposure_days,args.provenance,Path(args.out)),indent=2));return 0
        if args.command=='read-workbook':
            from .data.workbooks import read_workbook
            atomic_json(Path(args.out),read_workbook(args.path));print(args.out);return 0
    except (ValueError,FileNotFoundError,FileExistsError,RuntimeError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
