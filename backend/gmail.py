"""Read-only Gmail ingestion. OAuth secrets and imported messages remain local."""
import base64
import hashlib
import json
import re
import threading
import time
import random
from uuid import uuid4
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from email.message import Message as MIMEHeader
from html.parser import HTMLParser
from pathlib import Path
import httpx
from .domain import Message

SCOPES=['https://www.googleapis.com/auth/gmail.readonly']
API='https://gmail.googleapis.com/gmail/v1/users/me'


class GmailError(ValueError): pass


def account_prefix(email):
    return 'gmail-'+hashlib.sha256(email.lower().encode()).hexdigest()[:12]+'-'


class PlainHTML(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.text=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        void=tag in ['br','hr','img','input','meta','link','wbr','source','area','base','embed','param','track','col']
        classes=(dict(attrs).get('class') or '').split()
        if self.hidden:
            if not void: self.hidden+=1
        elif tag in ['script','style'] or 'gmail_quote' in classes or 'gmail_quote_container' in classes: self.hidden=1
        elif tag in ['p','br','div','li'] and not self.hidden: self.text.append('\n')
    def handle_endtag(self,tag):
        if self.hidden: self.hidden=max(0,self.hidden-1)
        elif tag in ['p','div','li'] and not self.hidden: self.text.append('\n')
    def handle_data(self,data):
        if not self.hidden: self.text.append(data)
    def handle_startendtag(self,tag,attrs):
        if self.hidden: return
        self.handle_starttag(tag,attrs)
        if tag not in ['br','hr','img','input','meta','link','wbr','source','area','base','embed','param','track','col']:
            self.handle_endtag(tag)


def strip_plain_reply_history(text):
    """Recognize short wrapped English reply headers; retain unquoted inline answers."""
    lines=text.splitlines();kept=[];quoting=False;index=0
    while index<len(lines):
        line=lines[index];header_end=None
        if re.match(r'^\s*On\s+',line,re.I):
            for end in range(index,min(index+4,len(lines))):
                header=' '.join(part.strip() for part in lines[index:end+1])
                if re.match(r'^On .+\bwrote:\s*$',header,re.I):
                    following=end+1
                    while following<len(lines) and not lines[following].strip():following+=1
                    if following<len(lines) and lines[following].lstrip().startswith('>'):header_end=following
                    break
        if header_end is not None:
            quoting=True;index=header_end;continue
        if not (quoting and line.lstrip().startswith('>')):kept.append(line)
        index+=1
    return '\n'.join(kept).strip()


def body_and_attachments(payload):
    plain=[]; html=[]; attachments=[]
    def visit(part):
        name=part.get('filename','')
        if name: attachments.append(name)
        mime=part.get('mimeType','')
        if not name and mime in ['text/plain','text/html']:
            data=part.get('body',{}).get('data')
            if data:
                content_type=next((h['value'] for h in part.get('headers',[]) if h['name'].lower()=='content-type'),mime)
                header=MIMEHeader(); header['content-type']=content_type
                try: decoded=base64.urlsafe_b64decode(data+'='*(-len(data)%4)).decode(header.get_content_charset() or 'utf-8')
                except (ValueError,TypeError,LookupError): raise GmailError('Gmail returned an invalid message body or unsupported charset.')
                (plain if mime=='text/plain' else html).append(decoded)
            elif part.get('body',{}).get('size',0)>0:
                raise GmailError('Gmail message body was not returned in full. Nothing was imported.')
        for child in part.get('parts',[]): visit(child)
    visit(payload)
    if plain:
        body=strip_plain_reply_history('\n'.join(plain))
    else:
        parser=PlainHTML(); parser.feed('\n'.join(html)); body=''.join(parser.text)
    body=body.strip()
    if not body: body='[No text body; attachment metadata only.]' if attachments else '[Empty message body.]'
    if len(body)>20000: raise GmailError('A Gmail message exceeds the 20,000-character demo limit. Choose a smaller test thread.')
    return body,list(dict.fromkeys(attachments))


def normalize_thread(raw,own_email):
    if not raw.get('messages'): raise GmailError('Gmail returned a thread with no messages.')
    prefix=account_prefix(own_email); tid=prefix+raw['id']; messages=[]; contact=None; domain=None; subject='(No subject)'
    for index,m in enumerate(raw['messages']):
        payload=m.get('payload',{})
        headers={h['name'].lower():h['value'] for h in payload.get('headers',[])}
        name,email=parseaddr(headers.get('from',''))
        if not email: raise GmailError('A Gmail message has no usable sender address.')
        outbound=email.lower()==own_email.lower() or 'SENT' in m.get('labelIds',[])
        direction='outbound' if outbound else 'inbound'
        if not outbound and contact is None: contact=name or email; domain=email.split('@')[-1]
        if index==0: subject=headers.get('subject','(No subject)')
        body,attachments=body_and_attachments(payload)
        try: sent_at=datetime.fromtimestamp(int(m['internalDate'])/1000,timezone.utc)
        except (KeyError,ValueError,OverflowError,OSError): raise GmailError('Gmail returned an invalid message timestamp.')
        authored_at=None
        try:
            authored_at=parsedate_to_datetime(headers.get('date',''))
            if authored_at.tzinfo is None:authored_at=None
        except (ValueError,TypeError,IndexError,OverflowError):pass
        message=Message(id=prefix+m['id'],sender=name or email,direction=direction,body=body,
                        sent_at=sent_at,authored_at=authored_at,attachments=attachments,gmail_label_ids=m.get('labelIds',[]))
        messages.append({**message.model_dump(mode='json'),'gmail_label_ids':message.gmail_label_ids})
    contact=contact or own_email
    company=domain if domain and domain not in ['gmail.com','googlemail.com','outlook.com','yahoo.com'] else contact
    return {'id':tid,'company':company,'subject':subject,'contact':contact,'deal_value':None,
            'messages':sorted(messages,key=lambda m:(m['sent_at'],m['id']))}


class QuotaPacer:
    """80 units/s = 4,800/min, below the published new-project 6,000/min default."""
    def __init__(self):self.next_allowed=0
    def wait(self,cost):
        now=time.monotonic()
        if self.next_allowed>now:time.sleep(self.next_allowed-now)
        self.next_allowed=max(self.next_allowed,now)+cost/80


class GmailEmailProvider:
    """Paginated, read-only imports with explicit selection, pacing, and partial errors."""
    def __init__(self,credentials,account,query,limit,selection='threads',progress=None,include_spam_trash=False):
        self.account=account; self.query=query; self.limit=limit
        self.include_spam_trash=include_spam_trash
        self.selection=selection;self.progress=progress or (lambda value:None)
        self.history_ids={};self.pacer=QuotaPacer();self.errors=[];self.estimated_total=None;self.has_more=False;self.quota_units=0
        self.client=httpx.Client(base_url=API,headers={'Authorization':'Bearer '+credentials.token},timeout=30)
    def close(self): self.client.close()
    def request(self,path,params):
        cost=40 if path.startswith('/threads/') else 10 if path=='/threads' else 5
        for attempt in range(4):
            self.pacer.wait(cost);self.quota_units+=cost
            try:response=self.client.get(path,params=params)
            except httpx.HTTPError:
                if attempt==3:raise
                time.sleep(2**attempt+random.random());continue
            try:reasons={e.get('reason') for e in response.json().get('error',{}).get('errors',[])}
            except (ValueError,AttributeError,TypeError):reasons=set()
            transient=response.status_code in [429,500,502,503,504] or (response.status_code==403 and bool(reasons&{'rateLimitExceeded','userRateLimitExceeded'}))
            if transient and attempt<3:
                try:delay=float(response.headers.get('Retry-After',''))
                except ValueError:delay=2**attempt+random.random()
                time.sleep(min(max(delay,0),30));continue
            response.raise_for_status();return response.json()
    def get_thread(self,thread_id):
        raw=self.request('/threads/'+thread_id,{'format':'full'})
        if raw.get('historyId'):self.history_ids[account_prefix(self.account)+thread_id]=str(raw['historyId'])
        return normalize_thread(raw,self.account)
    def list_threads(self):
        maximum=self.limit if self.limit is not None else 5000
        endpoint='/messages' if self.selection=='messages' else '/threads'
        key='messages' if self.selection=='messages' else 'threads'
        selected=[];seen=set();tokens=set();token=None
        while len(selected)<maximum:
            params={'q':self.query,'maxResults':min(500,maximum-len(selected)),'includeSpamTrash':str(self.include_spam_trash).lower()}
            if token:params['pageToken']=token
            page=self.request(endpoint,params)
            if self.estimated_total is None:self.estimated_total=page.get('resultSizeEstimate')
            for entry in page.get(key,[]):
                if entry['id'] in seen:continue
                seen.add(entry['id']);selected.append(entry.get('threadId',entry['id']))
                if len(selected)==maximum:break
            token=page.get('nextPageToken');self.has_more=bool(token)
            self.progress({'phase':'listing','selected':len(selected),'estimated_total':self.estimated_total,'quota_units':self.quota_units})
            if not token:break
            if token in tokens:raise GmailError('Gmail returned a repeated page token. Narrow the search and retry.')
            tokens.add(token)
        ids=list(dict.fromkeys(selected));rows=[]
        for index,tid in enumerate(ids):
            try:rows.append(self.get_thread(tid))
            except httpx.HTTPStatusError as error:
                if error.response.status_code in [401,403]:raise
                self.errors.append({'thread_id':account_prefix(self.account)+tid,'error':f'Gmail returned HTTP {error.response.status_code} for this thread.'})
            except (GmailError,httpx.HTTPError) as error:
                self.errors.append({'thread_id':account_prefix(self.account)+tid,'error':str(error) if isinstance(error,GmailError) else 'Gmail connection failed for this thread.'})
            self.progress({'phase':'fetching','fetched':index+1,'total_threads':len(ids),'skipped':len(self.errors),'quota_units':self.quota_units})
        return rows


class GmailConnection:
    def __init__(self,directory):
        self.directory=Path(directory); self.guard=threading.Lock(); self.connecting=False;self.pacer=QuotaPacer()
    def recover_imports(self,store):
        for item in store.operations('import'):
            if item['status']=='running':
                item.update(status='interrupted',error='Import stopped before it completed. Choose the scope again and explicitly retry.')
                store.save_operation(item['id'],'import',item)
    def current_account(self):
        try:
            email=json.loads((self.directory/'profile.json').read_text(encoding='utf-8'))['email']
            return email if isinstance(email,str) else None
        except (OSError,ValueError,KeyError):return None
    def saved_accounts(self):
        current=self.current_account();saved={}
        folder=self.directory/'accounts'
        if folder.is_dir():
            for path in folder.iterdir():
                if path.is_symlink() or not path.is_dir() or not (path/'token.json').is_file():continue
                try:email=json.loads((path/'profile.json').read_text(encoding='utf-8'))['email']
                except (OSError,ValueError,KeyError):continue
                if not isinstance(email,str) or path.name!=account_prefix(email).removesuffix('-'):continue
                saved[path.name]={'id':path.name,'email':email,'active':bool(current and email.lower()==current.lower())}
        if current and (self.directory/'token.json').exists():
            aid=account_prefix(current).removesuffix('-');saved[aid]={'id':aid,'email':current,'active':True}
        return sorted(saved.values(),key=lambda a:a['email'].lower())
    def account_imports(self,store):
        imports=store.operations('import');email=self.current_account()
        if not email:return imports
        prefix=account_prefix(email)
        return [batch for batch in imports if (batch.get('account') or '').lower()==email.lower() or
            (not batch.get('account') and batch.get('thread_ids') and all(t.startswith(prefix) for t in batch['thread_ids']))]
    def _remember_current(self):
        email=self.current_account();token=self.directory/'token.json'
        if not email or not token.is_file():return
        folder=self.directory/'accounts'/account_prefix(email).removesuffix('-')
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'token.json').write_text(token.read_text(encoding='utf-8'),encoding='utf-8')
        (folder/'profile.json').write_text(json.dumps({'email':email}),encoding='utf-8')
    def select_account(self,account_id):
        if not self.guard.acquire(blocking=False):raise GmailError('A Gmail connection or import is already in progress.')
        try:
            saved=next((a for a in self.saved_accounts() if a['id']==account_id),None)
            if not saved:raise GmailError('Unknown saved Gmail account. Connect it through Google first.')
            self._remember_current()
            folder=self.directory/'accounts'/saved['id']
            from google.oauth2.credentials import Credentials
            try:credentials=Credentials.from_authorized_user_file(str(folder/'token.json'))
            except (OSError,ValueError,KeyError):raise GmailError('Saved authorization is invalid. Reconnect this account.') from None
            if not credentials.has_scopes(SCOPES) or not (credentials.valid or credentials.refresh_token):
                raise GmailError('Saved authorization has expired. Reconnect this account.')
            self._save(credentials,saved['email']);return self.status()
        finally:self.guard.release()
    def status(self,store=None):
        connected=False; account=None; error=None
        try:
            credentials=self._load_credentials()
            connected=bool(credentials and (credentials.valid or credentials.refresh_token) and credentials.has_scopes(SCOPES))
            if (self.directory/'profile.json').exists(): account=json.loads((self.directory/'profile.json').read_text())['email']
        except (GmailError,KeyError,ValueError): error='Stored Gmail credentials are invalid. Reconnect your account.'
        imports=self.account_imports(store) if store else []
        latest=imports[-1] if imports else None
        return {'connected':connected,'connecting':self.connecting,'credentials_present':(self.directory/'credentials.json').is_file(),
                'account':account,'accounts':self.saved_accounts(),'error':error,'scope':'gmail.readonly','last_import':latest,
                'importing':bool(latest and latest['status']=='running')}
    def _load_credentials(self):
        path=self.directory/'token.json'
        if not path.exists(): return None
        from google.oauth2.credentials import Credentials
        try: return Credentials.from_authorized_user_file(str(path))
        except (ValueError,KeyError): raise GmailError('Stored Gmail credentials are invalid.')
    def _save(self,credentials,email):
        self.directory.mkdir(parents=True,exist_ok=True)
        self._remember_current()
        (self.directory/'token.json').write_text(credentials.to_json(),encoding='utf-8')
        (self.directory/'profile.json').write_text(json.dumps({'email':email}),encoding='utf-8')
        self._remember_current()
    def _account(self,credentials):
        with httpx.Client(timeout=30) as client:
            response=client.get(API+'/profile',headers={'Authorization':'Bearer '+credentials.token}); response.raise_for_status()
            return response.json()['emailAddress']
    def connect(self):
        path=self.directory/'credentials.json'
        if not path.is_file(): raise GmailError('Save a Desktop OAuth client JSON as runtime/gmail/credentials.json first. See the Gmail setup guide.')
        try:
            if 'installed' not in json.loads(path.read_text(encoding='utf-8')): raise GmailError('Use a Desktop OAuth client JSON, not a Web client.')
        except (json.JSONDecodeError,UnicodeError): raise GmailError('The OAuth credentials.json is not valid JSON.')
        if not self.guard.acquire(blocking=False): raise GmailError('A Gmail connection or import is already in progress.')
        self.connecting=True
        try:
            try: from google_auth_oauthlib.flow import InstalledAppFlow
            except ImportError: raise GmailError('Install updated requirements.txt to enable Gmail OAuth.')
            flow=InstalledAppFlow.from_client_secrets_file(str(path),SCOPES)
            credentials=flow.run_local_server(host='127.0.0.1',port=8765,open_browser=True,timeout_seconds=180,
                authorization_prompt_message='',success_message='Gmail connected. You can close this tab and return to Autharva.',
                access_type='offline',prompt='consent select_account')
            email=self._account(credentials); self._save(credentials,email)
            return {**self.status(),'connecting':False}
        except GmailError: raise
        except Exception: raise GmailError('Gmail authorization failed or timed out. Check the Desktop OAuth client, test-user setting, and port 8765, then reconnect.') from None
        finally: self.connecting=False; self.guard.release()
    def import_threads(self,store,query,limit,selection='threads',include_spam_trash=False):
        if not self.guard.acquire(blocking=False): raise GmailError('A Gmail connection or import is already in progress.')
        provider=None
        operation_id=uuid4().hex
        state={'source':'gmail','status':'running','phase':'starting','account':self.current_account(),'query':query,'limit':limit,'selection':selection,
               'fetched':0,'imported':0,'skipped':0,'thread_ids':[],'errors':[],'include_spam_trash':include_spam_trash}
        store.save_operation(operation_id,'import',state)
        def progress(value):
            state.update(value);store.save_operation(operation_id,'import',state)
        try:
            credentials=self._load_credentials()
            if not credentials or not credentials.has_scopes(SCOPES): raise GmailError('Connect Gmail before importing threads.')
            if not credentials.valid:
                from google.auth.transport.requests import Request
                credentials.refresh(Request())
            email=self._account(credentials); self._save(credentials,email)
            state['account']=email;store.save_operation(operation_id,'import',state)
            provider=GmailEmailProvider(credentials,email,query,limit,selection,progress,include_spam_trash=include_spam_trash)
            provider.pacer=self.pacer
            rows=provider.list_threads()
            store.import_threads(rows)
            state.update(status='partial' if provider.errors else 'completed',phase='done',imported=len(rows),
                         thread_ids=[t['id'] for t in rows],history_ids=provider.history_ids,errors=provider.errors,skipped=len(provider.errors),
                         quota_units=provider.quota_units+1,has_more=provider.has_more,capped=limit is None and provider.has_more)
            result=store.save_operation(operation_id,'import',state)
            return {**result,'account':email}
        except Exception as error:
            detail=str(error) if isinstance(error,GmailError) else 'Gmail import failed. Check API access, authorization, and connectivity. No batch was imported.'
            state.update(status='error',error=detail);store.save_operation(operation_id,'import',state)
            raise GmailError(detail) from None
        finally:
            if provider: provider.close()
            self.guard.release()
    def sync_threads(self,store):
        batches=[b for b in self.account_imports(store) if b['status'] in ['completed','partial']]
        if not batches or not batches[-1]['thread_ids']:raise GmailError('Import a Gmail batch before syncing.')
        batch=batches[-1]
        if not self.guard.acquire(blocking=False):raise GmailError('A Gmail operation is already in progress.')
        oid=uuid4().hex;provider=None
        state={**batch,'source':'gmail','mode':'sync','status':'running','phase':'syncing','fetched':0,'imported':0,'unchanged':0,'skipped':0,'errors':[]}
        state.pop('id',None);state.pop('updated_at',None)
        state.pop('error',None)
        state['history_ids']=dict(batch.get('history_ids') or {})
        store.save_operation(oid,'import',state)
        try:
            credentials=self._load_credentials()
            if not credentials or not credentials.has_scopes(SCOPES):raise GmailError('Connect Gmail before syncing.')
            if not credentials.valid:
                from google.auth.transport.requests import Request
                credentials.refresh(Request())
            email=self._account(credentials);prefix=account_prefix(email)
            if any(not tid.startswith(prefix) for tid in batch['thread_ids']):raise GmailError('The imported batch belongs to another Gmail account. Import a new batch.')
            self._save(credentials,email)
            provider=GmailEmailProvider(credentials,email,batch.get('query',''),len(batch['thread_ids']))
            provider.pacer=self.pacer
            for tid in batch['thread_ids']:
                try:
                    store.thread(tid)
                    rawid=tid[len(prefix):]
                    metadata=provider.request('/threads/'+rawid,{'format':'metadata','fields':'id,historyId'})
                    history=str(metadata['historyId']) if metadata.get('historyId') else None
                    known=state['history_ids'].get(tid)
                    if known and history and known==history:
                        state['unchanged']+=1
                    else:
                        row=provider.get_thread(rawid);store.import_threads([row]);state['imported']+=1
                        if provider.history_ids.get(tid):state['history_ids'][tid]=provider.history_ids[tid]
                        else:state['history_ids'].pop(tid,None)
                except httpx.HTTPStatusError as error:
                    if error.response.status_code in [401,403]:raise
                    state['errors'].append({'thread_id':tid,'error':f'Gmail returned HTTP {error.response.status_code}; previous local messages retained.'})
                except (GmailError,httpx.HTTPError,KeyError,ValueError):
                    state['errors'].append({'thread_id':tid,'error':'Could not refresh this conversation; previous local messages retained.'})
                state.update(fetched=state['fetched']+1,skipped=len(state['errors']),quota_units=provider.quota_units+1)
                store.save_operation(oid,'import',state)
            state.update(status='partial' if state['errors'] else 'completed',phase='done')
            return store.save_operation(oid,'import',state)
        except Exception as error:
            detail=str(error) if isinstance(error,GmailError) else 'Gmail sync failed. Previously stored conversations remain available; retry explicitly.'
            state.update(status='error',error=detail);store.save_operation(oid,'import',state)
            raise GmailError(detail) from None
        finally:
            if provider:provider.close()
            self.guard.release()

    def disconnect(self,store):
        if not self.guard.acquire(blocking=False): raise GmailError('Wait for the current Gmail operation to finish.')
        try:
            # Capture ownership before deleting the rows; only hash-named local
            # rejection artifacts are eligible. Also clean the new private namespace.
            with store.connection() as db:
                keys={r[0] for r in db.execute("SELECT cache_key FROM analysis_operations WHERE json_extract(state_json,'$.thread_id') LIKE 'gmail-%' UNION SELECT cache_key FROM analysis_snapshots WHERE thread_id LIKE 'gmail-%'") if r[0]}
            rejected=store.path.parent/'rejected'
            private=rejected/'gmail'
            files=[rejected/f'{key}.json' for key in keys if re.fullmatch(r'[0-9a-f]{64}',key)]
            if private.exists():files.extend(p for p in private.glob('*.json') if re.fullmatch(r'[0-9a-f]{64}\.json',p.name))
            for path in files:path.unlink(missing_ok=True)
            with store.connection() as db:
                for table in ['analysis_snapshots','messages','threads']:
                    key='id' if table=='threads' else 'thread_id'
                    db.execute(f"DELETE FROM {table} WHERE {key} LIKE 'gmail-%'")
            with store.connection() as db:
                db.execute("DELETE FROM analysis_operations WHERE json_extract(state_json,'$.source')='gmail' OR json_extract(state_json,'$.thread_id') LIKE 'gmail-%' OR EXISTS (SELECT 1 FROM json_each(state_json,'$.thread_ids') WHERE value LIKE 'gmail-%')")
            # Clear only this app's marked review artifacts, with resolved-path checks.
            review_files=['before-fixes.sqlite','before-fixes.sqlite-wal','before-fixes.sqlite-shm',
                          'review-before-rerun.json','rerun-job.json','full-batch-rerun-job.json',
                          'results-first-rerun.json','results-after-fixes.json']
            for review in self.directory.glob('review-*'):
                marker=review/'.autharva-mail-review'
                if review.is_symlink() or review.resolve().parent!=self.directory.resolve() or not marker.is_file():continue
                for name in review_files:
                    path=review/name
                    if path.is_file() and path.resolve().parent==review.resolve():path.unlink()
                marker.unlink()
                try:review.rmdir()
                except OSError:pass  # Retain unrelated user files.
            for name in ['token.json','profile.json']:
                (self.directory/name).unlink(missing_ok=True)
            accounts=self.directory/'accounts'
            if accounts.is_dir():
                for folder in accounts.iterdir():
                    if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent!=accounts.resolve() or not re.fullmatch(r'gmail-[0-9a-f]{12}',folder.name):continue
                    for name in ['token.json','profile.json']:
                        path=folder/name
                        if path.is_file() and path.resolve().parent==folder.resolve():path.unlink()
                    try:folder.rmdir()
                    except OSError:pass
            return self.status()
        finally: self.guard.release()
