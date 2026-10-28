"""Shared types for the kodex/acquire/clients/ package (Batch C — see
claude/omnibus-och-ai-forbattringar.md for why the actual qBittorrent/
SABnzbd/Prowlarr/FlareSolverr containers this code talks to aren't
running anywhere yet: code/schema only in this pass, external-host mode
by design — every client here is a plain HTTP client against a
configurable base URL, nothing assumes it's reachable on the same Docker
network as Kodex's own containers).
"""

from __future__ import annotations

from dataclasses import dataclass


class DownloadClientError(Exception):
    """Any failure talking to qBittorrent/SABnzbd — caught at the job/
    route layer and turned into Download.status=FAILED + error_message,
    never left to crash the worker.
    """


@dataclass
class DownloadClientStatus:
    """Normalized status poll result — qBittorrent and SABnzbd each
    report progress completely differently (0..1 float vs a percentage
    string, respectively) so kodex/acquire/clients/manager.py's callers never
    need to know which client they're talking to.
    """

    progress: float  # 0.0..1.0
    is_complete: bool
    save_path: str | None
    error: str | None = None
    # The download's own file or folder (qBittorrent's content_path,
    # SABnzbd's storage), which save_path may only contain.
    content_path: str | None = None
