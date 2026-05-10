"""Receiver agent entrypoint."""

from __future__ import annotations

import asyncio
import logging

from .config import load
from .runtime import Receiver


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    r = Receiver(load())
    try:
        await r.run()
    finally:
        await r.client.aclose()
        await r.aclose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
