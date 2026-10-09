import base64
import json
import pytest
from backend.gmail import normalize_thread, GmailConnection, GmailError


def mail(mid, sender, body, labels=None):
    return {'id':mid,'internalDate':'1791266400000','labelIds':labels or [],'payload':{
        'mimeType':'text/plain','headers':[{'name':'From','value':sender},{'name':'Subject','value':'Purchase review'}],
        'body':{'data':base64.urlsafe_b64encode(body.encode()).decode()}}}


def test_gmail_normalizes_identity_mime_attachments_and_timestamps():
    inbound=mail('a','Maya Chen <maya@example.com>','Can you send the DPA?')
    inbound['payload']={'mimeType':'multipart/mixed','headers':inbound['payload']['headers'],'parts':[
        {'mimeType':'text/html','body':{'data':base64.urlsafe_b64encode(b'<p>Can you send the DPA?</p><script>bad()</script>').decode()}},
        {'filename':'questionnaire.pdf','mimeType':'application/pdf','body':{'attachmentId':'secret'}}]}
    outbound=mail('b','Me <seller@gmail.com>','Tomorrow.', ['SENT'])
    thread=normalize_thread({'id':'t1','messages':[outbound,inbound]},'seller@gmail.com')
    assert thread['id'].startswith('gmail-')
    assert thread['contact']=='Maya Chen'
    by_id={m['direction']:m for m in thread['messages']}
    assert by_id['outbound']['body']=='Tomorrow.'
    assert 'Can you send the DPA?' in by_id['inbound']['body'] and 'bad()' not in by_id['inbound']['body']
    assert by_id['inbound']['attachments']==['questionnaire.pdf']
    from datetime import datetime
    assert datetime.fromisoformat(by_id['inbound']['sent_at']).utcoffset().total_seconds()==0
    assert normalize_thread({'id':'t1','messages':[inbound]},'other@gmail.com')['id']!=thread['id']


def test_gmail_rejects_missing_body_data_instead_of_using_snippet():
    broken=mail('a','maya@example.com','unused')
    broken['payload']['body']={'size':500}
    with pytest.raises(GmailError,match='body'): normalize_thread({'id':'t','messages':[broken]},'me@gmail.com')


def test_gmail_preserves_declared_charset_and_prefers_plain_alternative():
    m=mail('a','maya@example.com','ignored')
    m['payload']['headers'].append({'name':'Content-Type','value':'text/plain; charset=iso-8859-1'})
    m['payload']['body']['data']=base64.urlsafe_b64encode('Café pricing approved.'.encode('iso-8859-1')).decode()
    assert normalize_thread({'id':'t','messages':[m]},'me@gmail.com')['messages'][0]['body']=='Café pricing approved.'


def test_gmail_removes_recognized_reply_history_but_keeps_inline_answers():
    from backend.gmail import body_and_attachments
    body='SSO is supported.\nOn Monday, Maya wrote:\n> Please confirm SSO.\nSCIM is also supported.\n> And SCIM?'
    m=mail('a','me@gmail.com',body)
    result=normalize_thread({'id':'t','messages':[m]},'me@gmail.com')['messages'][0]['body']
    assert result=='SSO is supported.\nSCIM is also supported.'
    html='<p>SCIM is supported.</p><div class="gmail_quote"><div>On Monday...</div><blockquote>Old ask<br/>Friday</blockquote></div><p class>Regards.</p>'
    result,_=body_and_attachments({'mimeType':'text/html','body':{'data':base64.urlsafe_b64encode(html.encode()).decode()}})
    assert 'SCIM is supported.' in result and 'Regards.' in result and 'Friday' not in result


def test_gmail_uses_readonly_rest_endpoints_and_bounded_search():
    import httpx
    from types import SimpleNamespace
    from backend.gmail import GmailEmailProvider
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.method=='GET'
        if request.url.path.endswith('/threads'):
            assert request.url.params['q']=='label:autharva-test' and request.url.params['maxResults']=='5'
            return httpx.Response(200,json={'threads':[{'id':'t'}]})
        assert request.url.path=='/gmail/v1/users/me/threads/t' and request.url.params['format']=='full'
        return httpx.Response(200,json={'id':'t','messages':[mail('a','maya@example.com','Please send the DPA.')]})
    provider=GmailEmailProvider(SimpleNamespace(token='test-token'),'me@gmail.com','label:autharva-test',5)
    provider.client.close()
    provider.client=httpx.Client(base_url='https://gmail.googleapis.com/gmail/v1/users/me',transport=httpx.MockTransport(handler))
    try: assert len(provider.list_threads())==1 and len(calls)==2
    finally: provider.close()


