import asyncio
import pytest
from test_core import at
from test_service import setup


def test_account_samples_have_explicit_identity_and_simulated_provenance():
    from backend.account_samples import account_sample_threads,BUYER,SELLER
    from backend.domain import Message
    rows=account_sample_threads()
    assert len(rows)==15 and len({t['id'] for t in rows})==15
    assert all(len(t['messages'])>=6 for t in rows)
    assert sum(t['id'].startswith('sample-pilot-') for t in rows)==5
    for t in rows:
        assert not t['id'].startswith('gmail-')
        for m in t['messages']:
            parsed=Message.model_validate(m)
            assert parsed.simulated
            assert parsed.sender==(BUYER if parsed.direction=='inbound' else SELLER)
            assert parsed.recipients==[SELLER if parsed.direction=='inbound' else BUYER]
            assert 25<=len(parsed.body.split())<=60
    meridian=next(t for t in rows if t['id']=='sample-pilot-1')
    assert 'SCIM provisioning and deactivation are included' in meridian['messages'][-1]['body']


def test_saved_library_lists_actual_runs_across_models_without_live_call(tmp_path):
    from test_api import client
    app,s=client(tmp_path);time=at('2026-10-09T18:00:00')
    asyncio.run(s.analyze('northstar',time));s.analyzer.model='other-real-test-identity'
    asyncio.run(s.analyze('northstar',time))
    s.analyzer.model='current-test-config'
    result=app.get('/api/saved-runs').json()
    assert len(result['runs'])==2
    assert {r['model'] for r in result['runs']}=={'test-only','other-real-test-identity'}
    rid=result['runs'][0]['id']
    view=app.get(f'/api/saved-runs/{rid}?as_of=2026-10-09T18:00:00%2B05:30').json()
    assert view['status']=='analyzed' and view['provenance']['model']!='current-test-config'
    assert view['provenance']['saved_run_id']==rid and s.analyzer.calls==2
    assert not view['provenance']['extraction_matches_current_config']
    assert view['ingestion_source']=='synthetic'
    assert 'raw_json' not in result['runs'][0]


def test_saved_run_excludes_future_evidence_and_does_not_claim_missing_message_version(tmp_path):
    from test_api import client
    app,s=client(tmp_path);time=at('2026-10-09T18:00:00')
    asyncio.run(s.analyze('northstar',time));rid=s.store.history('northstar')[0]['id']
    assert app.get(f'/api/saved-runs/{rid}?as_of=2026-10-04T09:00:00%2B05:30').status_code==409


def test_clear_demo_workspace_is_reversible_and_preserves_runs(tmp_path):
    from test_api import client
    app,s=client(tmp_path);asyncio.run(s.analyze('northstar',at('2026-10-09T18:00:00')))
    assert app.post('/api/demo/visibility',json={'visible':False}).status_code==200
    assert app.get('/api/threads').json()['threads']==[]
    assert s.store.thread('northstar') and len(s.store.history('northstar'))==1
    assert app.get('/api/saved-runs').json()['runs']
    assert app.post('/api/demo/visibility',json={'visible':True}).status_code==200
    assert app.get('/api/threads').json()['threads']


def test_sync_applies_demo_preference_only_on_success(tmp_path,monkeypatch):
    from test_api import client
    from backend.gmail import GmailError
    app,s=client(tmp_path)
    monkeypatch.setattr(app.app.state.gmail,'sync_threads',lambda _: {'status':'completed','fetched':0})
    assert app.post('/api/gmail/sync',json={'keep_demos':False}).status_code==200
    assert app.get('/api/threads').json()['threads']==[]
    app.post('/api/demo/visibility',json={'visible':True})
    def fail(_):raise GmailError('Connection failed')
    monkeypatch.setattr(app.app.state.gmail,'sync_threads',fail)
    assert app.post('/api/gmail/sync',json={'keep_demos':False}).status_code==409
    assert app.get('/api/threads').json()['threads']
