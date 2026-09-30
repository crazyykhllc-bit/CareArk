import asyncio

import pytest

from app import worker
from app.config import Settings


def test_worker_uses_edited_model_settings_for_next_task(monkeypatch):
    before = Settings(_env_file=None, model_api_key='', model_name='vision-test')
    after = Settings(_env_file=None, model_api_key='example-key', model_name='vision-test')
    settings = iter((before, after))
    batch_keys = []
    job_keys = []

    class StopWorker(Exception):
        pass

    class FakeBatchProcessor:
        def __init__(self, session_factory, storage, extractor, configuration):
            batch_keys.append(extractor.settings.model_api_key)

        async def claim_next(self):
            return None

    class FakeJobProcessor:
        def __init__(self, session_factory, storage, extractor, configuration):
            job_keys.append(extractor.settings.model_api_key)

        async def claim_next(self, worker_id):
            raise StopWorker()

    monkeypatch.setattr(worker, 'get_model_settings', lambda: next(settings))
    monkeypatch.setattr(worker, 'get_storage', object)
    monkeypatch.setattr(worker, 'BatchProcessor', FakeBatchProcessor)
    monkeypatch.setattr(worker, 'JobProcessor', FakeJobProcessor)

    with pytest.raises(StopWorker):
        asyncio.run(worker.run())

    assert batch_keys == ['', 'example-key']
    assert job_keys == ['', 'example-key']
