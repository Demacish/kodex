"""Small response shapes several routes share."""

from __future__ import annotations

from pydantic import BaseModel


class JobQueuedOut(BaseModel):
    """A background job was queued; follow it at /jobs/{job_id}."""

    job_id: str | None = None
