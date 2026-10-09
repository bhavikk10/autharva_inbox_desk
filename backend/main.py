import asyncio
import json
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from .jobs import AnalysisJobs
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, AwareDatetime, Field
from typing import Literal
from .providers import Settings, make_analyzer, OllamaAnalyzer, ROOT
from dataclasses import replace
from .store import Store
from .service import AttentionService
from .fixtures import DEFAULT_AS_OF, PRESETS
from .gmail import GmailConnection, GmailError
from .timezones import validate_timezone


class AnalyzeRequest(BaseModel):
    as_of: AwareDatetime
    thread_ids: list[str] | None = Field(default=None,min_length=1,max_length=5000)
    force: bool = False
    replay: bool = False
    source: Literal["demo","long","gmail"] | None = None
    timezone: str | None = None


class MessageRequest(BaseModel):
    direction: Literal['inbound','outbound']
    body: str = Field(min_length=1,max_length=10000)
    sent_at: AwareDatetime
    attachments: list[str] = Field(default_factory=list)


class GmailImportRequest(BaseModel):
    query: str = Field(default='label:autharva-test',min_length=1,max_length=500)
    limit: int | None = Field(default=20,ge=1,le=500)
    selection: Literal['threads','messages'] = 'threads'
    include_spam_trash: bool = False
    keep_demos: bool = True


