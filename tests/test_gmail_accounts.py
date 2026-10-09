import json
import pytest
from google.oauth2.credentials import Credentials
from backend.gmail import GmailConnection, GmailError, SCOPES, account_prefix
from backend.store import Store


def credentials(token):
    return Credentials(token=token,refresh_token='test-refresh',client_id='test-client',
        client_secret='test-secret',token_uri='https://oauth2.googleapis.com/token',scopes=SCOPES)


def test_adding_an_account_preserves_the_existing_connection_and_switches_locally(tmp_path):
    connection=GmailConnection(tmp_path/'gmail')
    connection._save(credentials('first'),'first@example.com')
    connection._save(credentials('second'),'second@example.com')
    status=connection.status()
    assert {a['email'] for a in status['accounts']}=={'first@example.com','second@example.com'}
    first=next(a for a in status['accounts'] if a['email']=='first@example.com')
    result=connection.select_account(first['id'])
    assert result['account']=='first@example.com' and result['connected']
    assert connection._load_credentials().token=='first'
    assert json.loads((connection.directory/'profile.json').read_text())['email']=='first@example.com'


def test_legacy_current_token_is_retained_when_a_new_account_is_added(tmp_path):
    directory=tmp_path/'gmail';directory.mkdir()
    (directory/'token.json').write_text(credentials('legacy').to_json())
    (directory/'profile.json').write_text(json.dumps({'email':'old@example.com'}))
    connection=GmailConnection(directory)
    connection._save(credentials('new'),'new@example.com')
    assert {a['email'] for a in connection.status()['accounts']}=={'old@example.com','new@example.com'}
    connection.select_account(account_prefix('old@example.com').removesuffix('-'))
    assert connection._load_credentials().token=='legacy'


def test_unknown_account_and_busy_switch_preserve_current_credentials(tmp_path):
    connection=GmailConnection(tmp_path/'gmail');connection._save(credentials('current'),'me@example.com')
    with pytest.raises(GmailError):connection.select_account('../../outside')
    assert connection._load_credentials().token=='current'
    connection.guard.acquire()
    try:
        with pytest.raises(GmailError,match='progress'):connection.select_account(account_prefix('me@example.com').removesuffix('-'))
    finally:connection.guard.release()


def test_account_import_history_is_isolated_including_legacy_batches(tmp_path):
    store=Store(tmp_path/'store.sqlite')
    connection=GmailConnection(tmp_path/'gmail')
    connection._save(credentials('a'),'a@example.com')
    first=store.save_operation('a-batch','import',{'status':'completed','source':'gmail',
        'thread_ids':[account_prefix('a@example.com')+'t']})
    store.save_operation('b-batch','import',{'status':'completed','source':'gmail','account':'b@example.com',
        'thread_ids':[account_prefix('b@example.com')+'t']})
    assert connection.status(store)['last_import']['id']==first['id']
    assert [b['id'] for b in connection.account_imports(store)]==['a-batch']


def test_disconnect_clears_all_saved_tokens_without_removing_other_files(tmp_path):
    store=Store(tmp_path/'store.sqlite')
    connection=GmailConnection(tmp_path/'gmail')
    connection._save(credentials('a'),'a@example.com');connection._save(credentials('b'),'b@example.com')
    notes=connection.directory/'accounts'/'notes.txt';notes.write_text('user notes')
    status=connection.disconnect(store)
    assert not status['connected'] and status['accounts']==[]
    assert not list((connection.directory/'accounts').rglob('token.json'))
    assert notes.read_text()=='user notes'


def test_account_selector_api_scopes_inbox_and_retains_other_mailboxes(tmp_path):
    from test_api import client
    from test_gmail import mail
    from backend.gmail import normalize_thread
    from test_core import at
    app,service=client(tmp_path)
    connection=app.app.state.gmail
    first=normalize_thread({'id':'same-id','messages':[mail('m','buyer@example.com','First mailbox ask.')]},'first@example.com')
    second=normalize_thread({'id':'same-id','messages':[mail('m','buyer@example.com','Second mailbox ask.')]},'second@example.com')
    service.store.import_threads([first,second])
    for email,row in [('first@example.com',first),('second@example.com',second)]:
        connection._save(credentials(email),email)
        service.store.save_operation(email,'import',{'source':'gmail','status':'completed','account':email,'thread_ids':[row['id']]})
    url='/api/threads?source=gmail&as_of=2026-10-09T18:00:00%2B05:30'
    assert [r['id'] for r in app.get(url).json()['threads']]==[second['id']]
    reply=app.post('/api/gmail/account',json={'account_id':account_prefix('first@example.com').removesuffix('-')})
    assert reply.status_code==200 and reply.json()['account']=='first@example.com'
    assert 'test-refresh' not in reply.text and 'test-secret' not in reply.text
    assert [r['id'] for r in app.get(url).json()['threads']]==[first['id']]
    assert service.store.thread(second['id'])['messages']
    app.app.state.jobs.submit([first['id']],at('2026-10-09T18:00:00'))
    blocked=app.post('/api/gmail/account',json={'account_id':account_prefix('second@example.com').removesuffix('-')})
    assert blocked.status_code==409 and connection.current_account()=='first@example.com'
