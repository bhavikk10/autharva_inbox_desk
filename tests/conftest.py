"""Isolate database tests without Pytest's Windows extended-path cleanup.

The restricted Windows host rejects cleanup of its permission-restricted temporary
directories. Fresh UUID folders inside the writable workspace avoid that dependency.
Artifacts are ignored under runtime and never reused between tests.
"""
from pathlib import Path
from uuid import uuid4
import pytest


@pytest.fixture(scope='session')
def workspace_test_run():
    path=Path(__file__).resolve().parents[1]/'runtime'/'tests'/uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.fixture
def tmp_path(workspace_test_run):
    path=workspace_test_run/uuid4().hex
    path.mkdir()
    return path
