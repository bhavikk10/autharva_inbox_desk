import asyncio
from datetime import datetime
from types import SimpleNamespace
import httpx
import pytest
from test_core import at,assessment,item,message


def test_general_mail_obligations_are_not_suppressed_by_sales_flag():
    from backend.policy import evaluate
    data=assessment([item(kind='ask',owner='us',important=False,material=False,urgent=False,deadline=None)])
    data.is_sales_related=False
    data.category='personal';data.conversation_state='active'
    assert evaluate(data,[message()],at('2026-10-07T18:00:00'),profile='general')['tier']=='T2'
    data.open_items[0].important=True
    assert evaluate(data,[message()],at('2026-10-07T18:00:00'),profile='general')['tier']=='T1'
    assert evaluate(data,[message()],at('2026-10-07T18:00:00'))['tier']=='T4'


@pytest.mark.parametrize('category',['promotion','spam','notification'])
def test_informational_mail_has_no_invented_attention(category):
    from backend.policy import evaluate
    data=assessment();data.is_sales_related=False
    data.category=category;data.conversation_state='informational'
    assert evaluate(data,[message()],at('2026-10-07T18:00:00'),profile='general')['tier']=='T4'


def test_personal_waiting_and_explicit_urgency_receive_tiers():
    from backend.policy import evaluate
    data=assessment();data.is_sales_related=False
    data.category='work';data.conversation_state='active'
    assert evaluate(data,[message()],at('2026-10-07T18:00:00'),profile='general')['tier']=='T3'
    data.open_items=[item(owner='us',kind='ask',material=False,important=False,urgent=True,deadline=None)]
    assert evaluate(data,[message()],at('2026-10-07T18:00:00'),profile='general')['tier']=='T1'


def test_due_today_uses_the_deadline_zone_not_the_display_zone():
    from backend.policy import evaluate
    data=assessment([item(deadline={'expression':'Friday at 5pm PDT','message_id':'m1'})])
    messages=[message(body='I will deliver Friday at 5pm PDT.')]
    assert evaluate(data,messages,at('2026-10-09T10:00:00'),timezone='Asia/Kolkata')['tier']=='T3'
    assert evaluate(data,messages,at('2026-10-09T21:30:00'),timezone='Asia/Kolkata')['tier']=='T2'


def test_source_header_zone_anchors_relative_days_and_new_import_updates():
    from backend.gmail import normalize_thread
    from test_gmail import mail
    raw=mail('a','buyer@example.com','I will reply tomorrow.')
    raw['payload']['headers'].append({'name':'Date','value':'Wed, 07 Oct 2026 23:00:00 -0700'})
    normalized=normalize_thread({'id':'t','messages':[raw]},'seller@gmail.com')
    from backend.domain import Message
    m=Message(**normalized['messages'][0])
    assert m.authored_at.utcoffset().total_seconds()==-7*3600
    from backend.dates import resolve_date
    result=resolve_date('tomorrow',m.authored_at,default_timezone='Asia/Kolkata',source_zone=m.authored_at.tzinfo)
    assert result.due_at==at('2026-10-09T05:30:00')


def test_gmail_pages_deduplicates_full_threads_and_keeps_valid_results(monkeypatch):
    from backend.gmail import GmailEmailProvider
    from test_gmail import mail
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/threads'):
            if 'pageToken' not in request.url.params:
                return httpx.Response(200,json={'threads':[{'id':'a'},{'id':'bad'}],'nextPageToken':'next'})
            return httpx.Response(200,json={'threads':[{'id':'a'},{'id':'b'}]})
        tid=request.url.path.split('/')[-1]
        if tid=='bad':return httpx.Response(200,json={'id':'bad','messages':[]})
        return httpx.Response(200,json={'id':tid,'messages':[mail(tid,'buyer@example.com','Please confirm receipt.')]})
    p=GmailEmailProvider(SimpleNamespace(token='test'),'seller@gmail.com','in:inbox',None)
    p.client.close();p.client=httpx.Client(base_url='https://gmail.googleapis.com/gmail/v1/users/me',transport=httpx.MockTransport(handler))
    p.pacer.wait=lambda cost:None
    try:
        rows=p.list_threads()
        assert len(rows)==2 and len(p.errors)==1
        assert len([r for r in calls if r.url.path.endswith('/threads/a')])==1
        assert all(r.url.params.get('format')=='full' for r in calls if not r.url.path.endswith('/threads'))
    finally:p.close()


