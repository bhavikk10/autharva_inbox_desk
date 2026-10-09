import asyncio
from fastapi.testclient import TestClient
from test_service import setup, TestAnalyzer
from test_core import at


def client(tmp_path):
    from backend.main import create_app
    from backend.providers import Settings
    service=setup(tmp_path)
    return TestClient(create_app(service,Settings(provider='gemini'))), service


def test_health_check_does_not_require_model_configuration(tmp_path):
    app,service=client(tmp_path)
    with app:
        response=app.get('/api/health')
        assert response.status_code==200
        assert response.json()=={'status':'ok'}
        assert service.analyzer.calls==0


def test_api_rejects_naive_time_and_missing_thread(tmp_path):
    app,_=client(tmp_path)
    assert app.get('/api/threads?as_of=2026-10-09T18:00:00').status_code==422
    assert app.get('/api/threads/missing').status_code==404
    assert app.post('/api/threads/northstar/messages',json={'direction':'outbound','body':'   ','sent_at':'2026-10-09T18:00:00+05:30'}).status_code==422


def test_stream_reports_every_thread_and_missing_key_is_explicit(tmp_path):
    app,_=client(tmp_path)
    config=app.get('/api/config').json()
    assert config['ready'] is False and 'GEMINI_API_KEY' in config['error']
    response=app.post('/api/analysis/run',json={'as_of':'2026-10-09T18:00:00+05:30','thread_ids':['northstar','evergreen']})
    import json
    events=[json.loads(line) for line in response.text.splitlines()]
    assert len(events)==2 and events[-1]['completed']==2


def test_failed_forced_refresh_stays_explicit_on_subsequent_get(tmp_path):
    async def run():
        service=setup(tmp_path)
        clock=at('2026-10-09T18:00:00')
        await service.analyze('northstar',clock)
        service.analyzer.fail=True
        result=await service.analyze('northstar',clock,force=True)
        assert result['status']=='error'
        later=service.view('northstar',clock)
        assert later['status']=='error' and later['attention'] is None
    asyncio.run(run())


def test_job_api_tracks_background_results_and_rejects_invalid_resume(tmp_path):
    app,service=client(tmp_path)
    with app:
        r=app.post('/api/analysis/jobs',json={'as_of':'2026-10-09T18:00:00+05:30','thread_ids':['northstar'],'source':'demo'})
        assert r.status_code==200
        job=r.json()
        assert job['status']=='queued' and job['total']==1 and job['source']=='demo'
        app.portal.call(app.app.state.jobs.wait,job['id'])
        final=app.get('/api/analysis/jobs/'+job['id']).json()
        assert final['status']=='completed' and final['completed']==1
        assert service.analyzer.calls==1
        assert app.get('/api/threads/northstar').json()['status']=='analyzed'
        assert app.post('/api/analysis/jobs/'+job['id']+'/resume').status_code==409
        assert app.get('/api/analysis/jobs/missing').status_code==404
