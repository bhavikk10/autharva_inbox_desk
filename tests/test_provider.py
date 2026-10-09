import asyncio
import httpx
import pytest


@pytest.fixture(autouse=True)
def isolated_glm_request_slot(monkeypatch,tmp_path):
    # Mock provider tests must never queue behind the live app or evaluator.
    import backend.providers as providers
    monkeypatch.setattr(providers,'ROOT',tmp_path)
from backend.providers import Settings, OllamaAnalyzer
from backend.fixtures import seed_threads
from backend.domain import Message


def test_settings_repr_excludes_credentials():
    assert 'test-sensitive-key' not in repr(Settings(gemini_key='test-sensitive-key'))
    assert 'test-sensitive-key' not in repr(Settings(glm_key='test-sensitive-key'))


@pytest.mark.parametrize('general',[False,True])
def test_ollama_generation_constrains_all_source_ids(monkeypatch,general):
    import json
    from test_core import message
    from backend.providers import extraction_schema
    thread={**seed_threads()[0],'id':'gmail-test' if general else 'test'}
    messages=[message('gmail-long-id-1'),message('gmail-long-id-2','outbound')]
    payloads=[]
    data={'is_sales_related':False,'lifecycle':'unknown','buyer_intent':'unknown','summary':'No action.',
          'reason':'No request remains.','blockers':[],'obligations':[],'recommendations':[],
          'ambiguity_notes':[],'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    if general:data.update(category='notification',conversation_state='informational')
    async def post(self,url,**kwargs):
        payloads.append(kwargs['json'])
        return httpx.Response(200,json={'message':{'content':json.dumps(data)},'done_reason':'stop'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    asyncio.run(OllamaAnalyzer(Settings()).analyze(thread,messages))
    schema=payloads[0]['format'];allowed=[m.id for m in messages]
    assert schema['$defs']['EvidenceQuote']['properties']['message_id']['enum']==allowed
    assert schema['$defs']['DatePhrase']['properties']['message_id']['enum']==allowed
    for name in ['LedgerObligation','Recommendation']:
        assert schema['$defs'][name]['properties']['evidence_message_ids']['items']['enum']==allowed
    assert schema['properties']['non_substantive_message_ids']['items']['enum']==allowed
    assert schema['properties']['proposal_message_id']['anyOf'][0]['enum']==allowed
    assert 'enum' not in extraction_schema(thread).model_json_schema()['$defs']['EvidenceQuote']['properties']['message_id']


def test_glm_cooldown_fails_fast_without_sending_another_request(tmp_path):
    import json,time
    from backend.providers import glm_request_slot
    folder=tmp_path/'runtime';folder.mkdir()
    (folder/'glm-provider-cooldown.json').write_text(json.dumps({'until':time.time()+90}))
    async def run():
        with pytest.raises(ValueError,match='cooling down'):
            async with asyncio.timeout(.2):
                async with glm_request_slot(1):
                    pytest.fail('An occupied remote stream must not accept another request.')
    asyncio.run(run())


def test_ollama_evidence_failure_requests_one_new_grounded_output(monkeypatch):
    import json
    from test_grounding import grounded_item
    from test_core import message
    from backend.domain import ExtractionAssessment
    good=grounded_item().model_dump(mode='json');good.update(status='open',resolution_evidence=None)
    base={'is_sales_related':True,'lifecycle':'open','buyer_intent':'high','summary':'SCIM request.',
        'reason':'An explicit request remains open.','blockers':[],'obligations':[good],
        'recommendations':[],'ambiguity_notes':[],'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    valid=json.dumps(base)
    bad=json.loads(valid);bad['obligations'][0]['evidence_message_ids']=['unavailable']
    outputs=[json.dumps(bad),valid];requests=[]
    async def post(self,url,**kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200,json={'message':{'content':outputs[len(requests)-1]},'done_reason':'stop'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    analyzer=OllamaAnalyzer(Settings())
    data,raw,_=asyncio.run(analyzer.analyze(seed_threads()[0],[message(body='Please confirm SCIM urgently.')]))
    assert len(requests)==2
    assert raw==valid
    assert analyzer.rejected_outputs==[outputs[0]]
    assert data.open_items[0].action_evidence.quote==good['action_evidence']['quote']
    assert 'Validation feedback' in requests[1]['messages'][0]['content']
    assert 'Previous validation error (diagnostic data): "Unknown evidence message ID in model response."' in requests[1]['messages'][0]['content']


def test_ollama_rejects_two_invalid_generations_without_more_calls(monkeypatch):
    calls=[]
    async def post(self,url,**kwargs):
        calls.append(1)
        return httpx.Response(200,json={'message':{'content':'{}'},'done_reason':'stop'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    with pytest.raises(ValueError):asyncio.run(OllamaAnalyzer(Settings()).analyze(seed_threads()[0],[]))
    assert len(calls)==2


def test_glm_validates_json_and_sanitizes_api_errors(monkeypatch):
    import pytest
    from backend.providers import GLMAnalyzer, make_analyzer
    from backend.domain import Assessment
    calls=[]
    async def post(self,url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(429,json={'error':{'message':'secret must not leak'}},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    analyzer=make_analyzer(Settings(provider='glm',glm_key='test-sensitive-key'))
    assert isinstance(analyzer,GLMAnalyzer)
    with pytest.raises(ValueError,match='GLM returned HTTP 429') as error:
        asyncio.run(analyzer.analyze(seed_threads()[0],[]))
    assert 'secret' not in str(error.value)
    payload=calls[0][1]['json']
    assert payload['model']=='glm-4.7-flash'
    assert payload['response_format']=={'type':'json_object'}
    assert str(Assessment.model_json_schema()['required'][0]) in payload['messages'][0]['content']
    with pytest.raises(ValueError,match='GLM_API_KEY'):
        asyncio.run(GLMAnalyzer(Settings()).analyze(seed_threads()[0],[]))


def test_glm_rejects_truncated_and_invalid_output(monkeypatch):
    import pytest
    from backend.providers import GLMAnalyzer
    async def post(self,url,**kwargs):
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    with pytest.raises(ValueError,match='truncated'):
        asyncio.run(GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))


def test_no_key_has_explicit_failure():
    from backend.providers import GeminiAnalyzer
    import pytest
    with pytest.raises(ValueError,match='GEMINI_API_KEY'):
        asyncio.run(GeminiAnalyzer(Settings()).analyze(seed_threads()[0],[]))


def test_unknown_provider_is_never_silently_substituted():
    from backend.providers import make_analyzer
    import pytest
    with pytest.raises(ValueError,match='MODEL_PROVIDER'): make_analyzer(Settings(provider='unknown'))


def test_gemini_uses_json_schema_and_handles_network_errors(monkeypatch):
    from google import genai
    from aiohttp import ClientConnectionError
    from types import SimpleNamespace
    from backend.providers import GeminiAnalyzer
    from backend.domain import Assessment
    import pytest
    calls=[]
    async def generate(**kwargs):
        calls.append(kwargs['config'])
        raise ClientConnectionError('unreachable')
    async def close(): pass
    monkeypatch.setattr(genai,'Client',lambda **kwargs: SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate),aclose=close),close=lambda:None))
    with pytest.raises(ValueError,match='connection'):
        asyncio.run(GeminiAnalyzer(Settings(gemini_key='test-only')).analyze(seed_threads()[0],[]))
    from backend.domain import ExtractionAssessment
    assert calls[0].response_json_schema == ExtractionAssessment.model_json_schema()
    assert calls[0].response_schema is None


def test_glm_accepts_only_valid_assessment_json(monkeypatch):
    import json
    import pytest
    from backend.providers import GLMAnalyzer
    from backend.domain import Assessment
    data={'is_sales_related':False,'lifecycle':'open','buyer_intent':'unknown','summary':'Personal support.',
          'blockers':[],'obligations':[],'recommendations':[],'ambiguity_notes':[],
          'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None,
          'reason':'This personal support conversation contains no commercial request or outstanding seller promise. The contact has received the requested help, so there is no unresolved sales obligation, explicit urgency, or timing ambiguity.'}
    async def post(self,url,**kwargs):
        assert kwargs['json']['thinking']=={'type':'enabled'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    a,raw,duration=asyncio.run(GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))
    assert a.model_dump()==Assessment(**data).model_dump() and duration>=0
    valid_reason=data['reason']
    for reason in [None, '', '   ']:
        data['reason']=reason
        with pytest.raises(ValueError,match='reason'):
            asyncio.run(GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))
    data['reason']=valid_reason
    data.pop('is_sales_related')
    with pytest.raises(ValueError):
        asyncio.run(GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))


def test_glm_serializes_independent_analyzers(monkeypatch,tmp_path):
    import json
    import backend.providers as providers
    monkeypatch.setattr(providers,'ROOT',tmp_path)
    active=0; maximum=0
    data={'is_sales_related':False,'lifecycle':'open','buyer_intent':'unknown','summary':'Personal support.',
          'blockers':[],'obligations':[],'recommendations':[],'ambiguity_notes':[],
          'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None,
          'reason':'This personal support conversation contains no commercial request or outstanding seller promise. The contact has received the requested help, so there is no unresolved sales obligation, explicit urgency, or timing ambiguity.'}
    async def post(self,url,**kwargs):
        nonlocal active,maximum
        active+=1;maximum=max(maximum,active)
        await asyncio.sleep(.02)
        active-=1
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    async def run():
        await asyncio.gather(*(providers.GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]) for _ in range(3)))
    asyncio.run(run())
    assert maximum==1


def test_glm_recovers_from_connect_timeout(monkeypatch,tmp_path):
    import json
    import backend.providers as providers
    monkeypatch.setattr(providers,'ROOT',tmp_path)
    requests=0
    data={'is_sales_related':False,'lifecycle':'open','buyer_intent':'unknown','summary':'Personal.',
          'reason':'Personal support is resolved; no commercial obligation remains.',
          'blockers':[],'obligations':[],'recommendations':[],'ambiguity_notes':[],
          'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    async def post(self,url,**kwargs):
        nonlocal requests
        requests+=1
        if requests==1: raise httpx.ConnectTimeout('sensitive diagnostic')
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]},request=httpx.Request('POST',url))
    async def pause(delay): pass
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    monkeypatch.setattr(providers.asyncio,'sleep',pause)
    result,raw,duration=asyncio.run(providers.GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))
    assert result.is_sales_related is False and result.open_items==[]
    assert requests==2


