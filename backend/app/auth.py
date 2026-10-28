"""Who is asking: every route's user comes from get_current_user, which
takes, in order,

- a bearer token: a personal API key (``kdx_…``, kodex.core.auth.keys) or,
  with a provider configured, an OpenID Connect access token from it (v1's
  Android app sends Authentik's), verified against its signing keys;
- the web client's session cookie (kodex.core.auth.sessions), with its
  CSRF token on unsafe requests.

A user from the provider is matched by its subject claim and must be in
OIDC_REQUIRED_GROUP when that is set; with OIDC_ADMIN_GROUP set,
membership in it decides who is an admin. Password logins, passkeys,
two-step login, OpenID Connect logins in the browser and API keys are
kodex.core.auth (ADR 0007, ADR 0020).

For local development, AUTH_DISABLED=true treats every request as a fixed
dev user. Never enable this in a real deployment.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from kodex.core.auth import keys, sessions
from kodex.core.auth.roles import apply_admin_group, set_role

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)
_basic = HTTPBasic(auto_error=False)

_DEV_USER_SUB = "dev-user"


class _JWKSCache:
    """Fetches and caches an OIDC provider's signing keys, refetching after
    an hour so a key rotation on the Authentik side is picked up without a
    restart.

    uvicorn runs this app as a single process with FastAPI's shared sync-
    dependency thread pool (see Dockerfile — no --workers flag), so
    get_current_user's several concurrent calls on one page load (the
    homepage alone fires 7 backendFetch calls, each independently
    depending on this) all land here in different threads. Without a
    lock, every one of them that arrives while the cache is cold/expired
    independently decides "no valid cache" and makes its own discovery +
    jwks round trip — up to 7+ redundant external HTTPS calls (~450ms
    each here, routed through the public internet even though Authentik
    runs on this same host) for what should be a single fetch. Found
    2026-09-21 chasing a recurring "everything is slow again" report:
    visible in the api logs as a burst of openid-configuration/jwks
    requests clustered right after every restart (cache cold) and,
    worse, recurring every ~hour after that as the cache expires and the
    next page load's concurrent requests re-trigger the exact same
    thundering herd. The lock below makes every concurrent caller but
    one block briefly and then reuse the one real fetch instead.
    """

    def __init__(self) -> None:
        self._keys: dict | None = None
        self._fetched_at: float = 0.0
        self._lock = threading.Lock()

    def get(self, issuer: str) -> dict:
        if self._keys is not None and (time.monotonic() - self._fetched_at) < 3600:
            return self._keys

        with self._lock:
            # Re-check — another thread may have already refreshed the
            # cache while this one was waiting for the lock.
            if self._keys is not None and (time.monotonic() - self._fetched_at) < 3600:
                return self._keys

            discovery = httpx.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration", timeout=10)
            discovery.raise_for_status()
            jwks_uri = discovery.json()["jwks_uri"]

            jwks_response = httpx.get(jwks_uri, timeout=10)
            jwks_response.raise_for_status()

            self._keys = jwks_response.json()
            self._fetched_at = time.monotonic()
            return self._keys


_jwks_cache = _JWKSCache()

# The parsed KeySet for the JWKS document _jwks_cache last returned, so the
# RSA keys aren't re-imported on every request.
_key_set: tuple[dict, KeySet] | None = None


def _key_set_for(jwks: dict) -> KeySet:
    global _key_set
    if _key_set is None or _key_set[0] is not jwks:
        _key_set = (jwks, KeySet.import_key_set(jwks))
    return _key_set[1]


def _decode_token(token: str) -> dict:
    settings = get_settings()
    # Both Authentik providers (web confidential + mobile PKCE) live on the
    # same Authentik instance and share the same RSA signing key, so JWKS
    # from the primary issuer verifies tokens from both providers.
    jwks = _jwks_cache.get(settings.oidc_issuer)

    valid_issuers = {settings.oidc_issuer}
    if settings.oidc_mobile_issuer:
        valid_issuers.add(settings.oidc_mobile_issuer)

    try:
        # Only the signature and the time claims (exp/nbf/iat) are checked
        # here; issuer and audience are verified manually below because
        # both the web and the mobile issuer/client id are accepted.
        decoded = jwt.decode(token, _key_set_for(jwks), algorithms=["RS256"])
        jwt.JWTClaimsRegistry().validate(decoded.claims)
    except (JoseError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}") from exc
    claims = decoded.claims

    if claims.get("iss") not in valid_issuers:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token: Invalid issuer")

    valid_audiences = {settings.oidc_client_id}
    if settings.oidc_mobile_client_id:
        valid_audiences.add(settings.oidc_mobile_client_id)
    token_audiences = claims.get("aud", [])
    if isinstance(token_audiences, str):
        token_audiences = [token_audiences]
    if not (set(token_audiences) & valid_audiences):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token: audience mismatch")

    return claims


def _upsert_user(db: Session, sub: str, username: str, email: str | None, is_admin: bool | None,
                 *, create: bool = True) -> User | None:  # fmt: skip
    """Runs on every request with a provider token, so it writes only when
    something changed: concurrent requests would otherwise queue on the
    user row's lock (found 2026-09-21; a page load makes several calls at
    once). ``is_admin`` None leaves the role alone (no admin group). The
    username is the provider's only when the account is made: afterwards
    it is Kodex's (a linked account keeps its own, and KOSync logins with
    it); the email follows the provider when it sends one."""
    user = db.query(User).filter(User.oidc_subject == sub).one_or_none()
    if user is None:
        if not create:
            return None
        user = User(oidc_subject=sub, username=username, email=email)
        set_role(user, "admin" if is_admin else "user")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    changed = is_admin is not None and apply_admin_group(user, is_admin)
    if email is not None and user.email != email:
        user.email = email
        changed = True
    if changed:
        db.commit()
        db.refresh(user)
    return user


def check_claims(claims: dict) -> list[str]:
    """Refuses someone outside OIDC_REQUIRED_GROUP; returns their groups."""
    settings = get_settings()
    groups = claims.get(settings.oidc_groups_claim) or []
    if settings.oidc_required_group and settings.oidc_required_group not in groups:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of the reader app group")
    return list(groups)


def user_from_claims(db: Session, claims: dict) -> User:
    """The user an OpenID Connect token or login stands for, created on
    first sight unless OIDC_CREATE_USERS is off."""
    settings = get_settings()
    groups = check_claims(claims)
    admin_group = settings.oidc_admin_group
    user = _upsert_user(
        db,
        sub=claims["sub"],
        username=claims.get("preferred_username", claims["sub"]),
        email=claims.get("email"),
        is_admin=(admin_group in groups) if admin_group else None,
        create=settings.oidc_create_users,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No Kodex account is linked to this login; ask an admin")  # fmt: skip
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled")
    return user


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()

    if settings.auth_disabled:
        logger.warning("AUTH_DISABLED is set — running with a fixed dev user, never do this in production")
        request.state.auth_method = "dev"
        return get_dev_user(db)

    if credentials is not None:
        token = credentials.credentials
        if token.startswith(keys.PREFIX):
            record = keys.record_for_key(db, token, ("app",))
            user = keys.used(db, record) if record is not None else None
            if record is None or user is None:
                raise _unauthorized("Invalid API key")
            request.state.auth_method = "api_key"
            request.state.api_key_id = record.id
            return user
        if not settings.oidc_issuer:
            raise _unauthorized("Invalid token")
        request.state.auth_method = "bearer"
        return user_from_claims(db, _decode_token(token))

    found = sessions.current(db, request)
    if found is None:
        raise _unauthorized("Not logged in")
    request.state.auth_method = "session"
    request.state.session = found[0]
    return found[1]


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def require_member(user: User = Depends(get_current_user)) -> User:
    """Refuses guests (kodex.core.auth.roles)."""
    if user.role == "guest":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guests can't do this")
    return user


def require_admin_or_upload_key(
    request: Request,
    x_kodex_upload_key: str | None = Header(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> None:
    """Alternate auth path for POST /libraries/{id}/upload (B7 — see
    app/config.py's upload_api_key docstring for why: a headless folder-
    watcher script on an external download-manager host, Mylar3/
    Kapowarr, can't do an interactive Authentik login the way a
    browser-based admin session can, so it authenticates with this
    shared secret instead.

    `credentials` is taken via Depends(_bearer) (auto_error=False, so a
    missing/malformed header returns None instead of raising) rather
    than Depends(get_current_user) directly — FastAPI resolves ALL
    Depends() parameters before this function's body runs, so if
    get_current_user's own 401 could fire before the upload-key check
    even happened, that would defeat the whole point of this being an
    OR, not an AND. get_current_user is called directly, as a plain
    function, only in the fallback branch below.
    """
    settings = get_settings()
    if settings.upload_api_key and x_kodex_upload_key == settings.upload_api_key:
        return
    user = get_current_user(request, credentials=credentials, db=db)
    require_admin(user)


def get_dev_user(db: Session) -> User:
    """The fixed AUTH_DISABLED user — for auth schemes outside the bearer
    flow (OPDS, kosync) that bypass the same way get_current_user does."""
    user = _upsert_user(db, _DEV_USER_SUB, username="dev", email=None, is_admin=True)
    assert user is not None
    return user


def get_current_user_via_opds_token(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    db: Session = Depends(get_db),
) -> User:
    """Auth for the OPDS catalog (kodex.delivery.opds): HTTP Basic, where
    the password is an OPDS API key (or v1's per-user opds_token, see POST
    /me/opds-token). OPDS reader apps authenticate with HTTP Basic and
    don't do OAuth/OIDC flows, which is why Kavita and Komga use keys for
    OPDS too. The username is not checked; only the key matters. The key
    names the reading device (``request.state.device``) in the journal.
    """
    settings = get_settings()

    if settings.auth_disabled:
        logger.warning("AUTH_DISABLED is set — OPDS access bypassed with a fixed dev user")
        return get_dev_user(db)

    if credentials is None or not credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OPDS requires HTTP Basic auth with an OPDS key as the password",
            headers={"WWW-Authenticate": "Basic"},
        )

    request.state.device = ("opds", "OPDS")
    if credentials.password.startswith(keys.PREFIX):
        record = keys.record_for_key(db, credentials.password, ("opds",))
        user = keys.used(db, record) if record is not None else None
        if record is not None:
            request.state.device = (f"opds-{record.id}", record.name)
    else:
        user = db.query(User).filter(User.opds_token == credentials.password).one_or_none()
    if user is None or user.disabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid OPDS key",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user
