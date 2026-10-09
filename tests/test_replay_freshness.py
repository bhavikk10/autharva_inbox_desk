import asyncio
from datetime import datetime, timezone, timedelta
from backend.replay import export_replay, import_replay
from test_core import at
from test_service import setup, TestAnalyzer


def test_import_does_not_replace_a_newer_actual_run(tmp_path):
    async def run():
        analyzer=TestAnalyzer();analyzer.provider='ollama';analyzer.model='qwen3.5:4b'
        service=setup(tmp_path,analyzer)
        await service.analyze('northstar',at('2026-10-09T18:00:00'))
        bundle=tmp_path/'actual.json';export_replay(service,bundle)
        _,_,key=service.prepared('northstar',at('2026-10-09T18:00:00'))
        old=service.store.snapshot(key)
        newer=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
        updated=analyzer.result.model_copy(update={'summary':'A newer actual extraction.'})
        service.store.save_snapshot(key,'northstar','ollama',analyzer.model,updated,updated.model_dump_json(),newer,12)
        import_replay(service.store,bundle)
        assert service.store.snapshot(key)['created_at']==newer
        assert service.store.snapshot(key)['assessment_json']!=old['assessment_json']
    asyncio.run(run())