def test_glm_read_timeout_is_explicit_and_never_resubmits(monkeypatch,tmp_path):
    import pytest
    import backend.providers as providers
    monkeypatch.setattr(providers,'ROOT',tmp_path)
    requests=0
    async def post(self,url,**kwargs):
        nonlocal requests
        requests+=1
        raise httpx.ReadTimeout('sensitive diagnostic')
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    with pytest.raises(ValueError,match='response timed out') as error:
        asyncio.run(providers.GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))
    assert requests==1
    assert 'sensitive' not in str(error.value)
    import json
    assert json.loads((tmp_path/'runtime/glm-provider-cooldown.json').read_text())['until']>0


def test_gmail_requires_general_classification_without_changing_demo_schema(monkeypatch):
    import json
    from backend.providers import GLMAnalyzer
    data={'is_sales_related':False,'lifecycle':'unknown','buyer_intent':'unknown','summary':'Personal request.',
          'reason':'The sender requested a response.','blockers':[],'obligations':[],'recommendations':[],
          'ambiguity_notes':[],'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    async def post(self,url,**kwargs):
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    thread={**seed_threads()[0],'id':'gmail-test'}
    with pytest.raises(ValueError,match='category'):
        asyncio.run(GLMAnalyzer(Settings(glm_key='test-only')).analyze(thread,[]))


@pytest.mark.parametrize('status,expected_requests',[ (500,2),(502,2),(503,2),(504,2),(401,1),(400,1)])
def test_glm_retries_transient_server_errors_only(monkeypatch,tmp_path,status,expected_requests):
    import json
    import backend.providers as providers
    monkeypatch.setattr(providers,'ROOT',tmp_path)
    calls=[]
    data={'is_sales_related':False,'lifecycle':'unknown','buyer_intent':'unknown','summary':'Informational.',
          'reason':'No required action.','blockers':[],'obligations':[],'recommendations':[],
          'ambiguity_notes':[],'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    async def post(self,url,**kwargs):
        calls.append(kwargs)
        payload={'error':{'code':'internal_error'}} if len(calls)==1 else {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]}
        return httpx.Response(status if len(calls)==1 else 200,json=payload,request=httpx.Request('POST',url))
    async def pause(delay):pass
    monkeypatch.setattr(httpx.AsyncClient,'post',post);monkeypatch.setattr(providers.asyncio,'sleep',pause)
    if status<500:
        with pytest.raises(ValueError):asyncio.run(providers.GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))
    else:assert asyncio.run(providers.GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))[0].open_items==[]
    assert len(calls)==expected_requests


