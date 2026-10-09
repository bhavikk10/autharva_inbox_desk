import asyncio
import pytest
from test_core import at
from test_service import setup, TestAnalyzer
from backend.jobs import AnalysisJobs


def test_forced_runs_preserved_cache_reuse_not_a_run(tmp_path):
    async def run():
        s=setup(tmp_path);time=at('2026-10-09T18:00:00')
        await s.analyze('northstar',time)
        await s.analyze('northstar',time)
        assert len(s.store.history('northstar'))==1
        await s.analyze('northstar',time,force=True)
        history=s.store.history('northstar')
        assert len(history)==2 and history[0]['id']!=history[1]['id']
        assert all(h['run_context']['as_of']==time.isoformat() for h in history)
        assert all(h['run_context']['attention']['tier'] for h in history)
    asyncio.run(run())


def test_reviews_are_tied_to_run_and_do_not_change_assessment(tmp_path):
    async def run():
        s=setup(tmp_path);time=at('2026-10-09T18:00:00')
        result=await s.analyze('northstar',time);h=s.store.history('northstar')[0]
        s.store.add_review('northstar',h['id'],'T4','The ask was answered in the latest reply.')
        assert s.view('northstar',time)['attention']==result['attention']
        assert s.store.reviews('northstar')[0]['run_id']==h['id']
        with pytest.raises(ValueError):s.store.add_review('evergreen',h['id'],'T1','Wrong thread')
    asyncio.run(run())


def test_cancel_finishes_current_call_but_not_pending_and_retry_errors_only(tmp_path):
    async def run():
        entered=asyncio.Event();release=asyncio.Event()
        class Slow(TestAnalyzer):
            async def analyze(self,*args):
                entered.set();await release.wait();return await super().analyze(*args)
        s=setup(tmp_path,Slow());j=AnalysisJobs(s);await j.start()
        try:
            job=j.submit(['northstar','evergreen'],at('2026-10-09T18:00:00'))
            await entered.wait();j.cancel(job['id']);release.set()
            state=await j.wait(job['id'])
            assert state['status']=='cancelled' and s.analyzer.calls==1
            assert state['items'][1]['status']=='cancelled'
            with pytest.raises(ValueError):j.retry(job['id'])
            s.analyzer.fail=True
            failed=j.submit(['evergreen'],at('2026-10-09T18:00:00'),force=True)
            await j.wait(failed['id']);s.analyzer.fail=False
            retry=j.retry(failed['id']);await j.wait(retry['id'])
            assert retry['id']!=failed['id'] and j.get(retry['id'])['items'][0]['status']=='analyzed'
        finally:await j.close()
    asyncio.run(run())


def test_drafts_share_fifo_and_do_not_replace_assessment(tmp_path):
    from backend.drafts import ReplyDraft,validate_draft
    async def run():
        order=[];s=setup(tmp_path)
        class Writer:
            async def generate(self,thread,messages,*args):
                order.append('draft');d=ReplyDraft(body='Could you clarify the remaining question?',rationale='Clarify the request.',evidence=[{'message_id':messages[0].id,'quote':messages[0].body[:30]}])
                validate_draft(d,messages);return d,d.model_dump_json(),4
        s.draft_writer=Writer()
        original=s.analyzer.analyze
        async def analyze(*args):order.append('analysis');return await original(*args)
        s.analyzer.analyze=analyze
        jobs=AnalysisJobs(s);await jobs.start()
        try:
            a=jobs.submit(['northstar'],at('2026-10-09T18:00:00'))
            b=jobs.submit(['northstar'],at('2026-10-09T18:00:00'),task='draft')
            await jobs.wait(b['id'])
            assert order==['analysis','draft']
            assert jobs.get(b['id'])['items'][0]['status']=='drafted'
            assert len(s.store.history('northstar'))==1
            draft=s.store.operations('draft')[0]
            assert draft['cache_key']==s.prepared('northstar',at('2026-10-09T18:00:00'))[2]
        finally:await jobs.close()
    asyncio.run(run())


