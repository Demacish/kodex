"""Authentication owned by the backend (docs/decisions/0007-auth.md).

- Local accounts with argon2id passwords; the first admin is created on
  the first visit, and ``python -m kodex.core.auth.cli`` sets a password
  for any user (an existing v1 user, say).
- The web client gets a session cookie (HttpOnly, SameSite=Lax) and a CSRF
  token it echoes in ``X-CSRF-Token`` on every unsafe request.
- Two-step login with an authenticator app (TOTP) and recovery codes, and
  passkeys (WebAuthn) for logging in without a password or as the second
  step (``factors``, ``passkeys``).
- An admin can hand out a one-time sign-in link for setting a password,
  for a new user or one from v1 who only ever logged in through Authentik.
- OpenID Connect (Authorization Code + PKCE) with any provider is
  optional; a user from it is matched by subject, so v1's Authentik users
  keep their accounts, and a Kodex account can be linked to it later.
- Apps send a bearer token: an OIDC access token (as v1 did) or a personal
  API key; OPDS, KOSync and Kobo use API keys too, shown once.
- Roles: admin, user, guest.
"""
