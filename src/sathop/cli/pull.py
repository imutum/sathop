"""Receiver as a one-shot CLI: parameterized, no .env required.

Usage:
    sathop-pull --url sathop://TOKEN@host:port
    sathop-pull --url ... --dir ./modis --id recv-laptop --concurrent 8
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
from pathlib import Path
from typing import Literal, cast

from sathop.receiver.config import Settings
from sathop.receiver.runtime import Receiver
from sathop.shared.config import add_orch_args, resolve_orch_or_exit


def _parse(argv: list[str] | None = None) -> Settings:
    p = argparse.ArgumentParser(
        prog="sathop-pull",
        description="SatHop receiver (CLI form): pull processed objects into a local directory.",
    )
    add_orch_args(p)
    p.add_argument("--dir", default="./downloads", help="local output directory (default: ./downloads)")
    p.add_argument(
        "--id",
        default=f"recv-{socket.gethostname()}",
        help="receiver id (default: recv-<hostname>)",
    )
    p.add_argument("--poll", type=int, default=10, help="poll/heartbeat interval seconds (default: 10)")
    p.add_argument("--concurrent", type=int, default=4, help="concurrent pulls (default: 4)")
    p.add_argument(
        "--trust-orch-ca",
        action="store_true",
        help="fetch orchestrator-aggregated worker CA bundle, verify against it "
        "(precise trust for self-signed workers — recommended over --insecure-tls)",
    )
    p.add_argument(
        "--insecure-tls",
        action="store_true",
        help="skip TLS cert verification entirely (insecure escape hatch)",
    )
    args = p.parse_args(argv)

    orch_url, token = resolve_orch_or_exit(args)

    return Settings(
        receiver_id=args.id,
        orchestrator_url=orch_url,
        token=token,
        storage_dir=Path(args.dir).resolve(),
        poll_interval=args.poll,
        concurrent_pulls=args.concurrent,
        platform=cast(Literal["linux", "windows"], "windows" if sys.platform == "win32" else "linux"),
        tls_verify=not args.insecure_tls,
        tls_trust_orch=args.trust_orch_ca,
    )


async def _run(s: Settings) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    log = logging.getLogger("sathop.pull")
    log.info("storage = %s", s.storage_dir)
    log.info("orchestrator = %s", s.orchestrator_url)
    r = Receiver(s)
    try:
        await r.run()
    finally:
        await r.client.aclose()
        await r.aclose()


def main() -> None:
    asyncio.run(_run(_parse()))


if __name__ == "__main__":
    main()