def test_draft_rejects_unknown_ids_and_changed_evidence(tmp_path):
    from backend.drafts import ReplyDraft,validate_draft
    from backend.domain import Message
    s=setup(tmp_path);messages=[Message(**m) for m in s.store.thread('northstar')['messages']]
    d=ReplyDraft(body='Hello',rationale='Context',evidence=[{'message_id':'invented','quote':'Hello'}])
    with pytest.raises(ValueError,match='unknown'):validate_draft(d,messages)
    d.evidence[0].message_id=messages[0].id
    d.evidence[0].quote='invented quotation'
    with pytest.raises(ValueError,match='verbatim'):validate_draft(d,messages)


def test_sync_unchanged_skips_full_body_and_changed_updates_only_current_batch(tmp_path,monkeypatch):
    from backend.gmail import GmailConnection,GmailEmailProvider,normalize_thread
    from test_gmail import mail
    from types import SimpleNamespace
    s=setup(tmp_path);email='test@example.com'
    raw={'id':'t','historyId':'1','messages':[mail('m1','buyer@example.com','Please send the file.') ]}
    row=normalize_thread(raw,email);s.store.import_threads([row])
    s.store.save_operation('batch','import',{'source':'gmail','status':'completed','thread_ids':[row['id']],'history_ids':{row['id']:'1'}})
    connection=GmailConnection(tmp_path/'gmail')
    monkeypatch.setattr(connection,'_load_credentials',lambda:SimpleNamespace(valid=True,token='test',has_scopes=lambda _:True))
    monkeypatch.setattr(connection,'_account',lambda _:email)
    monkeypatch.setattr(connection,'_save',lambda *_:None)
    calls=[]
    def fetch(self,path,params):calls.append(params['format']);return raw
    monkeypatch.setattr(GmailEmailProvider,'request',fetch)
    result=connection.sync_threads(s.store)
    assert calls==['metadata'] and result['unchanged']==1
    raw['historyId']='2';raw['messages'].append(mail('m2',email,'Here is the answer.',['SENT']))
    result=connection.sync_threads(s.store)
    assert calls==['metadata','metadata','full'] and result['imported']==1
    assert len(s.store.thread(row['id'])['messages'])==2
    assert result['thread_ids']==[row['id']] and result['history_ids'][row['id']]=='2'


def test_history_api_hides_raw_and_review_validates_thread(tmp_path):
    from test_api import client
    app,s=client(tmp_path)
    asyncio.run(s.analyze('northstar',at('2026-10-09T18:00:00')))
    h=app.get('/api/threads/northstar/history').json()
    assert 'raw_json' not in h['runs'][0]
    rid=h['runs'][0]['id']
    r=app.post('/api/threads/northstar/reviews',json={'run_id':rid,'expected_tier':'T3','note':'The reply answered the ask.'})
    assert r.status_code==200
    assert app.post('/api/threads/evergreen/reviews',json={'run_id':rid,'note':'Wrong thread'}).status_code==422


def test_blank_draft_evidence_is_rejected(tmp_path):
    from backend.drafts import ReplyDraft,validate_draft
    from backend.domain import Message
    s=setup(tmp_path);messages=[Message(**m) for m in s.store.thread('northstar')['messages']]
    d=ReplyDraft(body='Hello',rationale='Context',evidence=[{'message_id':messages[0].id,'quote':'   '}])
    with pytest.raises(ValueError,match='verbatim'):validate_draft(d,messages)


def test_sync_retains_local_data_on_partial_failure_and_rejects_wrong_account(tmp_path,monkeypatch):
    import httpx
    from types import SimpleNamespace
    from backend.gmail import GmailConnection,GmailEmailProvider,normalize_thread,GmailError
    from test_gmail import mail
    s=setup(tmp_path);email='me@example.com'
    row=normalize_thread({'id':'t','messages':[mail('m','sender@example.com','Please send a reply.')]},email)
    s.store.import_threads([row]);s.store.save_operation('batch','import',{'status':'completed','source':'gmail','thread_ids':[row['id']]})
    c=GmailConnection(tmp_path/'gmail')
    monkeypatch.setattr(c,'_load_credentials',lambda:SimpleNamespace(valid=True,token='test',has_scopes=lambda _:True))
    monkeypatch.setattr(c,'_account',lambda _:email);monkeypatch.setattr(c,'_save',lambda *_:None)
    def fail(*args):raise httpx.ConnectError('unavailable')
    monkeypatch.setattr(GmailEmailProvider,'request',fail)
    result=c.sync_threads(s.store)
    assert result['status']=='partial' and result['thread_ids']==[row['id']]
    assert s.store.thread(row['id'])==row
    monkeypatch.setattr(c,'_account',lambda _:'different@example.com')
    with pytest.raises(GmailError,match='another'):c.sync_threads(s.store)


