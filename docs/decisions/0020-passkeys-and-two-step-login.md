# 0020. Kodex's own login has passkeys and two-step login; a provider is optional

Status: Accepted (2026-10-26)

Extends [0007](0007-auth.md).

## Context

ADR 0007 made accounts Kodex's own, with OpenID Connect beside them. Its
settings kept v1's `AUTHENTIK_*` names and v1's required group, so a fresh
install still looked like it expected Authentik. A server that only has
Kodex's own accounts needs what an identity provider would otherwise give:
passkeys, a second step after the password, and a way to hand an account to
someone without telling them a password. Moving v1's users off Authentik
needs that last part too, since they have no password.

## Decision

- **Passkeys** (WebAuthn, py_webauthn on the server and
  @simplewebauthn/browser in the web client). A passkey is a discoverable
  credential: it logs in without a username or password, and the device
  checks who is holding it (user verification required). It is also
  accepted as the second step after a password, where presence is enough,
  so a security key without a PIN works there. The relying party is the
  host name of `PUBLIC_APP_URL`, or the request's when that is unset. The
  login page offers passkeys among the username field's suggestions
  (conditional mediation) as well as on a button.
- **Two-step login** with an authenticator app (TOTP, RFC 6238: SHA-1, six
  digits, 30 seconds, one step either side) and ten one-time recovery codes,
  stored as SHA-256 hashes. TOTP is about 30 lines with `hmac`, tested
  against the RFC's vectors, so there is no library for it. A code works
  once (the last used step is kept). With it on, a password login answers
  with a ticket instead of a session; the ticket lives five minutes, takes
  five wrong codes, and failures count towards the username's login limit.
  Turning it off, or making new recovery codes, needs a current code.
- **Sign-in links**: an admin makes a one-time link (three days) for a user,
  who opens it and chooses a password. The token is after the `#`, so it
  doesn't reach access logs, and only its hash is kept. It replaces mailing
  passwords and is how v1's Authentik-only users get a password. The second
  step still applies afterwards.
- **Recovery**: an admin can turn a user's two-step login off and remove
  their passkeys; `python -m kodex.core.auth.cli reset-two-factor` does the
  same from the command line for a locked-out admin.
- **A provider is generic and optional.** The settings are `OIDC_*` (v1's
  `AUTHENTIK_*` names still work), there is no default required or admin
  group, and `OIDC_CREATE_USERS=false` lets in only accounts already linked.
  A logged-in user can link their Kodex account to the provider, or unlink
  it while a password or passkey remains. Linking starts with a POST (CSRF
  token) and the callback checks that the same session started it. The
  provider's username is used when it creates an account, never after, so a
  linked account keeps its name (KOSync logs in with it). Logins through
  the provider skip Kodex's second step: the provider owns that.
- Changing passkeys or two-step login needs a web session; an app's API key
  can't.
- `LOCAL_LOGIN_ENABLED=false` turns passwords and passkeys off together,
  leaving the provider.

## Consequences

Kodex runs without any identity provider, with passkeys and a second step
for those who want them, and still works with Authentik, Keycloak,
Authelia, Zitadel or any other OpenID Connect provider. TOTP secrets are
stored as they are (like the providers above do); encrypting them needs a
server key, which is a phase 7 question with the rest of the secrets.
Passkeys belong to one host name: moving Kodex to another leaves them
behind, while passwords keep working. v1's Android app logs in through
Authentik, so a server that drops Authentik should wait for the v2 app
(phase 5), or keep the provider configured for bearer tokens until then.