def test_gmail_missing_or_invalid_credentials_are_explicit(tmp_path):
    connection=GmailConnection(tmp_path)
    assert connection.status()['credentials_present'] is False
    with pytest.raises(GmailError,match='credentials.json'): connection.connect()
    (tmp_path/'credentials.json').write_text(json.dumps({'web':{'client_secret':'secret'}}))
    with pytest.raises(GmailError,match='Desktop'): connection.connect()


def test_gmail_source_is_separate_and_cannot_be_simulated(tmp_path):
    from test_api import client
    app,service=client(tmp_path)
    t=normalize_thread({'id':'t','messages':[mail('a','maya@example.com','Please send the DPA.')]},'me@gmail.com')
    class Provider:
        def list_threads(self): return [t]
    service.store.seed(Provider())
    assert all(not x['id'].startswith('gmail-') for x in app.get('/api/threads').json()['threads'])
    assert [x['id'] for x in app.get('/api/threads?source=gmail').json()['threads']]==[t['id']]
    assert app.post(f"/api/threads/{t['id']}/messages",json={'direction':'outbound','body':'Pretend','sent_at':'2026-10-09T18:00:00+05:30'}).status_code==409
    assert 'prompt_variant' in service.context(t)


def test_replay_export_excludes_private_gmail(tmp_path):
    from test_service import setup, TestAnalyzer
    from backend.replay import export_replay
    analyzer=TestAnalyzer(); analyzer.provider='ollama'
    service=setup(tmp_path,analyzer)
    class Provider:
        def list_threads(self): return [normalize_thread({'id':'private','messages':[mail('x','maya@example.com','PRIVATE MAIL')]},'me@gmail.com')]
    service.store.seed(Provider())
    from backend.domain import Assessment
    from datetime import datetime,timezone
    private=next(t for t in service.store.threads() if t['id'].startswith('gmail-'))
    _,_,key=service.prepared(private['id'],datetime(2026,10,9,tzinfo=timezone.utc))
    data=Assessment(is_sales_related=False,lifecycle='unknown',buyer_intent='unknown',summary='Test fixture',blockers=[],open_items=[],recommendations=[],ambiguity_notes=[],non_substantive_message_ids=[],proposal_message_id=None,deferral=None)
    service.store.save_snapshot(key,private['id'],'ollama',analyzer.model,data,data.model_dump_json(),datetime.now(timezone.utc).isoformat(),1)
    path=tmp_path/'replay.json'
    assert export_replay(service,path)==0
    assert 'PRIVATE MAIL' not in path.read_text()


def test_disconnect_clears_rejected_private_outputs_only(tmp_path):
    import asyncio
    from backend.store import Store
    from backend.service import AttentionService
    from test_core import at
    class Bad:
        provider='ollama';model='test'
        async def analyze(self,*args):
            error=ValueError('Invalid output')
            error.raw_output='Private mail quotation'
            raise error
    store=Store(tmp_path/'attention.sqlite');store.seed()
    private=normalize_thread({'id':'t','messages':[mail('a','buyer@example.com','Send the contract please.')]},'seller@gmail.com')
    class Imported:
        def list_threads(self):return [private]
    store.seed(Imported());service=AttentionService(store,Bad());clock=at('2026-10-09T18:00:00')
    asyncio.run(service.analyze(private['id'],clock));asyncio.run(service.analyze('northstar',clock))
    private_files=[p for p in (tmp_path/'rejected').rglob('*.json') if 'Private mail' in p.read_text()]
    assert len(private_files)==2
    _,_,demo_key=service.prepared('northstar',clock)
    connection=GmailConnection(tmp_path/'gmail');connection.disconnect(store)
    assert len(list((tmp_path/'rejected').rglob('*.json')))==1
    assert (tmp_path/'rejected'/f'{demo_key}.json').exists()


def test_disconnect_clears_owned_review_files_and_preserves_unrelated_files(tmp_path):
    from backend.store import Store
    directory=tmp_path/'gmail';review=directory/'review-2026-10-07';review.mkdir(parents=True)
    (review/'.autharva-mail-review').write_text('owned')
    (review/'before-fixes.sqlite').write_text('private mail backup')
    (review/'review-before-rerun.json').write_text('private review')
    (review/'notes.txt').write_text('user-owned notes')
    unrelated=directory/'review-unrelated';unrelated.mkdir();(unrelated/'before-fixes.sqlite').write_text('user file')
    GmailConnection(directory).disconnect(Store(tmp_path/'db.sqlite'))
    assert not (review/'before-fixes.sqlite').exists()
    assert not (review/'review-before-rerun.json').exists()
    assert (review/'notes.txt').exists() and (unrelated/'before-fixes.sqlite').exists()


