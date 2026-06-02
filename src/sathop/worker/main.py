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
    # `sys.exit` inside an `except*` handler is re-wrapped into a BaseExceptionGroup
    # (PEP 654), so the runtime prints a traceback and the exit code degrades to 1 —
    # the entrypoint then treats a clean removal as a crash and restart-loops instead
    # of honouring EXIT_CODE_REMOVED. Flag it and exit with a bare SystemExit after
    # the try/except*/finally (same fix as shared/agent_lifecycle.py::run_agent).
    removed = False
    try:
        await w.run()
    except* WorkerRemoved:
        log.warning("worker has been removed by orchestrator — exiting")
        removed = True
    finally:
        await w.client.aclose()
        await w.downloader.aclose()
    if removed:
        sys.exit(EXIT_CODE_REMOVED)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
