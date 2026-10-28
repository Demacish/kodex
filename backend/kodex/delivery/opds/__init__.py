"""The OPDS catalog for reading apps (ADR 0014): OPDS 1.2 in Atom with
Page Streaming (PSE 1.2) at ``/opds`` (``atom``), and OPDS 2.0 in JSON with
the Progression draft at ``/opds/v2`` (``v2``). Both list the same things
(``catalog``) and log in with HTTP Basic and an OPDS key as the password.

Reading progress comes back two ways: OPDS 2 clients send it to a book's
progression link, and PSE clients by the pages they fetch (``reports``).
Either goes into the reading journal, named after the key."""
