import asyncio
from datetime import datetime
import pytest
from test_core import assessment, item, at


class TestAnalyzer:
    __test__ = False
    provider='test'
    model='test-only'
    calls=0
    def __init__(self, result=None, fail=False):
        self.result=result or assessment()
        self.fail=fail
    async def analyze(self, thread, messages):
        self.calls+=1
        if self.fail: raise ValueError('Provider unavailable')
        return self.result, self.result.model_dump_json(), 12


def setup(tmp_path, analyzer=None):
    from backend.service import AttentionService
    from backend.store import Store
    store=Store(tmp_path/'test.sqlite')
    store.seed()
    return AttentionService(store,analyzer or TestAnalyzer())


def test_invented_date_is_classified_as_evidence_failure(tmp_path):
    async def run():
        service=setup(tmp_path)
        tid='northstar';clock=at('2026-10-09T18:00:00')
        mid=service.prepared(tid,clock)[1][0].id
        service.analyzer.result=assessment([item(evidence_message_ids=[mid],deadline={'expression':'2099-01-01','message_id':mid})])
        result=await service.analyze(tid,clock)
        assert result['status']=='error' and result['attention'] is None
        assert service.store.latest_attempt(service.prepared(tid,clock)[2])['error_category']=='evidence'
    asyncio.run(run())


def test_cache_reuse_on_clock_change(tmp_path):
    async def run():
        analyzer=TestAnalyzer()
        service=setup(tmp_path,analyzer)
        await service.analyze('northstar',at('2026-10-08T15:00:00'))
        await service.analyze('northstar',at('2026-10-09T18:00:00'))
        assert analyzer.calls==1
    asyncio.run(run())


def test_history_from_future_message_version_does_not_constrain_rewind(tmp_path):
    from types import SimpleNamespace
    from test_grounding import grounded_item
    from test_core import message
    from backend.domain import LedgerObligation,Assessment
    first=message(body='Please confirm SCIM urgently. Please provide both requirements.')
    later=message(body='SCIM is supported.').model_copy(update={'id':'m2','sent_at':at('2026-10-09T19:00:00')})
    old_item=grounded_item().model_dump()
    old_item['action_evidence']={'message_id':first.id,'quote':'Please provide both requirements.'}
    old_item.update(status='fulfilled',resolution_evidence={'message_id':'m2','quote':'SCIM is supported.'})
    old=assessment(category='work',conversation_state='active')
    old.obligations=[LedgerObligation(**old_item)]
    old=Assessment.model_validate(old.model_dump(exclude={'open_items','resolved_items'}))
    now=assessment(category='work',conversation_state='active')
    now.obligations=[LedgerObligation(**grounded_item().model_dump(),status='open',resolution_evidence=None)]
    now=Assessment.model_validate(now.model_dump(exclude={'open_items','resolved_items'}))
    analyzer=TestAnalyzer(old);analyzer.extraction_contract='test-grounded'
    service=setup(tmp_path,analyzer)
    service.store.seed(SimpleNamespace(list_threads=lambda:[{'id':'sample-clock','company':'Clock',
        'subject':'SCIM','contact':'Buyer','deal_value':None,'messages':[first.model_dump(mode='json'),later.model_dump(mode='json')]}]))
    async def run():
        assert (await service.analyze('sample-clock',at('2026-10-09T19:00:00')))['status']=='analyzed'
        analyzer.result=now
        earlier=await service.analyze('sample-clock',at('2026-10-09T18:00:00'),force=True)
        assert earlier['status']=='analyzed' and len(earlier['messages'])==1
    asyncio.run(run())


def test_glm_thinking_configuration_has_a_distinct_cache_identity(tmp_path):
    from backend.providers import GLMAnalyzer,Settings
    service=setup(tmp_path,GLMAnalyzer(Settings(glm_key='test-only')))
    time=at('2026-10-09T18:00:00')
    original=service.prepared('northstar',time)[2]
    service.analyzer.settings.glm_thinking='disabled'
    assert service.prepared('northstar',time)[2]!=original


def test_new_message_invalidates_cache_and_removes_future_visibility(tmp_path):
    async def run():
        analyzer=TestAnalyzer()
        service=setup(tmp_path,analyzer)
        await service.analyze('northstar',at('2026-10-09T18:00:00'))
        service.append_message('northstar','inbound','Legal approved. Ready to sign.',at('2026-10-09T18:05:00'))
        early=service.view('northstar',at('2026-10-09T18:00:00'))
        assert len(early['messages'])==2 and early['status']=='analyzed'
        later=service.view('northstar',at('2026-10-09T18:05:00'))
        assert len(later['messages'])==3 and later['status']=='unassessed'
        await service.analyze('northstar',at('2026-10-09T18:05:00'))
        assert analyzer.calls==2
    asyncio.run(run())