def create_app(service=None,settings=None):
    settings=settings or Settings.from_env()
    if service is None:
        store=Store(ROOT/'runtime'/'attention.sqlite'); store.seed()
        from .replay import import_replay
        for path in (ROOT/'reports').glob('replay-*.json'):
            try: import_replay(store,path)
            except (ValueError,KeyError): logging.getLogger(__name__).warning('Rejected incompatible replay bundle: %s',path.name)
        fallback=OllamaAnalyzer(replace(settings,timeout=settings.fallback_timeout)) if settings.fallback_provider=='ollama' and settings.provider!='ollama' else None
        service=AttentionService(store,make_analyzer(settings),fallback_analyzer=fallback,primary_budget_seconds=settings.primary_analysis_budget)
    from .drafts import DraftWriter
    service.draft_writer=DraftWriter(settings)
    jobs=AnalysisJobs(service)
    @asynccontextmanager
    async def lifespan(app):
        await jobs.start()
        gmail.recover_imports(service.store)
        try: yield
        finally: await jobs.close()
    app=FastAPI(title='Inbox Desk',version='1.1.0',lifespan=lifespan)
    app.state.jobs=jobs
    app.state.service=service
    gmail=GmailConnection(service.store.path.parent/'gmail')
    app.state.gmail=gmail
    app.state.gmail_reserved=False
    @asynccontextmanager
    async def gmail_change():
        if app.state.gmail_reserved or any(j['status'] in ['queued','running'] and any(t.startswith('gmail-') for t in j['thread_ids']) for j in jobs.active()):
            raise HTTPException(409,'Wait for Gmail operations, analysis and drafts to finish before updating local mail.')
        app.state.gmail_reserved=True
        try:yield
        finally:app.state.gmail_reserved=False
    def clock(value):
        try:
            time=datetime.fromisoformat(value)
            if time.tzinfo is None: raise ValueError()
            return time
        except ValueError: raise HTTPException(422,'as_of must be an ISO timestamp with timezone.')
    def zone(name):
        try:return validate_timezone(name or service.timezone)
        except ValueError as error:raise HTTPException(422,str(error))
    def view(tid,time,timezone=None):
        try: return service.view(tid,time,zone(timezone))
        except KeyError: raise HTTPException(404,'Thread not found.')
    @app.get('/api/config')
    async def config():
        ready,error=True,None
        if settings.provider=='gemini':
            ready=bool(settings.gemini_key)
            if not ready: error='Add GEMINI_API_KEY to the local .env and restart the server.'
            if getattr(service.analyzer,'availability_error',None): ready=False; error=service.analyzer.availability_error
        elif settings.provider=='glm':
            ready=bool(settings.glm_key)
            if not ready: error='Add GLM_API_KEY to the local .env and restart the server.'
        elif settings.provider=='ollama':
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    response=await client.get(settings.ollama_url.rstrip('/')+'/api/tags'); response.raise_for_status()
                ready=any(m['name']==settings.ollama_model for m in response.json()['models'])
                if not ready: error=f'{settings.ollama_model} is not installed in Ollama.'
            except (httpx.HTTPError,KeyError,ValueError): ready=False; error='Ollama is unavailable. Start Ollama and refresh.'
        fallback=None
        if service.fallback:
            fallback_ready=False
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    response=await client.get(settings.ollama_url.rstrip('/')+'/api/tags');response.raise_for_status()
                fallback_ready=any(m['name']==service.fallback.analyzer.model for m in response.json()['models'])
            except (httpx.HTTPError,KeyError,ValueError):pass
            fallback={'provider':service.fallback.analyzer.provider,'model':service.fallback.analyzer.model,'ready':fallback_ready,'primary_budget_seconds':service.primary_budget_seconds}
            ready=ready or fallback_ready
        return {'provider':service.analyzer.provider,'model':service.analyzer.model,'ready':ready,'error':error,'fallback':fallback,
                'default_as_of':DEFAULT_AS_OF,'presets':PRESETS,'timezone':service.timezone,'now':datetime.now(timezone.utc).isoformat(),'saved_analyses':service.store.snapshot_count(),
                'demo_workspace_visible':service.store.demos_visible(),'replay_available':service.store.snapshot_count()>0}
    def scoped_threads(source):
        rows=service.store.threads()
        if source=='gmail':
            imports=[i for i in gmail.account_imports(service.store) if i['status'] in ['completed','partial']]
            selected=set(imports[-1]['thread_ids']) if imports else None
            from .gmail import account_prefix
            account=gmail.current_account();prefix=account_prefix(account) if account else 'gmail-'
            return [t for t in rows if t['id'].startswith(prefix) and (selected is None or t['id'] in selected)]
        if not service.store.demos_visible():return []
        if source=='long':return [t for t in rows if t['id'].startswith('long-')]
        return [t for t in rows if not t['id'].startswith('gmail-')]
    @app.get('/api/threads')
    async def threads(as_of:str=DEFAULT_AS_OF,source:Literal['demo','long','gmail']='demo',timezone:str|None=None):
        time=clock(as_of);zone(timezone)
        return {'threads':[view(t['id'],time,timezone) for t in scoped_threads(source)],'as_of':time.isoformat()}
    class DemoVisibilityRequest(BaseModel):
        visible:bool
    @app.post('/api/demo/visibility')
    async def demo_visibility(request:DemoVisibilityRequest):
        return service.store.set_demos_visible(request.visible)
    @app.get('/api/saved-runs')
    async def saved_runs():
        rows=[];conversations=[]
        for thread in service.store.threads():
            runs=service.store.history(thread['id'])
            origin='gmail' if thread['id'].startswith('gmail-') else 'sample' if thread['id'].startswith('sample-') else 'synthetic'
            if origin!='gmail':conversations.append({k:thread[k] for k in ['id','company','subject']}|{'ingestion_source':origin,'message_count':len(thread['messages']),'saved_runs':len(runs)})
            for run in runs:
                rows.append({k:run[k] for k in ['id','thread_id','cache_key','created_at','provider','model','duration_ms']}|
                    {'company':thread['company'],'subject':thread['subject'],'ingestion_source':origin,
                     'as_of':(run.get('run_context') or {}).get('as_of')})
        return {'runs':sorted(rows,key=lambda r:r['created_at'],reverse=True),'conversations':conversations,'demo_workspace_visible':service.store.demos_visible()}
    @app.get('/api/saved-runs/{run_id}')
    async def saved_run(run_id:str,as_of:str=DEFAULT_AS_OF,timezone:str|None=None):
        try:return service.saved_view(run_id,clock(as_of),zone(timezone))
        except KeyError:raise HTTPException(404,'Saved run not found.')
        except ValueError as error:raise HTTPException(409,str(error))
    @app.get('/api/gmail/status')
    async def gmail_status(): return gmail.status(service.store)
    @app.post('/api/gmail/connect')
    async def gmail_connect():
        try:
            async with gmail_change():return await asyncio.to_thread(gmail.connect)
        except GmailError as error: raise HTTPException(409,str(error))
    class GmailAccountRequest(BaseModel):
        account_id:str=Field(min_length=1,max_length=60)
    @app.post('/api/gmail/account')
    async def gmail_account(request:GmailAccountRequest):
        try:
            async with gmail_change():
                await asyncio.to_thread(gmail.select_account,request.account_id)
                return gmail.status(service.store)
        except GmailError as error:raise HTTPException(409,str(error))
    @app.post('/api/gmail/import')
    async def gmail_import(request:GmailImportRequest):
        if any(j['status'] in ['queued','running'] and any(t.startswith('gmail-') for t in j['thread_ids']) for j in jobs.active()):
            raise HTTPException(409,'Wait for the current Gmail analysis to finish before updating imported conversations.')
        try:
            async with gmail_change():
                result=await asyncio.to_thread(gmail.import_threads,service.store,request.query,request.limit,request.selection,request.include_spam_trash)
                service.store.set_demos_visible(request.keep_demos)
                return result
        except GmailError as error: raise HTTPException(409,str(error))
    @app.post('/api/gmail/disconnect')
    async def gmail_disconnect():
        if any(j['status'] in ['queued','running'] and any(t.startswith('gmail-') for t in j['thread_ids']) for j in jobs.active()):
            raise HTTPException(409,'Wait for the current Gmail analysis to finish before disconnecting.')
        try:
            async with gmail_change():return await asyncio.to_thread(gmail.disconnect,service.store)
        except GmailError as error: raise HTTPException(409,str(error))
    @app.get('/api/threads/{tid}')
    async def thread(tid:str,as_of:str=DEFAULT_AS_OF,timezone:str|None=None): return view(tid,clock(as_of),timezone)
    @app.post('/api/threads/{tid}/analyze')
    async def analyze_thread(tid:str,request:AnalyzeRequest):
        guard_import([tid])
        view(tid,request.as_of,request.timezone)
        job=await submit(request.model_copy(update={'thread_ids':[tid]}))
        await jobs.wait(job['id'])
        return view(tid,request.as_of,request.timezone)
    def guard_import(ids):
        if any(tid.startswith('gmail-') for tid in ids) and (app.state.gmail_reserved or gmail.status(service.store)['importing']):
            raise HTTPException(409,'Wait for the Gmail import to finish before analyzing conversations.')
    async def submit(request):
        ids=request.thread_ids if request.thread_ids is not None else [t['id'] for t in scoped_threads(request.source)]
        guard_import(ids)
        for tid in ids: view(tid,request.as_of,request.timezone)
        try:
            await jobs.start()
            return jobs.submit(ids,request.as_of,request.force,request.replay,request.source,request.timezone)
        except ValueError as error: raise HTTPException(409,str(error))
    @app.post('/api/analysis/jobs')
    async def create_job(request:AnalyzeRequest): return await submit(request)
    @app.get('/api/analysis/jobs')
    async def active_jobs(include_finished:bool=False):
        await jobs.start()
        return {'jobs':(service.store.operations('job') if include_finished else jobs.active())[-50:]}
    @app.get('/api/analysis/jobs/{job_id}')
    async def get_job(job_id:str):
        try: return jobs.get(job_id)
        except KeyError: raise HTTPException(404,'Analysis job not found.')
    @app.post('/api/analysis/jobs/{job_id}/resume')
    async def resume_job(job_id:str):
        try:
            job=jobs.get(job_id);guard_import(job['thread_ids']);await jobs.start();return jobs.resume(job_id)
        except KeyError: raise HTTPException(404,'Analysis job not found.')
        except ValueError as error: raise HTTPException(409,str(error))
    @app.post('/api/analysis/jobs/{job_id}/dismiss')
    async def dismiss_job(job_id:str):
        try: return jobs.dismiss(job_id)
        except KeyError: raise HTTPException(404,'Analysis job not found.')
        except ValueError as error: raise HTTPException(409,str(error))
    @app.post('/api/analysis/jobs/{job_id}/cancel')
    async def cancel_job(job_id:str):
        try:return jobs.cancel(job_id)
        except KeyError:raise HTTPException(404,'Job not found.')
        except ValueError as error:raise HTTPException(409,str(error))
    @app.post('/api/analysis/jobs/{job_id}/retry')
    async def retry_job(job_id:str):
        try:
            job=jobs.get(job_id);guard_import(job['thread_ids']);await jobs.start();return jobs.retry(job_id)
        except KeyError:raise HTTPException(404,'Job not found.')
        except ValueError as error:raise HTTPException(409,str(error))
    @app.get('/api/threads/{tid}/history')
    async def history(tid:str):
        try:
            rows=[]
            for run in service.store.history(tid):
                data=json.loads(run['assessment_json'])
                rows.append({k:v for k,v in run.items() if k not in ['assessment_json','raw_json','updated_at']}|{'assessment':data})
            return {'runs':rows,'reviews':service.store.reviews(tid)}
        except KeyError:raise HTTPException(404,'Thread not found.')
    class ReviewRequest(BaseModel):
        run_id:str
        expected_tier:Literal['T1','T2','T3','T4']|None=None
        note:str=Field(min_length=1,max_length=3000)
    @app.post('/api/threads/{tid}/reviews')
    async def review(tid:str,request:ReviewRequest):
        try:return service.store.add_review(tid,request.run_id,request.expected_tier,request.note)
        except KeyError:raise HTTPException(404,'Thread not found.')
        except ValueError as error:raise HTTPException(422,str(error))
    @app.post('/api/threads/{tid}/drafts')
    async def draft(tid:str,request:AnalyzeRequest):
        guard_import([tid]);view(tid,request.as_of,request.timezone)
        try:
            await jobs.start()
            return jobs.submit([tid],request.as_of,True,False,None,request.timezone,task='draft')
        except ValueError as error:raise HTTPException(409,str(error))
    @app.get('/api/threads/{tid}/drafts')
    async def drafts(tid:str,as_of:str=DEFAULT_AS_OF):
        try:
            _,_,key=service.prepared(tid,clock(as_of))
            rows=[{k:v for k,v in d.items() if k!='raw_json'}|{'stale':d['cache_key']!=key or datetime.fromisoformat(d['as_of'])!=clock(as_of)} for d in service.store.operations('draft') if d['thread_id']==tid]
            return {'drafts':rows[-20:][::-1]}
        except KeyError:raise HTTPException(404,'Thread not found.')
    class SyncRequest(BaseModel):
        keep_demos:bool=True
    @app.post('/api/gmail/sync')
    async def sync(request:SyncRequest=SyncRequest()):
        if any(j['status'] in ['queued','running'] and any(t.startswith('gmail-') for t in j['thread_ids']) for j in jobs.active()):
            raise HTTPException(409,'Wait for Gmail analysis and drafts to finish before syncing.')
        try:
            async with gmail_change():
                result=await asyncio.to_thread(gmail.sync_threads,service.store)
                service.store.set_demos_visible(request.keep_demos)
                return result
        except GmailError as error:raise HTTPException(409,str(error))
    @app.post('/api/analysis/run')
    async def analyze_inbox(request:AnalyzeRequest):
        job=await submit(request)
        async def events():
            delivered=0
            while True:
                state=jobs.get(job['id'])
                while delivered<state['completed']:
                    item=state['items'][delivered];delivered+=1
                    result=view(item['thread_id'],request.as_of,request.timezone)
                    yield json.dumps({'job_id':job['id'],'completed':delivered,'total':state['total'],'thread':result},ensure_ascii=False)+'\n'
                if state['status'] not in ['queued','running']:break
                await asyncio.sleep(.25)
        return StreamingResponse(events(),media_type='application/x-ndjson',headers={'Cache-Control':'no-store'})
    @app.post('/api/threads/{tid}/messages')
    async def append(tid:str,request:MessageRequest):
        view(tid,request.sent_at)
        if tid.startswith('gmail-'): raise HTTPException(409,'Gmail import is read-only. Simulate replies in the demo inbox.')
        if not request.body.strip(): raise HTTPException(422,'Message cannot be blank.')
        message=service.append_message(tid,request.direction,request.body.strip(),request.sent_at,request.attachments)
        return {'message':message.model_dump(mode='json'),'thread':service.view(tid,request.sent_at)}
    @app.post('/api/demo/reset')
    async def reset():
        service.reset(); return {'as_of':DEFAULT_AS_OF}
    dist=ROOT/'frontend'/'dist'
    if dist.exists(): app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
    return app


app=create_app()
