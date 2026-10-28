# Security

How Kodex protects accounts and the server, and what it leaves to the
reverse proxy. Phase 7's review (2026-10-27) found and fixed the items
marked **Fixed**.

To report a vulnerability, write to the maintainer privately rather than
opening an issue.

## Accounts and logins

- **Passwords** are hashed with argon2id: argon2-cffi's defaults, 64 MiB of
  memory, 3 passes and 4 lanes (RFC 9106's second recommendation).
- **Failed logins.** After `LOGIN_MAX_FAILURES` failures for a username
  (5), or `LOGIN_MAX_FAILURES_PER_IP` from one address (30), within
  `LOGIN_LOCKOUT_MINUTES` (15), it waits before it can try again. The same
  applies to the app's password login and its second step.
- **Sessions** are random tokens, kept as SHA-256 hashes. They last
  `SESSION_DAYS` (30), are extended while used, and can be ended one by one
  under Inställningar. The cookie is HttpOnly, SameSite=Lax, and Secure
  over HTTPS.
- **CSRF.** A request with the session cookie and an unsafe method must
  carry the session's CSRF token in `X-CSRF-Token`, compared in constant
  time. API keys and bearer tokens aren't cookies and need none.
- **API keys** (`kdx_` and 43 random characters) are shown once and kept as
  SHA-256 hashes. They don't expire, and are revoked under Inställningar.
  The Android app gets a key of its own per device.
- **Two-step login.** Codes from an authenticator app (TOTP, each code
  usable once) or passkeys (WebAuthn). There are ten recovery codes, each
  usable once and kept hashed.
- **Short-lived steps** (a second step, a passkey challenge, an app's
  browser login, a tracker's OAuth state) expire after 5 minutes and work
  once. Sign-in links expire after 3 days.
- **OpenID Connect** uses the authorization code flow with PKCE, and checks
  the state, the nonce and the token's signature against the provider's
  keys.

## Secrets at rest

`SECRET_KEY` (or `SECRET_KEY_FILE`) encrypts the authenticator secrets and
the tracker tokens (kodex.core.sealed). Each kind gets a key derived for
it, and a copy of the database alone opens neither. Secrets stored before
`SECRET_KEY` was set are encrypted at the next start. **Fixed:** the
authenticator secrets used to be stored in the clear.

The key must not change. With another key, two-step login by app fails
(recovery codes and passkeys still work) and trackers must be connected
again. Keep it with the backups, not in them.

Every setting can come from a file (`NAME_FILE`), so secrets needn't sit in
`.env`.

## The server

- **Fetching for others' data (SSRF).** Cover images come from addresses in
  the metadata providers' answers. They are fetched only over http(s), and
  never from this machine or its network; redirects are checked too
  (kodex.core.outbound). **Fixed:** they used to be fetched from anywhere.
  The services an admin configures (Prowlarr, qBittorrent, ntfy, …) are
  meant to be on the local network. Their addresses come only from the
  environment, never from the web client.
- **Uploads** (admins, and scripts with the upload key) take only `.cbz`,
  `.cbr`, `.cb7`, `.epub` and `.pdf`, up to 500 MB, inside the library's
  folder. **Fixed:** an upload used to be read into memory whole; it is now
  written to disk a megabyte at a time.
- **Archives** are read with limits on the number of entries, the size of
  an entry and the compression ratio, against decompression bombs.
- **Headers.** Every response has `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin` and `X-Frame-Options: SAMEORIGIN`.
  **Fixed:** the API's responses lacked them. The web client's pages also
  have a Content-Security-Policy: scripts only from the server itself, and
  none from inside EPUBs.
- **The container** runs as an unprivileged user (`PUID`/`PGID`), with a
  read-only root filesystem and `no-new-privileges`.

## Left to the reverse proxy

- **TLS and HSTS.** Kodex doesn't know whether it is reached over HTTPS, so
  `Strict-Transport-Security` is the proxy's to send.
- **Rate limits** on anything but logins. Logins are limited by Kodex
  itself.
- `FORWARDED_ALLOW_IPS`: set it to the proxy's address, so the client
  addresses Kodex logs and throttles by are real.
