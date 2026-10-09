"""Persisted sequential jobs; model work outlives the requesting browser connection."""
import asyncio
import hashlib
import json
import os
from datetime import datetime
from uuid import uuid4


class AnalysisJobs:
    def __init__(self,service):
        self.service=service;self.store=service.store;self.task=None;self.wake=asyncio.Event()

    def identity(self):
        a=self.service.analyzer
        from .providers import GLM_OUTPUT_CONTRACT
        from .domain import GENERAL_EXTRACTION_CONTRACT
        return {'provider':a.provider,'model':a.model,'extraction_contract':getattr(a,'extraction_contract',None),
                'output_contract':GLM_OUTPUT_CONTRACT if a.provider=='glm' else None,'gmail_contract':GENERAL_EXTRACTION_CONTRACT,
                'generation_config':self.service.context({'id':'job-config','company':'','subject':'','deal_value':None}).get('generation_config'),
                **({'fallback':{'provider':self.service.fallback.analyzer.provider,'model':self.service.fallback.analyzer.model,
                    'primary_budget_seconds':self.service.primary_budget_seconds}} if self.service.fallback else {})}

    async def start(self):
        if self.task and not self.task.done(): return
        self.wake=asyncio.Event()
        handle=open(self.store.path.parent/'analysis-worker.lock','a+b')
        if handle.tell()==0:handle.write(b'0');handle.flush()
        try:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            handle.close();raise ValueError('Another local analysis worker already owns this database.')
        for job in self.store.operations('job'):
            if job['status']=='running':
                job['status']='interrupted'
                for entry in job['items']:
                    if entry['status']=='running':entry['status']='interrupted'
                self.store.save_operation(job['id'],'job',job)
        for attempt in self.store.operations('attempt'):
            if attempt['status']=='running':
                attempt.update(status='interrupted',error='Analysis stopped before a result was saved. Wait for the provider before explicitly retrying.')
                self.store.save_operation(attempt['id'],'attempt',attempt,attempt.get('cache_key'))
        self.task=asyncio.create_task(self.worker(handle));self.wake.set()

    def submit(self,ids,as_of,force=False,replay=False,source=None,timezone=None,task='analysis'):
        ids=list(dict.fromkeys(ids))
        if not ids:raise ValueError('Choose at least one visible thread.')
        for tid in ids:self.service.prepared(tid,as_of)
        from .timezones import validate_timezone
        request={'task':task,'thread_ids':ids,'as_of':as_of.isoformat(),'force':force,'replay':replay,'identity':self.identity(),
                 'timezone':validate_timezone(timezone or self.service.timezone),
                 'source':source or ('gmail' if all(t.startswith('gmail-') for t in ids) else 'long' if all(t.startswith('long-') for t in ids) else 'demo')}
        fingerprint=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        for existing in self.store.operations('job'):
            if existing['status'] in ['queued','running'] and not existing.get('cancel_requested') and existing['fingerprint']==fingerprint:return existing
        state={**request,'fingerprint':fingerprint,'status':'queued','completed':0,'total':len(ids),
               'items':[{'thread_id':tid,'status':'queued','attempts':0} for tid in ids]}
        result=self.store.enqueue_job(uuid4().hex,state);self.wake.set();return result

    def get(self,oid):
        value=self.store.operation(oid)
        if 'items' not in value:raise KeyError(oid)
        return value

    def active(self):
        return [j for j in self.store.operations('job') if j['status'] in ['queued','running','interrupted']]

    def resume(self,oid):
        job=self.get(oid)
        if job['status']!='interrupted':raise ValueError('Only interrupted jobs can be resumed.')
        if job['identity']!=self.identity():raise ValueError('Provider or extraction version changed. Start a new analysis with the current configuration.')
        for item in job['items']:
            _,_,key=self.service.prepared(item['thread_id'],datetime.fromisoformat(job['as_of']))
            if item['status'] in ['interrupted','running']:
                item['status']='queued'
            elif item.get('cache_key') and item['cache_key']!=key:
                item['status']='queued';job['completed']-=1
        job['cancel_requested']=False;job['status']='queued';result=self.store.enqueue_job(oid,job);self.wake.set();return result

    def dismiss(self,oid):
        job=self.get(oid)
        if job['status']!='interrupted':raise ValueError('Only interrupted jobs can be dismissed.')
        job['status']='cancelled'
        return self.store.save_operation(oid,'job',job)

    def cancel(self,oid):
        job=self.get(oid)
        if job['status'] not in ['queued','running','interrupted']:raise ValueError('This job has already finished.')
        job['cancel_requested']=True
        if job['status']!='running':
            job['status']='cancelled'
            for item in job['items']:
                if item['status'] in ['queued','interrupted']:item['status']='cancelled'
        return self.store.save_operation(oid,'job',job)

    def retry(self,oid):
        job=self.get(oid)
        if job['status'] in ['queued','running']:raise ValueError('Wait for this job to finish before retrying.')
        if job['identity']!=self.identity():raise ValueError('Provider changed; start a new job with the current configuration.')
        ids=[i['thread_id'] for i in job['items'] if i['status'] in ['error','interrupted']]
        if not ids:raise ValueError('There are no failed items to retry.')
        return self.submit(ids,datetime.fromisoformat(job['as_of']),True,False,job['source'],job.get('timezone'),job.get('task','analysis'))

    async def wait(self,oid):
        while self.get(oid)['status'] in ['queued','running']:await asyncio.sleep(.025)
        return self.get(oid)

    async def close(self):
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass

    async def worker(self,handle):
        try:
            while True:
                queued=sorted((j for j in self.store.operations('job') if j['status']=='queued'),key=lambda j:(j.get('queue_sequence',0),j['updated_at']))
                if not queued:
                    self.wake.clear()
                    await self.wake.wait();continue
                job=queued[0]
                if job['identity']!=self.identity():
                    job.update(status='interrupted',error='Provider configuration changed; start a fresh analysis.')
                    self.store.save_operation(job['id'],'job',job);continue
                job['status']='running';self.store.save_operation(job['id'],'job',job)
                try:
                    for item in job['items']:
                        if self.get(job['id']).get('cancel_requested'):break
                        if item['status']!='queued':continue
                        item['status']='running';item['attempts']+=1
                        self.store.save_operation(job['id'],'job',job)
                        if job.get('task')=='draft':
                            try:
                                draft=await self.service.generate_draft(item['thread_id'],datetime.fromisoformat(job['as_of']),job.get('timezone'))
                                result={'status':'drafted','error':None};item['draft_id']=draft['id']
                            except (ValueError,TimeoutError) as error:
                                result={'status':'error','error':str(error) or 'Draft generation timed out. Check provider availability and retry explicitly.'}
                        else:
                            result=await self.service.analyze(item['thread_id'],datetime.fromisoformat(job['as_of']),job['force'],job['replay'],timezone=job.get('timezone'))
                        _,_,key=self.service.prepared(item['thread_id'],datetime.fromisoformat(job['as_of']))
                        item.update(status=result['status'],error=result['error'],cache_key=key)
                        job['cancel_requested']=self.get(job['id']).get('cancel_requested',False)
                        job['completed']+=1;self.store.save_operation(job['id'],'job',job)
                    cancelled=job.get('cancel_requested') or self.get(job['id']).get('cancel_requested')
                    for item in job['items']:
                        if cancelled and item['status']=='queued':item['status']='cancelled'
                    job['status']='cancelled' if cancelled else 'completed';self.store.save_operation(job['id'],'job',job)
                except (Exception,asyncio.CancelledError) as error:
                    job['status']='interrupted'
                    for item in job['items']:
                        if item['status']=='running':item['status']='interrupted'
                    self.store.save_operation(job['id'],'job',job)
                    if isinstance(error,asyncio.CancelledError):raise
        finally:handle.close()