def test_wrapped_reply_headers_strip_history_and_preserve_new_and_inline_answers():
    body=('SCIM provisioning is included.\n\n'
          'On Wed, Oct 7 at 6:59 PM Seller <seller@example.com>\n'
          'wrote:\n\n> I am still checking provisioning.\n'
          '> On Tuesday, Buyer wrote:\n>> Please answer urgently.\n'
          'Deactivation is included too.\n')
    result=normalize_thread({'id':'t','messages':[mail('a','me@gmail.com',body)]},'me@gmail.com')['messages'][0]['body']
    assert result=='SCIM provisioning is included.\n\nDeactivation is included too.'


def test_wrapped_text_without_a_quoted_reply_block_is_preserved():
    body='Notes: On our roadmap we\nwrote:\nSCIM first, then SSO.\n> is a comparison operator.'
    result=normalize_thread({'id':'t','messages':[mail('a','me@gmail.com',body)]},'me@gmail.com')['messages'][0]['body']
    assert result==body


def test_gmail_labels_survive_import_and_use_only_visible_messages(tmp_path):
    from backend.service import AttentionService
    from backend.store import Store
    from test_service import TestAnalyzer
    from datetime import datetime, timezone
    a=mail('a','buyer@example.com','Please send the notes.', ['INBOX','CATEGORY_SOCIAL','UNREAD'])
    b=mail('b','me@gmail.com','Here are the notes.', ['SENT','CATEGORY_PROMOTIONS'])
    b['internalDate']=str(int(a['internalDate'])+3600000)
    row=normalize_thread({'id':'labels','messages':[a,b]},'me@gmail.com')
    assert row['messages'][0]['gmail_label_ids']==a['labelIds']
    store=Store(tmp_path/'labels.sqlite');store.import_threads([row])
    service=AttentionService(store,TestAnalyzer())
    early=datetime.fromtimestamp(int(a['internalDate'])/1000,timezone.utc)
    view=service.view(row['id'],early)
    assert set(view['gmail_label_ids'])==set(a['labelIds'])
    assert view['gmail_labels_complete'] is True
    assert view['messages'][0]['gmail_label_ids']==a['labelIds']
    late=service.view(row['id'],datetime.fromtimestamp(int(b['internalDate'])/1000,timezone.utc))
    assert 'CATEGORY_PROMOTIONS' in late['gmail_label_ids'] and 'CATEGORY_SOCIAL' in late['gmail_label_ids']
    old={**row,'messages':[{k:v for k,v in m.items() if k!='gmail_label_ids'} for m in row['messages']]}
    store.import_threads([old])
    assert service.view(row['id'],early)['gmail_labels_complete'] is False


def test_gmail_relabel_does_not_change_model_input_or_cache_key():
    from backend.domain import Message,content_hash
    from backend.providers import model_input
    base=normalize_thread({'id':'labels','messages':[mail('a','buyer@example.com','Please send the notes.',['INBOX'])]},'me@gmail.com')
    before=[Message(**m) for m in base['messages']]
    after=[Message(**{**base['messages'][0],'gmail_label_ids':['SPAM','CATEGORY_PROMOTIONS']})]
    assert model_input(base,before)==model_input(base,after)
    assert content_hash(before,'test','test',{})==content_hash(after,'test','test',{})
    assert 'gmail_label_ids' not in model_input(base,after)


@pytest.mark.parametrize('selection',['threads','messages'])
@pytest.mark.parametrize('include',[False,True])
def test_gmail_spam_trash_inclusion_is_explicit(selection,include):
    import httpx
    from types import SimpleNamespace
    from backend.gmail import GmailEmailProvider
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={selection:[]})
    provider=GmailEmailProvider(SimpleNamespace(token='test'),'me@gmail.com','in:spam',5,selection=selection,include_spam_trash=include)
    provider.client.close()
    provider.client=httpx.Client(base_url='https://gmail.googleapis.com/gmail/v1/users/me',transport=httpx.MockTransport(handler))
    try:
        assert provider.list_threads()==[]
        assert seen[0].url.params['includeSpamTrash']==str(include).lower()
    finally:provider.close()