def test_error_never_becomes_t4_or_fake_success(tmp_path):
    async def run():
        service=setup(tmp_path,TestAnalyzer(fail=True))
        result=await service.analyze('northstar',at('2026-10-09T18:00:00'))
        assert result['status']=='error' and result['attention'] is None
        assert service.store.snapshot_count()==0
    asyncio.run(run())


def test_invalid_evidence_not_persisted(tmp_path):
    async def run():
        service=setup(tmp_path,TestAnalyzer(assessment([item(evidence_message_ids=['invented'])])))
        result=await service.analyze('northstar',at('2026-10-09T18:00:00'))
        assert result['status']=='error' and service.store.snapshot_count()==0
    asyncio.run(run())


def test_reset_keeps_authentic_snapshots_and_removes_simulated_messages(tmp_path):
    service=setup(tmp_path)
    service.append_message('northstar','outbound','Checking in.',at('2026-10-09T18:00:00'))
    assert len(service.store.thread('northstar')['messages'])==3
    service.reset()
    assert len(service.store.thread('northstar')['messages'])==2


def test_no_messages_before_thread_start(tmp_path):
    service=setup(tmp_path)
    result=service.view('kinetic',at('2026-10-08T12:00:00'))
    assert result['status']=='not_started' and result['attention'] is None


def test_labels_frozen_before_inference_and_separate_from_inputs():
    import json
    from pathlib import Path
    from backend.fixtures import seed_threads
    labels=json.loads(Path('data/expected_labels.json').read_text())
    assert len(labels['cases'])==20
    assert sum(c['split']=='held_out' for c in labels['cases'])==5
    expanded=json.loads(Path('data/expected_labels_expansion.json').read_text())
    assert len(expanded['cases'])==15
    assert sum(c['split']=='held_out' for c in expanded['cases'])==5
    assert {c['id'] for c in labels['cases']}.isdisjoint({c['id'] for c in expanded['cases']})
    long=json.loads(Path('data/expected_labels_long.json').read_text())
    assert len(long['cases'])==8 and all(c['split']=='development' for c in long['cases'])
    edge=json.loads(Path('data/expected_labels_long_edge.json').read_text())
    assert len(edge['cases'])==20 and all(c['split']=='development' for c in edge['cases'])
    assert {c['id'] for c in labels['cases']+expanded['cases']+long['cases']+edge['cases']}=={t['id'] for t in seed_threads()}
    assert all('tier' not in t and 'split' not in t for t in seed_threads())


def test_malformed_model_response_is_retained_locally_without_an_assessment(tmp_path,monkeypatch):
    import httpx
    import backend.providers as providers
    monkeypatch.setattr(providers,'ROOT',tmp_path)
    raw='{"unexpected":"private email fragment"}'
    async def post(self,url,**kwargs):
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':raw}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    service=setup(tmp_path,providers.GLMAnalyzer(providers.Settings(glm_key='test-only')))
    result=asyncio.run(service.analyze('northstar',at('2026-10-09T18:00:00')))
    assert result['status']=='error' and result['attention'] is None
    assert 'private email fragment' not in result['error']
    assert service.store.snapshot_count()==0
    paths=list((tmp_path/'rejected').glob('*.json'))
    assert len(paths)==1 and paths[0].read_text()==raw


@pytest.mark.parametrize('changed_contract',[False,True])
@pytest.mark.parametrize('tid',['gmail-test','sample-test'])
def test_gmail_history_guard_applies_only_within_same_extraction_contract(tmp_path,changed_contract,tid):
    from test_grounding import grounded_item
    from test_core import message
    from backend.domain import LedgerObligation,Assessment
    old=assessment(category='work',conversation_state='active')
    old.obligations=[LedgerObligation(**grounded_item().model_dump(),status='open',resolution_evidence=None)]
    old=Assessment.model_validate(old.model_dump(exclude={'open_items','resolved_items'}))
    current=assessment(category='work',conversation_state='informational');current.obligations=[]
    a=TestAnalyzer(old);a.extraction_contract='test-grounded'
    s=setup(tmp_path,a)
    row={'id':tid,'company':'Example','subject':'Task','contact':'Example', 'deal_value':None,'messages':[message(body='Please confirm SCIM urgently.').model_dump(mode='json')]}
    if tid.startswith('gmail-'):s.store.import_threads([row])
    else:
        from types import SimpleNamespace
        s.store.seed(SimpleNamespace(list_threads=lambda:[row]))
    original=s.context
    async def run():
        assert (await s.analyze(tid,at('2026-10-09T18:00:00')))['status']=='analyzed'
        a.result=current
        if changed_contract:s.context=lambda t:{**original(t),'prompt_variant':'new-contract'}
        result=await s.analyze(tid,at('2026-10-09T18:00:00'),force=True)
        assert result['status']==('analyzed' if changed_contract else 'error')
    asyncio.run(run())
