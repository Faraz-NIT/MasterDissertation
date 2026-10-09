"""Meaningful invariants for the new allocator, FIFO simulator and source gate."""
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts/ollama_clean_study"))
from core import Inventory, checks, constrained_order, conventional_order, rng, verify_source


def rules():
    return {"rules":[{"supplier":f"S{i+1}","pack":p,"moq":p*2,"lead_days":1,"capacity":c}
            for i,(p,c) in enumerate([(2,12),(4,24),(6,36)])],"budget":48}


def data(dataset="RetailNet"):
    return {"series_ids":[str(i) for i in range(30)],"dataset":dataset,
            "historical_mean":np.ones(30)*2,"groups":np.arange(30)%3}


def test_both_allocators_respect_pack_moq_capacity_and_budget():
    groups=np.arange(30)%3
    for seed in range(8):
        target=rng(seed,"allocator_test").uniform(0,20,30)
        for q,status in [conventional_order(target,rules(),groups),constrained_order(target,np.ones(30),rules(),groups)]:
            assert status["feasible"]
            assert not checks(q,rules(),groups)
            assert q.sum()<=48


def test_exact_source_gate_rejects_wrong_numbers_and_duplicate_suppliers():
    source=rules()
    valid,count,_=verify_source(source,source)
    assert valid and count==13
    changed={"rules":[dict(r) for r in source["rules"]],"budget":48}
    changed["rules"][0]["pack"]=6
    assert not verify_source(changed,source)[0]
    changed["rules"][0]=dict(changed["rules"][1])
    assert not verify_source(changed,source)[0]


def test_fifo_sales_then_expiry_conserve_stock():
    env=Inventory(data(),101)
    env.begin(0);first=env.end(0,np.ones(30))
    assert first["sales"]==30 and first["expiry_units"]==30 and first["stock"]==120
    env.begin(1);second=env.end(1,np.zeros(30))
    assert second["expiry_units"]==60 and second["stock"]==60
    env.begin(2);third=env.end(2,np.zeros(30))
    assert third["expiry_units"]==60 and third["stock"]==0
    assert env.initial_units==sum(x["sales"]+x["expiry_units"] for x in (first,second,third))


def test_supply_is_paired_by_opportunity_not_previous_action_count():
    left=Inventory(data("M5"),108);right=Inventory(data("M5"),108)
    groups=np.arange(30)%3
    q=np.zeros(30);q[0]=4
    left.execute(0,q,rules(),groups)
    q=np.zeros(30);q[1]=8
    left.execute(1,q,rules(),groups);right.execute(1,q,rules(),groups)
    assert [p for p in left.pending if p["ordered"]==1]==right.pending


def test_age_projection_does_not_count_stock_that_expires_before_delivery():
    fresh=Inventory(data(),101);durable=Inventory(data("M5"),101)
    forecast=np.ones((30,14))*2
    target_f,_=fresh.target(forecast,np.zeros(30),0,rules(),np.arange(30)%3,"balanced",True)
    target_d,_=durable.target(forecast,np.zeros(30),0,rules(),np.arange(30)%3,"balanced",True)
    assert np.all(target_f>=target_d)
