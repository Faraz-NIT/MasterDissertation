"""Optional Chronos-T5 sample adapter. Downloads weights only when explicitly selected."""
from __future__ import annotations
import numpy as np
from .core import corrected_history,forecast_artifact

class ChronosForecaster:
    name='chronos'
    def __init__(self,config):self.config=config
    def fit(self,panel,train_end):
        try:
            import torch
            from chronos import ChronosPipeline
        except ImportError as exc:raise RuntimeError('Install pip install -e ".[foundation]" for B5') from exc
        kwargs={'device_map':'cpu','torch_dtype':torch.float32}
        if self.config.chronos_revision:kwargs['revision']=self.config.chronos_revision
        self.pipeline=ChronosPipeline.from_pretrained(self.config.chronos_model,**kwargs)
        self.training_end=train_end-1
        return self
    def predict(self,snapshot,horizon,scenarios,seed):
        import torch
        torch.manual_seed(seed)
        x,adjusted=corrected_history(snapshot,self.config.censor_correction)
        with torch.no_grad():
            values=self.pipeline.predict(torch.tensor(x,dtype=torch.float32),prediction_length=horizon,num_samples=scenarios)
        samples=np.maximum(0,np.rint(values.detach().cpu().numpy().transpose(1,0,2)))
        return forecast_artifact(snapshot,samples,self.config.chronos_model,self.config.chronos_revision or 'UNPINNED',
                                 self.training_end,adjusted,seed,{'pretraining_contamination':'Cannot exclude M5 exposure in public pretrained weights'})
