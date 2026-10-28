from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.routes import (
    ai,
    books,
    cbl,
    collections,
    enrichment,
    jobs,
    kosync,
    leagueofcomicgeeks,
    libraries,
    me,
    page_flags,
    reading_progress,
    releases,
    search,
    series,
    stats,
)
from app.config import get_settings
from kodex.acquire import api as acquire_api
from kodex.acquire import downloads, requests
from kodex.acquire.sorting import api as sorting
from kodex.core import integrations
from kodex.core import sync as sync_api
from kodex.core.auth import api as auth_api
from kodex.core.auth import apps as auth_apps
from kodex.core.auth import factors_api
from kodex.core.headers import SecurityHeaders
from kodex.core.legacy import V1Proxy
from kodex.core.spa import WebClient
from kodex.delivery.federation import admin as peers_admin
from kodex.delivery.federation import api as federation_api
from kodex.delivery.opds import atom as opds_atom
from kodex.delivery.opds import v2 as opds_v2
from kodex.library import api as library_api
from kodex.matching import api as matching_api
from kodex.reading.kobo import api as kobo_api
from kodex.reading.kobo import devices as kobo_devices
from kodex.reading.trackers import api as trackers_api

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The schema is owned by Alembic and migrated before the API starts
    # (python -m kodex.core.migrate, see backend/Dockerfile).
    settings = get_settings()
    if settings.auth_disabled:
        logging.getLogger(__name__).warning(
            "Starting with AUTH_DISABLED=true — every request is treated as an admin dev user. "
            "Do not run like this outside local development."
        )

    yield


def _operation_id(route: APIRoute) -> str:
    """Stable names for generated clients: tag and function name."""
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


app = FastAPI(
    title="Kodex",
    description="Self-hosted library server and reader for comics, manga and e-books",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
    generate_unique_id_function=_operation_id,
)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """Alive: the process answers (Docker's healthcheck uses /readyz)."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz() -> JSONResponse:
    """Ready for traffic: the database answers and its schema is at the
    migrations' head (so the worker, which waits on this, starts after them)."""
    from kodex.core.migrate import readiness

    problem = readiness()
    if problem:
        return JSONResponse(status_code=503, content={"status": "not ready", "reason": problem})
    return JSONResponse(content={"status": "ready"})


@app.exception_handler(kosync.KosyncUnauthorized)
async def _kosync_unauthorized(_request, _exc) -> JSONResponse:
    return JSONResponse(status_code=401, content=kosync.UNAUTHORIZED_BODY)


# The API the clients use, under /api and described by /api/openapi.json.
_API_ROUTERS = [
    auth_api.router,
    factors_api.router,
    auth_apps.router,
    sync_api.router,
    kobo_devices.router,
    trackers_api.router,
    acquire_api.router,
    integrations.router,
    ai.router,
    libraries.router,
    series.router,
    books.router,
    reading_progress.router,
    enrichment.router,
    jobs.router,
    me.router,
    search.router,
    collections.router,
    peers_admin.router,
    requests.router,
    sorting.router,
    stats.router,
    cbl.router,
    leagueofcomicgeeks.router,
    page_flags.router,
    releases.router,
    downloads.router,
    matching_api.router,
    library_api.router,
]
# Protocols other programs find by address: OPDS readers, KOReader, other
# Kodex servers.
_PROTOCOL_ROUTERS = [opds_atom.router, opds_v2.router, kosync.router, kobo_api.router, federation_api.router]

for _router in _API_ROUTERS:
    app.include_router(_router, prefix="/api")
for _router in _PROTOCOL_ROUTERS:
    app.include_router(_router)
# v1's clients (the Android app until v2 ships, phase 5) call the API at
# the root; the same routes stay there, out of the schema.
for _router in _API_ROUTERS:
    app.include_router(_router, include_in_schema=False)

# The web client (web/, built into the image): its files, and index.html
# for every page the browser navigates to (kodex.core.spa).
app.add_middleware(WebClient, dist=get_settings().web_dist_dir)
# Added last, so it runs first: v1's /api/backend/<path> is /<path>.
app.add_middleware(V1Proxy)
# Outermost: every response, the web client's and the protocols' too.
app.add_middleware(SecurityHeaders)
