"""Worker agent entrypoint."""

from __future__ import annotations

import asyncio
import logging

from .config import load
from .runtime import Worker


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    w = Worker(load())
    try:
        await w.run()
    finally:
        await w.client.aclose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
