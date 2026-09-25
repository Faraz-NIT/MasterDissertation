import pytest
from ega.quality import certify
from ega.disturbances import perturb,Fault,QUALITY_CLASSES,FaultSchedule
from ega.config import QualityLayerConfig
from ega.util import digest


def test_clean_certificate(snapshot,config):
    c=certify(snapshot,config.gate);assert c.quality==1 and not c.hard_fail

@pytest.mark.parametrize('family',QUALITY_CLASSES)
def test_fault_detected(snapshot,config,family):
    previous=snapshot.model_copy(deep=True)
    previous.lineage.day-=1
    # A previous snapshot must contain a different, plausible quantity for frozen-feed tests.
    previous.inventory[0].quantity+=10
    snapshot.movement_volume=10
    bad=perturb(snapshot,previous,[Fault(family,138,5,2)])
    cert=certify(bad,config.gate)
    assert cert.quality<1,(family,cert)
    assert any(c.family==family and c.outcome!='pass' for c in cert.checks)


def test_fault_does_not_modify_true_state(snapshot):
    before=digest(snapshot)
    observed=perturb(snapshot,None,[Fault('derived_field_collapse',140,3,2)])
    assert digest(snapshot)==before and observed.inventory[0].quantity==0


def test_hard_failure_zeroes_quality(snapshot,config):
    snapshot.inventory[0].quantity=-1
    assert certify(snapshot,config.gate).quality==0


def test_missing_dates_warn_not_invented(snapshot,config):
    snapshot.open_orders[0].due_day=None
    c=certify(snapshot,config.gate)
    assert 0<c.quality<1 and not c.hard_fail


def test_common_fault_random_streams():
    q=QualityLayerConfig(onset_rate=.5)
    a=FaultSchedule('mixed_quality',100,30,4,q)
    b=FaultSchedule('mixed_quality',100,30,4,q)
    assert a.events==b.events
    assert a.events!=FaultSchedule('mixed_quality',100,30,5,q).events