def test_import_messages_includes_unique_complete_conversations():
    from backend.gmail import GmailEmailProvider
    from test_gmail import mail
    def handler(request):
        if request.url.path.endswith('/messages'):
            return httpx.Response(200,json={'messages':[{'id':'m1','threadId':'t'},{'id':'m2','threadId':'t'}]})
        return httpx.Response(200,json={'id':'t','messages':[mail('a','buyer@example.com','First request.'),mail('b','seller@gmail.com','Answer.', ['SENT'])]})
    p=GmailEmailProvider(SimpleNamespace(token='test'),'seller@gmail.com','in:inbox',2,selection='messages')
    p.client.close();p.client=httpx.Client(base_url='https://gmail.googleapis.com/gmail/v1/users/me',transport=httpx.MockTransport(handler));p.pacer.wait=lambda cost:None
    try:
        rows=p.list_threads();assert len(rows)==1 and len(rows[0]['messages'])==2
    finally:p.close()


def test_gmail_reimport_replaces_the_complete_thread_atomically(tmp_path):
    from backend.store import Store
    from backend.gmail import normalize_thread
    from test_gmail import mail
    s=Store(tmp_path/'attention.sqlite')
    t=normalize_thread({'id':'t','messages':[mail('a','buyer@example.com','Original.')]},'seller@gmail.com')
    s.import_threads([t])
    t=normalize_thread({'id':'t','messages':[mail('a','buyer@example.com','Updated.'),mail('b','seller@gmail.com','Delivered.', ['SENT'])]},'seller@gmail.com')
    s.import_threads([t]);assert len(s.thread(t['id'])['messages'])==2
    assert s.thread(t['id'])['messages'][0]['body']=='Updated.'


def test_fifo_order_is_not_changed_by_progress_updates(tmp_path):
    from backend.jobs import AnalysisJobs
    from test_service import setup,TestAnalyzer
    async def run():
        order=[]
        class Recorder(TestAnalyzer):
            provider='glm'
            async def analyze(self,thread,messages):
                order.append(thread['id']);return await super().analyze(thread,messages)
        s=setup(tmp_path,Recorder());j=AnalysisJobs(s)
        first=j.submit(['northstar'],at('2026-10-09T18:00:00'));second=j.submit(['evergreen'],at('2026-10-09T18:00:00'))
        s.store.save_operation(first['id'],'job',first)
        await j.start()
        try:
            await j.wait(second['id']);assert order==['northstar','evergreen']
        finally:await j.close()
    asyncio.run(run())


def test_glm_single_thread_endpoint_joins_the_same_queue(tmp_path):
    from test_api import client
    c,s=client(tmp_path);s.analyzer.provider='glm'
    with c:
        result=c.post('/api/threads/northstar/analyze',json={'as_of':'2026-10-09T18:00:00+05:30'})
        assert result.status_code==200 and result.json()['status']=='analyzed'
        assert len(s.store.operations('job'))==1


def test_timezone_policy_recompute_reuses_extraction(tmp_path):
    from test_service import setup
    s=setup(tmp_path);clock=at('2026-10-09T18:00:00')
    asyncio.run(s.analyze('northstar',clock))
    for zone in ['Asia/Kolkata','America/New_York','Pacific/Auckland']:
        assert s.view('northstar',clock,timezone=zone)['attention']['timezone']==zone
    assert s.analyzer.calls==1


def test_gmail_default_job_uses_latest_import_scope(tmp_path):
    from test_api import client
    from backend.gmail import normalize_thread
    from test_gmail import mail
    c,s=client(tmp_path)
    t=normalize_thread({'id':'t','messages':[mail('a','buyer@example.com','A task.')]},'seller@gmail.com')
    s.store.import_threads([t])
    s.store.save_operation('import-scope','import',{'status':'completed','thread_ids':[t['id']]})
    with c:
        response=c.post('/api/analysis/jobs',json={'as_of':'2026-10-09T18:00:00+05:30','source':'gmail'})
        assert response.status_code==200
        assert response.json()['thread_ids']==[t['id']]


def test_import_recovery_requires_explicit_retry(tmp_path):
    from backend.gmail import GmailConnection
    from backend.store import Store
    s=Store(tmp_path/'db.sqlite');g=GmailConnection(tmp_path/'gmail')
    s.save_operation('pending','import',{'status':'running','source':'gmail','thread_ids':[]})
    g.recover_imports(s)
    assert s.operations('import')[0]['status']=='interrupted'


def test_gmail_analysis_waits_for_import_completion(tmp_path):
    from test_api import client
    from backend.gmail import normalize_thread
    from test_gmail import mail
    c,s=client(tmp_path)
    t=normalize_thread({'id':'t','messages':[mail('a','buyer@example.com','A task.')]},'seller@gmail.com')
    s.store.import_threads([t])
    with c:
        s.store.save_operation('import-running','import',{'status':'running','thread_ids':[]})
        payload={'as_of':'2026-10-09T18:00:00+05:30','source':'gmail','thread_ids':[t['id']]}
        assert c.post('/api/analysis/jobs',json=payload).status_code==409
        assert c.post('/api/threads/'+t['id']+'/analyze',json=payload).status_code==409
