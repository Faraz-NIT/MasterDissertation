import copy
import numpy as np
import pandas as pd
import pytest
from ega.forecasting.core import corrected_history,sba_mean,build_forecaster
from ega.forecasting.hierarchy import summing_matrix,bottom_up,mint_shrink
from ega.data.m5 import prepare_m5
from ega.data.panel import Panel
from ega.simulator import InventoryEnvironment
from ega.schemas import Snapshot


def test_forecast_shapes_seed_and_past_only(model,snapshot):
    a=model.predict(snapshot,6,4,9);b=model.predict(snapshot,6,4,9)
    assert a.samples==b.samples
    assert np.asarray(a.samples).shape==(4,2,6)
    assert a.training_end<snapshot.lineage.day
    assert a.diagnostics['coverage'] is None


def test_future_sales_cannot_change_snapshot_forecast(panel,config):
    m=build_forecaster('seasonal_naive',config.forecast).fit(panel,140)
    e=InventoryEnvironment(panel,140,7,'x',config)
    a=m.predict(e.snapshot(56),6,3,9)
    panel.sales[:,140:]=99999
    f=InventoryEnvironment(panel,140,7,'x',config)
    b=m.predict(f.snapshot(56),6,3,9)
    assert a.samples==b.samples


def test_missing_history_not_zeroed(snapshot):
    snapshot.history[0][-1]=None
    x,changed=corrected_history(snapshot)
    assert changed and x[0,-1]>0 and np.isfinite(x).all()


def test_sba_zero_and_intermittent():
    assert sba_mean(np.zeros(40))==0
    assert 0<sba_mean(np.array([0,0,5,0,0,0,3]))<5


def test_no_future_history(snapshot):
    data=snapshot.model_dump();data['history_days'][-1]=data['lineage']['day']
    with pytest.raises(ValueError):Snapshot.model_validate(data)


def test_hierarchy_coherence(panel):
    S,labels,levels=summing_matrix(panel.series)
    bottom=np.arange(panel.n*3).reshape(panel.n,3)
    values=S@bottom
    assert S.shape[1]==panel.n and set(levels)==set(range(12))
    assert values[0].tolist()==bottom.sum(axis=0).tolist()


def test_m5_import_preserves_groups_and_no_backward_fill(tmp_path):
    raw=tmp_path/'raw';raw.mkdir()
    records=[]
    for item,dept in [('A','FOODS_1'),('B','HOUSEHOLD_1')]:
        for store in ['CA_1','CA_2']:
            records.append(dict(id=item+'_'+store+'_evaluation',item_id=item,dept_id=dept,cat_id=dept.split('_')[0],store_id=store,state_id='CA',**{f'd_{j}':float(j%3) for j in range(1,71)}))
    pd.DataFrame(records).to_csv(raw/'sales_train_evaluation.csv',index=False)
    pd.DataFrame({'d':[f'd_{j}' for j in range(1,71)],'date':pd.date_range('2011-01-29',periods=70),'wm_yr_wk':[1+(j//7) for j in range(70)]}).to_csv(raw/'calendar.csv',index=False)
    pd.DataFrame([{'item_id':i,'store_id':s,'wm_yr_wk':w,'sell_price':2.5} for i in ['A','B'] for s in ['CA_1','CA_2'] for w in range(2,11)]).to_csv(raw/'sell_prices.csv',index=False)
    panel=prepare_m5(raw,tmp_path/'canonical',items=2,materialize_facts=True)
    assert panel.n==4 and panel.days==70
    assert np.isnan(panel.prices[:,:7]).all() and np.isfinite(panel.prices[:,7:]).all()
    assert np.isnan(panel.price_at(7)).all()  # day 7 uses price at observed day 6
    assert sum(panel.eligibility(0))==0
    assert (tmp_path/'canonical/catalog.sqlite').exists()
    assert Panel.load(tmp_path/'canonical').provenance['dataset']=='M5'

@pytest.mark.parametrize('name,dependency',[('deep','torch'),('lightgbm','lightgbm')])
def test_optional_forecasters_are_real_models(name,dependency,panel,snapshot,config):
    pytest.importorskip(dependency)
    m=build_forecaster(name,config.forecast).fit(panel,138)
    result=m.predict(snapshot,3,2,7)
    x=np.asarray(result.samples)
    assert x.shape==(2,2,3) and np.isfinite(x).all() and (x>=0).all()
    assert result.training_end==137
