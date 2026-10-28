"""Endpoints for the logged-in user's own account settings: profile info,
Send-to-Kindle address, and the OPDS token. See app/auth.py's
get_current_user_via_opds_token for why OPDS needs its own credential
instead of reusing the OIDC session.
"""

from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.user import OpdsTokenOut, UserOut, UserUpdate

router = APIRouter(prefix="/me", tags=["me"])

# Deliberately loose — this only guards against obvious typos before we
# hand the address to an SMTP server, not full RFC 5322 validation (which
# would need the email-validator package for little real benefit here).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        is_admin=user.is_admin,
        kindle_email=user.kindle_email,
        has_opds_token=user.opds_token is not None,
        home_sections=user.home_sections,
        ntfy_topic=user.ntfy_topic,
    )


@router.get("", response_model=UserOut)
def get_my_profile(user: User = Depends(get_current_user)) -> UserOut:
    return _to_user_out(user)


@router.put("", response_model=UserOut)
def update_my_profile(
    payload: UserUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> UserOut:
    if payload.kindle_email is not None:
        cleaned = payload.kindle_email.strip()
        if cleaned and not _EMAIL_RE.match(cleaned):
            raise HTTPException(status_code=400, detail="Det ser inte ut som en giltig e-postadress")
        user.kindle_email = cleaned or None

    if payload.home_sections is not None:
        user.home_sections = payload.home_sections

    if payload.ntfy_topic is not None:
        user.ntfy_topic = payload.ntfy_topic.strip() or None

    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_user_out(user)


@router.post("/opds-token", response_model=OpdsTokenOut)
def create_opds_token(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """(Re-)generates the user's OPDS token. Any previous token stops
    working immediately — there's only ever one active token per user.
    """
    user.opds_token = secrets.token_urlsafe(32)
    db.add(user)
    db.commit()
    return {"opds_token": user.opds_token}


@router.delete("/opds-token", status_code=204, response_model=None)
def revoke_opds_token(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    user.opds_token = None
    db.add(user)
    db.commit()
