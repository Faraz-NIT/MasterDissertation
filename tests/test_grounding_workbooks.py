import json
import pytest
from ega.evaluation.grounding import make_corpus,evaluate_corpus
from ega.data.workbooks import parse_season_month,cluster_union
from ega.calibration import calibrate
from ega.disturbances import FaultSchedule
from ega.config import QualityLayerConfig


def test_grounding_template_corpus(tmp_path):
    path=tmp_path/'corpus.jsonl';assert make_corpus(path)==6
    results=evaluate_corpus(path,tmp_path/'run')
    assert all(x['whole_set_exact_match'] and not x['escalated'] for x in results)


def test_prose_not_passed_as_mock_llm(tmp_path):
    path=tmp_path/'prose.jsonl';make_corpus(path,True)
    results=evaluate_corpus(path,tmp_path/'run')
    assert all(x['escalated'] for x in results)


def test_year_rollover_and_cluster_union():
    assert parse_season_month(2026,9,1)==(2027,1)
    assert parse_season_month(2026,9,10)==(2026,10)
    locations=[{'location':'A','cluster':'CA'},{'location':'B','cluster':'TX'}]
    assert cluster_union(['CA','ALL'],locations)==['A','B']
    with pytest.raises(ValueError):cluster_union(['UNKNOWN'],locations)


def test_calibration_refuses_identifiers(tmp_path):
    f=tmp_path/'incidents.csv';f.write_text('failure_class,duration_days,retailer_id\nfeed_gap,2,private\n')
    with pytest.raises(ValueError):calibrate(f,100,'test',tmp_path/'calibration.json')


def test_isolated_calibration_not_promoted_to_regular_rate(tmp_path):
    f=tmp_path/'incidents.csv';f.write_text('failure_class,duration_days\nfeed_gap,2\n')
    out=tmp_path/'calibration.json';calibrate(f,100,'SYNTHETIC TEST ONLY',out)
    q=QualityLayerConfig(calibrated=True,calibration_file=str(out),onset_rate=1)
    assert not FaultSchedule('mixed_quality',100,50,7,q).events
