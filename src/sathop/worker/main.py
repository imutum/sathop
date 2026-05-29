from __future__ import annotations

import asyncio
import logging
import sys

from .config import load
from .runtime import EXIT_CODE_REMOVED, Worker, WorkerRemoved

log = logging.getLogger("sathop.worker")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    w = Worker(load())
    try:
        await w.run()
    except* WorkerRemoved:
        log.warning("worker has been removed by orchestrator — exiting")
        sys.exit(EXIT_CODE_REMOVED)
    finally:
        await w.client.aclose()
        await w.downloader.aclose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
