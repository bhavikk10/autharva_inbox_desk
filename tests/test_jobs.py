import asyncio
from test_core import at
from test_service import setup,TestAnalyzer


def test_detached_job_finishes_and_resubmission_reuses_active_job(tmp_path):
    from backend.jobs import AnalysisJobs
    async def run():
        release=asyncio.Event();entered=asyncio.Event()
        class Slow(TestAnalyzer):
            async def analyze(self,*args):
                entered.set();await release.wait();return await super().analyze(*args)
        service=setup(tmp_path,Slow());jobs=AnalysisJobs(service)
        await jobs.start()
        try:
            j=jobs.submit(['northstar','evergreen'],at('2026-10-09T18:00:00'))
            await entered.wait()
            assert jobs.submit(['northstar','evergreen'],at('2026-10-09T18:00:00'))['id']==j['id']
            assert jobs.get(j['id'])['status']=='running'
            release.set();await jobs.wait(j['id'])
            result=jobs.get(j['id'])
            assert result['status']=='completed' and result['completed']==2
            assert service.analyzer.calls==2
        finally:await jobs.close()
    asyncio.run(run())


def test_restart_preserves_completed_work_and_requires_explicit_resume(tmp_path):
    from backend.jobs import AnalysisJobs
    async def run():
        blocked=asyncio.Event();second=asyncio.Event()
        class StopSecond(TestAnalyzer):
            async def analyze(self,thread,messages):
                if thread['id']=='evergreen':second.set();await blocked.wait()
                return await super().analyze(thread,messages)
        service=setup(tmp_path,StopSecond());jobs=AnalysisJobs(service);await jobs.start()
        j=jobs.submit(['northstar','evergreen'],at('2026-10-09T18:00:00'))
        await second.wait();await jobs.close()
        fresh=setup(tmp_path,TestAnalyzer());restored=AnalysisJobs(fresh);await restored.start()
        try:
            assert restored.get(j['id'])['status']=='interrupted'
            assert restored.get(j['id'])['completed']==1
            assert fresh.analyzer.calls==0
            restored.resume(j['id']);await restored.wait(j['id'])
            assert restored.get(j['id'])['status']=='completed'
            assert fresh.analyzer.calls==1
        finally:await restored.close()
    asyncio.run(run())


def test_failed_forced_analysis_remains_error_after_service_restart(tmp_path):
    async def run():
        service=setup(tmp_path);clock=at('2026-10-09T18:00:00')
        await service.analyze('northstar',clock)
        service.analyzer.fail=True;await service.analyze('northstar',clock,force=True)
        fresh=setup(tmp_path)
        result=fresh.view('northstar',clock)
        assert result['status']=='error' and result['attention'] is None
    asyncio.run(run())


def test_recovery_keeps_cache_key_and_masks_incomplete_forced_result(tmp_path):
    from backend.jobs import AnalysisJobs
    async def run():
        service=setup(tmp_path);clock=at('2026-10-09T18:00:00')
        await service.analyze('northstar',clock)
        _,_,key=service.prepared('northstar',clock)
        service.store.save_operation('unfinished','attempt',{'status':'running','thread_id':'northstar','error':None},key)
        jobs=AnalysisJobs(setup(tmp_path));await jobs.start()
        try:
            result=jobs.service.view('northstar',clock)
            assert result['status']=='error' and result['attention'] is None
            assert jobs.store.latest_attempt(key)['status']=='interrupted'
        finally:await jobs.close()
    asyncio.run(run())
