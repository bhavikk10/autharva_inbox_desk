import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone as utc_timezone
from uuid import uuid4
import httpx
from pydantic import ValidationError
from .domain import Message, Assessment, content_hash, validate_evidence, validate_history, visible_messages, GENERAL_EXTRACTION_CONTRACT
from .policy import evaluate
from .providers import GLM_OUTPUT_CONTRACT

log=logging.getLogger(__name__)


class AttentionService:
    def __init__(self,store,analyzer,fallback_analyzer=None,primary_budget_seconds=90):
        self.store=store; self.analyzer=analyzer; self.errors={}; self.lock=asyncio.Lock()
        self.fallback=AttentionService(store,fallback_analyzer) if fallback_analyzer else None
        self.primary_budget_seconds=primary_budget_seconds
        from .timezones import system_timezone
        self.timezone=system_timezone()
    def context(self,thread):
        context={key:thread[key] for key in ['company','subject','deal_value']}
        if thread['id'].startswith(('gmail-','sample-')): context['prompt_variant']=GENERAL_EXTRACTION_CONTRACT
        if self.analyzer.provider=='glm':
            context['output_contract']=GLM_OUTPUT_CONTRACT
            settings=getattr(self.analyzer,'settings',None)
            if settings:context['generation_config']={'thinking':settings.glm_thinking,'max_output_tokens':settings.glm_max_tokens,'reasoning_exhaustion_recovery':settings.glm_recover_reasoning_exhaustion}
        if getattr(self.analyzer,'extraction_contract',None): context['extraction_contract']=self.analyzer.extraction_contract
        return context
    def prepared(self,tid,as_of):
        thread=self.store.thread(tid)
        messages=visible_messages([Message(**m) for m in thread['messages']],as_of)
        key=content_hash(messages,self.analyzer.provider,self.analyzer.model,self.context(thread))
        return thread,messages,key
    def view(self,tid,as_of,timezone=None):
        thread,messages,key=self.prepared(tid,as_of)
        snapshot=self.store.snapshot(key)
        attempt=self.store.latest_attempt(key)
        persistent_error=attempt.get('error') if attempt and attempt['status'] in ['error','interrupted'] else None
        error=self.errors.get(key) or persistent_error
        fallback=(attempt or {}).get('fallback')
        if error and self.fallback and fallback:
            candidate=self.fallback.view(tid,as_of,timezone)
            if candidate['status']=='analyzed' and candidate['provenance']['cache_key']==fallback.get('cache_key'):
                return {**candidate,'attempt':attempt,'provenance':{**candidate['provenance'],'fallback':{
                    'from_provider':self.analyzer.provider,'from_model':self.analyzer.model,'reason':persistent_error or error,
                    'primary_cache_key':key}}}
            if fallback.get('error'):error=f'{error} Fallback {fallback["model"]}: {fallback["error"]}'
        assessment=Assessment.model_validate_json(snapshot['assessment_json']) if snapshot and not error else None
        status='not_started' if not messages else 'analyzed' if assessment else 'error' if error else 'unassessed'
        gmail=tid.startswith('gmail-')
        labels=sorted({label for message in messages for label in (message.gmail_label_ids or [])}) if gmail else None
        return {**{k:v for k,v in thread.items() if k!='messages'},'messages':[{**m.model_dump(mode='json'),**({'gmail_label_ids':m.gmail_label_ids} if gmail else {})} for m in messages],
                'gmail_label_ids':labels,'gmail_labels_complete':gmail and bool(messages) and all(m.gmail_label_ids is not None for m in messages),
                'ingestion_source':'gmail' if gmail else 'sample' if tid.startswith('sample-') else 'synthetic','status':status,'error':error,'assessment':assessment.model_dump(mode='json') if assessment else None,
                'attempt':attempt,
                'resolved_items':[{**i.model_dump(mode='json'),'obligation_id':i.obligation_id} for i in assessment.resolved_items] if assessment else [],
                'attention':evaluate(assessment,messages,as_of,profile='general' if tid.startswith(('gmail-','sample-')) else 'sales',timezone=timezone or self.timezone) if assessment else None,'as_of':as_of.isoformat(),
                'provenance':{'provider':snapshot['provider'],'model':snapshot['model'],'created_at':snapshot['created_at'],
                              'duration_ms':snapshot['duration_ms'],'cache_key':key} if assessment else None}
    async def analyze(self,tid,as_of,force=False,replay=False,timezone=None):
        async with self.lock:
            thread,messages,key=self.prepared(tid,as_of)
            if not messages: return self.view(tid,as_of,timezone)
            if replay:
                current=self.view(tid,as_of,timezone)
                if current['status']=='analyzed' and current['provenance'].get('fallback'):return current
                if self.store.snapshot(key):
                    self.errors.pop(key,None)
                    # Replay is an explicit request for the stored successful run.
                    self.store.save_operation('replay-'+uuid4().hex,'attempt',{'status':'success','error':None,'thread_id':tid},key)
                    return self.view(tid,as_of,timezone)
                self.errors[key]='No actual saved model run matches this thread, message history, and provider. Run live analysis first.'
                self.store.save_operation(uuid4().hex,'attempt',{'status':'error','thread_id':tid,'error':self.errors[key],'error_category':'replay','duration_ms':0},key)
                return self.view(tid,as_of,timezone)
            previous_attempt=self.store.latest_attempt(key)
            failed=previous_attempt and previous_attempt['status'] in ['error','interrupted']
            if not force and failed and self.fallback:
                current=self.view(tid,as_of,timezone)
                if current['status']=='analyzed':return current
                return await self.use_fallback(tid,as_of,timezone,key,previous_attempt['id'],previous_attempt,False)
            if not force and not failed and key not in self.errors and self.store.snapshot(key): return self.view(tid,as_of,timezone)
            operation_id=uuid4().hex;started=time.monotonic()
            attempt={'status':'running','thread_id':tid,'provider':self.analyzer.provider,'model':self.analyzer.model,'error':None,'extraction_context':self.context(thread)}
            self.store.save_operation(operation_id,'attempt',attempt,key)
            try:
                if self.fallback:
                    try:
                        data,raw,duration=await asyncio.wait_for(self.analyzer.analyze(thread,messages),timeout=self.primary_budget_seconds)
                    except TimeoutError as error:
                        raise TimeoutError(f'Primary analysis exceeded its {self.primary_budget_seconds:g}-second budget. No primary assessment was accepted.') from error
                else:data,raw,duration=await self.analyzer.analyze(thread,messages)
                self.save_provider_rejections(tid,key,attempt)
                try:
                    grounded=bool(getattr(self.analyzer,'extraction_contract',None))
                    validate_evidence(data,messages,require_grounded=grounded)
                    prior=self.store.latest_snapshot(tid,self.analyzer.provider,self.analyzer.model)
                    if grounded and prior:
                        previous=Assessment.model_validate_json(prior['assessment_json'])
                        previous_attempt=self.store.latest_attempt(prior['cache_key']) or {}
                        compatible=previous_attempt.get('extraction_context')==self.context(thread)
                        if compatible:
                            prior_run=next((r for r in self.store.history(tid) if r['cache_key']==prior['cache_key'] and r['created_at']==prior['created_at']),None)
                            prior_ids=(prior_run or {}).get('run_context') or {}
                            prior_ids=prior_ids.get('visible_message_ids')
                            # History can constrain only an unchanged, visible prefix.
                            # Never let a later clock/version constrain a rewind.
                            prefix=messages[:len(prior_ids)] if prior_ids is not None else messages
                            compatible=(prior_ids is None or [m.id for m in prefix]==prior_ids) and content_hash(prefix,prior['provider'],prior['model'],self.context(thread))==prior['cache_key']
                        if compatible and previous.obligations is not None and (not tid.startswith('gmail-') or previous.category is not None):
                            validate_history(previous,data,messages)
                except ValueError:
                    self.save_rejected(tid,key,raw)
                    raise
                self.store.save_snapshot(key,tid,self.analyzer.provider,self.analyzer.model,data,raw,datetime.now(utc_timezone.utc).isoformat(),duration,run_context={'as_of':as_of.isoformat(),'timezone':timezone or self.timezone,'visible_message_ids':[m.id for m in messages],'input_messages':[m.model_dump(mode='json') for m in messages],'provider_responses':getattr(self.analyzer,'response_diagnostics',[]),'attention':evaluate(data,messages,as_of,profile='general' if tid.startswith(('gmail-','sample-')) else 'sales',timezone=timezone or self.timezone)})
                self.errors.pop(key,None)
                self.store.save_operation(operation_id,'attempt',{**attempt,'status':'success','duration_ms':duration},key)
            except asyncio.CancelledError:
                self.store.save_operation(operation_id,'attempt',{**attempt,'status':'interrupted','error':'Analysis was interrupted. Wait for the provider before explicitly retrying.','duration_ms':round((time.monotonic()-started)*1000)},key)
                raise
            except (httpx.HTTPError,ValueError,KeyError,TimeoutError) as error:
                rejected_raw=getattr(error,'raw_output',None)
                self.save_provider_rejections(tid,key,attempt,rejected_raw)
                if rejected_raw is not None:
                    self.save_rejected(tid,key,rejected_raw)
                if isinstance(error,ValidationError): detail='Model output failed the structured schema. No assessment was accepted.'
                elif isinstance(error,httpx.HTTPStatusError): detail=f'Provider returned HTTP {error.response.status_code}. Check provider availability or quota and retry.'
                elif isinstance(error,httpx.HTTPError): detail='Provider connection failed or timed out. Check Ollama or API connectivity and retry.'
                elif isinstance(error,TimeoutError):detail=str(error) or 'Analysis timed out. No assessment was accepted.'
                else: detail=str(error)
                self.errors[key]=detail
                category='schema' if isinstance(error,ValidationError) else 'timeout' if 'timed out' in detail.lower() else 'evidence' if 'evidence' in detail.lower() or 'quote' in detail.lower() or 'obligation disappeared' in detail.lower() else 'provider'
                self.store.save_operation(operation_id,'attempt',{**attempt,'status':'error','error':detail,'error_category':category,'duration_ms':round((time.monotonic()-started)*1000)},key)
                log.warning('Analysis failed for %s: %s',tid,type(error).__name__)
                if self.fallback:
                    return await self.use_fallback(tid,as_of,timezone,key,operation_id,{**attempt,'status':'error','error':detail,
                        'error_category':category,'duration_ms':round((time.monotonic()-started)*1000)},force)
                # A failed forced refresh must remain explicit even if an older success exists.
                result=self.view(tid,as_of,timezone)
                return {**result,'status':'error','error':detail,'attention':None,'assessment':None,'provenance':None}
            return self.view(tid,as_of,timezone)
    async def use_fallback(self,tid,as_of,timezone,key,operation_id,attempt,force):
        # Separate service means separate provider cache, grounded validation,
        # historical continuity and raw response. Never save Qwen under GLM.
        result=await self.fallback.analyze(tid,as_of,force=force,timezone=timezone)
        fallback_key=self.fallback.prepared(tid,as_of)[2]
        attempt={**attempt,'fallback':{'provider':self.fallback.analyzer.provider,'model':self.fallback.analyzer.model,
            'cache_key':fallback_key,'status':result['status'],'error':result['error']}}
        self.store.save_operation(operation_id,'attempt',attempt,key)
        return self.view(tid,as_of,timezone)
    def save_provider_rejections(self,tid,key,attempt,final_raw=None):
        if getattr(self.analyzer,'response_diagnostics',None):
            attempt['provider_responses']=self.analyzer.response_diagnostics.copy()
        rejected=getattr(self.analyzer,'rejected_outputs',[])
        attempt['schema_retry_count']=len(rejected)
        for raw in rejected:
            if raw==final_raw:continue  # Identical final rejection is retained by the error handler.
            artifact_key=hashlib.sha256((key+'|schema-retry|'+raw).encode()).hexdigest()
            self.save_rejected(tid,artifact_key,raw)

    def save_rejected(self,tid,key,raw):
        rejected=self.store.path.parent/'rejected'
        if tid.startswith('gmail-'):rejected=rejected/'gmail'
        rejected.mkdir(parents=True,exist_ok=True)
        (rejected/f'{key}.json').write_text(raw,encoding='utf-8')
    def append_message(self,tid,direction,body,sent_at,attachments=None):
        thread=self.store.thread(tid)
        source=next((m for m in thread['messages'] if m['direction']==direction),None)
        message=Message(id=f'{tid}-sim-{uuid4().hex[:12]}',sender=source['sender'] if source else 'Alex Morgan' if direction=='outbound' else thread['contact'],
                        recipients=source.get('recipients') if source else None,
                        direction=direction,body=body,sent_at=sent_at,attachments=attachments or [],simulated=True)
        self.store.append(tid,message)
        return message
    def reset(self): self.store.reset(); self.errors.clear()

    async def generate_draft(self,tid,as_of,timezone=None):
        async with self.lock:
            thread,messages,key=self.prepared(tid,as_of)
            if not messages:raise ValueError('No messages are visible at this evaluation time.')
            writer=getattr(self,'draft_writer',None)
            if writer is None:raise ValueError('Reply drafting is not configured for this provider.')
            draft,raw,duration=await asyncio.wait_for(writer.generate(thread,messages,as_of,timezone or self.timezone),timeout=getattr(getattr(writer,'settings',None),'timeout',180)+30)
            return self.store.save_operation(uuid4().hex,'draft',{'thread_id':tid,'source':'gmail' if tid.startswith('gmail-') else 'demo',
                'provider':self.analyzer.provider,'model':self.analyzer.model,'as_of':as_of.isoformat(),'timezone':timezone or self.timezone,
                'draft':draft.model_dump(mode='json'),'raw_json':raw,'duration_ms':duration,'visible_message_ids':[m.id for m in messages]},key)

    def saved_view(self,run_id,as_of,timezone=None):
        import json
        from .providers import ROOT
        run=next((r for t in self.store.threads() for r in self.store.history(t['id']) if r['id']==run_id),None)
        if not run:raise KeyError(run_id)
        tid=run['thread_id'];thread=self.store.thread(tid);context=run.get('run_context') or {}
        inputs=context.get('input_messages')
        if not inputs:
            # Existing exports preserve authentic original inputs. Never reconstruct invented emails.
            for path in (ROOT/'reports').glob('replay-*.json'):
                try:document=json.loads(path.read_text(encoding='utf-8'))
                except (ValueError,OSError):continue
                if document.get('origin')!='actual-model-runs':continue
                entry=next((e for e in document.get('runs',[]) if e['cache_key']==run['cache_key'] and e['raw_json']==run['raw_json']),None)
                if entry:inputs=entry['input_messages'];break
        if not inputs:
            attempt=self.store.latest_attempt(run['cache_key']) or {}
            original_context=attempt.get('extraction_context') or {k:thread[k] for k in ['company','subject','deal_value']}
            candidates=visible_messages([Message(**m) for m in thread['messages']],as_of)
            for end in range(1,len(candidates)+1):
                prefix=candidates[:end]
                if content_hash(prefix,run['provider'],run['model'],original_context)==run['cache_key']:
                    inputs=[m.model_dump(mode='json') for m in prefix];break
        if not inputs:raise ValueError('The original message version is unavailable. Inspect this run in analysis history instead.')
        messages=sorted([Message(**m) for m in inputs],key=lambda m:(m.sent_at,m.id))
        if any(m.sent_at>as_of for m in messages):raise ValueError('This saved run includes messages after the selected evaluation time. Move the clock forward or select an earlier run.')
        data=Assessment.model_validate_json(run['assessment_json'])
        if Assessment.model_validate_json(run['raw_json'])!=data:raise ValueError('Saved assessment does not match its original model output.')
        validate_evidence(data,messages)
        _,current_messages,current_key=self.prepared(tid,as_of)
        gmail=tid.startswith('gmail-')
        return {**{k:v for k,v in thread.items() if k!='messages'},'messages':[m.model_dump(mode='json') for m in messages],
            'ingestion_source':'gmail' if gmail else 'sample' if tid.startswith('sample-') else 'synthetic',
            'gmail_label_ids':None,'gmail_labels_complete':False,'status':'analyzed','error':None,'attempt':None,
            'assessment':data.model_dump(mode='json'),'resolved_items':[i.model_dump(mode='json') for i in data.resolved_items],
            'attention':evaluate(data,messages,as_of,profile='general' if tid.startswith(('gmail-','sample-')) else 'sales',timezone=timezone or self.timezone),
            'as_of':as_of.isoformat(),'provenance':{'provider':run['provider'],'model':run['model'],'created_at':run['created_at'],
                'duration_ms':run['duration_ms'],'cache_key':run['cache_key'],'saved_run_id':run_id,
                'extraction_matches_current_config':run['cache_key']==current_key,
                'input_is_current':[m.model_dump(mode='json') for m in messages]==[m.model_dump(mode='json') for m in current_messages]}}
