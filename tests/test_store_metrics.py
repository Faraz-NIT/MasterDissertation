import json
import numpy as np
import pytest
from ega.store import ArtifactStore
from ega.schemas import Receipt,assert_lineage
from ega.evaluation.metrics import cvar,crps_samples,bullwhip,paired_bootstrap,holm,pinball
from ega.config import ExperimentConfig
from ega.util import keyed_rng


def test_content_hash_tampering(tmp_path):
    store=ArtifactStore(tmp_path);ref=store.put({'a':1});assert store.get(ref)=={'a':1}
    (tmp_path/'objects'/f'{ref}.json').write_text('{"a":2}')
    with pytest.raises(ValueError):store.get(ref)
    store.close()


def test_audit_chain_tampering(tmp_path):
    s=ArtifactStore(tmp_path);s.event('a','observe',{'a':1});s.event('a','forecast',{'b':2});assert s.verify_chain()
    s.db.execute("UPDATE events SET payload='{}' WHERE seq=1");s.db.commit()
    assert not s.verify_chain();s.close()


def test_receipt_idempotency_collision(tmp_path):
    s=ArtifactStore(tmp_path)
    a=Receipt(decision_id='d',idempotency_key='d',action_hash='a',status='executed',order_ids=['order'])
    assert s.record_receipt(a)==s.record_receipt(a)
    with pytest.raises(ValueError):s.record_receipt(a.model_copy(update={'action_hash':'b'}))
    s.close()


def test_memory_expiry_and_approval(tmp_path):
    s=ArtifactStore(tmp_path)
    with pytest.raises(ValueError):s.memory_write('k',{},'',5)
    s.memory_write('k',{'note':'reviewed'},'reviewer',5)
    assert s.memory_read(['k'],5) and not s.memory_read(['k'],6);s.close()


def test_lineage_mismatch(snapshot):
    other=snapshot.model_copy(deep=True);other.lineage.snapshot_version='other'
    with pytest.raises(ValueError):assert_lineage(snapshot,other)


def test_cvar_fractional_tail():
    assert cvar([1,2,3,4],.5)==3.5
    assert cvar([1,2,3,4],.625)==pytest.approx((4+0.5*3)/1.5)


def test_crps_matches_definition():
    x=np.array([1.,2.,4.]);y=3.
    expected=np.abs(x-y).mean()-.5*np.abs(x[:,None]-x[None,:]).mean()
    assert crps_samples(y,x)==pytest.approx(expected)


def test_constant_demand_not_infinite_bullwhip():assert bullwhip([1,2,3],[2,2,2]) is None


def test_paired_bootstrap_and_holm():
    result=paired_bootstrap([3,4,5],[1,2,3],resamples=100)
    assert result['mean_difference']==2 and result['n_pairs']==3
    assert holm([.01,.04,.2])==pytest.approx([.03,.08,.2])
    with pytest.raises(ValueError):paired_bootstrap([1],[1])


def test_real_llm_required_not_fake_b10():
    with pytest.raises(ValueError):ExperimentConfig(policies=['B10'])


def test_rng_is_order_independent():
    a=keyed_rng(7,'supply','series',10).random(4)
    _=keyed_rng(7,'anything_else').random(50)
    assert np.array_equal(a,keyed_rng(7,'supply','series',10).random(4))
