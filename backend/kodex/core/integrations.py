"""Which integrations a server has set up, for the admin view: each one
with its group, whether it's configured, and the environment variables
that configure it. Values are never returned, only whether they're set
(and, for addresses, the host)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_admin
from app.config import Settings, get_settings
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


@dataclass(frozen=True)
class Integration:
    key: str
    group: str  # login | metadata | search | notifications | delivery | ai | downloads | sync
    needs: tuple[str, ...]  # every one must be set
    address: str | None = None  # the setting holding its URL, shown as a host
    optional: bool = True


INTEGRATIONS = (
    Integration("oidc", "login", ("oidc_issuer", "oidc_client_id"), "oidc_issuer"),
    Integration("comicvine", "metadata", ("comicvine_api_key",)),
    Integration("metron", "metadata", ("metron_username", "metron_password")),
    Integration("hardcover", "metadata", ("hardcover_api_token",)),
    Integration("google_books", "metadata", ("google_books_api_key",)),
    Integration("ntfy", "notifications", ("ntfy_url",), "ntfy_url"),
    Integration("telegram", "notifications", ("telegram_bot_token", "telegram_chat_id")),
    Integration("discord", "notifications", ("discord_webhook_url",)),
    Integration("kindle", "delivery", ("smtp_host", "smtp_from_address"), "smtp_host"),
    Integration("ai", "ai", ("ai_provider", "ai_api_key")),
    Integration("prowlarr", "downloads", ("prowlarr_url", "prowlarr_api_key"), "prowlarr_url"),
    Integration("qbittorrent", "downloads", ("qbittorrent_url",), "qbittorrent_url"),
    Integration("sabnzbd", "downloads", ("sabnzbd_url", "sabnzbd_api_key"), "sabnzbd_url"),
    Integration("mylar3", "downloads", ("mylar3_url", "mylar3_api_key"), "mylar3_url"),
    Integration("kapowarr", "downloads", ("kapowarr_url", "kapowarr_api_key"), "kapowarr_url"),
    Integration("flaresolverr", "downloads", ("flaresolverr_url",), "flaresolverr_url"),
    Integration("progress_sync", "sync", ("progress_sync_url", "progress_sync_token"), "progress_sync_url"),
    Integration("peers", "sync", ("kodex_peers",)),
    Integration("stats_key", "sync", ("stats_api_key",)),
    Integration("upload_key", "sync", ("upload_api_key",)),
)


class IntegrationOut(BaseModel):
    key: str
    group: str
    configured: bool
    optional: bool
    env: list[str]
    host: str | None = None


def _set(settings: Settings, name: str) -> bool:
    value = getattr(settings, name, None)
    return bool(value) and value != "change-me"


def status(settings: Settings) -> list[IntegrationOut]:
    out = []
    for item in INTEGRATIONS:
        configured = all(_set(settings, name) for name in item.needs)
        host = None
        if configured and item.address:
            raw = str(getattr(settings, item.address))
            host = urlsplit(raw).hostname or raw.split(":")[0] or None
        out.append(IntegrationOut(key=item.key, group=item.group, configured=configured, optional=item.optional,
                                  env=[name.upper() for name in item.needs], host=host))  # fmt: skip
    return out


@router.get("/integrations", response_model=list[IntegrationOut])
def list_integrations(_admin: User = Depends(require_admin)) -> list[IntegrationOut]:
    return status(get_settings())
