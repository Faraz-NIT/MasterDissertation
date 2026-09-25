"""Forecast interface and no-leakage seasonal / intermittent distributions."""
from __future__ import annotations
import numpy as np
from ..schemas import Snapshot, Forecast
from ..config import ForecastConfig
from ..util import keyed_rng

def corrected_history(snapshot: Snapshot, correct: bool=True) -> tuple[np.ndarray,bool]:
    x=np.asarray([[np.nan if v is None else v for v in row] for row in snapshot.history],dtype=float)
    flags=np.asarray(snapshot.stockout_flags,dtype=bool)
    changed=False
    # Conservative heuristic, not a claim to recover true censored demand.
    for i in range(len(x)):
        for t in range(x.shape[1]):
            if not np.isfinite(x[i,t]) or (correct and flags[i,t]):
                previous=x[i,max(0,t-28):t]
                previous=previous[np.isfinite(previous)]
                estimate=float(np.mean(previous)) if len(previous) else 0.0
                original=x[i,t]
                x[i,t]=max(original,estimate) if np.isfinite(original) else estimate
                changed=True
    return np.maximum(x,0),changed

def sba_mean(values: np.ndarray, alpha: float=0.1) -> float:
    nz=np.flatnonzero(values>0)
    if not len(nz):return 0.0
    demand=float(values[nz[0]]);interval=float(nz[0]+1);last=int(nz[0])
    for t in nz[1:]:
        demand+=alpha*(float(values[t])-demand)
        interval+=alpha*(float(t-last)-interval);last=int(t)
    return (1-alpha/2)*demand/max(interval,1)

def forecast_artifact(snapshot: Snapshot, samples: np.ndarray, model: str, version: str,
                      train_end: int, adjusted: bool, seed: int, extra: dict | None=None) -> Forecast:
    if samples.ndim!=3 or samples.shape[1]!=len(snapshot.series):raise ValueError('Samples must be [scenario,series,horizon]')
    if not np.isfinite(samples).all() or (samples<0).any():raise ValueError('Forecast samples must be finite and nonnegative')
    qlevels=[0.005,0.025,0.165,0.25,0.5,0.75,0.835,0.975,0.995,0.95]
    quantiles={str(q):np.quantile(samples,q,axis=0).tolist() for q in sorted(qlevels)}
    return Forecast(lineage=snapshot.lineage,model=model,model_version=version,training_end=train_end,
                    samples=samples.tolist(),quantiles=quantiles,
                    diagnostics={'coverage':None,'coverage_note':'Coverage is evaluated out of sample, not asserted during prediction.',
                                 'hierarchy':'bottom-up aggregation of scenario samples is coherent',**(extra or {})},
                    censor_adjusted=adjusted,seed=seed)

class SeasonalForecaster:
    name='seasonal_naive'
    def __init__(self, config: ForecastConfig, intermittent: bool=False):
        self.config=config;self.intermittent=intermittent;self.training_end=-1
        if intermittent:self.name='croston_sba'
    def fit(self,panel,train_end:int):
        self.training_end=train_end-1
        return self
    def predict(self,snapshot:Snapshot,horizon:int,scenarios:int,seed:int)->Forecast:
        x,adjusted=corrected_history(snapshot,self.config.censor_correction)
        n,t=x.shape;rng=keyed_rng(seed,'forecast',self.name,snapshot.lineage.day)
        if self.intermittent:
            centers=np.repeat(np.array([sba_mean(row) for row in x])[:,None],horizon,axis=1)
        else:
            centers=x[:,[t-7+j%7 for j in range(horizon)]]
        errors=x[:,7:]-x[:,:-7]
        # Shared block indices preserve cross-series empirical error dependence.
        samples=np.empty((scenarios,n,horizon))
        for w in range(scenarios):
            start=int(rng.integers(0,max(1,errors.shape[1])))
            residual=errors[:,[(start+j)%errors.shape[1] for j in range(horizon)]]
            samples[w]=np.maximum(0,np.rint(centers+residual))
        return forecast_artifact(snapshot,samples,self.name,'native-v1',self.training_end,adjusted,seed,
                                 {'resampling':'shared moving residual blocks','intermittent':self.intermittent})

def build_forecaster(name:str,config:ForecastConfig):
    if name in {'seasonal_naive','croston_sba'}:return SeasonalForecaster(config,name=='croston_sba')
    if name=='lightgbm':
        from .lightgbm_model import QuantileLightGBM
        return QuantileLightGBM(config)
    if name=='deep':
        from .deep import DeepNegativeBinomial
        return DeepNegativeBinomial(config)
    if name=='chronos':
        from .chronos_model import ChronosForecaster
        return ChronosForecaster(config)
    raise ValueError(f'Unknown forecaster {name}')
