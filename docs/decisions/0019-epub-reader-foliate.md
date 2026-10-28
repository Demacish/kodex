# 0019. foliate-js for EPUB on the web

Status: Accepted (2026-10-26, phase 3). Supersedes [0009](0009-epub-reader-web.md).

## Context

ADR 0009 left the web's EPUB reader to a spike between `@readium/navigator`
(ts-toolkit 2.x, BSD-3) and foliate-js (MIT). The spike used the
synthetic library's EPUBs and the reader route of the new web client.

| | `@readium/navigator` 2.14 | foliate-js (commit `78914ae`) |
| --- | --- | --- |
| Input | A Readium Web Publication manifest, the book's resources one by one, and a list of positions: the toolkit has no EPUB parser in JavaScript, so the server would need a streamer | The EPUB file as it is (`/books/{id}/file`), unpacked in the browser |
| Positions | Readium Locators, the same model as Readium Kotlin on Android | EPUB CFIs (what v1's epub.js stored, so saved positions keep working) and fractions of the book and of each section |
| Features | Reflowable and fixed layout, preferences, decorations, speech | The same, plus search in the book, footnotes, page lists, MOBI/AZW3 and FB2 |
| Size (unpacked) | about 2.5 MB with `@readium/shared` and its injectables | about 300 kB of modules, loaded only when an EPUB opens |
| Releases | Versioned npm releases from the Readium project | No releases; one maintainer. The npm package called `foliate-js` is published by a third party |
| Untrusted content | Same-origin frames that need scripting for its own injected code | Same-origin `blob:` frames; scripts in books must be blocked by the page's CSP (its README says so) |

## Decision

foliate-js, vendored at a pinned commit in `web/src/vendor/foliate-js`
(its PDF module replaced by a stub, since PDFs open in Kodex's pdf.js
reader). It needs no server work, keeps v1's positions, and does more.

The api sends the web client with a Content Security Policy that allows no
scripts except the app's own files (`script-src 'self'`), which the
book's `blob:` documents inherit, so a script in an EPUB doesn't run.

Positions stay CFIs on the web for now. Phase 4's position model stores a
Locator-like position (section href and progression next to the CFI) so
that the Android app (Readium Kotlin, phase 5) and the web share
positions without converting CFIs.

## Consequences

- Updating foliate-js is deliberate: copy the same files from a newer
  commit and record it in its README and in NOTICE.
- If foliate-js stops being maintained, Readium is the way out; it needs
  the server-side manifest and positions first.
- A playwright test proves that a script in a book is blocked.
