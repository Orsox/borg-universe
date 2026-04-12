from __future__ import annotations

import logging
import os
import time

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.repositories import ArtifactRepository, TaskRepository
from app.db.supabase_client import SupabaseRestClient
from app.services.agent_worker import AgentWorker


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = logging.getLogger("borg_universe.worker")
    client = SupabaseRestClient(settings)
    worker = AgentWorker(
        task_repository=TaskRepository(client),
        artifact_repository=ArtifactRepository(client),
        settings=settings,
    )

    run_once = os.getenv("WORKER_RUN_ONCE", "false").strip().lower() in {"1", "true", "yes", "on"}
    logger.info("Worker started. run_once=%s poll_interval=%s", run_once, settings.worker_poll_interval_seconds)

    while True:
        processed = worker.process_next_batch()
        if processed:
            logger.info("Processed %s queued task(s).", processed)
        if run_once:
            break
        time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
