from __future__ import annotations
import numpy as np
import pandas as pd
from .panel import Panel
from .m5 import write_canonical_sqlite
from ..schemas import Series
from ..util import keyed_rng
from pathlib import Path

def make_demo(path=None, items: int=2, stores: int=2, days: int=220, seed: int=7) -> Panel:
    """Small synthetic fixture; deliberately NOT advertised as an M5 sample."""
    series=[]; sales=[]; prices=[]
    for item in range(items):
        for store in range(stores):
            rng=keyed_rng(seed,'demo',item,store)
            base=2+item*1.5+store*0.8
            lam=base*(1+0.25*np.sin(np.arange(days)*2*np.pi/7))
            y=rng.poisson(lam).astype(float)
            if item%3 == 2: y *= rng.binomial(1,0.25,size=days)
            series.append(Series(series_id=f'ITEM_{item}@CA_{store+1}',item_id=f'ITEM_{item}',
                          department=f'DEPT_{item%2}',family='FOODS',location=f'CA_{store+1}',
                          cluster='CA',supplier=f'SUP_DEPT_{item%2}'))
            sales.append(y);prices.append(np.full(days,4.0+item))
    dates=pd.date_range('2015-01-01',periods=days)
    calendar=pd.DataFrame({'date':dates.strftime('%Y-%m-%d'),'d':[f'd_{d+1}' for d in range(days)],
                           'wday':dates.dayofweek+1,'month':dates.month,'year':dates.year,
                           'event_name_1':['' for _ in dates], 'snap_CA':(dates.day<=10).astype(int)})
    panel=Panel(series,np.asarray(sales),np.asarray(prices),calendar,{'dataset':'synthetic-demo','synthetic':True,'seed':seed})
    if path:
        panel.save(path);write_canonical_sqlite(panel,Path(path)/'catalog.sqlite')
    return panel
