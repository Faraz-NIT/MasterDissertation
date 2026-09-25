"""All 12 M5 aggregation levels, bottom-up samples, and small-panel MinT shrinkage."""
from __future__ import annotations
import numpy as np
from scipy.sparse import csr_matrix

LEVELS=[(),('cluster',),('location',),('family',),('department',),('cluster','family'),
        ('cluster','department'),('location','family'),('location','department'),('item_id',),
        ('cluster','item_id'),('location','item_id')]

def summing_matrix(series):
    rr=[];cc=[];labels=[];level_ids=[]
    for level,keys in enumerate(LEVELS):
        groups={}
        for j,s in enumerate(series):
            key=tuple(getattr(s,k) for k in keys) if keys else ('Total',)
            groups.setdefault(key,[]).append(j)
        for key,indices in sorted(groups.items()):
            row=len(labels);labels.append('/'.join(map(str,key)));level_ids.append(level)
            for j in indices:rr.append(row);cc.append(j)
    matrix=csr_matrix((np.ones(len(rr)),(rr,cc)),shape=(len(labels),len(series)))
    return matrix,labels,np.asarray(level_ids)

def bottom_up(samples,series):
    S,labels,levels=summing_matrix(series)
    out=np.stack([S@sample for sample in np.asarray(samples)])
    return out,labels,levels

def mint_shrink(base_forecasts,residuals,S,shrinkage=0.5,nonnegative=True):
    """Dense MinT for research-sized panels. residuals=[time,all_nodes].

    All residuals must come from training/validation, never final test targets.
    Clipping negative bottom-level values then reaggregating preserves coherence,
    but is NOT the exact nonnegative-MinT constrained solution.
    """
    S=S.toarray() if hasattr(S,'toarray') else np.asarray(S)
    if S.shape[0]>2500:raise ValueError('Dense MinT limited to 2,500 nodes; use sparse decomposition for the full hierarchy')
    if not 0<=shrinkage<=1:raise ValueError('shrinkage must lie in [0,1]')
    residuals=np.asarray(residuals)
    if residuals.ndim!=2 or residuals.shape[1]!=S.shape[0]:raise ValueError('Residual dimensions do not match hierarchy')
    W=np.atleast_2d(np.cov(residuals,rowvar=False));W=(1-shrinkage)*W+shrinkage*np.diag(np.diag(W))+np.eye(len(W))*1e-6
    Wi=np.linalg.pinv(W);G=np.linalg.pinv(S.T@Wi@S)@S.T@Wi
    bottom=G@np.asarray(base_forecasts)
    if nonnegative:bottom=np.maximum(0,bottom)
    return S@bottom