def test_glm_gmail_contract_excludes_marketing_before_obligation_scan():
    from backend.providers import glm_contract
    text=glm_contract({'id':'gmail-test'})
    assert 'ALL explicit asks and promises' not in text
    assert 'bulk job-opportunity' in text
    assert 'specific interview' in text


def test_glm_schema_retry_requests_actual_new_json_and_retains_rejection(monkeypatch,tmp_path):
    import json
    import backend.providers as providers
    monkeypatch.setattr(providers,'ROOT',tmp_path)
    replies=[];requests=[]
    bad={'is_sales_related':False,'lifecycle':'closed','buyer_intent':'unknown','category':'notification','conversation_state':'closed','summary':'Delivery completed.',
         'reason':'There is no outstanding task.','blockers':[],'obligations':[],'recommendations':[],'ambiguity_notes':[],
         'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    valid={**bad,'lifecycle':'unknown'}
    replies=[json.dumps(bad),json.dumps(valid)]
    async def post(self,url,**kwargs):
        requests.append(kwargs['json']['messages'][0]['content'])
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':replies[len(requests)-1]}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    a=providers.GLMAnalyzer(Settings(glm_key='test-only'))
    data,raw,duration=asyncio.run(a.analyze({**seed_threads()[0],'id':'gmail-test'},[]))
    assert len(requests)==2 and 'lifecycle' in requests[1] and 'Validation feedback' in requests[1]
    assert raw==replies[1] and data.lifecycle=='unknown'
    assert a.rejected_outputs==[replies[0]]


def test_glm_schema_retry_is_bounded_and_never_coerces_invalid_output(monkeypatch,tmp_path):
    import json
    import backend.providers as providers
    monkeypatch.setattr(providers,'ROOT',tmp_path)
    calls=[]
    async def post(self,url,**kwargs):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"lifecycle":"closed"}'}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    with pytest.raises(ValueError):asyncio.run(providers.GLMAnalyzer(Settings(glm_key='test-only')).analyze({**seed_threads()[0],'id':'gmail-test'},[]))
    assert len(calls)==2


