import asyncio
import pytest
from test_core import at
from test_service import setup, TestAnalyzer


def test_replay_requires_matching_actual_run_and_never_calls_model(tmp_path):
    async def run():
        analyzer=TestAnalyzer(); analyzer.provider='ollama'; analyzer.model='qwen3.5:4b'
        service=setup(tmp_path,analyzer)
        time=at('2026-10-09T18:00:00')
        empty=await service.analyze('northstar',time,replay=True)
        assert empty['status']=='error' and empty['attention'] is None and analyzer.calls==0
        await service.analyze('northstar',time)
        assert analyzer.calls==1
        result=await service.analyze('northstar',time,replay=True)
        assert result['status']=='analyzed' and analyzer.calls==1
        service.append_message('northstar','inbound','A new question.',time)
        result=await service.analyze('northstar',time,replay=True)
        assert result['status']=='error' and analyzer.calls==1
    asyncio.run(run())


@pytest.mark.parametrize('provider,model',[('ollama','qwen3.5:4b'),('glm','glm-4.7-flash')])
def test_replay_export_import_validates_evidence_and_provenance(tmp_path,provider,model):
    async def run():
        import json
        from backend.replay import export_replay, import_replay
        from backend.store import Store
        analyzer=TestAnalyzer();analyzer.provider=provider;analyzer.model=model
        service=setup(tmp_path,analyzer)
        await service.analyze('northstar',at('2026-10-09T18:00:00'))
        path=tmp_path/'runs.json'
        assert export_replay(service,path)==1
        target=Store(tmp_path/'clean.sqlite');target.seed()
        assert import_replay(target,path)==1
        data=json.loads(path.read_text())
        data['runs'][0]['provider']='test'
        path.write_text(json.dumps(data))
        import pytest
        with pytest.raises(ValueError,match='provider'): import_replay(target,path)
    asyncio.run(run())
