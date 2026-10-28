"""The worker: ``python -m kodex.jobs.worker`` runs every queue, one job at
a time (the tasks are synchronous; run more containers for more at once).
``python -m kodex.jobs.worker --check`` is the container's healthcheck: a
worker's heartbeat in the last minute."""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
from typing import Any

from sqlalchemy import text


def healthy() -> bool:
    from kodex.core.db import engine

    with engine.connect() as connection:
        age = connection.execute(
            text("SELECT extract(epoch FROM now() - max(last_heartbeat)) FROM procrastinate_workers")
        ).scalar()
    return age is not None and age < 60


def run(queues: list[str], *, wait: bool = True, name: str | None = None, install_signal_handlers: bool = True) -> None:
    """Runs a worker on these queues; with ``wait=False`` until they are
    empty (tests, one-off runs)."""
    from kodex.jobs.app import app
    from kodex.jobs.registry import load_tasks

    load_tasks()

    options: dict[str, Any] = {"queues": queues, "wait": wait, "concurrency": 1,
                               "install_signal_handlers": install_signal_handlers}  # fmt: skip
    if name:
        options["name"] = name

    async def work() -> None:
        async with app.open_async():
            await app.run_worker_async(**options)

    asyncio.run(work())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 0 if a worker is alive")
    args = parser.parse_args(argv)
    if args.check:
        return 0 if healthy() else 1
    logging.basicConfig(level=logging.INFO)
    import kodex.jobs.periodic  # noqa: F401 - registers the periodic jobs
    from kodex.jobs.queue import QUEUE_NAMES

    run(list(QUEUE_NAMES), name=socket.gethostname())
    return 0


if __name__ == "__main__":
    sys.exit(main())
