import asyncio
import json
from types import SimpleNamespace
import pytest
from backend import evaluate as benchmark


def test_unreviewed_holdout_does_not_call_model(tmp_path,monkeypatch):
    (tmp_path/'data').mkdir()
    labels={'as_of':'2026-10-09T18:00:00+05:30','cases':[], 'clock_checks':[], 'human_reviewed':False}
    (tmp_path/'data'/'expected_labels_expansion.json').write_text(json.dumps(labels))
    monkeypatch.setattr(benchmark,'ROOT',tmp_path)
    def unexpected(settings):
        pytest.fail('An unreviewed hold-out must not initialize a model.')
    monkeypatch.setattr(benchmark,'make_analyzer',unexpected)
    args=SimpleNamespace(benchmark='expansion',split='held_out',provider='gemini',model=None,ids=None,force=False)
    with pytest.raises(ValueError,match='review'):
        asyncio.run(benchmark.run(args))
