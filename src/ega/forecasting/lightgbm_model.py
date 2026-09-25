from __future__ import annotations
import numpy as np
from .core import corrected_history,forecast_artifact
from ..util import keyed_rng

class QuantileLightGBM:
    name='lightgbm'
    levels=np.array([0.005,0.025,0.165,0.25,0.5,0.75,0.835,0.95,0.975,0.995])
    def __init__(self,config):self.config=config;self.models=[]
    @staticmethod
    def features(hist,price,day,series_index,calendar):
        last=hist[-28:]
        def lag(k):return hist[-k] if len(hist)>=k else float(np.mean(hist))
        cal=calendar.iloc[min(day,len(calendar)-1)]
        return [lag(1),lag(7),lag(14),lag(28),float(np.mean(last[-7:])),float(np.mean(last)),float(np.std(last)),
                float(np.mean(last>0)),float(price),float(cal.get('wday',day%7+1)),float(cal.get('month',1)),
                float(cal.get('snap_CA',0)),int(str(cal.get('event_name_1','nan')) not in {'nan','','None'}),float(series_index)]
    def fit(self,panel,train_end):
        try:from lightgbm import LGBMRegressor
        except ImportError as e:raise RuntimeError('Install pip install -e ".[ml]" to run B2') from e
        self.training_end=train_end-1;self.calendar=panel.calendar.copy();X=[];Y=[]
        rng=keyed_rng(42,'lgbm-training',train_end)
        span=max(0,train_end-28);total=panel.n*span
        flat=rng.choice(total,min(total,self.config.max_training_windows),replace=False) if total else []
        candidates=[(int(j)//span,28+int(j)%span) for j in flat]
        for i,t in candidates:
            p=float(panel.prices[i,t-1])
            if not np.isfinite(p) or p<=0:continue
            X.append(self.features(panel.sales[i,:t],p,t,i,self.calendar));Y.append(panel.sales[i,t])
        if len(Y)<16:raise ValueError('Too little past-only training data for LightGBM')
        for level in self.levels:
            m=LGBMRegressor(objective='quantile',alpha=float(level),n_estimators=self.config.lgbm_estimators,
                            max_depth=5,num_leaves=20,min_child_samples=10,verbosity=-1,n_jobs=1,random_state=42,
                            deterministic=True,force_col_wise=True)
            m.fit(np.asarray(X),np.asarray(Y));self.models.append(m)
        return self
    def predict(self,snapshot,horizon,scenarios,seed):
        hist,adjusted=corrected_history(snapshot,self.config.censor_correction)
        paths=np.repeat(hist[None,:,:],scenarios,axis=0);rng=keyed_rng(seed,'lgbm',snapshot.lineage.day)
        out=np.empty((scenarios,len(hist),horizon))
        for t in range(horizon):
            features=np.asarray([self.features(paths[w,i],snapshot.prices[i],snapshot.lineage.day+t,i,self.calendar)
                                 for w in range(scenarios) for i in range(len(hist))])
            import pandas as pd
            feature_frame=pd.DataFrame(features,columns=self.models[0].feature_name_)
            qs=np.sort(np.maximum(0,np.stack([m.predict(feature_frame) for m in self.models],axis=1)),axis=1)
            u=rng.uniform(size=len(features))
            draws=np.array([np.interp(u[j],self.levels,qs[j]) for j in range(len(features))]).reshape(scenarios,len(hist))
            draws=np.maximum(0,np.rint(draws));out[:,:,t]=draws;paths=np.concatenate([paths,draws[:,:,None]],axis=2)
        return forecast_artifact(snapshot,out,self.name,'lightgbm-quantile-v1',self.training_end,adjusted,seed,
                                 {'quantile_crossing':'sorted','price_features':'last observed price held constant','sampling':'conditional inverse-quantile recursion'})
