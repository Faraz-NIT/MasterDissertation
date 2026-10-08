"""Public data invariants must detect a broken hourly/stockout mapping."""
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('fresh_prepare',Path(__file__).resolve().parents[1]/'scripts/freshretailnet/prepare_data.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def row():
    sales=np.zeros(24);sales[8]=.4;status=np.zeros(24,dtype=int);status[21]=1;status[22]=1
    return dict(store_id=1,product_id=2,city_id=0,management_group_id=0,first_category_id=0,second_category_id=0,third_category_id=0,dt='2024-01-01',sale_amount=.4,hours_sale=sales,hours_stock_status=status,stock_hour6_22_cnt=1,discount=1.)

def test_operating_hour_endpoint_and_daily_total(tmp_path):
    p=tmp_path/'x.parquet';pd.DataFrame([row()]).to_parquet(p)
    _,result=module.validate(p)
    assert result['stockout_flag_value']==1
    assert result['operating_hour_stockout_fraction']==1/16
    assert result['invalid_rows']['sales_alignment']==0

@pytest.mark.parametrize('field,value',[('stock_hour6_22_cnt',2),('sale_amount',.5)])
def test_wrong_availability_alignment_or_total_rejected(tmp_path,field,value):
    data=row();data[field]=value;p=tmp_path/'x.parquet';pd.DataFrame([data]).to_parquet(p)
    with pytest.raises(AssertionError):module.validate(p)

def test_duplicate_observation_rejected(tmp_path):
    p=tmp_path/'x.parquet';pd.DataFrame([row(),row()]).to_parquet(p)
    with pytest.raises(AssertionError):module.validate(p)

def test_unusual_discount_preserved_as_observed_flag(tmp_path):
    data=row();data['discount']=1.2;p=tmp_path/'x.parquet';pd.DataFrame([data]).to_parquet(p)
    _,result=module.validate(p)
    assert result['invalid_rows']['invalid_discount']==1
