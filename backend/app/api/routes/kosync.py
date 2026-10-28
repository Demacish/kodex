"""KOReader sync server ("kosync") — lets KOReader and Kobo-with-KOReader
devices sync reading position with Kodex, alongside the OPDS catalog they
already browse. Also the protocol other Kodex servers use to share
progress with a central one (see app/progress/upstream.py).

Point KOReader's "Progress sync" → "Custom sync server" at
<public backend url>/kosync and log in with your Kodex username and a
KOSync key (Settings → API keys; v1's OPDS token works too) as the password. KOReader sends the
username plus an MD5 of the password in x-auth-user/x-auth-key on every
request; there's no session.

Documents are identified by KOReader's partial-MD5 hash ("Binary"
document matching in KOReader), which is what books.content_hash stores
(see app/scanning/fingerprint.py), so a position from a device lands on
the matching book here — and on every other server holding the same
file. The newest position wins and goes into the reading journal; see
app/progress/sync.py.

Not implemented: account registration (POST /users/create answers with a
pointer to Kodex's own login instead — accounts are made in Kodex).
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_dev_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.progress.sync import apply_incoming, best_position
from kodex.core.auth import keys

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kosync", tags=["kosync"])


class KosyncUnauthorized(Exception):
    """Raised by get_kosync_user; app/main.py turns it into kosync's own
    401 body ({"message": ...}), which KOReader shows to the user —
    FastAPI's default {"detail": ...} would just read as an unknown error."""


UNAUTHORIZED_BODY = {"message": "Fel användarnamn eller OPDS-token"}


def get_kosync_user(
    x_auth_user: str | None = Header(default=None),
    x_auth_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if get_settings().auth_disabled:
        return get_dev_user(db)
    if not x_auth_user or not x_auth_key:
        raise KosyncUnauthorized
    user = keys.user_for_kosync(db, x_auth_user, x_auth_key)
    if user is not None:
        return user
    for user in db.query(User).filter(User.username == x_auth_user, User.opds_token.isnot(None)).all():
        expected = hashlib.md5(user.opds_token.encode()).hexdigest()
        if hmac.compare_digest(expected, x_auth_key.lower()) and not user.disabled:
            return user
    raise KosyncUnauthorized


class ProgressIn(BaseModel):
    document: str = Field(min_length=1, max_length=64)
    progress: str | None = Field(default=None, max_length=1024)
    percentage: float = 0.0
    device: str | None = Field(default=None, max_length=255)
    device_id: str | None = Field(default=None, max_length=255)
    # Sent by v1's Kodex servers for "Markera som oläst"; the newest
    # position wins anyway, so it changes nothing.
    kodex_reset: bool = False


@router.post("/users/create", status_code=status.HTTP_403_FORBIDDEN)
def create_user() -> dict:
    return {
        "message": "Konton skapas inte här — logga in med ditt Kodex-användarnamn och ditt OPDS-token som lösenord."
    }


@router.get("/users/auth")
def authorize(_user: User = Depends(get_kosync_user)) -> dict:
    return {"authorized": "OK"}


@router.put("/syncs/progress")
def update_progress(payload: ProgressIn, db: Session = Depends(get_db), user: User = Depends(get_kosync_user)) -> dict:
    """Always 200: kosync clients treat anything else as a sync failure."""
    apply_incoming(db, user, payload.document, progress=payload.progress, percentage=payload.percentage,
                   device=payload.device, device_id=payload.device_id)  # fmt: skip
    best = best_position(db, user, payload.document, for_koreader=False)
    timestamp = int(best.timestamp.timestamp()) if best else 0
    return {"document": payload.document, "timestamp": timestamp}


@router.get("/syncs/progress/{document}")
def get_progress(
    document: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_kosync_user),
    x_kodex_client: str | None = Header(default=None),
) -> dict:
    # Another Kodex server (see app/progress/upstream.py) can use an EPUB
    # position given only as a percentage; a KOReader device can't.
    best = best_position(db, user, document, for_koreader=not x_kodex_client)
    if best is None:
        return {}
    return {
        "document": document,
        "progress": best.progress,
        "percentage": best.percentage,
        "device": best.device,
        "device_id": best.device_id,
        "timestamp": int(best.timestamp.timestamp()),
    }
