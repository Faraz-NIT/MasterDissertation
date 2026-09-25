"""Explicit metric denominators and paired, not pseudo-replicated, inference."""
from __future__ import annotations
import numpy as np
from scipy.stats import wilcoxon, ttest_rel

def cvar(values,alpha=0.95):
    x=np.sort(np.asarray(values,dtype=float))[::-1]
    if len(x)==0:return float('nan')
    if not 0<alpha<1:raise ValueError('alpha must lie in (0,1)')
    mass=(1-alpha)*len(x);whole=int(np.floor(mass));frac=mass-whole
    total=float(x[:whole].sum())
    if frac>1e-12 and whole<len(x):total+=frac*x[whole]
    return total/mass

def pinball(y,q,tau):
    e=np.asarray(y)-np.asarray(q);return float(np.mean(np.maximum(tau*e,(tau-1)*e)))

def crps_samples(y,samples):
    x=np.sort(np.asarray(samples),axis=0);n=len(x)
    first=np.mean(np.abs(x-np.asarray(y)),axis=0)
    weights=(2*np.arange(1,n+1)-n-1).reshape((n,)+(1,)*(x.ndim-1))
    half_pairwise=np.sum(weights*x,axis=0)/(n*n)
    return float(np.mean(first-half_pairwise))

def interval_coverage(y,lower,upper):
    y=np.asarray(y);return float(np.mean((y>=np.asarray(lower))&(y<=np.asarray(upper))))

def bullwhip(orders,demand):
    q=np.asarray(orders);d=np.asarray(demand)
    denominator=float(np.var(d,ddof=1)) if len(d)>1 else 0
    return float(np.var(q,ddof=1)/denominator) if denominator>1e-12 else None

def detection_counts(injected,detected):
    truth=set(injected);pred=set(detected)
    return {'tp':len(truth&pred),'fp':len(pred-truth),'fn':len(truth-pred)}

def paired_bootstrap(a,b,seed=42,resamples=5000,confidence=0.95):
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float)
    if a.shape!=b.shape or a.ndim!=1 or len(a)<2:raise ValueError('At least two matched independent replication outcomes are required')
    diff=a-b;rng=np.random.default_rng(seed)
    means=diff[rng.integers(0,len(diff),size=(resamples,len(diff)))].mean(axis=1)
    lo,hi=np.quantile(means,[(1-confidence)/2,(1+confidence)/2])
    sd=float(diff.std(ddof=1))
    return {'mean_difference':float(diff.mean()),'ci_low':float(lo),'ci_high':float(hi),'n_pairs':len(diff),
            'paired_standardized_effect':float(diff.mean()/sd) if sd>0 else None,
            'wilcoxon_p':float(wilcoxon(diff).pvalue) if np.any(diff!=0) else 1.0,
            'paired_t_p':float(ttest_rel(a,b).pvalue) if sd>0 else (1.0 if np.all(diff==0) else 0.0)}

def holm(pvalues):
    values=np.asarray(pvalues);order=np.argsort(values);out=np.ones_like(values,dtype=float);running=0.
    for rank,i in enumerate(order):
        running=max(running,(len(values)-rank)*values[i]);out[i]=min(1,running)
    return out.tolist()

def hierarchical_scores(train,actual,predicted,price_history,series,quantiles=None,samples=None):
    """Subset-aware 12-level WRMSSE and WSPL; scales exclude pre-first-sale zeros.

    Reported as official full-hierarchy scores ONLY when all original M5 series are present.
    train=[bottom,train_time], predicted=[bottom,horizon], quantiles={tau: [bottom,horizon]}.
    """
    from ..forecasting.hierarchy import summing_matrix
    S,labels,levels=summing_matrix(series);tr=S@np.asarray(train);a=S@np.asarray(actual);p=S@np.asarray(predicted)
    dollars=np.nansum(np.asarray(train)[:,-28:]*np.asarray(price_history)[:,-28:],axis=1)
    weights=S@dollars;weights=np.asarray(weights,dtype=float)
    for level in range(12):
        mask=levels==level;denom=weights[mask].sum()
        if denom>0:weights[mask]/=denom*12
        else:weights[mask]=0
    sq=[];ab=[]
    for row in tr:
        nonzero=np.flatnonzero(row>0);trim=row[nonzero[0]:] if len(nonzero) else np.array([])
        delta=np.diff(trim);sq.append(float(np.mean(delta**2)) if len(delta) else np.nan);ab.append(float(np.mean(np.abs(delta))) if len(delta) else np.nan)
    sq=np.asarray(sq);ab=np.asarray(ab);valid=np.isfinite(sq)&(sq>0)
    wrmsse=float(np.sum(weights[valid]*np.sqrt(np.mean((a-p)**2,axis=1)[valid]/sq[valid])))
    result={'wrmsse':wrmsse,'zero_scale_nodes':int((~valid).sum()),'scored_weight_mass':float(weights[valid].sum()),
            'nodes':len(labels),'full_m5_shape':len(series)==30490 and len(labels)==42840,
            'zero_scale_policy':'excluded without renormalization; report scored_weight_mass'}
    if quantiles:
        losses=[]
        aggregated_samples=np.stack([S@x for x in np.asarray(samples)]) if samples is not None else None
        for tau,pred in quantiles.items():
            hierarchy_quantile=np.quantile(aggregated_samples,float(tau),axis=0) if aggregated_samples is not None else S@np.asarray(pred)
            e=a-hierarchy_quantile;loss=np.mean(np.maximum(float(tau)*e,(float(tau)-1)*e),axis=1)
            mask=np.isfinite(ab)&(ab>0);losses.append(float(np.sum(weights[mask]*loss[mask]/ab[mask])))
        result['weighted_scaled_pinball']=float(np.mean(losses))
        result['hierarchical_quantile_method']='quantile of aggregated scenarios' if samples is not None else 'sum of marginal quantiles: approximation, not official M5 WSPL'
    return result
