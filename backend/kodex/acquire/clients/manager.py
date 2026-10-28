"""Path mapping + provider dispatch shared by the download job bodies in
app/workers/tasks.py. See kodex/acquire/clients/base.py's module docstring for
why external-host mode (a configurable base URL, no assumption of a
shared Docker network) is the design baseline throughout this package.
"""

from __future__ import annotations

# Formats a completed download is actually allowed to land in a library
# as — same set B7's admin upload endpoint accepts (app/api/routes/
# libraries.py's _UPLOAD_EXTENSIONS), intentionally duplicated here
# rather than imported: a 4-item literal isn't worth a shared-module
# dependency between an admin upload route and a background job.
IMPORTABLE_EXTENSIONS = {".cbz", ".cbr", ".cb7", ".epub", ".pdf"}


def map_download_path(path: str, mapping: str) -> str:
    """`mapping` is "host_prefix:container_prefix" (DOWNLOAD_PATH_MAP_
    TORRENT/USENET) — rewrites a path the download client reported (in
    ITS OWN filesystem view) into the path Kodex's worker container sees
    for the same file, when the two run in different containers/hosts
    that mount the same underlying storage at different mount points.
    Empty/malformed mapping (no ":") is a no-op — same path both sides,
    the common case when everything shares one filesystem.
    """
    if not mapping or ":" not in mapping:
        return path
    host_prefix, container_prefix = mapping.split(":", 1)
    if path.startswith(host_prefix):
        return container_prefix + path[len(host_prefix) :]
    return path
