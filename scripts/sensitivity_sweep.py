"""Explicit synthetic/calibrated rate and hold-budget sweeps; outputs never overwrite."""
import argparse
from ega.config import load_config,ExperimentConfig
from ega.experiment import run_experiment
p=argparse.ArgumentParser();p.add_argument('--config',required=True)
p.add_argument('--rate-multipliers',nargs='+',type=float,default=[0.5,1,2])
p.add_argument('--hold-budgets',nargs='+',type=int,default=[0,2,5]);p.add_argument('--output',default='results/sensitivity')
a=p.parse_args();raw=load_config(a.config).model_dump()
for rate in a.rate_multipliers:
    for hold in a.hold_budgets:
        import copy
        cfg=copy.deepcopy(raw);cfg['quality']['rate_multiplier']=rate;cfg['gate']['hold_budget']=hold
        cfg['scenarios']=['mixed_quality'];cfg['output']=f'{a.output}/rate_{rate}_hold_{hold}'
        # The hold budget changes escalation urgency, not automatic approval or state repair.
        run_experiment(ExperimentConfig.model_validate(cfg))
