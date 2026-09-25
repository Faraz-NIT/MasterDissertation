"""Rolling-origin, past-only probabilistic forecast scoring, separate from policy simulation."""
from __future__ import annotations
import numpy as np
from ..simulator import InventoryEnvironment
from ..forecasting.core import build_forecaster
from .metrics import hierarchical_scores,crps_samples,interval_coverage

def forecast_backtest(panel,config,model_name,origins,horizon=28):
    rows=[]
    for origin in origins:
        if origin<config.forecast.lookback or origin+horizon>panel.days:raise ValueError('Origin does not have enough training/future evaluation days')
        model=build_forecaster(model_name,config.forecast).fit(panel,origin)
        env=InventoryEnvironment(panel,origin,42,'forecast-backtest',config);env.begin_day(origin)
        snap=env.snapshot(config.forecast.lookback)
        pred=model.predict(snap,horizon,max(32,config.solver.scenarios),42)
        samples=np.asarray(pred.samples);actual=np.asarray(panel.sales[:,origin:origin+horizon])
        qs={q:np.asarray(v) for q,v in pred.quantiles.items()}
        official_quantiles={q:v for q,v in qs.items() if q!='0.95'}
        metrics=hierarchical_scores(panel.sales[:,:origin],actual,qs['0.5'],panel.prices[:,:origin],panel.series,official_quantiles,samples=samples)
        metrics.update(origin=origin,model=model_name,training_end=pred.training_end,crps=crps_samples(actual,samples),
                       coverage_95=interval_coverage(actual,qs['0.025'],qs['0.975']),
                       calibration_error_95=abs(interval_coverage(actual,qs['0.025'],qs['0.975'])-0.95))
        rows.append(metrics)
    return rows
