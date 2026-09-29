import json
import numpy as np
import pytest
import httpx
from ega.agents.llm import LLMClient,Extraction,decode_object,ModelUnavailable
from ega.config import LLMConfig,ExperimentConfig
from ega.store import ArtifactStore
from ega.agents.orchestrator import OrchestratorAutonomyAgent
from ega.disturbances import perturb,Fault
from ega.experiment import run_experiment
from ega.evaluation.report import render_report
from ega.evaluation.faithfulness import replay,counterfactual,deletion_test,trace_audit
from ega.evaluation.human_audit import export_packets


def test_llm_http_adapter_mocked_not_real_call(monkeypatch,tmp_path):
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"constraints": [], "issues": ["insufficient evidence"]}'},'finish_reason':'stop'}],'usage':{'total_tokens':17}},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    s=ArtifactStore(tmp_path);client=LLMClient(LLMConfig(enabled=True,model='test',max_calls=2),s)
    a=client.ask('test',{'documents':[]},Extraction)
    assert a.issues and client.tokens==17 and 'response_format' in calls[0]['json'];s.close()


def test_free_form_bridges_reject_ambiguity():
    assert decode_object('A note. {"a":1}')=={'a':1}
    with pytest.raises(ValueError):decode_object('{"a":1} {"b":2}')


def test_remote_http_is_rejected(tmp_path):
    s=ArtifactStore(tmp_path)
    with pytest.raises(ValueError):LLMClient(LLMConfig(enabled=True,model='test',base_url='http://external.example/v1'),s)
    s.close()


def test_hard_failure_stops_before_forecast(snapshot,docs,model,config,tmp_path):
    store=ArtifactStore(tmp_path);agent=OrchestratorAutonomyAgent('D1',model,config,store)
    bad=perturb(snapshot,None,[Fault('derived_field_collapse',140,3,2)])
    d=agent.run(bad,docs,'blocked',7)
    assert not d.autonomy.permitted and not d.plan.orders and d.certificate.quality==0
    assert 'forecast' not in d.trace['references'];store.close()


def test_end_to_end_replay_report_and_audit(panel,config,tmp_path):
    dataset=tmp_path/'data';panel.save(dataset)
    output=tmp_path/'experiment'
    c=ExperimentConfig.model_validate({**config.model_dump(),'dataset':str(dataset),'output':str(output),
            'policies':['D0','D1'],'scenarios':['normal','derived_field_collapse'],'seeds':[7],'days':4})
    rows=run_experiment(c)
    assert len(rows)==4 and rows.chain_valid.all()
    run=next(p.parent for p in output.glob('*/run_manifest.json') if json.loads(p.read_text())['run_id']=='D1-normal-seed7-origin0')
    result=replay(run)
    assert result['state_certificate_matches'] and result['problem_reconstruction_matches'] and result['action_matches']
    assert deletion_test(run)['reconstruction_blocked']
    assert trace_audit(run)['artifacts_hash_verified']
    cf=counterfactual(run,factor='budget',multiplier=0)
    assert not cf['counterfactual_action']['orders']
    report=render_report(output)
    assert report.exists() and 'SYNTHETIC' in report.read_text()
    n=export_packets(output,tmp_path/'audit',participants=3,max_cases=3)
    assert n>0 and (tmp_path/'audit/participant_001/index.html').exists()


def test_bundled_demo_reconstructs_byte_equivalent_problem():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    result=replay(root/'examples/validated_demo/D1__normal__seed7__origin0',140)
    assert result['problem_reconstruction_matches'] and result['action_matches']

def test_anthropic_adapter_mocked_not_real_call(monkeypatch,tmp_path):
    pytest.importorskip('anthropic')
    from types import SimpleNamespace
    from ega.agents.llm import Route
    sent={}
    class Messages:
        def create(self,**request):
            sent.update(request)
            block=SimpleNamespace(type='text',text='{"requested_tool":"stochastic_milp","evidence_refs":[],"escalation_reason":""}')
            usage={'input_tokens':10,'output_tokens':5,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}
            return SimpleNamespace(content=[block],stop_reason='end_turn',model=request['model'],
                                   to_dict=lambda:{'usage':usage,'model':request['model']})
    monkeypatch.setenv('EGA_LLM_API_KEY','test-key')
    s=ArtifactStore(tmp_path)
    client=LLMClient(LLMConfig(enabled=True,provider='anthropic',model='claude-test',fallbacks=False,spend_ledger=str(tmp_path/'spend.json'),max_cost_usd=1,input_usd_per_mtok=1e6,output_usd_per_mtok=0),s)
    client.anthropic=SimpleNamespace(messages=Messages())
    route=client.ask('optimizer',{'x':1},Route)
    assert route.requested_tool=='stochastic_milp' and client.tokens==15 and client.calls==1
    assert sent['output_config']['format']['type']=='json_schema' and 'temperature' not in sent
    from ega.agents.llm import SpendCapReached
    with pytest.raises(SpendCapReached):client.ask('optimizer',{'x':1},Route)  # $10 spent > $1 cap
    s.close()
