import asyncio
import os
import socket

from app.config import get_model_settings, model_settings_changed
from app.db import SessionLocal
from app.services.extraction import OpenAICompatibleExtractor
from app.services.jobs import JobProcessor
from app.services.storage import get_storage
from app.services.batch_jobs import BatchProcessor
from app.services.batch_extraction import BatchExtractor


async def run() -> None:
    settings = get_model_settings()
    storage = get_storage()
    processor = JobProcessor(SessionLocal, storage, OpenAICompatibleExtractor(settings), settings)
    batches = BatchProcessor(SessionLocal, storage, BatchExtractor(settings), settings)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    while True:
        latest = get_model_settings()
        if model_settings_changed(settings, latest):
            settings = latest
            processor = JobProcessor(SessionLocal, storage, OpenAICompatibleExtractor(settings), settings)
            batches = BatchProcessor(SessionLocal, storage, BatchExtractor(settings), settings)
        claimed = await batches.claim_next()
        if claimed:
            await batches.process(*claimed)
        job_id = await processor.claim_next(worker_id)
        if job_id:
            await processor.process(job_id)
        else:
            await asyncio.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    asyncio.run(run())
