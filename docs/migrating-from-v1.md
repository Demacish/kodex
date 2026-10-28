# Migrating from Kodex v1

Kodex v2 adopts a v1 database as it is. The first start recognises it,
brings its schema up to date, and keeps every library, series, book,
collection, reading position and user. What changes is around it: there
is no Redis or Meilisearch any more, accounts no longer need an identity
provider, and the web client and the Android app are new.

## Before you start

- Keep v1 as it is until v2 runs; nothing below changes v1's database.
- Note v1's `.env`: the library paths, the metadata keys and, if you used
  Authentik, its issuer and client.

## 1. Dump v1's database

    docker exec <v1 db container> pg_dump -U <user> -d <db> -Fc > v1.dump

## 2. Set up v2 beside it

Follow [install.md](install.md) up to the first start, with:

- the same library paths (`LIBRARIES_HOST_PATH`, `SORTED_LIBRARY_HOST_PATH`);
- the metadata keys from v1 (`COMICVINE_API_KEY`, `METRON_*`, …);
- `PUID=0` and `PGID=0`, if v1 ran as root and your library files are
  only readable by root;
- for logins through Authentik, v1's `AUTHENTIK_*` settings, which still
  work, or the same values as `OIDC_*`.

## 3. Restore the dump into v2's database, then start

    docker compose up -d db
    docker compose cp v1.dump db:/tmp/v1.dump
    docker compose exec db pg_restore -U kodex -d kodex --no-owner /tmp/v1.dump
    docker compose up -d

The api's log shows `Adopting a v1 database`, then the migrations. Any
difference between the adopted schema and v2's models is logged as an
error. There should be none: write to the maintainer if there is.

The covers are made again from the books. v1's page cache isn't used, so
its volume can go.

## 4. Accounts

v1's users logged in through Authentik and have no password. Either:

- keep logging in through the provider: set `OIDC_*` (or the `AUTHENTIK_*`
  names), and register `<PUBLIC_APP_URL>/api/auth/oidc/callback` as a
  redirect URI with it; or
- give each person a password: make them a sign-in link, which works once
  within 3 days, and send it to them:

      docker compose exec api python -m kodex.core.auth.cli sign-in-link <username>

  They choose a password, and can add a passkey and two-step login under
  Inställningar.

## 5. Clients

- **The v1 Android app** keeps working: its `/api/backend/…` addresses are
  served by v2. Move to the new app when you can
  ([clients.md](clients.md#the-kodex-android-app)).
- **OPDS apps** with v1's OPDS token keep working until it is revoked; new
  keys are made under Inställningar.
- **KOReader** needs a KOReader key from Inställningar, and the address
  `https://<server>/kosync`.

## Going back

v1's database is untouched (v2 restored a copy of it). Stop v2 and start
v1 again. Positions read in v2 don't go back with you.
