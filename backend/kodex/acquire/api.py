"""Whether the acquisition add-on is on, for the web client: with it, a
missing issue is requested and arrives on its own once approved."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.config import get_settings
from app.models.user import User
from kodex.acquire import pipeline

router = APIRouter(tags=["acquire"])


class AcquireOut(BaseModel):
    enabled: bool = Field(description="An approved request for a missing issue is downloaded and imported")
    clients: list[str] = Field(description="The download clients set up: qbittorrent, sabnzbd")


@router.get("/acquire", response_model=AcquireOut)
def acquire_status(_user: User = Depends(get_current_user)) -> AcquireOut:
    settings = get_settings()
    clients = [
        name for name, url in (("qbittorrent", settings.qbittorrent_url), ("sabnzbd", settings.sabnzbd_url)) if url
    ]
    return AcquireOut(enabled=pipeline.enabled(), clients=clients)
