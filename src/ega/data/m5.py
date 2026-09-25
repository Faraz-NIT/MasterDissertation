"""Memory-bounded M5 wide CSV import. No competition credentials or downloads required."""
from __future__ import annotations
import hashlib
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
from .panel import Panel
from ..schemas import Series

IDENTIFIERS = ['id','item_id','dept_id','cat_id','store_id','state_id']

def file_sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

def prepare_m5(raw: str | Path, output: str | Path, items: int | None=3,
               stores: list[str] | None=None, materialize_facts: bool=False) -> Panel:
    root=Path(raw)
    evaluation=root/'sales_train_evaluation.csv'; validation=root/'sales_train_validation.csv'
    sales_path=evaluation if evaluation.exists() else validation
    for path in [sales_path,root/'calendar.csv',root/'sell_prices.csv']:
        if not path.is_file():
            raise FileNotFoundError(f"Missing {path}. Supply the original M5 CSV files, unzipped.")
    # Select items round-robin across departments, retaining every requested store for each item.
    catalog=pd.read_csv(sales_path,usecols=IDENTIFIERS)
    unique=catalog[['item_id','dept_id']].drop_duplicates().sort_values(['dept_id','item_id'])
    if items is not None and items <= 0:
        raise ValueError("items must be positive; omit it to import the entire hierarchy")
    groups=[x.item_id.tolist() for _,x in unique.groupby('dept_id',sort=True)]
    chosen=[]
    while any(groups) and (items is None or len(chosen)<items):
        for g in groups:
            if g and (items is None or len(chosen)<items): chosen.append(g.pop(0))
    selected=set(chosen); frames=[]
    header=pd.read_csv(sales_path,nrows=0).columns
    dcols=sorted([c for c in header if c.startswith('d_')],key=lambda c:int(c[2:]))
    if [int(c[2:]) for c in dcols]!=list(range(1,len(dcols)+1)):
        raise ValueError('M5 day columns must be contiguous d_1 through d_N')
    if catalog[['item_id','store_id']].duplicated().any():raise ValueError('Duplicate item/store series')
    for chunk in pd.read_csv(sales_path,chunksize=512,dtype={d:'float32' for d in dcols}):
        keep=chunk.item_id.isin(selected)
        if stores: keep &= chunk.store_id.isin(stores)
        frames.append(chunk.loc[keep])
    frame=pd.concat(frames,ignore_index=True).sort_values(['item_id','store_id']).reset_index(drop=True)
    if frame.empty: raise ValueError("Item/store selection contains no series")
    calendar=pd.read_csv(root/'calendar.csv').set_index('d').loc[dcols].reset_index()
    dates=pd.to_datetime(calendar.date,errors='raise')
    if dates.duplicated().any() or not dates.is_monotonic_increasing or not dates.diff().dropna().eq(pd.Timedelta(days=1)).all():
        raise ValueError('Calendar must contain unique consecutive, increasing daily dates')
    series=[Series(series_id=f'{r.item_id}@{r.store_id}',item_id=r.item_id,department=r.dept_id,
                   family=r.cat_id,location=r.store_id,cluster=r.state_id,supplier=f'SUP_{r.dept_id}')
            for r in frame.itertuples()]
    prices=pd.read_csv(root/'sell_prices.csv')
    prices=prices[prices.item_id.isin(selected)]
    if prices.duplicated(['store_id','item_id','wm_yr_wk']).any():
        raise ValueError("Duplicate sell-price keys")
    mapping={(s.item_id,s.location):i for i,s in enumerate(series)}
    week_table=prices.pivot(index=['item_id','store_id'],columns='wm_yr_wk',values='sell_price')
    weeks=calendar.wm_yr_wk.tolist()
    p=np.full((len(series),len(weeks)),np.nan,dtype=np.float32)
    for key,i in mapping.items():
        if key in week_table.index:
            # Reindex repeated week keys to daily dates, then forward-fill only.
            daily=week_table.loc[key].reindex(weeks).reset_index(drop=True).ffill()
            p[i]=daily.to_numpy(dtype=np.float32)
    panel=Panel(series,frame[dcols].to_numpy(dtype=np.float32),p,calendar,
                {'dataset':'M5','synthetic':False,'sales_file':sales_path.name,
                 'raw_sha256':{path.name:file_sha256(path) for path in [sales_path,root/'calendar.csv',root/'sell_prices.csv']},
                 'selection':{'items':chosen,'stores':stores or 'all'},
                 'note':'Observed historical sales used as exogenous demand proxy; no latent-demand claim.'})
    panel.save(output)
    write_canonical_sqlite(panel,Path(output)/'catalog.sqlite',materialize_facts)
    return panel

def write_canonical_sqlite(panel: Panel, path: Path, materialize_facts: bool=False):
    """Normalized catalog; optionally materialize large daily sales tables in bounded chunks."""
    db=sqlite3.connect(path)
    meta=pd.DataFrame([s.model_dump() for s in panel.series])
    tables={
      'locations':meta[['location','cluster','currency']].drop_duplicates().assign(location_type='store'),
      'suppliers':meta[['supplier']].drop_duplicates().assign(provenance='synthetic_department_assignment'),
      'families':meta[['family']].drop_duplicates(),
      'categories':meta[['department','family']].drop_duplicates(),
      'products':meta[['item_id','department']].drop_duplicates(),
      'variants':meta[['item_id']].drop_duplicates().assign(variant_count=1),
      'supplier_products':meta[['item_id','supplier']].drop_duplicates(),
      'series_catalog':meta,
    }
    for name,df in tables.items(): df.to_sql(name,db,if_exists='replace',index=False)
    pd.DataFrame({'currency':['USD'],'base_currency':['USD'],'rate':[1.0]}).to_sql('exchange_rates',db,if_exists='replace',index=False)
    db.execute('CREATE TABLE IF NOT EXISTS transfers (transfer_id TEXT PRIMARY KEY, series_id TEXT, quantity REAL, ordered_day INTEGER, due_day INTEGER, kind TEXT, status TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS inventory_snapshots (snapshot_version TEXT, series_id TEXT, day INTEGER, quantity REAL, PRIMARY KEY(snapshot_version,series_id))')
    db.execute('CREATE TABLE IF NOT EXISTS live_inventory (series_id TEXT PRIMARY KEY, quantity REAL, day INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS catalogs (series_id TEXT, valid_from INTEGER, valid_to INTEGER, eligible INTEGER)')
    if materialize_facts:
        db.execute('DROP TABLE IF EXISTS line_items');db.execute('DROP TABLE IF EXISTS orders');db.execute('DROP TABLE IF EXISTS prices')
        for start in range(0,panel.days,28):
            end=min(start+28,panel.days)
            rows=[]; price_rows=[]
            for i,s in enumerate(panel.series):
                for d in range(start,end):
                    q=float(panel.sales[i,d]); p=float(panel.prices[i,d])
                    rows.append((f'{s.series_id}:{d}',s.series_id,d,q,p if np.isfinite(p) else None,'store'))
                    price_rows.append((s.series_id,d,p if np.isfinite(p) else None,'USD'))
            pd.DataFrame(rows,columns=['order_id','series_id','day','quantity','unit_price','channel']).to_sql('line_items',db,if_exists='append',index=False)
            pd.DataFrame(price_rows,columns=['series_id','day','unit_price','currency']).to_sql('prices',db,if_exists='append',index=False)
        db.execute('CREATE TABLE orders AS SELECT order_id,day,channel FROM line_items')
        db.execute('CREATE INDEX line_items_series_day ON line_items(series_id,day)')
    db.commit();db.close()
