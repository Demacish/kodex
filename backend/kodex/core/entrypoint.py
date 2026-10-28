"""The container's entrypoint: ``python -m kodex.core.entrypoint [api | worker | command …]``.

1. Secrets from files: for each ``NAME_FILE`` whose ``NAME`` isn't set,
   ``NAME`` becomes the file's content (Docker and Podman secrets,
   Kubernetes). See :func:`load_file_secrets`.
2. Started as root, the process becomes ``PUID``:``PGID`` (1000:1000 when
   they aren't set) after giving them /data. ``PUID=0`` stays root, for
   libraries only root can read. Started as anyone else (compose's
   ``user:``, rootless Podman), it stays who it is.
3. The command takes the process over (exec), so SIGTERM from ``docker
   stop`` reaches it directly: uvicorn finishes the requests in flight, the
   worker the jobs it is running.

``api`` migrates the database and serves; ``worker`` runs the jobs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DATA = Path("/data")
DEFAULT_ID = 1000


def setting_names() -> set[str]:
    """The environment names of Kodex's settings (and their older aliases)."""
    from pydantic import AliasChoices

    from app.config import Settings

    names = set()
    for field, info in Settings.model_fields.items():
        names.add(field.upper())
        alias = info.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(str(choice).upper() for choice in alias.choices)
    return names


def load_file_secrets(environ: dict[str, str] | None = None, names: set[str] | None = None) -> list[str]:
    """Sets ``NAME`` from the file ``NAME_FILE`` points at, when ``NAME`` is
    one of Kodex's settings and unset or empty; returns the names it set.
    One trailing newline is dropped (``echo secret > file`` adds one).
    Other ``_FILE`` variables (compose's own, say) are left alone."""
    env = os.environ if environ is None else environ
    known = setting_names() if names is None else names
    loaded = []
    for key in sorted(k for k in env if k.endswith("_FILE") and len(k) > 5):
        name = key[:-5]
        if name not in known or env.get(name):
            continue
        path = Path(env[key])
        try:
            value = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"{key}: can't read {path}: {exc}") from exc
        env[name] = value[:-1] if value.endswith("\n") else value
        loaded.append(name)
    return loaded


def _id(name: str) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return DEFAULT_ID
    if not raw.isdigit():
        raise SystemExit(f"{name} must be a number, not {raw!r}")
    return int(raw)


def _give(path: Path, uid: int, gid: int) -> None:
    """Makes path (and, when it isn't theirs yet, everything in it) uid:gid's."""
    if not path.exists():
        return
    stat = path.stat()
    if (stat.st_uid, stat.st_gid) == (uid, gid):
        return
    for root, dirs, files in os.walk(path):
        os.chown(root, uid, gid)
        for name in dirs + files:
            os.chown(os.path.join(root, name), uid, gid, follow_symlinks=False)


def drop_privileges() -> None:
    if os.geteuid() != 0:
        return
    uid, gid = _id("PUID"), _id("PGID")
    if uid == 0:
        return
    for sub in ("covers", "downloads", "backups"):
        target = DATA / sub
        try:
            target.mkdir(parents=True, exist_ok=True)
            _give(target, uid, gid)
        except OSError as exc:  # a read-only root filesystem without that volume
            print(f"kodex: can't give {target} to {uid}:{gid}: {exc}", file=sys.stderr)
    os.setgroups([gid])
    os.setgid(gid)
    os.setuid(uid)
    os.environ.setdefault("HOME", "/tmp")


def command(args: list[str]) -> list[str]:
    if not args or args == ["api"]:
        return ["sh", "-c", 'python -m kodex.core.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 '
                '--timeout-graceful-shutdown 25']  # fmt: skip
    if args == ["worker"]:
        return [sys.executable, "-m", "app.workers.worker"]
    return args


def main(argv: list[str]) -> None:
    load_file_secrets()
    drop_privileges()
    run = command(argv)
    os.execvp(run[0], run)


if __name__ == "__main__":
    main(sys.argv[1:])
