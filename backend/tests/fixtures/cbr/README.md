# CBR test fixtures

Prebuilt RAR archives, so the test suite needs no RAR *creator* (the `rar`
CLI is proprietary). Reading them uses the same open source tools as
production (`rarfile` + `unar`/`bsdtar`).

| File | Format | Contents |
| --- | --- | --- |
| `comicinfo_number_2.rar5.cbr` | RAR5 | `0001.png` + `ComicInfo.xml` (Series SeriesA, Number 2) |
| `three_pages.rar5.cbr` | RAR5 | `0000.png`, `0001.png`, `0002.png` (text bytes "not-a-real-image-but-extraction-never-decodes-it NNNN") |
| `nested_pages.rar5.cbr` | RAR5 | `Book/0001.png`, `Book/0002.png` and an AppleDouble `Book/._0001.png` sidecar |
| `rar3_solid_from_rarfile.rar` | RAR3, solid | `stest1.txt`, `stest2.txt`; copied from the rarfile 4.5 test suite (ISC license, © Marko Kreen) |

The RAR5 files were created with `rar a -ep` (RAR 7); `rar` 7 can no
longer create RAR4 archives, hence the borrowed RAR3 sample.
