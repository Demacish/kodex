"""Entry point for the worker container: `python -m app.workers.worker`
(see kodex.jobs.worker)."""

from __future__ import annotations

import sys

from kodex.jobs.worker import main

if __name__ == "__main__":
    sys.exit(main())
