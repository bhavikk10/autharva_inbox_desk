import asyncio
import pytest
from test_core import assessment, item, at
from test_service import setup, TestAnalyzer
from backend.service import AttentionService


class LocalAnalyzer(TestAnalyzer):
    provider = 'ollama'
    model = 'qwen3.5:4b'


@pytest.mark.parametrize('invalid', [False, True])
def test_fallback_has_its_own_validated_snapshot_and_visible_provenance(tmp_path, invalid):
    async def run():
        primary = TestAnalyzer(assessment([item(evidence_message_ids=['invented'])]) if invalid else None, fail=not invalid)
        local = LocalAnalyzer()
        base = setup(tmp_path, primary)
        service = AttentionService(base.store, primary, fallback_analyzer=local)
        clock = at('2026-10-09T18:00:00')
        primary_key = service.prepared('northstar', clock)[2]
        result = await service.analyze('northstar', clock)
        assert result['status'] == 'analyzed'
        assert result['provenance']['provider'] == 'ollama'
        assert result['provenance']['fallback']['from_provider'] == 'test'
        assert result['provenance']['fallback']['reason']
        assert base.store.snapshot(primary_key) is None
        assert base.store.snapshot(result['provenance']['cache_key'])['raw_json'] == local.result.model_dump_json()
        assert base.store.latest_attempt(primary_key)['status'] == 'error'
        reloaded = AttentionService(base.store, primary, fallback_analyzer=local)
        assert reloaded.view('northstar', clock)['provenance']['provider'] == 'ollama'
        assert (await reloaded.analyze('northstar', clock))['status'] == 'analyzed'
        assert primary.calls == 1 and local.calls == 1
        assert (await reloaded.analyze('northstar', clock, replay=True))['status'] == 'analyzed'
        assert primary.calls == 1 and local.calls == 1
        reloaded.append_message('northstar', 'inbound', 'Approved.', at('2026-10-09T18:05:00'))
        assert reloaded.view('northstar', at('2026-10-09T18:05:00'))['status'] == 'unassessed'
    asyncio.run(run())


def test_known_primary_failure_retries_local_without_another_remote_call(tmp_path):
    async def run():
        primary = TestAnalyzer(fail=True)
        base = setup(tmp_path, primary)
        clock = at('2026-10-09T18:00:00')
        assert (await base.analyze('northstar', clock))['status'] == 'error'
        service = AttentionService(base.store, primary, fallback_analyzer=LocalAnalyzer())
        assert (await service.analyze('northstar', clock))['status'] == 'analyzed'
        assert primary.calls == 1
        primary.fail = False
        result = await service.analyze('northstar', clock, force=True)
        assert result['provenance']['provider'] == 'test'
        assert not result['provenance'].get('fallback')
    asyncio.run(run())


def test_invalid_local_output_keeps_both_failures_explicit(tmp_path):
    async def run():
        base = setup(tmp_path, TestAnalyzer(fail=True))
        local = LocalAnalyzer(assessment([item(evidence_message_ids=['invented'])]))
        service = AttentionService(base.store, base.analyzer, fallback_analyzer=local)
        result = await service.analyze('northstar', at('2026-10-09T18:00:00'))
        assert result['status'] == 'error' and result['attention'] is None
        assert 'Fallback' in result['error'] and 'Provider unavailable' in result['error']
        assert base.store.snapshot_count() == 0
    asyncio.run(run())


def test_primary_deadline_cancels_before_local_fallback(tmp_path):
    class SlowAnalyzer(TestAnalyzer):
        cancelled = False
        async def analyze(self, thread, messages):
            try:
                await asyncio.sleep(5)
            finally:
                self.cancelled = True
    async def run():
        primary = SlowAnalyzer()
        base = setup(tmp_path, primary)
        service = AttentionService(base.store, primary, fallback_analyzer=LocalAnalyzer(), primary_budget_seconds=.01)
        result = await service.analyze('northstar', at('2026-10-09T18:00:00'))
        assert primary.cancelled
        assert result['status'] == 'analyzed'
        assert 'budget' in result['provenance']['fallback']['reason']
    asyncio.run(run())


def test_cancellation_does_not_start_fallback(tmp_path):
    class CancelledAnalyzer(TestAnalyzer):
        async def analyze(self, thread, messages):
            raise asyncio.CancelledError()
    async def run():
        base = setup(tmp_path, CancelledAnalyzer())
        local = LocalAnalyzer()
        service = AttentionService(base.store, base.analyzer, fallback_analyzer=local)
        with pytest.raises(asyncio.CancelledError):
            await service.analyze('northstar', at('2026-10-09T18:00:00'))
        assert local.calls == 0
    asyncio.run(run())


def test_local_timeout_has_an_explicit_error_and_no_tier(tmp_path):
    class TimedOutLocal(LocalAnalyzer):
        async def analyze(self, thread, messages):raise TimeoutError()
    async def run():
        base=setup(tmp_path,TestAnalyzer(fail=True))
        service=AttentionService(base.store,base.analyzer,fallback_analyzer=TimedOutLocal())
        result=await service.analyze('northstar',at('2026-10-09T18:00:00'))
        assert result['status']=='error' and result['attention'] is None
        assert 'timed out' in result['error']
    asyncio.run(run())
