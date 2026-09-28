import asyncio
import os
import socket

from app.config import get_settings
from app.db import SessionLocal
from app.services.extraction import OpenAICompatibleExtractor
from app.services.jobs import JobProcessor
from app.services.storage import get_storage
from app.services.batch_jobs import BatchProcessor
from app.services.batch_extraction import BatchExtractor


async def run() -> None:
    settings = get_settings()
    processor = JobProcessor(SessionLocal, get_storage(), OpenAICompatibleExtractor(settings), settings)
    batches = BatchProcessor(SessionLocal, get_storage(), BatchExtractor(settings), settings)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    while True:
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
