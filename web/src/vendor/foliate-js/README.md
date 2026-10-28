# foliate-js (vendored)

The EPUB reader's engine (ADR 0009): [foliate-js](https://github.com/johnfactotum/foliate-js)
by John Factotum, MIT (see LICENSE), copied from commit
`78914aef4466eb960965702401634c2cb348e9b1` (2026-05-01). The npm package
called `foliate-js` is not published by its author, so it is not used.

Copied as is: the modules the EPUB, MOBI/AZW3, FB2 and CBZ paths of
`view.js` load, and `vendor/zip.js` and `vendor/fflate.js`.

Changed:

- `pdf.js` is replaced by a stub, since Kodex reads PDFs with its own
  pdf.js reader; foliate-js's `vendor/pdfjs` is not copied.

To update: copy the same files from a newer commit, keep the stub, and
record the commit here and in NOTICE.