def test_glm_reasoning_enabled_but_only_final_json_is_accepted(monkeypatch):
    import json
    from backend.providers import GLMAnalyzer
    data={'is_sales_related':False,'lifecycle':'unknown','buyer_intent':'unknown','summary':'Informational.',
          'reason':'No required action.','blockers':[],'obligations':[],'recommendations':[],
          'ambiguity_notes':[],'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    requests=[]
    async def post(self,url,**kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{
            'content':json.dumps(data),'reasoning_content':'Internal reasoning is not the assessment JSON.'}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    assessment,raw,_=asyncio.run(GLMAnalyzer(Settings(glm_key='test-only')).analyze(seed_threads()[0],[]))
    assert requests[0]['thinking']['type']=='enabled'
    assert requests[0]['max_tokens']>=8192
    assert json.loads(raw)==data and assessment.open_items==[]
    assert 'Internal reasoning' not in raw


def test_glm_budget_and_thinking_are_configurable_and_truncation_is_diagnosable(monkeypatch):
    from backend.providers import GLMAnalyzer
    requests=[]
    async def post(self,url,**kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200,json={'usage':{'completion_tokens':16384,'prompt_tokens':2000},
            'choices':[{'finish_reason':'length','message':{'content':'{"obligations":',
                'reasoning_content':'private reasoning'}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    analyzer=GLMAnalyzer(Settings(glm_key='test-only',glm_thinking='disabled',glm_max_tokens=16384))
    with pytest.raises(ValueError,match='truncated'):
        asyncio.run(analyzer.analyze(seed_threads()[0],[]))
    assert len(requests)==1 and requests[0]['thinking']=={'type':'disabled'}
    assert requests[0]['max_tokens']==16384
    diagnostic=analyzer.response_diagnostics[0]
    assert diagnostic['finish_reason']=='length' and diagnostic['completion_tokens']==16384
    assert diagnostic['final_chars']==len('{"obligations":')
    assert 'private reasoning' not in str(diagnostic)


@pytest.mark.parametrize('options',[{'glm_thinking':'auto'},{'glm_max_tokens':0},{'glm_max_tokens':131073}])
def test_glm_rejects_invalid_generation_settings(options):
    with pytest.raises(ValueError):Settings(**options)


def test_glm_evidence_retry_regenerates_from_sources_without_rewriting_quotes(monkeypatch):
    import json
    from backend.providers import GLMAnalyzer
    from test_core import message
    from test_grounding import grounded_item
    bad=grounded_item().model_dump(mode='json')
    bad.update(status='open',resolution_evidence=None)
    bad['action_evidence']['quote']='Invented SCIM request'
    base={'is_sales_related':True,'lifecycle':'open','buyer_intent':'high','summary':'SCIM requested.',
        'reason':'The SCIM request remains unanswered.','blockers':[],'recommendations':[],
        'ambiguity_notes':[],'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    good=grounded_item().model_dump(mode='json');good.update(status='open',resolution_evidence=None)
    replies=[json.dumps({**base,'obligations':[bad]}),json.dumps({**base,'obligations':[good]})]
    requests=[]
    async def post(self,url,**kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':replies[len(requests)-1]}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    analyzer=GLMAnalyzer(Settings(glm_key='test-only'))
    data,raw,_=asyncio.run(analyzer.analyze(seed_threads()[0],[message(body='Please confirm SCIM urgently.')]))
    assert len(requests)==2 and 'Evidence validation' in requests[1]['messages'][0]['content']
    assert analyzer.rejected_outputs==[replies[0]] and raw==replies[1]
    assert data.open_items[0].action_evidence.quote==good['action_evidence']['quote']


def test_busy_remote_stream_waits_before_retrying_and_records_only_safe_metadata(monkeypatch,tmp_path):
    import json
    import backend.providers as providers
    calls=[];pauses=[]
    async def post(self,url,**kwargs):
        calls.append(1)
        return httpx.Response(429,json={'error':{'code':'1302','message':'private provider text'}},request=httpx.Request('POST',url))
    async def pause(seconds):pauses.append(seconds)
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    monkeypatch.setattr(providers.asyncio,'sleep',pause)
    analyzer=providers.GLMAnalyzer(Settings(glm_key='test-only'))
    with pytest.raises(ValueError,match='rate limit reached'):
        asyncio.run(analyzer.analyze(seed_threads()[0],[]))
    assert len(calls)==3 and pauses==[30,60]
    assert json.loads((tmp_path/'runtime/glm-provider-cooldown.json').read_text())['until']>0
    assert all(r['provider_code']=='1302' for r in analyzer.response_diagnostics)
    assert 'private provider text' not in str(analyzer.response_diagnostics)


def test_reasoning_exhaustion_has_one_explicit_same_model_recovery(monkeypatch):
    import json
    from backend.providers import GLMAnalyzer
    data={'is_sales_related':False,'lifecycle':'unknown','buyer_intent':'unknown','summary':'Informational.',
        'reason':'No required action.','blockers':[],'obligations':[],'recommendations':[],
        'ambiguity_notes':[],'non_substantive_message_ids':[],'proposal_message_id':None,'deferral':None}
    calls=[]
    async def post(self,url,**kwargs):
        calls.append(kwargs['json'])
        body={'usage':{'completion_tokens':16384},'choices':[{'finish_reason':'length',
            'message':{'content':'','reasoning_content':'Long internal reasoning.'}}]} if len(calls)==1 else {
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]}
        return httpx.Response(200,json=body,request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    analyzer=GLMAnalyzer(Settings(glm_key='test-only'))
    result,raw,_=asyncio.run(analyzer.analyze(seed_threads()[0],[]))
    assert len(calls)==2 and {c['model'] for c in calls}=={'glm-4.7-flash'}
    assert [c['thinking']['type'] for c in calls]==['enabled','disabled']
    assert json.loads(raw)==data and result.open_items==[]
    assert analyzer.response_diagnostics[0]['recovery']=='reasoning_exhaustion'
    assert analyzer.response_diagnostics[1]['thinking']=='disabled'
