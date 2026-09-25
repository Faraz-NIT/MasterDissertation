"""Compact global autoregressive GRU with a negative-binomial likelihood.

A probabilistic deep-model baseline, not a claim of reproducing the published DeepAR
or TFT architectures. Training and prediction are CPU-compatible and deterministic.
"""
from __future__ import annotations
import numpy as np
from .core import corrected_history,forecast_artifact
from ..util import keyed_rng

class DeepNegativeBinomial:
    name='deep'
    def __init__(self,config):self.config=config
    def fit(self,panel,train_end):
        try:
            import torch
            from torch import nn
        except ImportError as e:raise RuntimeError('Install pip install -e ".[ml]" to run deep baselines') from e
        torch.set_num_threads(1);torch.manual_seed(42);torch.use_deterministic_algorithms(True)
        hidden=self.config.hidden_size
        class Model(nn.Module):
            def __init__(self):
                super().__init__();self.gru=nn.GRU(3,hidden,batch_first=True);self.head=nn.Linear(hidden,2)
            def forward(self,x,h=None):
                z,h=self.gru(x,h);params=torch.nn.functional.softplus(self.head(z))+1e-4
                return params,h
        self.net=Model();self.training_end=train_end-1
        context=min(self.config.lookback,56);rng=keyed_rng(42,'deep-train',train_end)
        span=max(0,train_end-context);total=panel.n*span
        flat=rng.choice(total,min(total,self.config.max_training_windows),replace=False) if total else []
        pairs=[(int(j)//span,context+int(j)%span) for j in flat]
        if len(pairs)<8:raise ValueError('Too little historical data for deep model')
        X=[];Y=[];scales=[]
        for i,t in pairs:
            hist=panel.sales[i,t-context:t].astype(float);scale=max(float(hist.mean()),1)
            days=np.arange(t-context,t)
            X.append(np.stack([np.log1p(hist)/np.log1p(scale),np.sin(days*2*np.pi/7),np.cos(days*2*np.pi/7)],axis=1))
            Y.append(float(panel.sales[i,t]));scales.append(scale)
        x=torch.tensor(np.asarray(X),dtype=torch.float32);y=torch.tensor(Y,dtype=torch.float32);scale=torch.tensor(scales,dtype=torch.float32)
        optimizer=torch.optim.Adam(self.net.parameters(),lr=0.003);losses=[]
        for epoch in range(self.config.deep_epochs):
            permutation=torch.randperm(len(x));epoch_loss=0
            for indices in permutation.split(128):
                params,_=self.net(x[indices]);mu=params[:,-1,0]*scale[indices];r=params[:,-1,1]+0.1
                dist=torch.distributions.NegativeBinomial(total_count=r,logits=torch.log(mu/r))
                loss=-dist.log_prob(y[indices]).mean();optimizer.zero_grad();loss.backward()
                torch.nn.utils.clip_grad_norm_(self.net.parameters(),1.0);optimizer.step();epoch_loss+=float(loss.detach())*len(indices)
            losses.append(epoch_loss/len(x))
        self.net.eval();self.losses=losses
        return self
    def predict(self,snapshot,horizon,scenarios,seed):
        import torch
        hist,adjusted=corrected_history(snapshot,self.config.censor_correction)
        rng=keyed_rng(seed,'deep-forecast',snapshot.lineage.day);hist=hist[:,-56:]
        n,t=hist.shape;scale=np.maximum(hist.mean(axis=1),1)
        days=np.asarray(snapshot.history_days[-t:])
        features=np.stack([np.log1p(hist)/np.log1p(scale[:,None]),np.broadcast_to(np.sin(days*2*np.pi/7),hist.shape),np.broadcast_to(np.cos(days*2*np.pi/7),hist.shape)],axis=2)
        x=torch.tensor(np.tile(features,(scenarios,1,1)),dtype=torch.float32)
        scales=np.tile(scale,scenarios);out=np.empty((scenarios,n,horizon))
        with torch.no_grad():
            params,h=self.net(x)
            for step in range(horizon):
                p=params[:,-1].numpy();mu=np.maximum(p[:,0]*scales,1e-5);r=p[:,1]+0.1
                draw=rng.negative_binomial(r,r/(r+mu)).astype(float);out[:,:,step]=draw.reshape(scenarios,n)
                day=snapshot.lineage.day+step
                feat=np.stack([np.log1p(draw)/np.log1p(scales),np.full(len(draw),np.sin(day*2*np.pi/7)),np.full(len(draw),np.cos(day*2*np.pi/7))],axis=1)
                params,h=self.net(torch.tensor(feat[:,None,:],dtype=torch.float32),h)
        return forecast_artifact(snapshot,out,'gru_negative_binomial','native-v1',self.training_end,adjusted,seed,
                                 {'training_nll':self.losses,'likelihood':'negative_binomial','architecture':'global GRU; not TFT/DeepAR replication'})
    def save(self,path):
        import torch
        torch.save({'state_dict':self.net.state_dict(),'training_end':self.training_end,'config':self.config.model_dump()},path)