def test_gmail_reservation_blocks_draft_and_analysis_submissions(tmp_path,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from test_api import client
    from backend.gmail import normalize_thread
    from test_gmail import mail
    app,s=client(tmp_path)
    row=normalize_thread({'id':'t','messages':[mail('m','sender@example.com','Please reply.')]},'me@example.com');s.store.import_threads([row])
    entered=threading.Event();release=threading.Event()
    def sync(_):entered.set();release.wait(5);return {'status':'completed'}
    monkeypatch.setattr(app.app.state.gmail,'sync_threads',sync)
    with app,ThreadPoolExecutor() as pool:
        future=pool.submit(app.post,'/api/gmail/sync')
        assert entered.wait(5)
        try:
            for route in ['analyze','drafts']:
                response=app.post(f"/api/threads/{row['id']}/{route}",json={'as_of':'2026-10-09T18:00:00+05:30'})
                assert response.status_code==409
            assert s.analyzer.calls==0
        finally:release.set()
        assert future.result().status_code==200


def test_legacy_review_identity_survives_forced_run_and_replay_is_idempotent(tmp_path):
    from backend.domain import Assessment
    async def run():
        s=setup(tmp_path);time=at('2026-10-09T18:00:00')
        await s.analyze('northstar',time)
        with s.store.connection() as db:db.execute("DELETE FROM analysis_operations WHERE kind='run'")
        legacy=s.store.history('northstar')[0]
        s.store.add_review('northstar',legacy['id'],'T1','Expected overdue legal decision.')
        snapshot=s.store.snapshot(legacy['cache_key'])
        s.store.save_snapshot(snapshot['cache_key'],'northstar',snapshot['provider'],snapshot['model'],Assessment.model_validate_json(snapshot['assessment_json']),snapshot['raw_json'],snapshot['created_at'],snapshot['duration_ms'])
        assert len(s.store.history('northstar'))==1
        await s.analyze('northstar',time,force=True)
        assert legacy['id'] in [r['id'] for r in s.store.history('northstar')]
        assert s.store.reviews('northstar')[0]['run_id']==legacy['id']
    asyncio.run(run())


def test_draft_timeout_has_explicit_error_and_no_fallback(tmp_path):
    async def run():
        s=setup(tmp_path)
        class Writer:
            async def generate(self,*args):raise TimeoutError()
        s.draft_writer=Writer();j=AnalysisJobs(s);await j.start()
        try:
            job=j.submit(['northstar'],at('2026-10-09T18:00:00'),task='draft')
            result=await j.wait(job['id'])
            assert result['items'][0]['status']=='error' and 'timed out' in result['items'][0]['error']
            assert s.store.operations('draft')==[] and s.analyzer.calls==0
        finally:await j.close()
    asyncio.run(run())


def test_saved_draft_is_stale_after_clock_change_without_model_call(tmp_path):
    from test_api import client
    app,s=client(tmp_path)
    _,_,key=s.prepared('northstar',at('2026-10-09T18:00:00'))
    s.store.save_operation('saved','draft',{'thread_id':'northstar','as_of':at('2026-10-09T18:00:00').isoformat(),'draft':{'body':'actual test output','rationale':'test','evidence':[]}},key)
    before=app.get('/api/threads/northstar/drafts?as_of=2026-10-09T18:00:00%2B05:30').json()
    after=app.get('/api/threads/northstar/drafts?as_of=2026-10-09T10:00:00%2B05:30').json()
    assert before['drafts'][0]['stale'] is False and after['drafts'][0]['stale'] is True
    assert s.analyzer.calls==0
