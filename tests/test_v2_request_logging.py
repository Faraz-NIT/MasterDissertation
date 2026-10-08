"""Version2 requests persist before HTTP starts; credentials never enter artifacts."""
import json

import httpx
import pytest

from ega.agents.llm import Extraction, LLMClient, ModelUnavailable
from ega.config import LLMConfig
from ega.store import ArtifactStore


@pytest.mark.parametrize('failure', [False, True])
def test_v2_request_is_audited_before_transport(monkeypatch, tmp_path, failure):
    store=ArtifactStore(tmp_path/'artifacts')
    monkeypatch.setenv('EGA_LLM_API_KEY','dummy-sensitive-value-must-not-be-logged')
    client=LLMClient(LLMConfig(enabled=True,model='mock',model_revision='mock-no-live-inference',
        prompt_profile='v2',retries=0,spend_ledger=str(tmp_path/'spend.json')),store)
    client.audit_decision_id='test-decision'

    def post(url, **kwargs):
        row=store.db.execute('SELECT stage,payload FROM events').fetchone()
        assert row[0]=='llm_request_started'
        artifact=store.get(json.loads(row[1])['output'])
        assert artifact['request']==kwargs['json']
        assert artifact['started_at_utc'] and artifact['attempt']==0
        assert 'dummy-sensitive-value-must-not-be-logged' not in json.dumps(artifact)
        if failure:raise httpx.ConnectError('mocked interrupted request')
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"constraints":[],"issues":[]}'},
            'finish_reason':'stop'}],'usage':{'total_tokens':7}},request=httpx.Request('POST',url))

    monkeypatch.setattr(httpx,'post',post)
    try:
        if failure:
            with pytest.raises(ModelUnavailable):client.ask('test',{'documents':[]},Extraction)
        else:assert not client.ask('test',{'documents':[]},Extraction).issues
        assert store.verify_chain()
        assert client.calls==1 and client.errors==int(failure)
        assert [r[0] for r in store.db.execute('SELECT stage FROM events ORDER BY seq')]==[
            'llm_request_started','llm_request_error' if failure else 'llm_request_response']
        for row in store.db.execute('SELECT payload FROM events'):
            store.get(json.loads(row[0])['output'])
    finally:store.close()
