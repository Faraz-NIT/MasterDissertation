"""Validate the pinned public release and select a train-only bounded panel."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from ega.data.panel import Panel
from ega.schemas import Series
from ega.util import atomic_json

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'results/freshretailnet'
RAW=ROOT/'data/raw/freshretailnet'
KEY=['store_id','product_id']
META=['city_id','management_group_id','first_category_id','second_category_id','third_category_id']

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(path):
    pf=pq.ParquetFile(path);rows=0;bad={'hour_lengths':0,'stock_coding':0,'stock_count':0,'sales_alignment':0,'negative_sales':0,'invalid_discount':0}
    max_diff=0.;frames=[];hour_stock=0;daily_stock=0
    for batch in pf.iter_batches(batch_size=100000):
        d=batch.to_pandas();n=len(d);rows+=n
        lengths=d.hours_sale.map(len);slength=d.hours_stock_status.map(len)
        bad['hour_lengths']+=int(((lengths!=24)|(slength!=24)).sum())
        if not (lengths.eq(24).all() and slength.eq(24).all()):raise ValueError('Unexpected hourly vector lengths')
        hourly=np.stack(d.hours_sale);status=np.stack(d.hours_stock_status)
        bad['stock_coding']+=int((~np.isin(status,[0,1])).any(axis=1).sum())
        count=status[:,6:22].sum(axis=1);bad['stock_count']+=int((count!=d.stock_hour6_22_cnt).sum())
        delta=np.abs(hourly.sum(axis=1)-d.sale_amount.to_numpy());max_diff=max(max_diff,float(delta.max()))
        bad['sales_alignment']+=int((delta>1e-7).sum());bad['negative_sales']+=int(((hourly<0).any(axis=1)|(d.sale_amount<0)).sum())
        bad['invalid_discount']+=int(((d.discount<=0)|(d.discount>1)|~np.isfinite(d.discount)).sum())
        hour_stock+=int(count.sum());daily_stock+=int((count>0).sum())
        frames.append(d[KEY+META+['dt','sale_amount','stock_hour6_22_cnt']])
    index=pd.concat(frames,ignore_index=True)
    duplicates=int(index.duplicated(KEY+['dt']).sum())
    counts=index.groupby(KEY).size();hier=index.groupby(KEY)[META].nunique()
    result={'file':str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),'sha256':sha(path),'rows':rows,'series':len(counts),'stores':int(index.store_id.nunique()),'products':int(index.product_id.nunique()),'cities':int(index.city_id.nunique()),'dates':sorted(index.dt.unique()),'duplicate_keys':duplicates,'rows_per_series_min':int(counts.min()),'rows_per_series_max':int(counts.max()),'hierarchy_conflicts':int((hier>1).any(axis=1).sum()),'invalid_rows':bad,'maximum_daily_hourly_difference':max_diff,'operating_hours':list(range(6,22)),'stockout_flag_value':1,'operating_hour_stockout_fraction':hour_stock/(rows*16),'daily_any_stockout_fraction':daily_stock/rows}
    # Discount and consistency problems are retained and reported, never silently fixed.
    assert not duplicates and not result['hierarchy_conflicts']
    assert all(bad[k]==0 for k in ['hour_lengths','stock_coding','stock_count','sales_alignment','negative_sales'])
    return index,result

def main():
    target=OUT/'data';target.mkdir(parents=True,exist_ok=True)
    train,train_audit=validate(RAW/'train.parquet')
    assert len(train)==4500000 and train_audit['series']==50000 and len(train_audit['dates'])==90
    dates=train_audit['dates'];early=train[train.dt.isin(dates[:62])]
    stats=early.groupby(KEY).agg(mean_sales=('sale_amount','mean'),stockout_hours=('stock_hour6_22_cnt','sum'),rows=('dt','size')).reset_index()
    stats['censor_rate']=stats.stockout_hours/(stats.rows*16)
    # Fixed modest-demand range avoids procurement-scale mismatch; no held-out targets used.
    eligible=stats[(stats.rows==62)&(stats.mean_sales>=.02)&(stats.mean_sales<=1)].copy()
    eligible['selection_hash']=[hashlib.sha256(f'FRN-panel-v1:{s}:{p}'.encode()).hexdigest() for s,p in zip(eligible.store_id,eligible.product_id)]
    eligible=eligible.sort_values(['censor_rate','selection_hash']).reset_index(drop=True)
    eligible['censor_stratum']=np.minimum(2,np.arange(len(eligible))*3//len(eligible))
    chosen=pd.concat([g.sort_values('selection_hash').head(10) for _,g in eligible.groupby('censor_stratum')]).sort_values(KEY)
    assert len(chosen)==30
    chosen['series_id']=[f'FRN_{int(p):04d}@S{int(s):04d}' for s,p in zip(chosen.store_id,chosen.product_id)]
    chosen.to_csv(target/'selected_series.csv',index=False)
    selection={'rule':'First62trainingdays only; complete62rows; mean normalized daily sales in[0.02,1.0]; three equal-rank censor-hour strata; ten deterministic SHA256-ranked pairs per stratum','eligible_series':len(eligible),'selected_series':30,'selection_train_end_date':dates[61],'seed_label':'FRN-panel-v1','evaluation_targets_used':False,'selected_catalog_sha256':sha(target/'selected_series.csv'),'scale':100,'economic_unit':'simulated cost index; not CNY, USD or retailer profit','physical_unit':'100 times globally normalized published sales amount; not cartons or kg','representativeness':'purposive computational panel; 0.06% of release series, not a population estimate'}
    atomic_json(target/'selection.json',selection)
    selected=[]
    pairs=set(map(tuple,chosen[KEY].to_numpy()))
    for batch in pq.ParquetFile(RAW/'train.parquet').iter_batches(batch_size=100000):
        d=batch.to_pandas();mask=[(s,p) in pairs for s,p in zip(d.store_id,d.product_id)]
        if any(mask):selected.append(d.loc[mask])
    d=pd.concat(selected).merge(chosen[KEY+['series_id','censor_stratum']],on=KEY,validate='many_to_one')
    d['day_index']=d.dt.map({day:i for i,day in enumerate(dates)});d=d.sort_values(['series_id','day_index'])
    assert len(d)==2700
    d.to_parquet(target/'selected_train.parquet',index=False)
    atomic_json(target/'train_validation.json',train_audit)
    atomic_json(target/'train_preparation_complete.json',{'status':'COMPLETE','selection':selection,'eval_targets_opened':False})
    print(json.dumps({'phase':'train_prepared','audit':train_audit,'selection':selection}),flush=True)

def unseal():
    protocol=json.loads((OUT/'protocol.json').read_text());assert protocol['status']=='frozen'
    selection_receipt=OUT/'forecast/selection_receipt.json'
    assert selection_receipt.is_file(), 'Official evaluation stays sealed until train-validation model selection is recorded'
    assert json.loads(selection_receipt.read_text())['eval_data_opened'] is False
    from datetime import datetime,timezone
    atomic_json(OUT/'data/eval_unseal_started.json',{'started_at_utc':datetime.now(timezone.utc).isoformat(),'selection_receipt_sha256':sha(selection_receipt),'protocol_sha256':sha(OUT/'protocol.json')})
    target=OUT/'data';d=pd.read_parquet(target/'selected_train.parquet');chosen=pd.read_csv(target/'selected_series.csv')
    evaluation,audit=validate(RAW/'eval.parquet');assert len(evaluation)==350000 and audit['series']==50000 and len(audit['dates'])==7
    train_audit=json.loads((target/'train_validation.json').read_text());assert set(audit['dates']).isdisjoint(train_audit['dates']) and min(audit['dates'])>max(train_audit['dates'])
    assert set(map(tuple,evaluation[KEY].drop_duplicates().to_numpy()))==set(map(tuple,pd.read_parquet(RAW/'train.parquet',columns=KEY).drop_duplicates().to_numpy()))
    parts=[];pairs=set(map(tuple,chosen[KEY].to_numpy()))
    for batch in pq.ParquetFile(RAW/'eval.parquet').iter_batches(batch_size=100000):
        e=batch.to_pandas();mask=[(s,p) in pairs for s,p in zip(e.store_id,e.product_id)]
        if any(mask):parts.append(e.loc[mask])
    e=pd.concat(parts).merge(chosen[KEY+['series_id','censor_stratum']],on=KEY,validate='many_to_one')
    e['day_index']=e.dt.map({day:90+i for i,day in enumerate(audit['dates'])});e=e.sort_values(['series_id','day_index']);assert len(e)==210
    e.to_parquet(target/'selected_eval.pending.parquet',index=False)
    (target/'selected_eval.pending.parquet').replace(target/'selected_eval.parquet')
    both=pd.concat([d,e]);ids=sorted(d.series_id.unique());all_dates=train_audit['dates']+audit['dates'];sales=both.pivot(index='series_id',columns='day_index',values='sale_amount').loc[ids].to_numpy()*100
    flags=both.pivot(index='series_id',columns='day_index',values='stock_hour6_22_cnt').loc[ids].to_numpy()>0
    prepared=ROOT/'data/processed/freshretailnet';prepared.mkdir(parents=True,exist_ok=True);np.save(prepared/'historical_stockout_flags.npy',flags)
    records=d.groupby('series_id').first();series=[]
    for sid in ids:
        r=records.loc[sid];series.append(Series(series_id=sid,item_id=f'FRN_{int(r.product_id):04d}',department=f'MG_{int(r.management_group_id)}',family=f'CAT_{int(r.first_category_id)}',location=f'S{int(r.store_id):04d}',cluster=f'C{int(r.city_id):02d}',supplier=f'SYNTHETIC_MG_{int(r.management_group_id)}',currency='USD'))
    cal=pd.DataFrame({'date':all_dates});parsed=pd.to_datetime(cal.date);cal['wday']=parsed.dt.weekday+1;cal['month']=parsed.dt.month
    provenance={'dataset':'Dingdong-Inc/FreshRetailNet-50K','revision':'08c1fab7f9257bc73679d415d65d644165d351d4','license':'CC-BY-4.0','source_files':{r['file']:r['sha256'] for r in json.loads((OUT/'setup/download_receipt.json').read_text())['files']},'observed':['normalized_daily_sales','hourly_sales','hourly_stockout','hierarchy','historical_weather','historical_promotions'],'simulated':['inventory','supplier','cost_index','lead_time','pack','shelf_life','purchase_order','fault'],'simulator_unit_scale':100,'economic_label':'cost_index; legacy USD schema tag is an internal compatibility label, not monetary evidence','source_observed_stockout_path':str(prepared/'historical_stockout_flags.npy'),'perishable_simulation':{'shelf_life_days':3},'selection':json.loads((target/'selection.json').read_text())}
    panel=Panel(series,sales,np.ones_like(sales),cal,provenance);panel.save(prepared)
    manifest=json.loads((prepared/'manifest.json').read_text());manifest['date_index']='zero-based:0=2024-03-28;90=official evaluation origin';atomic_json(prepared/'manifest.json',manifest)
    atomic_json(target/'eval_validation.json',audit);atomic_json(target/'preparation_complete.json',{'status':'COMPLETE','series':30,'days':97,'training_days':90,'evaluation_days':7,'protocol_sha256':sha(OUT/'protocol.json'),'files_sha256':{str(p.relative_to(ROOT)):sha(p) for p in prepared.iterdir() if p.is_file()}})
    print(json.dumps({'phase':'eval_unsealed_and_panel_prepared','audit':audit}),flush=True)

if __name__=='__main__':
    import sys
    unseal() if len(sys.argv)>1 and sys.argv[1]=='unseal' else main()
