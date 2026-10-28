# Kodex – Omarbetningsplan

2026-10-25

## Syfte och användning

Planen är en komplett, självständig arbetsorder för en AI-agent (t.ex. Claude Code) som ska omarbeta Kodex: en självhostad bibliotekstjänst och läsare för serier, manga och e-böcker, bestående av en webbapp (Next.js-frontend + FastAPI-backend + PostgreSQL/Redis/Meilisearch) och en Android-app (Kotlin/Compose) som hämtar allt från samma backend.

Planen är skriven för att kunna delas publikt: den innehåller inga personliga uppgifter, inga servernamn, nycklar eller interna adresser. Allt instansspecifikt (domäner, inloggningsleverantör, API-nycklar) förutsätts ligga i miljövariabler och nämns bara som platshållare.

Så används planen av en agent:

1. Läs hela dokumentet innan något kodas; avsnitten Nuläge och Målarkitektur avgör vad som får röras.
2. Arbeta fas för fas enligt Genomförandeplanen; varje fas har egna uppgifter och ett avslutande kriterium.
3. Verifiera varje uppgift mot Acceptanskriterierna innan nästa påbörjas; befintliga tester ska förbli gröna (backend `pytest`, frontend `npm run typecheck && npm run build`; Android‑tester gäller från fas 5 med `./gradlew test`).
4. Fatta inga beslut som kräver hemligheter, extern kontoåtkomst eller destruktiva databasändringar utan att stanna och fråga.
5. Metadata‑matchning för serier är det prioriterade området; vid resurskonflikt går det före nya läsarfunktioner. Ordlistan nedan är bindande: termerna används exakt så i kod, API och UI.

Språk: det här är masterdokumentet på svenska. Den publika versionen (README, docs, ärenden) skrivs på engelska; identifierare i kod är redan engelska. Licens väljs i fas 0 och styr vilka beroenden som får användas (se Målarkitektur).

### Ordlista

Ordet "volym" betyder tre olika saker i serievärlden och är den vanligaste källan till fel kod. Planen använder termerna nedan konsekvent.

| Term | Betydelse i planen |
| --- | --- |
| Serie | Kodex gruppering av böcker som hör ihop. Motsvarar Comic Vines *volume*, Metrons *series*, AniLists *Media* |
| Run | En Comic Vine‑volym, dvs. en serieomgång med startår (Batman 1940, 2011, 2016). Kallas aldrig "volym" i planen |
| Volymnummer | ComicInfo `<Volume>`: seriens volymnummer, eller startår enligt Mylar/Komga‑konvention (värde ≥ 1900 tolkas som år) |
| Volym | Enbart för manga och samlade utgåvor: en fysisk bok (tankōbon, TPB, omnibus) som innehåller flera kapitel eller nummer |
| Nummer | Enskilt serietidningsnummer (*issue*); kan vara `0`, `-1`, `1.5`, `1.MU`, `1000` |
| Kapitel | Manga‑kapitel (*chapter*); ett kapitel kan sakna volym |
| Format | `issue`, `collected` (TPB/omnibus/deluxe/hardcover), `annual`, `special`, `one_shot`, `chapter`, `volume` |
| Bok | Alltid exakt en fil (CBZ/CBR/EPUB/PDF/bildmapp). Volym‑ och kapitelnummer är attribut på boken |
| Leverantör | Extern metadatakälla (Comic Vine, Metron, MangaDex, MangaUpdates, AniList, Open Library, Google Books, Hardcover) |
| Externt id | Leverantörens id för en serie eller bok; en serie kan ha flera (MangaDex + AniList + MAL + MangaUpdates) |
| Alias | Lärd koppling normaliserad titel (+ år) → leverantör + externt id, positiv eller negativ |
| Konfidens | Matchningspoäng 0–1 plus marginal till näst bästa kandidat; beslut `auto`, `review` eller `none` |
| Lås | Fält eller serie som manuellt satts och aldrig skrivs över av automatik |
| Granskningskö | Lista över beslut som kräver en människa: osäkra matchningar, dubbletter, omgrupperingar, sidflaggor |

## Nuläge

Kodex är redan funktionsrikt (webben har fler funktioner än de flesta jämförbara projekt) men matchningsmotorn är den svagaste delen: serier grupperas enbart på mappnamn, kandidater jämförs bara på titel, årtal ignoreras och det finns inget konfidensbegrepp eller granskningskö. Android-appen är omfattande men aldrig byggd i CI, och delar bugg­ar i offline- och synkflödet.

### Webb och backend

| Område | Status i dag |
| --- | --- |
| Stack | Next.js 14 + React 18 + NextAuth 4; FastAPI + SQLAlchemy 2 + PostgreSQL 16; Redis/RQ (6 köer, en enda worker); Meilisearch 1.10; OIDC-inloggning med gruppkrav |
| Format | EPUB, PDF, CBZ, CBR (unar/unrar), bildmappar |
| Bibliotekstyper | COMICS, MANGA, EBOOKS, MIXED; styr metadata‑leverantör |
| Seriegruppering | Första mappnivån under biblioteket = serie, mappnamnet rått som titel; `ComicInfo <Series>` läses men används inte; en mapp per nummer ger en serie per nummer tills berikning slår ihop dem via Comic Vine‑volym‑id |
| Filnamnsparsning | Kräver 3–4-siffrigt nummer (`Batman 012`), `vNN` lagras i samma fält som nummer; manga bara `volume N`; `[Grupp] Titel - c012 (v03)` går sönder |
| Metadataleverantörer | Comic Vine (volym + nummer), Metron (story arcs), AniList, Open Library, Google Books, CBL‑läslistor, League of Comic Geeks |
| Kandidatval | Titel exakt → delsträng → `difflib` ≥ 0,5; lika‑vikt = flest nummer; år/förlag/numret‑finns‑kontroll används aldrig; ingen cache, ingen konfidens, ingen granskningskö |
| Manuell matchning | Per bok: sök → volym → nummer (max 100, ingen paginering) → fält‑diff → apply låser som MANUAL; ingen upplåsning; ingen seriebred matchning |
| Skrivning till fil | ComicInfo.xml bara i sorteringsflödet (Series/Number/Year/Manga, endast CBZ); berikad data skrivs aldrig tillbaka; `series.json`‑export per serie |
| Läsare | Bildläsare (sid/scroll/guided, RTL, uppslag, zoom, ljus/kontrast, sidflaggning), EPUB (epub.js), PDF (pdf.js); läsframsteg med "längst vinner"; KoSync‑server; OPDS 1.2 (otestad mot riktiga klienter) |
| Samlingar | Manuella, smarta (Meilisearch‑filter, JSON‑regler) och story arc (CBL/Metron/Comic Vine) med saknade‑nummer‑vy |
| Övrigt | Följda serier med veckovis släppkoll, släppkalender, AI‑rekommendationer/‑samlingar (OpenAI/Claude/Gemini), önskemål + nedladdningsautomation (Prowlarr, qBittorrent, SABnzbd, Mylar3, Kapowarr m.fl.), Send‑to‑Kindle, Telegram/Discord/ntfy, CSV‑import, peer‑federation, sorteringsassistent, panelidentifiering (OpenCV, avstängd) |
| Tester | \~507 backend‑tester (inga nätverkstester; `best_match` har 1 test); frontend saknar tester helt |
| Teknisk skuld | Ingen Alembic (handgjord `migrations.py` + manuella ALTER TABLE); Next 14/NextAuth 4 blockerar uppgraderingar; python‑jose ounderhållen; in‑process‑ratelimiter och schemaläggartråd fungerar inte med flera replikor; `tasks.py` (1 000 rader) och `ImageReader.tsx` (1 100 rader); hårdkodad svenska; mycket "ej verifierat mot riktig tjänst" |

### Android

| Område | Status i dag |
| --- | --- |
| Stack | Kotlin 2.2, Compose (BOM 2024.09), Material 3 Adaptive, Hilt, Room v5, Retrofit/Moshi, Coil 2, AppAuth (OIDC/PKCE), Readium 3.0.3, AOSP PdfRenderer + pdfium för outline, WorkManager, Glance‑widget; minSdk 26 |
| Byggstatus | \~18 800 rader Kotlin, 161 enhetstester + 45 instrumenterade — men aldrig kompilerad eller körd i CI |
| Flerserver | Serverlista med prioritet, automatisk failover, sammanslagna serier över servrar (egen `SeriesMatcher`: normaliserad titel + år + bibliotekstyp, volymer via ISBN/nummer), federerad sök |
| Skärmar | Hem, Bibliotek (1–3 paneler), Serie, Bokdetalj, Sök, Samlingar (+ skapa/redigera med ALLA/NÅGOT), Önskemål, Nedladdningar, Inställningar (\~1 450 rader) |
| Bildläsare | PAGE/SPREAD (bara platta)/SCROLL; RTL; tap‑zoner i tredjedelar; pinch 1–5× (ej i scroll/spread); ljusstyrka (sparas inte); volymknappar; e‑ink‑läge; guided view (heuristik, minnesläcka) |
| EPUB/PDF | Readium med TOC, textstorlek, tema, TTS; PDF sid/scroll med LRU‑cache och outline |
| Offline | Hel fil per bok via WorkManager; CBZ extraheras vid behov; ingen katalog‑cache offline |
| Synk | 800 ms debounce → PUT; kö i Room vid fel; "längst vinner" utan tidsstämplar |
| Kända buggar | Nedladdad CBR öppnas via `ZipFile` → tyst nätverksfallback; avbruten temp‑fil återanvänds som komplett; nedladdning utan constraints/foreground; `runBlocking` i interceptor; bearer‑token i debug‑logg; utloggning utan revokering |
| Saknas | Webtoon‑läge med zoom/marginaler, färgfilter, kantbeskärning, förladdning, dubbeltryck‑zoom, nästa‑nummer‑kedja, konfigurerbara tap‑zoner, OPDS‑klient, Android TV, lokalisering, paging |

### Styrkor att bevara

- Bred funktionsyta: story arcs, släppkalender, önskemål→nedladdning, Kindle, KoSync, federation.
- Tydlig MANUAL‑lås‑semantik och fält‑för‑fält‑diff vid manuell matchning.
- Separata bibliotekstyper som styr leverantör och läsriktning.
- Stor testsvit i backend att bygga vidare på.

## Jämförelse: server och webb

Kodex ligger redan före de flesta på funktionsbredd (story arcs, släppkalender, önskemål, Kindle, federation) men efter på det som gör Komga och Kavita pålitliga i vardagen: robust filnamnsparsning, en matchningsmotor med konfidens och granskning, snabb skanning, migrationer, Kobo‑sync, OPDS‑PSE och ett API‑kontrakt som klienter kan lita på. Uppgifterna nedan är hämtade från projektens release‑sidor och dokumentation den 25 oktober 2026.

| Projekt | Senaste version | Metadata och matchning | Läsare | Övrigt att notera |
| --- | --- | --- | --- | --- |
| [Komga](https://github.com/gotson/komga/releases) | 1.29.1 (okt 2026); nytt webb‑UI i beta sedan 1.26 | Enbart inbäddat: ComicInfo (inkl. `SeriesGroup`→samlingar, `StoryArc`/`AlternateSeries`→läslistor), EPUB OPF, Mylar `series.json`, ISBN från streckkoder på första/sista sidorna; redigerade fält låses automatiskt; extern matchning via Komf | DIVINA‑läsare: LTR/RTL/vertikal/webtoon, dubbelsida (första/sista/liggande alltid ensam), skalning, miniatyrer; EPUB med fonter, kolumner, marginaler | OPDS 1.2 + PSE 1.2 **och** OPDS 2.0 med testad klienttabell; Kobo‑sync (EPUB, KEPUB i farten, butiksproxy); KOReader‑sync; CBL‑import; dubbletter av filer och sidor; auto CBR→CBZ; RAR5 i ren Java; REST v2 |
| [Kavita](https://github.com/Kareadita/Kavita/releases) | 0.9.1.4 (sep 2026); Kobo‑sync aviserad för 0.9.2 | Stark filnamnsparser (serie/volym/kapitel/special, CJK/koreanska/ryska markörer); ComicInfo `Series`/`Volume`/`Number`/`Format`/`GTIN`/`Web`; betald Kavita+ (Hardcover, ComicBookRoundup, MangaBaka) som auto‑väljer bara en ensam 100 %‑träff eller en ensam ≥ 90 %, annars manuell matchningsdialog med fältvisa skrivkontroller | LTR/RTL, dubbelsida med "offset by 1", bilddelning, skalning, läsprofiler per enhet, fortsätt in i nästa kapitel; journalbaserat läsframsteg med omläsning (0.8.9); EPUB med anteckningar | OPDS + PSE; KOReader‑sync för arkiv/PDF/EPUB; CBL‑import med stegvis matchning (id från `Notes`/`Web` → normaliserat namn + år → artikel‑ och editionsstripp); flertrådad skanner (användarrapport 141 000 filer på 3 h); ingen dubblettdetektering; `x-api-key`‑API |
| [Komf](https://github.com/Snd-R/komf/releases) | 2.1.0 (sep 2026) | 14 leverantörer i prioritetsordning (MangaUpdates, MAL, AniList, MangaDex, Bangumi, Comic Vine, MangaBaka, förlagssajter …); första träff som passerar en längdskalad Levenshtein (≤ 1/2/3 redigeringar) vinner; Comic Vine‑provider kräver samma startår och jämför första bokens omslag med aHash; aggregeringsläge fyller luckor; `[cv-ID]` i namn läses direkt | — | Skriver serie/bok‑metadata, omslag och ComicInfo.xml; manuell matchning via webbläsartillägg i Komgas/Kavitas UI och `POST /identify`; eventlyssnare matchar nya serier automatiskt |
| [Calibre‑Web Automated](https://github.com/crocodilestick/Calibre-Web-Automated/releases) | 4.0.8 (sep 2026) | Google Books, Internet Archive, DNB, Comic Vine, Douban, ISBNdb, Hardcover, Kobo, LitRes; auto‑hämtning vid ingest utan bekräftelsesteg; skriver tillbaka till filerna | Standardläsare; ny webbläsare på roadmap | OPDS, Kobo‑sync, KOSync; dubbletthantering med fuzzy‑matchning och sammanslagning; e‑boksfokus |
| [Suwayomi](https://github.com/Suwayomi/Suwayomi-Server/releases) | 2.4.x (sep 2026) | Mihon‑källor och trackers; lokal källa med `details.json` | Webb‑UI med enkel/dubbel/kontinuerlig/webtoon, filter, tangentbindningar | OPDS 1.2 + PSE; GraphQL; inriktat på online‑källor |
| [BookLore → BookOrbit](https://github.com/bookorbit/bookorbit) | BookLore 2.4.0 i underhållsläge; BookOrbit 3.5.0 (okt 2026, AGPL + tilläggsvillkor) | 14 leverantörer (Google Books, Open Library, Amazon, Goodreads, Hardcover, Comic Vine …); "BookDrop": bevakad mapp → berikas → granskningskö | EPUB/PDF/serier i webbläsaren med anteckningar | Trevägssynk Kobo + KOReader + webb med auto‑KEPUB; OPDS; Send‑to‑Kindle; iOS‑app |
| [Stump](https://github.com/stumpapp/stump/releases) | 0.1.11 (okt 2026, beta) | ComicInfo‑intag; extern hämtning "extremt experimentell" | Readium‑kompatibel EPUB‑läsare; Expo‑mobilapp | Rust/Axum; OPDS 1.2 + PSE och 2.0 med progression‑API; Kobo‑ och KOReader‑sync; smarta listor; läsutmaningar |
| Audiobookshelf, Librum | 2.37 / 0.12 | Begränsat e‑boksstöd; dokumentationen hänvisar till Kavita/Komga för serier | — | Inte relevanta som förebild för serier |

### Vad som sticker ut i jämförelsen

- Alla ledande projekt separerar **matchningstjänst** (Komf, Kavita+) från **bibliotekskärna**; Kodex bakar in båda, vilket är en fördel om motorn görs bra och exponeras med samma "identify by ID"‑API som Komf.
- **Kavita** tar ComicInfo `Series`/`Volume`/`Number` som sanning före mappnamn; **Komga** gör tvärtom (en mapp = en serie, vilket gör den förutsägbar); Kodex grupperar på mapp men läser inte ComicInfo för gruppering alls. Båda strategierna behövs som val per bibliotek.
- Kavitas **journal‑modell för läsframsteg** och **auto‑acceptans bara vid en ensam säker kandidat** är de två mönster som direkt löser Kodex största svagheter.
- **Kobo‑sync med KEPUB i farten** och **OPDS‑PSE** finns hos Komga, Stump, BookLore/BookOrbit och Calibre‑Web; Kavita får Kobo i 0.9.2. Kodex har bara OPDS 1.2 utan PSE och KoSync.
- **Granskningskö vid import** finns hos BookLore/BookOrbit (BookDrop) och Komga; Kodex har det bara för sortering, inte för matchning.
- Komgas **dubblettdetektering av filer och sidor**, **automatisk CBR→CBZ** och Kavitas **flertrådade skanner** är konkreta prestanda‑ och kvalitetsmål.

Sources: [Komga releases](https://github.com/gotson/komga/releases) · [Komga OPDS](https://komga.org/docs/guides/opds) · [Komga Kobo](https://komga.org/docs/guides/kobo) · [Komga dubbletter](https://komga.org/docs/guides/duplicate-pages) · [Kavita releases](https://github.com/Kareadita/Kavita/releases) · [Kavita+ metadata](https://wiki.kavitareader.com/kavita+/metadata/) · [Kavita CBL‑import](https://wiki.kavitareader.com/guides/features/cbl-import/) · [Kavita v0.8.9](https://opencollective.com/kavita/updates/v0-8-9-new-stats-pages-journal-style-reading-50x-faster-scanner-and-so-much-more) · [Komf](https://github.com/Snd-R/komf) · [Calibre‑Web Automated](https://github.com/crocodilestick/Calibre-Web-Automated) · [Suwayomi](https://github.com/Suwayomi/Suwayomi-Server) · [BookOrbit](https://github.com/bookorbit/bookorbit) · [Stump](https://github.com/stumpapp/stump/releases)

## Jämförelse: Android‑appar

Måttstocken för en serie‑/mangaläsare på Android är Mihon‑familjen (Mihon, Komikku, TachiyomiSY) för läsaren och Komelia för serverkopplingen; för e‑böcker är KOReader och Moon+ Reader referensen. Kodex Android har redan den ovanliga flerserver‑modellen men ligger efter på läsarkärnan. Versioner nedan är från projektens release‑sidor den 25 oktober 2026.

| App | Version | Läsarkärna | Bibliotek och offline | Vad som är värt att notera |
| --- | --- | --- | --- | --- |
| [Mihon](https://mihon.app/changelogs/) | 0.21.2 (okt 2026) | Lägen: Paged RTL/LTR/vertikal, Long strip, Long strip med mellanrum; per‑serie‑override; rotation fri/låst; bakgrund svart/grå/vit/auto; tap‑zoner Default/L‑shaped/Kindle‑ish/Edge/Right‑Left/Av med invertering, separat för pager och webtoon; volymknappar; beskär kanter (separat per läge); dela breda sidor + invertera placering; rotera breda sidor; skalning Fit screen/Stretch/Fit width/Fit height/Original/Smart fit; zoomstart auto/vänster/höger/mitten; auto‑zoom på breda bilder; sidmarginal i long strip; dubbeltryck‑zoom; filter: ljusstyrka, RGBA‑färgfilter med blandningslägen, gråskala, invertering; e‑ink‑blink vid sidbyte; "keep screen on" | Kategorier; schemalagd uppdatering med smarta hoppöver‑regler; trackers MangaBaka, MAL, AniList, Kitsu, MangaUpdates, Shikimori, Bangumi, Hikka, Comick samt "enhanced" Komga/Kavita/Suwayomi med tvåvägssynk; lokal källa `local/<Serie>/<kapitel>` med `details.json` och ComicInfo; "load ahead only on Wi‑Fi"; ingen OPDS‑klient | Dubbelsida är inte i release än (finns i `main` som `DualPageView` NEVER/ALWAYS/WIDE); ingen användarsynlig förladdningsräknare |
| Komikku / TachiyomiSY | 1.14.1 / 1.13.2 (jul 2026) | Mihon plus automatisk webtoon‑detektering, smart bakgrund, autoscroll, konfigurerbar förladdning, bildcache‑storlek | Feed för alla källor, sammanslagning av poster, tracker‑baserad dubblettdetektering, källmigrering | Power‑users; SY slopade Android 6–7 |
| [Komelia](https://github.com/Snd-R/Komelia/releases) (Komga‑klient) | 0.20.0 (sep 2026) | Paged, kontinuerlig, dubbelsida med och utan omslag + offset; riktning från seriemetadata; färgkurvor/nivåer; nedsampling Lanczos/Mitchell; ONNX‑uppskalning på desktop; panel‑för‑panel via RF‑DETR‑modell (arm64/desktop); volymknappar | Offline‑läge med serie‑/boknedladdning (4 parallella, RAR); Komf‑inställningar och auto‑identifiera inbyggt | Kotlin Multiplatform: Android **och** JVM‑desktop (deb/AppImage/msi) från samma kodbas — beviset för Kodex KMP‑val |
| [KOReader](https://github.com/koreader/koreader) | 2026.07 (aug 2026) | Fixed‑layout: beskärning none/auto/semi/manuell, zoom till sida/innehåll/kolumner/rader, 8 läsriktningar, sida/kontinuerlig, kontrast/mättnad/vit‑tröskel/dithering, invertering; ingen dubbelsida | OPDS‑klient med PSE (fungerar mot Komga/Kavita), OPDS 2.0 basstöd nytt, KOSync med kö och retry, Kobo v5 | Standard på e‑ink; Kodex KoSync‑server gör den till en gratis andra klient |
| Perfect Viewer | 5.0.4 (mar 2026) | Auto enkel/dubbel/efter orientering; LTR/RTL; sida, vertikal scroll, horisontell scroll; Lanczos3; ljus/kontrast/gamma; auto‑beskärning av vita kanter | CIFS/SMB, FTP, SFTP, OPDS | Klassisk referens för bildkvalitet och snabbhet |
| Moon+ Reader / Librera | 10.8 (okt 2026) / 10.0 (okt 2026) | Starka textläsare: teman, autoscroll, TTS, dubbelsida i landskap; Librera byter till foliate‑js‑WebView och PDFium | OPDS 1.2 (utan OpenSearch/PSE mot Komga), WebDAV/Dropbox‑synk | Typografi och TTS |
| CDisplayEx | aug 2026 | cbr/cbz/pdf; kontinuerligt horisontellt/vertikalt; avancerad skalning | Komga/Kavita via REST i premium: virtuella mappar, progress‑synk, offline per bok | Visar hur en tredjepartsklient konsumerar ett server‑API |

### Luckor i Kodex Android jämfört med referensen

- Ingen riktig long‑strip‑/kontinuerlig‑vy med zoom och sidmarginaler; scroll‑läget saknar zoom helt.
- Uppslag bara på platta; ingen manuell enkel/dubbel‑växling, ingen "utan omslag"/offset‑toggle (Komelia och Kavita har båda).
- Inga bildfilter, ingen kantbeskärning, ingen delning av breda sidor, ingen orienteringslåsning, ingen "keep screen on".
- Ingen förladdning, ingen dubbeltryck‑zoom, oklampad panorering, fasta tap‑zoner utan layoutval.
- Ingen kedja till nästa nummer vid bokslut, ingen offline‑katalog, inga trackers.
- Ingen lokalisering, ingen paging, ingen CI — appen har aldrig byggts.

Sources: [Mihon changelogs](https://mihon.app/changelogs/) · [Mihon ReaderPreferences.kt](https://github.com/mihonapp/mihon/blob/main/app/src/main/java/eu/kanade/tachiyomi/ui/reader/setting/ReaderPreferences.kt) · [Mihon tracking](https://mihon.app/docs/guides/tracking) · [Komikku](https://github.com/komikku-app/komikku) · [TachiyomiSY](https://github.com/jobobby04/TachiyomiSY) · [Komelia releases](https://github.com/Snd-R/Komelia/releases) · [KOReader koptoptions.lua](https://github.com/koreader/koreader/blob/master/frontend/ui/data/koptoptions.lua) · [Librera](https://github.com/foobnix/LibreraReader) · [Komga CDisplayEx‑guide](https://komga.org/docs/guides/cdisplayex)

## Vad vi bör låna

Det här är de mönster som är värda att ta över rakt av, med källa och var de landar i Kodex. Allt är öppen källkod (MIT/Apache/GPL); vid portering av kod ska licensen respekteras, i övrigt lånas idéer.

| Lån | Från | Vad det ger Kodex |
| --- | --- | --- |
| Omslagsjämförelse med perceptuell hash som sista steg i matchningen | ComicTagger (`issueidentifier.py`): aHash/pHash, Hamming‑avstånd, accepteras under 16 i Hamming‑avstånd (≤ 8 = stark träff), 16 eller mer avvisas, alternativomslag kräver < 12, kandidater inom bästa + 4 behålls; trösklarna är kalibrerade för aHash | Löser "Batman #12 — vilken volym?" där titel och år inte räcker |
| Serie‑filter på år, förlag och TPB‑status före nummeruppslag | ComicTagger: serie släpps om startår > bokens år + 1; förlags‑svartlista; TPB vs nummer skiljs (nyckelord, format, > 100 sidor) | Tar bort de vanligaste felträffarna innan de kostar API‑anrop |
| Filnamnskonventioner och tolerant tokenisering | ComicTagger (`Serie v2 #012 (of 12) (2016)`), Kavita (serie/volym/kapitel/special), Mylar3/Kapowarr (scene‑namn med `(digital) (Grupp)`) | En parser som klarar både serie‑ och manga‑namngivning |
| ComicInfo.xml som primär sanning, filnamn som fallback | Kavita (Komga: mapp = serie som förutsägbart alternativ) | Rätt gruppering direkt för redan taggade samlingar |
| Leverantörer i prioritetsordning + aggregeringsläge som fyller luckor | Komf | Manga: MangaUpdates/MangaDex för namn, AniList för omslag och staff, Bangumi för CJK |
| "Identifiera med ID"‑endpoint och seriebred matchning | Komf | Manuell matchning på serienivå i stället för bok för bok |
| Granskningskö för nya filer med föreslagen match | BookLore (BookDrop), Komga import | Nollar risken för tyst felmatchning |
| Journalbaserat läsframsteg med omläsning | Kavita (sedan v0.8.9, jan 2026) | Ersätter "längst vinner" i både webb och Android |
| Flertrådad skanner, omslag i bakgrunden, förloppsindikator | Kavita (sedan v0.8.9; 0.9.1 förbättrade stora kataloger) | Skanning av stora bibliotek på minuter i stället för timmar |
| Dubblettdetektering av filer och sidor | Komga | Städar bibliotek som vuxit organiskt |
| OPDS 2 + Kobo‑sync | Komga, Kavita, BookLore | Fler gratisklienter; e‑bokläsare direkt mot servern |
| Läsarkärna: lägen, filter, beskärning, förladdning, uppslag med shift | Mihon | Android‑läsare i nivå med referensen |
| Trackers (AniList/MAL/MangaUpdates) som frivillig synk | Mihon | Följd status i användarens egna konton |
| Delad KMP‑klientmodul | Komelia | Desktop/iOS senare utan att skriva om API‑lager och synk |
| Explicit viktad poängsättning med omslag som signal och ett billigt lokalt filter före externa anrop | comicbox (motorn i Codex): serie 0,30, nummer 0,25, år 0,10, förlag 0,10, sidor 0,05, omslag 0,20; auto 0,95, marginal 0,10; pHash kompatibel med imagehash; fuzz.ratio ≥ 0,7 innan Comic Vine anropas | Referensimplementation för score.py; de enda publika, dokumenterade vikterna |
| Förberäknade omslagshashar och id‑bryggor från leverantören | Metron: cover\_hash (pHash) samt cv\_id och gcd\_id på serie och nummer; MangaDex links; Kitsu mappings; AniList idMal | Omslagsjämförelse utan nedladdning; en träff hos en leverantör ger id hos de andra |
| Id först, sök sist | Mylar3 cvinfo och series.json, Kapowarr \[cv-ID\] i mappnamn, Kavita+ som bara auto‑accepterar en ensam kandidat med poäng 1,0 eller en ensam över 0,9 | Noll sökningar för bibliotek som redan är taggade; försiktig enkandidatsregel |

Sources: [ComicTagger issueidentifier.py](https://github.com/comictagger/comictagger/blob/develop/comictaggerlib/issueidentifier.py) · [ComicTagger UserGuide](https://github.com/comictagger/comictagger/wiki/UserGuide) · [comicbox](https://github.com/ajslater/comicbox) · [Komf](https://github.com/Snd-R/komf) · [Kavita v0.8.9](https://opencollective.com/kavita/updates/v0-8-9-new-stats-pages-journal-style-reading-50x-faster-scanner-and-so-much-more) · [Komga](https://github.com/gotson/komga) · [BookLore](https://github.com/booklore-app/booklore) · [Mihon](https://github.com/mihonapp/mihon) · [Mylar3 series.json](https://github.com/mylar3/mylar3/wiki/series.json-examples) · [Kapowarr](https://github.com/Casvt/Kapowarr) · [Metron via mokkari](https://mokkari.readthedocs.io/)

## Metadata och matchning för serier

Målet är att en nyinskannad fil hamnar i rätt serie, kopplad till rätt extern run och rätt nummer, utan handpåläggning i de flesta fall, och att resten hamnar i en granskningskö med ett bra förslag i stället för en tyst felmatch. Hellre fler i kön än en enda felmatch som ingen ser: kravet är precision ≥ 0,98 på automatiska beslut. Motorn byggs som ett eget paket (`matching/`) med en tydlig pipeline, konfiguration i `matching.toml`, egen testkorpus och mätbar precision per stratum.

### Principer

1. **Inbäddade id:n och metadata är sanning, filnamn är fallback.** Ordning: externa id:n i filen eller mappen (ComicInfo `Web`/`Notes` — Comic Vine‑URL:er där `4050-` är serie och `4000-` är nummer, `ComicVine [CVDB…]`, `urn:comicvine:series:…`, MetronTagger `[issue_id:…]`; MetronInfo.xml `<IDS>`; `GTIN`; EPUB ISBN; Calibre `metadata.opf`; Mylar3 `cvinfo`; `[cv-123]`/`cv:123`/`4050-123` i mapp‑ eller filnamn) → ComicInfo‑fält (`Series`, `Volume`, `Number`, `Count`, `Year`, `Format`, `Manga`, `LanguageISO`, `Publisher`, `LocalizedSeries`, `SeriesSort`) → `series.json` → OPF/PDF‑egenskaper → mapp‑ och filnamn.
2. **Serien matchas en gång, numren många.** Seriens identitet (leverantör + run‑id) bestäms på serienivå med evidens från alla dess böcker; varje bok löser sedan sitt nummer inom runnen. Manuell matchning sker därför primärt på serie.
3. **Konfidens är ett tal, inte en gissning.** Varje kandidat får en poäng 0–1 och en marginal till tvåan; beslutet är `auto`, `review` eller `none`. Saknade signaler är neutrala, aldrig negativa.
4. **Inget sker tyst.** Omgruppering, delning, dubblettmarkering och auto‑beslut loggas och kan återställas; omgruppering av en serie som har samlingar eller läsframsteg går alltid via kön.
5. **Inget API‑anrop utan cache och utan budget.** Alla leverantörssvar cachas i databasen med TTL; rate limits läses från svarens headers; ett billigt lokalt titelfilter körs innan en enda extern sökning (Comic Vines 200 anrop per resurs och timme är den knappaste resursen).
6. **Korrigeringar lär motorn.** Varje manuellt beslut sparas som positivt eller negativt alias och används före nätverkssök nästa gång, men kontrolleras fortfarande mot år och bibliotek.

### Grupperingsstrategi per bibliotek

| Strategi | Beteende | När |
| --- | --- | --- |
| `folder` (Komga‑stil) | En mapp = en serie, alltid; metadata påverkar bara fält | Välordnade bibliotek där användaren redan sorterat; förutsägbart |
| `metadata` (Kavita‑stil, standard) | ComicInfo `Series`+`Volume` grupperar; mapp och filnamn när metadata saknas; omgrupperingsförslag till kön | Blandade och scene‑namngivna bibliotek |
| `comicvine` (Mylar3/Kapowarr‑layout) | Mappen `Serie (År)` är en run; `cvinfo` eller `[cv-ID]` binder alla filer i mappen till run‑id:t utan sökning | Bibliotek som fylls av Mylar3 eller Kapowarr |

### Pipeline

1. **Id‑upplösning** (`matching/identify.py`): hittas ett externt id i fil, ComicInfo, MetronInfo, `cvinfo` eller mapp‑/filnamn slås det upp direkt ("identify by ID") och steg 5–7 hoppas över; ett Comic Vine‑nummer‑id ger både run och nummer, Metron‑id ger `cv_id` och `gcd_id` på köpet, ISBN ger e‑boksutgåva.
2. **Tokenisering av namn** (`matching/parse.py`): ger `series`, `volume`, `issue`, `issue_count`, `year`, `series_year`, `format`, `chapter`, `chapter_end`, `scan_group`, `language`, `publisher`, `edition`, `extra_tags`. Regler: `#` vinner; text i `[]`/`()`/`{}` är taggar (utom sammanvuxna parenteser som `rent-a-(really shy)-girlfriend`); text efter `--`/`__` ignoreras; `(of N)` ger `issue_count`; en andra `vol|ch`‑markör klipps bort om den inte är ett intervall; `vNN`/`Vol.`/`Volume`/`Tome`/`T3`/`S01`/`第3巻`/`제3권`/`Том 3` ger `volume`, aldrig `issue`; `c012`, `ch. 12`, `c010-012`, `Episode 12`, `第12话`, `Глава 12` ger kapitel; `153b` → `153.5`; en `(YYYY)` direkt efter serienamnet är `series_year`, en efter numret är `year`; `Annual`, `Special`, `One-Shot`, `TPB`, `Omnibus`, `HC`, `SP01` och ComicInfo `Format` (Kavitas lista: Special, Annual, One‑Shot, TPB, Omnibus, Compendium, Absolute, Graphic Novel, FCBD, Giant Size …) ger `format`. Tvetydiga mönster (`Batman 2021 Annual`, `Action Comics 1000`, `2000 AD 2350`, `Batman Beyond 2.0 001`) hanteras av en prioritetstabell i koden med testfall; det som inte går att avgöra märks `ambiguous` och går till kön. Golden‑korpusen seedas med Kavitas och ComicTaggers publika testfall.
3. **Normalisering** (`matching/normalize.py`): NFKD, diakritik bort (`æ→ae`, `ø→o`, `ß→ss`), casefold, `&`→`and`, inledande artiklar bort (`the`, `a`, `an`, `le`, `la`, `der`, `die`, `das`, `den`, `det`), stoppord som ComicTagger (`of`, `or`, `is`, `issue`), skiljetecken → mellanslag, **CJK behålls** (dagens alfanumeriska regex nollar japanska titlar). Romerska siffror konverteras bara som avslutande token eller efter `Vol`/`Book`/`Part` (så att `X-Men`, `Malcolm X` och `V for Vendetta` lämnas ifred). Spara `norm_ascii` och `norm_unicode`.
4. **Lokal gruppering** (`matching/group.py`): nyckel `(library, norm_title, series_year?, format_family)`; serier får persistent id; en mapp per nummer ger en serie direkt. Ändrad nyckel efter omdöpning ger ett omgrupperingsförslag, aldrig en tyst flytt. Åtgärder: slå ihop, dela (en `Batman`‑mapp med 1940/2011/2016‑runs), flytta bok. `Specials/`‑undermapp tillhör föräldraserien.
5. **Alias‑uppslag före nätverk**: `SeriesAlias` positiva träffar ger kandidaten direkt men poängsätts ändå (år, bibliotek); negativa alias tar bort kandidater. Alias seedas från leverantörernas egna synonymer (`aliases`, `altTitles`, `synonyms`, `associated`).
6. **Kandidatsök** (`matching/providers/*`), styrt av bibliotekstyp, `format_family` och parserresultat; i `MIXED` avgör format och inbäddad metadata per bok. Före varje extern sökning körs ett billigt lokalt filter (`rapidfuzz.fuzz.ratio` ≥ 0,7 mot cachade kandidater) som i comicbox, för att spara budget.
   - Serier: Comic Vine (`search?resources=volume` med `field_list=id,name,start_year,publisher,count_of_issues,aliases,image`; filtrera på `start_year` ≤ bokens år + 1 och förlag; max 100 per sida), Metron (seriesök med `name`/`year_began`; `cv_id` och `gcd_id` på serie och nummer; `cover_hash` förberäknad och imagehash‑kompatibel, så omslag behöver inte laddas ner), GCD‑dump (CC BY 4.0, ingen API) som offline‑fallback senare.
   - Manga: MangaDex (`GET /manga?title=` → `title`, alla `altTitles`, `links` med nycklarna `al`, `mal`, `mu`, `kt`, `ap`, `bw`, `nu`, `amz`, `ebj`, `cdj`, `raw`, `engtl`; `originalLanguage`, `publicationDemographic`, `contentRating`), MangaUpdates v1 (`POST /v1/series/search`; `associated` namn, bäst på scanlation‑namn), AniList (GraphQL `Media(type: MANGA)`: `title.romaji/english/native`, `synonyms`, `idMal`, `format` MANGA/NOVEL/ONE\_SHOT, `countryOfOrigin`, `status`, `staff`, `coverImage`), Kitsu `mappings` och Bangumi som extra id‑bryggor och CJK‑originaltitlar.
   - E‑böcker: ISBN först (Open Library `/isbn/{isbn}.json`, Google Books `isbn:`, Hardcover `editions`; skilj verk från utgåva), sedan titel + författare.
   - Gemensam `ProviderClient`: rate limit per leverantör styrd av `X-RateLimit-*`/`Retry-After` och lagrad i databasen; startvärden: Comic Vine 200 anrop per resurs och timme, 1 anrop/10 s med standardnyckel (10/10 s med personlig), icke‑kommersiell användning och länk tillbaka krävs; Metron 20/min burst och 5 000/dag (Bearer‑token); MangaDex ca 5 anrop/s per IP med obligatorisk `User-Agent`; AniList 90/min nominellt, för närvarande 30/min; MangaUpdates ingen siffra men "rimligt mellanrum"; Open Library 1/s (3/s med identifierande `User-Agent`, `fields` måste anges); Google Books 1 000/dag; Hardcover 60/min och 5 000/dag. Retry/backoff, svarscache (`ProviderCache`, TTL 7 dagar för sök, 30 dagar för id‑uppslag).
7. **Poängsättning på serienivå** (`matching/score.py`): evidens aggregeras från alla böcker i serien innan beslut. Närmaste publika referens är comicbox (serie 0,30, nummer 0,25, år 0,10, förlag 0,10, sidor 0,05, omslag 0,20; auto 0,95, marginal 0,10); Kodex använder samma signaler men på serienivå.
   - Titel: `rapidfuzz.fuzz.WRatio` (skala 0–100, normaliserad till 0–1) mot kandidatens namn **och alla alias/synonymer**, med straff för extra ord som inte finns i frågan ("Batman Beyond" för "Batman"; WRatio ger annars 90 för "Lois Lane" mot "Adventures of Lois Lane and Friends").
   - År: överlapp mellan böckernas årsintervall och runnens startår/slutår (1,0/0,7/0,4 vid 0/1/2 års avvikelse, avtar till 0 vid 7 år; 0,5 när båda saknas).
   - Nummertäckning: andel parsade nummer som finns i runnens nummerlista (hämtas en gång per kandidat, Comic Vine `issues?filter=volume:ID` med `field_list=issue_number` eller Metron `issue?series=ID`). Saknat nummer är en stark negativ signal bara för avslutade runs; `count_of_issues` används aldrig som hårt filter (omnumrering, `#1000`).
   - Format: TPB‑fil mot TPB‑run, nummer mot nummer‑run; fel format är diskvalificerande om kandidater av rätt format finns.
   - Förlag: träff efter borttagning av `inc`, `comics`, `publishing`, `press`.
   - Sidantal: jämfört med leverantörens `page_count` när det finns (1,0 / 0,7 inom 10 % / 0,3 inom 25 %).
   - Omslag: pHash (8×8, `imagehash.phash`‑kompatibel så att Metrons `cover_hash` kan användas utan nedladdning) av `Page[@Type=FrontCover]` (annars första sidan, med kantbeskuren variant och höger halva för uppslag) mot kandidatens omslag plus alternativomslag; en stark träff (Hamming ≤ 8) kan lyfta en osäker titel till `auto`, en miss är neutral. Beräknas bara för topp‑3 och bara när titelpoängen är ≥ 0,6.
   - Vikterna i `matching.toml` är startvärden och normaliseras om över de signaler som faktiskt finns; de anpassas mot eval‑korpusen, inte för hand.
   - Beslut: `auto` kräver poäng ≥ `auto_min`, marginal ≥ `auto_margin` (eller en enda kandidat med poäng ≥ `auto_single`, jfr Kavita+ som bara auto‑accepterar en ensam kandidat med poäng 1,0 eller en ensam över 0,9) **och minst två oberoende positiva signaler** utöver titel (år, nummertäckning, förlag, omslag eller alias). Annars `review` om poäng ≥ `review_min`, annars `none`.
8. **Nummerupplösning per bok**: mot runnens nummerlista (`N`, `N.0`, `N.5`, annual/special‑varianter); Metron via `cv_id`‑brygga. Manga: volym‑ och kapitelnummer mappas best‑effort mot MangaDex `aggregate` (scanlation‑volymer, inte officiella tankōbon) och visas som förslag; AniList `volumes` är bara ett totalantal. Saknas numret markeras boken `issue_unresolved` men behåller seriematchen.
9. **Tillämpning**: fyll tomma fält, respektera `locked_fields`, uppdatera `SeriesExternalId` och bokens `external_ids`, hämta omslag om saknas, spara `match_confidence`, `match_reason` (JSON med delpoäng) och `matched_at`; auto‑beslut loggas med återställning.
10. **Granskningskö** (`/admin/review`): grupperad per serie, sorterad på antal berörda böcker; visar parsade tokens (många "matchningsfel" är parserfel) med "lägg till i golden‑korpus", topp‑3 kandidater med delpoäng och omslag sida vid sida; åtgärder *Välj*, *Sök annan*, *Ingen match (lås som okänd)*, *Fel serie → flytta/dela*; tangentbordsstyrd; bulk‑accept med ångra. Valet skrivs som alias.
11. **Skrivning tillbaka till filer** (opt‑in per bibliotek): ComicInfo.xml v2.1 (och MetronInfo.xml) i CBZ med id:n i `Notes`/`Web` som andra verktyg läser; `series.json` (Mylar3‑format v1.0.2) och `cvinfo` per seriemapp med leverantör‑id, alias och låsstatus. Innehållsidentiteten (`content_id` över sidposter, exklusive XML) ändras inte av write‑back, så KoSync‑id, dubbletter och Android‑verifiering består. CBR→CBZ‑konvertering lämnar originalet kvar tills användaren raderar det.
12. **Mätning**: `matching/eval.py` kör motorn mot en frusen, stratifierad korpus (≥ 500 poster: daterade och odaterade US‑nummer, TPB, annual, manga romaji/engelska/CJK, e‑böcker) med inspelade svar och rapporterar precision, recall och review‑andel per stratum. Körs i CI; en regression stoppar merge.

### Konfiguration (`matching.toml`, startvärden)

| Nyckel | Startvärde | Betydelse |
| --- | --- | --- |
| `weights.title` | 0,30 | Titelsimilaritet med alias (WRatio + straff för extra ord) |
| `weights.issue_coverage` | 0,25 | Andel nummer som finns i runnen |
| `weights.year` | 0,10 | Årsöverlapp |
| `weights.publisher` | 0,10 | Förlagsträff |
| `weights.pages` | 0,05 | Sidantal mot leverantör |
| `weights.cover` | 0,20 | Omslagsavstånd (kan också fungera som grind) |
| `auto_min` / `auto_margin` / `auto_single` | 0,95 / 0,10 / 0,95 | Tröskel, marginal och enkandidatsregel för `auto` (samma som comicbox) |
| `review_min` | 0,50 | Under detta: `none` |
| `min_positive_signals` | 2 | Oberoende signaler utöver titel för `auto` |
| `prefilter.ratio_min` | 0,70 | Lokalt `fuzz.ratio`‑filter innan extern sökning |
| `cover.strong` / `cover.weak` | 8 / 16 | Hamming‑trösklar på 64‑bitars pHash (ComicTagger använder samma på aHash) |
| `cover.top_n` / `cover.min_title` | 3 / 0,60 | När omslag jämförs |
| `cache.search_ttl_days` / `cache.id_ttl_days` | 7 / 30 | Svarscache |
| `providers.<namn>.enabled/priority/rate` | per bibliotekstyp | Komf‑liknande prioritetsordning; `rate` överskrivs av headers |
| `grouping.strategy` | `metadata` | `folder`, `metadata` eller `comicvine` per bibliotek |
| `write_back.comicinfo` / `write_back.series_json` | false / true | Skrivning till filer per bibliotek |
| `llm.enabled` / `llm.max_calls_per_day` | false / 50 | Valfri disambiguering |

### Särfall som egna testfall

| Id | Fall | Förväntat |
| --- | --- | --- |
| M‑01 | Samma titel, flera runs (Batman 1940/2011/2016), bok med år | Rätt run via år; `auto` |
| M‑02 | Samma, bok utan år | `review` om fler än en kandidat med titel ≥ 0,9 |
| M‑03 | TPB/omnibus mot löpande nummer | Egen `format_family`; matchas mot samlad run, aldrig nummer N |
| M‑04 | Annual, special, one‑shot | Egen `format`; annual mot egen run eller som nummer i huvudrun; one‑shot får nummer 1 |
| M‑05 | Omnumrering (`#1000`, legacy) | Nummertäckning via nummerlista, aldrig `count_of_issues` som filter |
| M‑06 | Manga kapitel utan volym, kapitelintervall `c010-012`, extra‑kapitel `12.5` | Grupperas till serie; volym best‑effort; inga påhittade volymer |
| M‑07 | Två scanlation‑grupper, samma kapitel | Inte dubblett; "alternativ fil" på samma kapitel via `scan_group` |
| M‑08 | Light novel vs manga med samma titel | AniList `format`/MangaDex `type` avgör; fel typ diskvalificeras |
| M‑09 | Icke‑engelska titlar (romaji, kanji, svenska utgåvor) | Sök på original + translittererad; alias för lokala utgåvor; CJK bevaras |
| M‑10 | `[Grupp] Titel - c012 (v03) [Kvalitet].cbz` | Parsern ger serie, kapitel 12, volym 3, grupp |
| M‑11 | `Batman 2021 Annual`, `Action Comics 1000`, `2000 AD 2350` | Prioritetstabell; annars `ambiguous` → kön |
| M‑12 | Dubbletter (samma nummer i två format eller skanningar) | `content_id` + pHash; en bok med alternativ fil |
| M‑13 | E‑bok med ISBN‑10 | Normaliseras till ISBN‑13; verk vs utgåva skiljs |
| M‑14 | Omdöpt mapp för serie med läsframsteg | Omgrupperingsförslag i kön, id oförändrat |
| M‑15 | Fil med ComicInfo `Web` som pekar på Comic Vine‑nummer | Id‑upplösning utan sök; `auto` |

### Manuell matchning

- Serienivå: *Koppla serie till…* söker i alla aktiva leverantörer samtidigt, visar kandidater med omslag, år, förlag, antal nummer; val matchar om alla böcker i serien.
- Boknivå: *Byt nummer* inom vald run med paginerad nummerlista; *Flytta till annan serie*; *Markera som alternativ fil*.
- Lås/lås upp per fält och per serie; *Ignorera* för filer som inte ska matchas.
- Alla manuella beslut exporteras i `series.json` så att en ny databas kan återskapa dem.

### Valfritt sista steg: LLM‑assisterad disambiguering

Ingen etablerad taggare (Kavita, Komf, ComicTagger, comicbox, Kapowarr, Mylar3) använder embeddings eller språkmodeller för disambiguering i oktober 2026; perceptuell omslagshash är den enda icke‑textuella signalen i bruk. Därför är detta ett tillval och aldrig ett auto‑beslut. Bara när motorn landat i `review` med minst två kandidater: skicka parserresultat, kandidaternas namn/år/förlag/sammanfattning och bokens ComicInfo till en modell med strikt JSON‑schema (`{choice: id|null, confidence, reason}`). Används som **förslag i kön**; avstängt som standard; anropstak i konfiguration; dokumentationen anger exakt vilka fält som lämnar servern.

Sources: [ComicTagger](https://github.com/comictagger/comictagger) (`comicapi/filenameparser.py`, `comictaggerlib/issueidentifier.py`, `ctsettings/file.py`) · [comicbox](https://github.com/ajslater/comicbox) · [Komf](https://github.com/Snd-R/komf) · [Kavita parser‑wiki](https://wiki.kavitareader.com/guides/scanner/manga/) · [Kapowarr](https://github.com/Casvt/Kapowarr) · [Mylar3 series.json](https://github.com/mylar3/mylar3/wiki/series.json-examples) · [Comic Vine API](https://comicvine.gamespot.com/api/) · [Metron via mokkari](https://mokkari.readthedocs.io/) · [MangaDex API](https://api.mangadex.org/docs/) · [AniList rate limiting](https://docs.anilist.co/guide/rate-limiting) · [Open Library API](https://openlibrary.org/developers/api) · [Hardcover API](https://docs.hardcover.app/api/getting-started) · [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) · [imagehash](https://github.com/JohannesBuchner/imagehash). Rate‑limit‑siffror gäller oktober 2026 och ska läsas från leverantörernas headers i drift.

## Nya lösningar och differentiering

Kodex kan skilja sig från Komga och Kavita genom att vara **läsordnings‑ och samlingscentrerad** i stället för mappcentrerad: det som gör serier svåra att läsa är inte att hitta filen utan att veta vad som kommer härnäst, vad som saknas och var en story arc fortsätter. Varje idé är kopplad till den fas där den byggs och till ett acceptanskriterium; idéer utan fas ligger i backloggen.

| Idé | Fas | Acceptans |
| --- | --- | --- |
| Läsordning som förstaklassobjekt: beräknad ordning per serie och story arc (nummer, annuals, tie‑ins, samlade utgåvor som alternativ), "Läs nästa" överallt; CBL och Metron‑arcs som ordningskällor; egna ordningar exporteras som CBL | 4 | Ett klick från hem, serie eller arc öppnar rätt nästa bok; CBL‑rundresa ger identisk lista |
| Luckor och "komplettera": saknade nummer i serie och arc, ett klick skapar önskemål; visar om numret redan finns i en samlad utgåva | 4 (vy), 6 (flöde) | Saknat nummer syns inom en minut efter skanning; önskemål skapas utan formulär |
| Granskningskö som adminstart: nya filer, osäkra matchningar, dubbletter, omgrupperingar, sidflaggor, misslyckade jobb; grupperad per serie, sorterad på antal berörda böcker, tangentbordsstyrd, bulk‑beslut med ångra, logg över automatiska beslut med återställning | 1 (matchning), 3 (UI) | Alla auto‑beslut kan återställas; kön kan tömmas med enbart tangentbord |
| Universell läsposition: journal av sessioner (bok, nativ position, normaliserad progression, enhet, tid, sekvens) i stället för "längst vinner"; omläsning, flera enheter, KOReader och Kobo rätt per automatik | 4 | Två enheter som läser samma bok ger korrekt historik; omläsning förstör inget |
| Offline‑first Android: katalog i Room, deltasynk med tombstones och sekvenscursor, nedladdning per serie med auto‑påfyllning och rensning | 5 | Bläddra och läsa nedladdat helt utan nät |
| Manga‑medvetenhet: kapitelfiler grupperas till volymer när MangaDex `aggregate` eller ComicInfo ger volym; annars bara kapitel. Visas som best‑effort, aldrig som fakta | 1 | Kapitel utan volyminfo visas utan påhittad volym |
| Flerserver synligt: "Finns på server X", kopiera, gemensam önskelista | 6 | Behåller v1‑funktionen utan regression |
| Importassistent: förhandsvisning av tolkning (serier, nummer, format) med rättning innan något skrivs; valfri ComicInfo/series.json i samma steg | 2 (motor), 3 (UI) | Fel tolkning kan rättas utan att röra databasen |
| Presentation: omslag i tre storlekar i bakgrunden, dominant färg, serie‑hero med sammanfattning, förlag, år, status | 2 (omslag), 3 (UI) | Seriesida visar metadata för matchade serier |
| AI där det ger mest: förslag i granskningskön, samlingsbeskrivningar, "varför hamnade boken här"; avstängt som standard, med kostnadstak och tydlig information om vad som skickas utanför servern | 3 | Ingen data lämnar servern utan att funktionen slagits på |
| Öppet API: OpenAPI 3.1, genererade klienter, OPDS 1.2 + PSE, OPDS 2.0, Kobo‑sync och KoSync som förstaklass så att tredjepartsklienter fungerar medan Android byggs | 4 | Minst tre externa klienter verifierade |
| Backlog: Android TV/leanback, iOS via KMP, delning mellan instanser med inbjudningar, läsutmaningar/statistik, panel‑för‑panel (Guided View) när ordningen är löst | — | — |

## Målarkitektur och teknikval

Rekommendation: **bygg om Kodex till en modulär monolit v2 i samma repo, modul för modul, med matchningsmotorn först.** Teknikvalen nedan är nya (Postgres som enda tjänst, Procrastinate i stället för Redis/RQ, Vite‑SPA i stället för Next.js, ny Android‑app), men bytet sker som en "strangler": varje fas ersätter en del av v1 och lämnar systemet körbart, databasen migreras med Alembic i stället för att kopieras, och v1 fortsätter leverera värde under tiden. Ett nytt tomt repo med fullständig omskrivning övervägdes och valdes bort: för en ensam underhållare innebär det åtta faser av parallellt underhåll plus en datamigrering utan att något lager vinner på en ren omstart, utom Android‑appen (som aldrig kompilerats och därför startas om oavsett).

Delar som återanvänds med sina tester: arkivhantering, ComicInfo/OPF‑parsers, Kindle, KoSync, OPDS, nedladdningsklienter, smarta regler, story arcs.

### Val av stack

| Lager | Alternativ som övervägts | Beslut och motiv (versioner per 25 okt 2026) |
| --- | --- | --- |
| Licens | MIT/Apache‑2.0, GPL‑3.0, AGPL‑3.0 | **Välj i fas 0.** Standardförslag: **MIT** för största spridning, vilket kräver att AGPL‑beroenden byts (PyMuPDF 2.0 → `pypdfium2` 5.x för rastrering + `pikepdf` för metadata; EbookLib → egen OPF‑parser med lxml) och att `unrar` ersätts av `unar`/`bsdtar`/`7z` via `rarfile`. AGPL‑3.0 om man hellre behåller dem; AGPL gäller även nätverkstjänster. |
| Backend‑språk | Python (FastAPI), Go, Kotlin/Spring (Komga), Rust (Stump), .NET (Kavita) | **Python 3.14 + FastAPI 0.16x.** 3.12/3.13 är i säkerhetsläge och 3.15 är aktuell; golvet är 3.11 (Pillow 13, SQLAlchemy 2.1). Matchning är prioriterat och ekosystemet är överlägset där: `rapidfuzz`, `imagehash`/Pillow, `pypdfium2`, `rarfile`, `httpx`. \~500 befintliga tester följer med. CPU‑tunga steg (hashning, bildomkodning, extraktion) körs i processpool, inte i event‑loopen. |
| ORM och migrationer | SQLAlchemy 2.0/2.1, SQLModel, Tortoise | **SQLAlchemy 2.1 + Alembic 1.20 + Pydantic 2.14.** |
| Datalager | PostgreSQL, SQLite | **PostgreSQL 18 som enda tjänst** (data, sök, kö; `uuidv7()`, async I/O). Alembic från fas 0. SQLite skulle ge enklare installation men dubbla testmatriser; det är den största driftskostnaden i valet och hanteras med `pg_dump` i api‑containern, låst majorversion och dokumenterad uppgradering. Utvärderas igen efter lansering. |
| Sök | Meilisearch, Postgres FTS | **Postgres:** `pg_trgm` GIN (`%`, `<%`, `word_similarity`) på titlar, alias och CJK; `tsvector` GIN med `websearch_to_tsquery` på sammanfattningar och fulltext (ingen CJK‑tokenisering); unionsrankat. Meilisearch 1.5x bakom ett `SearchBackend`‑gränssnitt som tillval; dess egen jämförelse medger att Postgres räcker för tusentals dokument. |
| Jobb och kö | Redis/RQ, Celery, Dramatiq, arq (underhållsläge), Hatchet, pgqueuer, Procrastinate | **Procrastinate 3.10** (Postgres‑baserad, async, `@app.periodic(cron=...)` med databas‑dedupe över flera workers, retries, lås, prioriteter, LISTEN/NOTIFY). Egna schema‑migrationer sekvenseras i Alembic; connector öppnas/stängs i FastAPI lifespan; en dödad workers lås måste hanteras. Projektet söker fler underhållare — **pgqueuer 1.6** (SKIP LOCKED, cron, dashboard, Prometheus) är reservalternativet bakom samma gränssnitt. Rate limiters flyttas till databasen. |
| Auth | OIDC via frontend (NextAuth), backend‑BFF, lokal inloggning | **Backend äger auth:** lokal lösenordsinloggning (argon2id) som standard, OIDC Authorization Code + PKCE som tillval via **Authlib 1.9** (Starlette/FastAPI‑klient, RP‑logout); tokens via **joserfc** (Authlibs eget ersättningsbibliotek) eller PyJWT; `python‑jose` fasas ut. Sessionskaka med CSRF‑skydd för webben, bearer för appar; API‑nycklar per användare för OPDS/KoSync/Kobo. |
| Webbklient | Next.js, Vite + React SPA, SvelteKit | **Vite 8 + React 19 + TypeScript 7, TanStack Router 1.x (stabil sedan 2023) och Query 5, Tailwind 4, shadcn/ui (Base UI som standard sedan juli 2026, Radix valbart), PWA.** Appen sitter bakom inloggning, behöver ingen SSR/SEO, och läsarna är helt klientdrivna. Backend serverar den byggda SPA:n. |
| EPUB‑läsare webb | epub.js (ounderhållen sedan 2022), foliate‑js, Readium ts‑toolkit | **`@readium/navigator` (ts‑toolkit 2.x, BSD‑3, används av Thorium Web)** som förstahandsval: släppt, roadmap, och **samma Locator/progression‑modell som Readium Kotlin på Android**, vilket gör läspositioner delbara utan konvertering. Kräver att backend serverar en Readium Web Publication‑manifest (streamer skrivs i Python; små EPUB‑manifest är enkla). **foliate‑js** (MIT, aktivt, CFI) är reserven men är enligt sin README inte stabil och saknar releaser: vendoras på pinnad commit om den används. Beslutet låses efter en spike i fas 3. |
| PDF och bildläsare webb | pdf.js, pdfium‑wasm | **pdfjs‑dist 6.x** (legacy‑build för äldre webbläsare) för PDF; egen bildläsare med förladdning och WebP‑omkodade sidor från servern med `{maxWidth}`‑parameter (samma som OPDS‑PSE). |
| Android | Kotlin/Compose, Flutter, React Native, KMP | **Kotlin + Compose, med `shared/` som KMP‑modul** (Ktor 3.6‑klient, modeller, synk, journal‑kö, Room 2.8 KMP) och Koin som DI (Hilt är Android‑only). **Navigation 3 1.2 (stabil sedan nov 2025; `navigation3-runtime` är KMP)** i stället för Navigation 2 som är i underhållsläge. Compose Multiplatform 1.12, Coil 3.6, Paging 3, WorkManager. **Readium Kotlin 3.4:** `EpubNavigatorFragment` (produktion, via `AndroidFragment`) och `TtsNavigator`; de nya Compose‑navigatorerna är alfa och används inte än. Inga iOS‑mål i CI förrän de behövs. |
| PDF Android | AOSP `PdfRenderer`, barteksc PdfiumAndroid (vilande, ingen 16 KB‑sidstöd), AhmerPdfium, PdfiumAndroidKt, androidx.pdf | **androidx.pdf 1.0 (beta, minSdk 28)** som förstahandsval för rendering, sök och outline; **PdfiumAndroidKt** eller **AhmerPdfium** som fallback för minSdk 26. AOSP `PdfRenderer` är bitmap‑only och inte trådsäker. |
| API‑kontrakt | Handskrivna DTO:er | **OpenAPI 3.1 från FastAPI**, TypeScript‑ och Kotlin‑klienter genererade i CI; kontraktstest per PR. |
| OPDS och Kobo | Bibliotek, egen implementation | Ingen underhållen OPDS 2.0‑generator finns på PyPI (`opds` är 1.2 och AGPL): **egna Pydantic‑modeller** för OPDS 2.0 JSON (RWPM + `publications`/`navigation`/`facets`/`groups`), Atom 1.2 + PSE 1.2 för äldre klienter; `palace-webpub-manifest-parser` för validering i tester. Kobo‑sync efter Komgas och Calibre‑Webs mönster: `v1/initialization`, `v1/library/sync` med `x-kobo-synctoken`, `v1/library/{id}/state`, butiksproxy, KEPUB via kepubify, stora proxy‑buffertar, HTTPS. |
| Bildbehandling | Pillow, libvips, pdfium | **pyvips 3.2 (`pyvips[binary]`, abi3‑wheels för x86‑64/aarch64/armv7)** för omslag/miniatyrer/sidomkodning (ca 10× lägre toppminne, ca 2× snabbare än Pillow på stora bilder); **pypdfium2** för PDF‑rastrering (pyvips‑wheels saknar PDF‑laddare); Pillow 13 för hashning med `MAX_IMAGE_PIXELS` satt. |
| Arkiv | rarfile, py7zr, patool | `rarfile` 4.5 (ISC) med `unar`/`bsdtar`/`7z`‑binär (RAR5), `py7zr` (LGPL, ren Python) för CB7, `puremagic` i stället för `python-magic` (ingen release sedan 2022). |
| Distribution | docker‑compose, enkel binär | **Docker är det primära distributionssättet** (se Docker‑kompatibel server): **två containrar** (`api+worker`, `postgres`) plus valfri `meilisearch`; en officiell avbild för x86‑64 och arm64 som kör både api och worker. |

Sources (versioner och status kontrollerade 25 okt 2026 mot PyPI/npm och projektens egna sidor): [foliate‑js](https://github.com/johnfactotum/foliate-js) · [Readium ts‑toolkit](https://github.com/readium/ts-toolkit) · [Procrastinate](https://procrastinate.readthedocs.io/) · [pgqueuer](https://pypi.org/project/pgqueuer/) · [Navigation 3](https://developer.android.com/jetpack/androidx/releases/navigation3) · [Room](https://developer.android.com/jetpack/androidx/releases/room) · [Compose Multiplatform](https://github.com/JetBrains/compose-multiplatform/releases) · [Readium Kotlin 3.4](https://readium.org/kotlin-toolkit/3.4.0/) · [pyvips](https://pypi.org/project/pyvips/) · [libvips speed and memory](https://github.com/libvips/libvips/wiki/Speed-and-memory-use) · [androidx.pdf](https://developer.android.com/jetpack/androidx/releases/pdf) · [pdf.js releases](https://github.com/mozilla/pdf.js/releases) · [Komga Kobo‑guide](https://komga.org/docs/guides/kobo) · [Calibre‑Web Kobo‑integration](https://github.com/janeczku/calibre-web/wiki/Kobo-Integration) · [Meilisearch vs PostgreSQL](https://www.meilisearch.com/docs/resources/comparisons/postgresql.md) · [OPDS 2.0](https://specs.opds.io/opds-2.0.html) · [OPDS‑PSE](https://github.com/anansi-project/opds-pse) · [ComicInfo v2.1 XSD](https://github.com/anansi-project/comicinfo/blob/main/drafts/v2.1/ComicInfo.xsd)

### Backend‑moduler (modulär monolit)

| Modul | Ansvar |
| --- | --- |
| `core/` | Konfiguration, databas, Alembic, auth, användare och roller, API‑nycklar, enheter |
| `library/` | Bibliotek, serier, böcker, filer, skanner (trådpool + processpool, inkrementell på mtime+storlek, hash bara vid ändring, pollning för nätverksdelningar), dubblettdetektering, omslag |
| `formats/` | Arkiv (CBZ/CBR/7z), EPUB, PDF, bildmappar; sidextraktion med cache; ComicInfo/MetronInfo/OPF/series.json läs och skriv; innehållsidentitet |
| `matching/` | Parser, normalisering, gruppering, id‑upplösning, leverantörer, poäng, granskningskö, alias, eval |
| `reading/` | Läsjournal, positioner, KoSync, Kobo‑sync, statistik |
| `collections/` | Manuella, smarta (regelmotor i SQL), story arcs, läsordningar, CBL‑import/export |
| `discovery/` | Sök, följda serier, släppkalender, rekommendationer |
| `acquire/` (tillval) | Önskemål, nedladdningsklienter, sorterings‑ och importassistent |
| `delivery/` | OPDS 1.2 + PSE, OPDS 2.0, Kindle, notiser (Telegram/Discord/ntfy/e‑post), federation |
| `jobs/` | Procrastinate‑uppgifter, periodiska jobb, jobböversikt, rate limiters |

### Datamodell, ändringar mot i dag

- `Series`: persistent id som aldrig byts vid omgruppering; `title`, `sort_title`, `start_year`, `publisher`, `format_family`, `status`, `summary`, `match_confidence`, `locked_fields[]`.
- `SeriesExternalId(series, provider, external_id, is_primary)`: en serie kan ha Comic Vine + Metron, eller MangaDex + AniList + MAL + MangaUpdates samtidigt.
- `Book`: alltid 1:1 med fil; `format`, `number`, `chapter_number`, `volume_number`, `scan_group`, `issue_unresolved`, `duplicate_of`, `content_id` (hash över sidposter, exklusive `ComicInfo.xml`), `external_ids`.
- `Person` och `Credit(book|series, person, role)`: writer, penciller, inker, colorist, letterer, cover, editor, translator, author; ersätter dagens `authors`‑lista och blir sökfasett.
- `BookMetadata`: `locked_fields[]` i stället för `source`; ISBN normaliserad till ISBN‑13; `series_index` (flyttal) från Calibre/OPF.
- `SeriesAlias(norm_title, year?, library?, provider, external_id, polarity: positive|negative, source)`.
- `ProviderCache(provider, query_hash, payload, fetched_at, ttl)`, `ProviderRateState`.
- `MatchReview(target, candidates[], scores, decision, decided_by, decided_at, auto_decision_log)`.
- `ReadingSession(user, book, device, native_locator, progression, started_at, ended_at, client_seq, server_received_at)` med retention (sessioner äldre än 90 dagar komprimeras till en rad per bok och dag). Dessutom: `Device`, `ApiKey`, `User.role`, `LibraryAccess(user, library)`, `Collection.visibility`.

### Användare och roller

- Roller: `admin` (allt), `user` (läsa, egna samlingar, önskemål), `guest` (läsa utvalda bibliotek). Per‑bibliotek‑åtkomst och åldersgräns per användare.
- Samlingar är privata som standard och kan delas inom instansen; story arcs och läsordningar är delade.
- Bara admin triggar skanning, matchning i bulk, anskaffning och skrivning till filer.

### Synk, positioner och offline

- `GET /sync/changes?since=<seq>`: monoton sekvenscursor (inte tidsstämplar), tombstones för raderade serier/böcker/samlingar, sidbrytning.
- Läsposition lagras som nativ locator (Readium Locator i webb och Android när ts‑toolkit väljs, EPUB CFI, KOReader xpointer, Kobo span‑id, sidindex) **plus** normaliserad progression 0–1; "samma position" avgörs på progression, aldrig genom konvertering mellan locator‑format. Att välja Readium på båda klienterna gör att webb och Android delar locator rakt av.
- Journalposter skickas med klientsekvens; servern stämplar mottagningstid; aktuell position härleds per användare och bok; klienten kan alltid välja "fortsätt här" eller "börja om".
- Kobo‑sync (efter Komgas och Calibre‑Webs mönster): enheten pekar `api_endpoint` på `https://host/kobo/<token>`; servern implementerar `v1/initialization`, sidbruten `v1/library/sync` styrd av `x-kobo-synctoken`, `v1/library/{id}/state`, hyllor, bild‑URL‑mallar, nedladdning, och proxar okända rutter till Kobos butik; EPUB konverteras till KEPUB i farten (kepubify) för sidprecis progress; reverse‑proxyn behöver större header‑buffertar; HTTPS obligatoriskt. OPDS‑PSE 1.2 (`pse:count`, `pse:lastRead`, `pse:lastReadDate`, `{pageNumber}`/`{maxWidth}`) är det serieappar och KOReader faktiskt använder för sidströmning och ingår i `delivery/`; OPDS 2.0 Progression‑utkastet används för progress mot OPDS 2‑klienter.
- Android: nedladdningar med foreground‑notis, Wi‑Fi‑constraint, `Range`‑återupptagning och verifiering mot `content_id` innan filen markeras komplett.

### Säkerhet och drift

- Inga hemligheter i repot; `.env.example` med platshållare; OIDC valfritt.
- Filsäkerhet: zip‑slip‑skydd, dekompressionsbomb‑gränser, `MAX_IMAGE_PIXELS`, alla sökvägar relativa biblioteksroten, skrivskyddade bibliotek stöds.
- Nätverk: SSRF‑skydd för admin‑konfigurerade URL:er (nedladdningsklienter, peers, omslag), rate limit och audit‑logg på API‑nycklar, streaming med `Range`.
- LLM‑funktioner: avstängda som standard; dokumentera exakt vilka fält som skickas; kostnadstak.
- Drift: hälsokontroller, strukturerad loggning, OpenTelemetry‑hooks, `pg_dump`‑backup + `series.json`, återställningsövning, dokumenterad Postgres‑majoruppgradering, minnestak för NAS‑klass (2 GB).

### Docker‑kompatibel server

Hela serverdelen ska gå att köra i Docker utan något installerat på värden utöver Docker Engine med Compose v2 (och Podman, som självhostare ofta använder). Det är det primära sättet att installera Kodex, så varje fas lämnar avbilden och compose‑filen körbara.

- **En avbild, flera roller:** samma avbild kör api (`kodex api`), worker (`kodex worker`) och engångskommandon (`kodex migrate`, `kodex backup`); webbklienten byggs in i avbilden och serveras av api:t. Byggs multi‑stage, för `linux/amd64` och `linux/arm64`, och publiceras versionerad (`ghcr.io/<ägare>/kodex:<version>` plus `latest`) från CI.
- **Allt beroende ingår:** `unar`, `bsdtar`, libvips, pdfium och kepubify finns i avbilden; inget verktyg förutsätts på värden.
- **Konfiguration via miljövariabler** (12‑factor) med `.env.example` som referens; varje hemlighet kan också läsas från fil via `<NAMN>_FILE` för Docker/Podman secrets.
- **Tillstånd bara i volymer:** databasen, omslag och miniatyrer (cache som kan byggas om), konfiguration och backup ligger i namngivna volymer eller bind mounts; containern i övrigt är utbytbar och kan köras med skrivskyddat rotfilsystem. Bibliotek monteras skrivskyddat som standard och skrivbart bara när write‑back, sortering eller CBR→CBZ är påslaget.
- **Rättigheter:** kör som icke‑root; `PUID`/`PGID` styr vilken användare filer på bind mounts skapas som (konventionen från NAS‑världen); fungerar med `--user` och rootless Podman.
- **Livscykel:** migrationer körs automatiskt vid start med advisory‑lås så att flera repliker inte krockar; `HEALTHCHECK` mot `/healthz` (liveness) och `/readyz` (databas och kö nåbara); SIGTERM avslutar pågående förfrågningar och jobb rent eller lägger tillbaka dem i kön.
- **Drift i container:** loggar till stdout/stderr (valfritt JSON); fungerar bakom omvänd proxy (`X‑Forwarded‑*`, valfri bas‑sökväg); minnestak per container dokumenterat för NAS‑klass (2 GB); `docker compose up -d` med bara `.env` ger en körbar instans.
- **Referensfiler i repot:** `docker-compose.yml` (drift), `docker-compose.dev.yml` (utveckling med hot reload) och exempel för vanliga NAS‑gränssnitt (Unraid‑mall, Synology/Portainer‑stack) från fas 7.

## Genomförandeplan

Åtta faser i samma repo, där varje fas ersätter en del av v1 och lämnar systemet körbart ("strangler"‑mönster). Matchningsmotorn byggs först, eftersom den är prioriterad och kan levereras i v1:s gränssnitt innan något annat rörs. Varje fas har uppgifter som en agent tar en i taget och ett gate‑kriterium som måste vara uppfyllt innan nästa fas börjar.

### Fas 0 — Grund och spelregler

- [x] Välj licens (se Målarkitektur) och byt ut beroenden som inte är förenliga med valet (PyMuPDF → pypdfium2 + pikepdf, EbookLib → lxml‑OPF, unrar → unar/bsdtar). Uppgradera samtidigt till Python 3.14, SQLAlchemy 2.1, Pydantic 2.14 och byt python‑jose mot joserfc.
- [x] Alembic‑baseline på nuvarande schema (`alembic stamp` + första riktiga migration); ta bort den handskrivna `migrations.py`.
- [x] Repo‑struktur: `backend/kodex/<modul>` enligt modultabellen, `web/` (ny SPA), `shared/` + `androidApp/` (fas 5), `docs/`, `tools/`. v1‑kod flyttas modul för modul, inte i ett svep.
- [x] `AGENTS.md` och `CONTRIBUTING.md`: kommandon, kodstandard, testkrav, regeln "stanna och fråga vid hemligheter, destruktiva ändringar eller beslut som inte går att härleda ur repot".
- [x] CI: backend `ruff` + `mypy` + `pytest` mot Postgres 18‑service; web `tsc` + `vitest` + Playwright; Android `./gradlew test assembleDebug` (aktiveras i fas 5). Pre‑commit, Conventional Commits, changelog.
- [x] Testfixtures: generator för syntetiska bibliotek (2 000 och 50 000 filer med ritade sidor), Gutenberg‑EPUB:er, golden‑filnamnskorpus, inspelade leverantörssvar (kontrollera leverantörernas villkor innan svar checkas in).
- [x] Skriv `docs/decisions/` (ADR) för varje rad i stack‑tabellen.
- [x] Docker‑grund (se Docker‑kompatibel server): multi‑stage‑avbild för api och worker med alla verktyg inbyggda, migrationer vid start, `HEALTHCHECK`, icke‑root; compose‑fil som startar hela stacken från `.env`; CI bygger avbilden och startar compose‑stacken som röktest.

Gate: CI grön på backend och web; Alembic äger schemat; fixtures genererar ett 2 000‑filers bibliotek på under en minut; `docker compose up` ger en körbar instans.

Status 2026‑10‑25: gate uppfylld (CI grön för backend, web och compose‑röktest; 2 000 filer på ca 6 s). Licens MIT; EbookLib användes inte i v1, så inget att byta där. Golden‑filnamnskorpusen byggs som första uppgift i fas 1 tillsammans med parsern, och inspelade leverantörssvar väntar på villkorskontroll och underhållarens nycklar (se `docs/testing.md`); fram till dess används syntetiska svar.

### Fas 1 — Matchningsmotor

- [x] `matching/parse.py` + golden‑korpus (≥ 300 filnamn, med `xfail`‑lista för kända tvetydigheter); 100 % på de icke‑xfailade.
- [x] `normalize.py`, `group.py`: gruppering utan nätverk, stabila serie‑id, omgrupperingsförslag till kön i stället för tyst flytt, "dela serie".
- [x] Id‑upplösning före sök: ComicInfo `Web`/`Notes` (ComicTagger skriver Comic Vine‑id), `GTIN`, MetronInfo.xml, EPUB ISBN, Calibre `metadata.opf`.
- [x] `providers/`: Comic Vine, Metron, MangaDex, MangaUpdates, AniList, Open Library, Google Books, Hardcover; gemensam klient med header‑styrd rate limit lagrad i databasen, retry/backoff, svarscache, inspelade svar i tester.
- [x] `score.py`: seriebedömning med aggregerad evidens, konfiguration i `matching.toml`, omslag via pHash som grind/utslagsröst.
- [x] Nummerupplösning per bok mot runnens nummerlista; tillämpning med fältnivålås; alias (positiva och negativa).
- [x] `MatchReview`‑kö med API och en enkel adminvy i v1:s frontend (ersätts i fas 3).
- [x] `eval.py` + stratifierad korpus (≥ 500 poster: daterade/odaterade nummer, TPB, annual, manga romaji/engelska/CJK, e‑böcker) med rapport per stratum; CI‑tröskel.

Gate: precision ≥ 0,98 på `auto`, review‑andel ≤ 25 % totalt och ≤ 10 % för daterade nummer, inga nätverksanrop i tester, kön fungerar i v1.

Status 2026‑10‑25: gate uppfylld på den syntetiska korpusen (624 fall i 13 strata, bland dem manga numrerad per volym, översättningar med samma titel och år som originalet, och samlade runs som Metron saknar Comic Vine‑id för): precision 100 % på `auto`, review 16,0 % totalt och 3,3 % för daterade nummer. `tests/conftest.py` stoppar nätverksanrop (det hittade fyra v1‑tester som anropade Comic Vine), och kön finns i v1:s admin under Granskning. Utvärderat lokalt mot ett riktigt bibliotek (resultaten checkas inte in): e‑böcker och manga matchades nästan helt automatiskt, och för serier gick review‑andelen från två tredjedelar till ungefär en femtedel utan felaktiga `auto` vid genomgång. Det som återstår är verkligt tvetydigt (två utgåvor med samma titel och omslag), saknar en andra signal (inget år i filen eller hos leverantören) eller saknas hos leverantören. Avvikelser: Comic Vines villkor tillåter inte att inspelade svar checkas in, så leverantörstesterna använder syntetiska svar med samma form medan de riktiga inspelningarna stannar lokalt (se `docs/testing.md`). Utöver listan: ISBN från PDF‑filers första sidor, manga per volym, samlade utgåvor mot samlade runs (> 100 sidor utan nummer, `Book N`, volymens egen titel), omslagsjämförelse med nyckelpunkter (OpenCV ORB) för samlade utgåvor vars omslag har ny trade dress, och översatta utgåvor som viker för originalet (förlagstabell i `matching.toml`). Det valfria LLM‑steget är inte byggt.

### Fas 2 — Kärna: format, bibliotek, jobb

- [x] `formats/`: portera arkiv‑, ComicInfo‑, OPF‑ och PDF‑läsning med tester; lägg till ComicInfo v2.1‑fält, MetronInfo.xml, 7z, `series.json` läs/skriv, `pypdfium2` i stället för PyMuPDF, `unar`/`bsdtar` för RAR.
- [x] Stabil innehållsidentitet: hash över sidposterna i arkivet (exklusive `ComicInfo.xml`), partiell hash för stora filer; hash beräknas bara när mtime eller storlek ändrats.
- [x] `library/`: skanner med trådpool och processpool för CPU‑tunga steg, pollning för SMB/NFS, omslag i tre storlekar via pyvips i bakgrundsjobb, dubbletter (innehållshash + pHash), saknade filer, skrivskyddade bibliotek.
- [x] `jobs/`: Procrastinate ersätter RQ; dess schema‑migrationer sekvenseras i Alembic; periodiska jobb; jobböversikt; rate limiters i databasen.
- [x] Skrivning tillbaka till filer (opt‑in per bibliotek) utan att innehållsidentiteten ändras; CBR→CBZ bara med originalet kvar tills användaren raderar.
- [x] Säkerhet i filhantering: zip‑slip, dekompressionsbomb‑gränser, `MAX_IMAGE_PIXELS`, sökvägar låsta till biblioteksroten.

Gate: första skanning av 50 000 syntetiska filer ≥ 30 filer/s; omskanning utan ändringar av samma bibliotek < 60 s; KoSync‑id och dubbletter stabila efter write‑back.

Status 2026‑10‑26: gate uppfylld. På en server med 2 kärnor skannas 50 000 syntetiska filer i 112 filer/s (445 s, inga fel) och oförändrade omskanningar tar 6,3 och 3,6 s (`tools/bench/scan.py`; v1:s skanner gjorde 70 filer/s och cirka 1,1 ms per oförändrad fil). Efter write‑back har en bok samma id, innehålls‑id och dubbletter, och både det gamla och det nya KOReader‑id:t hittar den (`tests/test_write_back.py`). Arkiv känns igen på innehållet (en `.cbr` som är en zip öppnas), sidorna står i naturlig ordning och en sidcache nycklas på index. Avvikelser: filerna läses i en processpool medan databasarbetet stannar i en tråd, så någon separat trådpool behövdes inte; pollningen för SMB/NFS är en periodisk omskanning (var tionde minut kontrolleras om ett bibliotek är äldre än `RESCAN_INTERVAL_MINUTES`); RQ:s tidsgräns per jobb har ingen motsvarighet i Procrastinate och arbetaren kör ett jobb i taget; `puremagic` behövdes inte (signaturer räcker, ADR 0016 uppdaterad); `series.json` bär både Mylar3‑blocket och v1:s säkerhetskopia i samma fil; liknande dubbletter (pHash) listas i API:t men får sin vy i fas 3, liksom omslagsstorlekarna i webbklienten.

### Fas 3 — Webbklient v2

- [x] Vite 8 + React 19 + TanStack Router/Query + Tailwind 4 + shadcn/ui (Base UI); genererad TS‑klient från OpenAPI; design‑tokens, tema, i18n (sv/en), skeletons, tomma/fel‑tillstånd, tillgänglighet (tangentbord, kontrast).
- [x] Vyer: Hem, Bibliotek, Serie (hero, metadata, läsordning, luckor), Bok, Sök, Samlingar, Följer, Släpp, Önskemål, Inställningar (inkl. API‑nycklar för OPDS/KoSync/Kobo med engangsvisning).
- [x] Admin: granskningskö som startsida, bibliotek, jobb, matchning på serienivå, importassistent, dubbletter, sidflaggor, användare och roller, integrationer med "inte konfigurerad"‑tillstånd.
- [x] Läsare: bildläsare (sida/dubbelsida med offset/webtoon/kontinuerlig, RTL, förladdning, filter, beskärning, tangentbord, tap‑zoner); EPUB efter en spike som jämför \`@readium/navigator\` (kräver RWPM‑manifest från backend) med vendorad foliate‑js — beslutet dokumenteras som ADR; PDF via pdfjs‑dist 6; journalbaserat framsteg.
- [x] PWA med offline‑skal; Playwright‑flöden; växla över från Next‑appen och ta bort den.

Gate: paritet med v1:s användarflöden plus granskningskö; en användare kan logga in, skanna, granska, läsa alla format och se framsteg synkas mellan två webbläsare.

Status 2026‑10‑26: gate uppfylld i CI. `web/e2e/gate.spec.ts` kör mot hela compose‑stacken (`tools/smoke-compose.sh`) och går igenom webbklienten: första admin skapas vid första besöket, fel lösenord avvisas, bibliotek skapas och skannas, ett ärende i granskningskön hoppas över och ångras, en serie läses och positionen följer med till en andra webbläsare (egen inloggning och egen enhet i journalen), en PDF och en EPUB läses, ett skript i en EPUB körs inte (CSP), och utloggning. Backend äger inloggningen (lokala konton med argon2id, sessionskaka med CSRF, valfri OIDC med PKCE, personliga API‑nycklar, rollerna admin/användare/gäst), API:t ligger under `/api` med OpenAPI som kontrakt (kontrolleras i CI), och Next‑appen och dess container är borttagna. Avvikelser: EPUB läses med foliate‑js vendorad på en fast commit i stället för Readium (ADR 0019), så positionerna är CFI tills fas 4:s positionsmodell; OIDC är skriven med httpx och joserfc i stället för Authlib (ADR 0007); Kobo har en nyckeltyp men själva synken kommer i fas 4; ordningen i en samling ändras med upp/ned‑knappar (dra‑och‑släpp i fas 4); offline‑skalet visar det som redan laddats, men att ladda ner böcker för läsning offline hör till Android‑appen (fas 5); v1:s rötter finns kvar för Android‑v1 och v1:s OPDS‑token fungerar tills den återkallas; smoke‑testet låter matchningen fråga de källor som inte kräver nycklar över nätet (pytest är fortfarande nätverksfritt). Kontrollerna körs i GitHub Actions (`gh workflow run ci.yml --ref <gren>`), inte på små delade maskiner.

Tillägg efter fasen (2026‑10‑26, ADR 0020): Kodex klarar sig utan identitetsleverantör. Passkeys (WebAuthn) loggar in utan lösenord och fungerar som andra steg; tvåstegsverifiering med autentiseringsapp (TOTP) och tio reservkoder; en admin ger en användare en engångslänk för att välja lösenord (så får v1:s Authentik‑användare lösenord), och kan återställa en användares andra steg (också från kommandoraden). En valfri OIDC‑leverantör är generisk: inställningarna heter `OIDC_*` (v1:s `AUTHENTIK_*` fungerar), ingen förvald obligatorisk grupp, `OIDC_CREATE_USERS` för att bara släppa in kopplade konton, och ett Kodex‑konto kan kopplas till och från leverantören. Gate‑flödet lägger till en passkey (Chromes virtuella autentiserare), slår på tvåstegsverifiering och loggar in med reservkod och med passkey.

### Fas 4 — Läsning, samlingar, upptäckt, externa klienter

- [ ] `reading/`: journal med retention/komprimering, positionsmodell (nativ locator + progression), KoSync (\`x-auth-user\`/\`x-auth-key\`, \`PUT /syncs/progress\`, binary‑matchning på partiell MD5), Kobo‑sync med KEPUB‑konvertering och butiksproxy, statistik.
  Status 2026‑10‑26: skrivet och testat mot klienternas anropsformer (journal med komprimering, positioner med locator‑sort, KoSync på journalen, Kobo‑sync med KEPUB och butiksproxy, statistiksida); väntar på riktiga enheter (docs/clients.md).
- [ ] `collections/`: smarta regler i SQL med "olästa i serie", story arcs, läsordningar, drag‑och‑släpp, CBL in/ut.
  Status 2026‑10‑26: regler i SQL per läsare (läsläge, följda serier, nästa olästa i serien, `not`), story arcs i bågens ordning, CBL ut och in, dra‑och‑släpp i manuella samlingar.
- [ ] `discovery/`: sök (FTS för text, pg\_trgm för titlar och CJK), följda serier med manuell toggle, släppkalender med notiser.
  Status 2026‑10‑26: sök i Postgres (pg_trgm, FTS med 'simple', delsträngar för CJK), Meilisearch borttagen helt i stället för som tillval bakom ett gränssnitt (ADR 0005); följ/sluta följa och släppkalendern med ntfy‑notiser finns sedan v1.
- [ ] OPDS 1.2 + PSE 1.2 (Atom) och OPDS 2.0 (egna Pydantic‑modeller, validerade med \`palace-webpub-manifest-parser\`) med Progression‑utkastet för progress; verifierade mot minst tre riktiga klienter (t.ex. KOReader med PSE, Panels/Chunky på iOS, Moon+/Librera på 1.2, Cantook på 2.0) enligt samma klienttabell som Komga publicerar.
  Status 2026‑10‑26: skrivet, OPDS 2 validerat med parsern i testerna; klienttabellen i docs/clients.md fylls i när klienterna provats.

Gate: KOReader, en Kobo och en OPDS‑PSE‑klient läser och synkar mot servern.

### Fas 5 — Android v2

- [x] `shared/` (ren Kotlin/KMP utan iOS‑mål i CI): Ktor‑klient från OpenAPI, modeller, synk‑cursor, journal‑kö, DI via Koin.
  Status 2026‑10‑26: KMP‑modul med bara JVM‑mål. Ktor‑klienten är handskriven för appens anrop och hålls mot `web/openapi.json` av ett kontraktstest i CI i stället för att genereras (ADR 0021). Där finns också deltasynk mot `GET /api/sync/changes` (katalog‑ och positionscursor, sidor, reset), utkorgen för läspositioner med `client_seq`, och läsarens regler: webbens layout och serverns sidordning i arkiv. Koin finns i appen; `shared/` behöver ingen DI.
- [x] App‑skal: Navigation 3 (1.2, \`@Serializable\` nycklar), adaptiv layout, sv/en, tema, inloggning (lokal + OIDC).
  Status 2026‑10‑26: NavigationSuiteScaffold, och list‑detalj på breda skärmar. Inloggning med lösenord och kod (tvåsteg), eller i webbläsaren för passkeys och OIDC: PKCE‑lik kod via `/app-login` och `kodex://login`. Appen får en egen nyckel per enhet, sparad krypterad med Android Keystore. Sv/en, systemtema eller ljust/mörkt.
- [x] Offline‑katalog i Room, nedladdningar med foreground‑notis, Wi‑Fi‑constraint, återupptagning med `Range`, verifiering mot innehållshash, auto‑hämtning av nästa N.
  Status 2026‑10‑26: Room 3 i appen. Nedladdningarna kör i WorkManager och kontrolleras mot `GET /api/books/{id}/digest` (SHA‑256). CBR, CB7 och bildmappar hämtas sida för sida, eftersom enheten inte packar upp RAR och 7z. Nästa N olästa i en serie som läses hämtas efter varje synk och när en bok läses klart.
- [x] Bildläsare i Mihon‑klass (lägen, dubbelsida med offset, tap‑zon‑layouter, filter, beskärning, dela breda sidor, förladdning, nästa nummer vid slut); EPUB via Readium Kotlin 3.4 \`EpubNavigatorFragment\` + \`TtsNavigator\`; PDF via androidx.pdf (beta) med PdfiumAndroidKt som fallback; widget; trackers (AniList/MAL/MangaUpdates/MangaBaka) som valfri synk.
  Status 2026‑10‑26: allt, men trackers ligger i servern (ADR 0023).
  - Bildläsaren har vänster–höger, höger–vänster och lodrät remsa; dubbelsida med omslaget för sig; tre tap‑layouter; gråskala, sepia och invertering; beskärning av marginaler (serverns `trim`, för sidor som strömmas); breda sidor i halvor; två sidor förladdade; och nästa nummer efter sista sidan. Zoom avkodar sidan i dubbel skärmstorlek, utan tile‑avkodning.
  - EPUB läses med Readium och kan läsas upp med TtsNavigator medan läsaren är öppen. Positionen sparas som Readiums locator i kort form (`other`); positioner från andra läsare öppnas på sin procent.
  - PDF läses med androidx.pdf:s Compose‑vy, utan Pdfium (minSdk 28, ADR 0022).
  - Widgeten visar senast lästa boken.
  - Trackers ligger i servern i stället för i appen (ADR 0023), så läsning i alla klienter når dem. Tjänsterna är MangaUpdates och Kitsu (lösenord), och AniList och MyAnimeList (deras egen inloggning, med en klient registrerad av admin). Token sparas krypterade med `SECRET_KEY`. Serier föreslås från matchningens externa id. Läsläget skickas var femtonde minut och bara framåt. MangaBaka dokumenterar inte sitt användar‑API och väntar.
- [x] Instrumenterade tester för läsare och nedladdning; CI bygger release‑APK; kompatibilitetsfönster: v1‑appen fungerar mot servern tills v2‑appen släppts.
  Status 2026‑10‑26: `.github/workflows/android.yml` kör `shared`:s tester (med kontraktstestet), Robolectric‑tester (katalog, positioner, nedladdning med Range och SHA‑256, sidordning) och lint. Det bygger debug‑APK och release‑APK med R8, signerad med projektets nyckel från secrets, och kör `OfflineReadingTest` på en emulator. v1‑appen når servern genom `/api/backend` (fas 3).

Gate: appen bygger i CI, tester gröna, läsflödet fungerar offline efter nedladdning.

Status 2026‑10‑26: gate uppfylld i CI (Android‑körning 40377190969). `OfflineReadingTest` gör följande på emulatorn: laddar ner en CBZ från en testserver, kontrollerar SHA‑256, stänger av servern, öppnar boken, bläddrar och sparar positionen i utkorgen. Kvar: prov på en riktig enhet och mot den riktiga servern, och trackers mot de riktiga tjänsterna. Release signeras sedan 2026‑10‑26 med en nyckel som finns i GitHub‑secrets och i en privat kopia utanför repot.

### Fas 6 — Anskaffning och leverans som tillval

- [x] Portera önskemål, sorterings‑/importassistent, Kindle, notiser och federation med tester.
  Status 2026‑10‑27: önskemål har serie och nummer (migration 0016) och kan göras från seriens saknade nummer. Följande ligger nu i `kodex/` och klarar mypy:s strikta läge:
  - `kodex/acquire`: önskemål, nedladdningar, klienterna och sorteringsassistenten.
  - `kodex/delivery`: Kindle, notiser och federation.
  - `kodex/collections/csv_import`: CSV‑importen av läslistor.

  v1‑modulerna är borttagna och testerna importerar de nya. Jobbens kroppar ligger kvar i `app/workers/tasks.py`, där registret laddar dem.
- [x] Nedladdningsklienter (Prowlarr, qBittorrent, SABnzbd, Mylar3, Kapowarr) som ett avstängt tillval med egen dokumentation; "saknat nummer → önskemål → nedladdning → import → matchning" som ett flöde när tillvalet är på.
  Status 2026‑10‑27: `ACQUIRE_ENABLED` (av som standard) och dokumentationen i docs/acquire.md. Ett godkänt önskemål söks i Prowlarr: bästa träffen har seriens titel och numret och är inget paket, och går till qBittorrent (magnet) eller SABnzbd (NZB). Klienterna frågas varannan minut. En färdig nedladdning flyttas in i seriens mapp och biblioteket skannas och matchas. Önskemålet uppfylls när numret finns i serien, och den som önskade får en ntfy‑notis. Mylar3, Kapowarr, Anna's Archive och GetComics nås för hand, än så länge bara genom API:t: webbklienten v2 har ingen sida för dem (v1:s Nedladdningar‑sida följde inte med).

Gate: ett saknat nummer kan beställas och dyka upp i serien utan manuellt arbete utöver godkännande.

Status 2026‑10‑27: gate uppfylld i CI med låtsade tjänster. `tests/test_acquire.py` har en serie med #1 och #3, önskar #2 och godkänner. Prowlarr och qBittorrent svarar som deras API:er dokumenterar, och #2 finns sedan i serien och önskemålet är uppfyllt. Kvar: prov mot riktiga Prowlarr och qBittorrent (driften har inga).

### Fas 7 — Härdning och lansering

- [x] Prestanda: 50 000 böcker, minnestak per jobb (NAS‑klass, 2 GB), arm64‑avbilder.
  Status 2026‑10‑27: `bench.yml` (för hand och varje söndag) gör 50 000 påhittade böcker och mäter med två CPU:er:
  - Skanningen med 2 GB och `SCAN_WORKERS=2`: första gången 6,8 minuter (124 filer/s) och högst 241 MB; utan ändringar 3,4 s.
  - API:t med 1 GB: högst 182 MB. Median: en sida böcker 124 ms, en sida serier 67 ms, sökning 404 ms (på "the", som nästan alla titlar har), OPDS 76 ms, fortsätt läsa 7 ms. En apps första synk av hela katalogen tar 10 s.
  - PostgreSQL: högst 594 MB, mest sidcache.

  Seriesidan byggde förut alla serier i biblioteket för varje sida (375 ms). Nu filtrerar och sidar den i SQL. Avbilden byggs och startas för amd64 och arm64 i `image.yml`.
- [x] Säkerhetsgenomgång: auth (argon2id, token‑livslängder, CSRF för kakor), SSRF‑skydd för admin‑konfigurerade URL:er, uppladdning, rate limit.
  Status 2026‑10‑27: genomgången står i docs/security.md. Argon2id, sessionernas och nycklarnas livslängd, CSRF‑token för kakor och begränsade inloggningsförsök (per användarnamn och per adress) fanns redan. Nytt:
  - SSRF‑skydd för adresser från andras data: omslag och metadata, även efter omdirigering. Tjänsterna admin anger (Prowlarr, ntfy, …) kommer bara från miljön, aldrig från webbklienten, och ska ligga i det lokala nätet, så de undantas.
  - Uppladdningar strömmas till disk.
  - Säkerhetshuvuden: nosniff, Referrer‑Policy och X‑Frame‑Options.

  Kvar och dokumenterat: DNS‑rebinding fångas inte.
- [x] Drift: `pg_dump` i api‑containern, dokumenterad Postgres‑majoruppgradering, återställningsövning från backup, hälsokontroller.
  Status 2026‑10‑27: avbilden har PGDG:s `postgresql-client` för `POSTGRES_MAJOR` (18). `python -m kodex.core.backup` har `dump`, `list`, `verify` och `restore`; en dump görs varje natt kl. 03.30 och `BACKUP_KEEP` (7) sparas. `verify` är återställningsövningen: den lägger den senaste dumpen i en egen databas och jämför antalen med den levande. Compose‑röktestet kör `dump` och `verify`. Majoruppgradering och återställning står i docs/operations.md. `/readyz` svarar när databasen svarar och schemat är aktuellt, och det är avbildens healthcheck.
- [x] Dokumentation på engelska: installation, konfiguration, migrering från v1, API, bidrag, "varför Postgres".
  Status 2026‑10‑27: docs/install.md, configuration.md, operations.md, security.md, migrating-from-v1.md, api.md, why-postgres.md, README och CONTRIBUTING. `.env.example` är också på engelska. Compose‑röktestet utgår från `.env.example` och sätter bara det install.md säger, så den dokumenterade vägen är den testade.
- [ ] Docker‑härdning: `PUID`/`PGID`, `<NAMN>_FILE`‑hemligheter, skrivskyddat rotfilsystem, `/readyz`, ren nedstängning vid SIGTERM, multi‑arch‑avbild publicerad från CI, NAS‑mallar (Unraid, Synology/Portainer) och verifiering med rootless Podman.
  Status 2026‑10‑27: allt utom publiceringen och NAS‑mallarna.
  - `PUID`/`PGID` (1000 som standard; 0 behåller root): containern startar som root bara för att ge `/data` till användaren, och byter sedan.
  - `NAMN_FILE` för alla inställningar.
  - `read_only`, tmpfs för `/tmp` och no‑new‑privileges i compose.
  - `/readyz`, och uvicorn ger pågående anrop 25 s vid SIGTERM.
  - Avbilden byggs för amd64 och arm64, men publiceras inte än.
  - Rootless Podman kör den i CI: skrivskyddad, i en pod med PostgreSQL. `podman compose` är inte testat.

  NAS‑mallarna behöver en publicerad avbild att peka på.
- [ ] Publik release med versionerade containrar och APK.
  Väntar på beslut: var avbilderna publiceras (GHCR?), versionsnummer och om repot blir publikt.
- [x] En automatisk tillgänglighetskontroll (axe) i Playwright‑flödena. (Generiska `OIDC_*`‑namn och ingen förvald grupp gjordes redan efter fas 3, ADR 0020.)
  Status 2026‑10‑27: `e2e/gate.spec.ts` kontrollerar första besöket och sju sidor mot WCAG 2.1 A/AA, med allvarliga och kritiska fel som stopp. Två fel rättades: accentfärgad text hade för låg kontrast (ny token `--primary-text`), och väljare saknade namn.
- [x] TOTP‑hemligheterna krypterade i vila med en servernyckel (`<NAMN>_FILE`), tillsammans med övriga hemligheter.
  Status 2026‑10‑27: `kodex.core.sealed` krypterar med en nyckel härledd ur `SECRET_KEY` per ändamål, med tvåstegshemligheterna och trackernas token. Hemligheter som sparats före `SECRET_KEY` krypteras vid nästa migrering (0017 breddar kolumnen).
- [ ] Innan repot blir publikt: sök igenom hela historiken efter instansdata (filnamn, titlar, sökvägar, domäner) och skriv om den vid behov. GitHub behåller commits som en stängd PR pekar på (`refs/pull/N/head`, i dag Renovates PR #1 från före omskrivningen 2026‑10‑25), så publicera från ett nyskapat repo eller be GitHub Support ta bort dem.
  Status 2026‑10‑27: genomsökt. Inga domäner, e‑postadresser, sökvägar eller användarnamn från driften. En verklig boktitel fanns i en test sedan v1‑importen; den är ersatt i HEAD men finns kvar i historiken. Väntar på beslut: ett nytt publikt repo med ny historik, eller omskrivning plus GitHub Support för `refs/pull/1`.

Gate: en utomstående kan installera och köra Kodex från dokumentationen utan hjälp.

Status 2026‑10‑27: i CI följer compose‑röktestet install.md från `.env.example` och klarar hela webbflödet. Kvar för gaten: en publicerad avbild eller ett publikt repo att klona (install.md:s `git clone` pekar på `<you>`), och någon utomstående som provar.

## Acceptanskriterier, tester och risker

En uppgift räknas som klar först när kriterierna nedan är uppfyllda och verifierade i CI, inte när koden är skriven. Fasernas gates i Genomförandeplanen är de bindande milstolparna; tabellen här är de löpande kraven som gäller i alla faser.

### Acceptanskriterier

| Område | Kriterium |
| --- | --- |
| Parser | 100 % av golden‑korpusen (≥ 300 filnamn) utanför `xfail`‑listan; varje nytt fel läggs i korpusen innan det rättas |
| Matchning | Precision ≥ 0,98 på `auto` (hellre fler i review än en tyst felmatch), review ≤ 25 %, 0 nätverksanrop i tester, varje beslut loggar delpoäng och kan återställas |
| Skanner | Första skanning ≥ 30 filer/s på syntetiskt bibliotek; omskanning utan ändringar < 60 s för 50 000 filer; inga raderingar av filer på disk; innehållsidentitet oförändrad efter write‑back |
| Läsframsteg | Två enheter som läser samma bok ger korrekt journal; omläsning startar om utan att förstöra historik; klockskevhet hanteras med serverns mottagningstid + klientsekvens; KoSync och Kobo verifierade mot riktiga klienter |
| Synk | `/sync/changes` levererar tombstones och en monoton sekvenscursor; en klient som varit offline en vecka kommer ikapp utan full omladdning |
| Läsare webb | Alla lägen på 380 px mobil och 1 440 px desktop; sidbyte < 100 ms med förladdning; tangentbord och touch; WCAG AA‑kontrast |
| Läsare Android | Alla lägen; 60 fps vid sidbyte på mellanklassenhet; offline‑läsning av CBZ/CBR/EPUB/PDF |
| API | OpenAPI validerar; genererade klienter kompilerar; brytande ändring kräver versionsbump; kontraktstest per PR |
| Säkerhet | Inga hemligheter i repo; sökvägar kan inte lämna biblioteksroten; zip‑slip och dekompressionsbomber stoppas; uppladdning begränsad till kända format; SSRF‑skydd på admin‑URL:er; argon2id; CSRF för kaksessioner; rate limit på publika endpoints; LLM‑funktioner avstängda som standard och dokumenterade |
| Docker | Serverdelen körs helt i containrar utan verktyg på värden; samma avbild för api och worker på amd64 och arm64; konfiguration via miljövariabler och `_FILE`‑hemligheter; tillstånd bara i volymer; icke‑root med `PUID`/`PGID`; `HEALTHCHECK` och migrationer vid start; compose‑röktest i CI per PR |
| Drift | `docker compose up` från dokumentationen ger en körbar instans på x86‑64 och arm64; minne ≤ 2 GB i vila med 50 000 böcker; Postgres‑uppgradering och återställning från backup dokumenterade och övade |
| Migrering | Alembic från v1‑schemat utan dataförlust; läsframsteg och manuella matchningar återkopplas via (sökväg, storlek) → innehållshash; v1‑Android fungerar under kompatibilitetsfönstret |

### Teststrategi

- Backend: pytest mot Postgres i CI (inte SQLite), inspelade leverantörssvar (`respx`/VCR), egenskapsbaserade tester för parsern (`hypothesis`), eval‑körning för matchning per stratum.
- Fixtures: syntetiska bibliotek med ritade sidor, Gutenberg‑EPUB:er, golden‑filnamn med riktiga titlar men utan upphovsrättsskyddat innehåll, provider‑kassetter beskurna till det som behövs.
- Webb: vitest för logik, Playwright för flöden, visuell regression på läsarna, axe för tillgänglighet.
- Android: enhetstester i `shared/`, Compose‑tester för läsare och nedladdning, Macrobenchmark för sidbyte.
- Kontraktstest mellan OpenAPI och klienter vid varje PR.
- Manuell verifieringslista mot riktiga tjänster (Comic Vine, Metron, MangaDex, AniList, SMTP, OPDS‑appar, KOReader, Kobo) körs före varje release och bockas av i releasen.

### Risker och motåtgärder

| Risk | Motåtgärd |
| --- | --- |
| Ombyggnaden drar ut på tiden för en ensam underhållare | Strangler‑ordning: v1 körs hela tiden; matchningsmotorn levereras först och ger värde direkt; varje fas lämnar systemet körbart |
| Leverantörs‑API:er ändras, stryper eller ändrar villkor | Header‑styrd rate limit, cache, alias, flera leverantörer per typ, GCD‑dump som offline‑fallback, villkoren kontrolleras innan svar checkas in |
| Matchningen blir "för försiktig" | Trösklar i `matching.toml`, eval per stratum visar effekten, alias lär över tid, bulk‑beslut i kön |
| Postgres som enda datalager avskräcker självhostare | En compose‑fil, `pg_dump` i api‑containern, dokumenterad majoruppgradering, "varför inte SQLite" i docs; utvärdera SQLite‑stöd efter lansering |
| Readium/Compose/KMP‑API:er rör sig | Lås versioner i version catalog, CI bygger varje PR, uppgradera i egna PR:er, inga iOS‑mål förrän de behövs |
| Procrastinate söker fler underhållare; foliate‑js saknar releaser | Kö bakom ett eget gränssnitt med pgqueuer som reserv; EPUB‑val avgörs av en spike i fas 3 där @readium/navigator är förstahandsval och foliate‑js vendoras på pinnad commit om den vinner |
| Readium Kotlin Compose‑navigatorer och androidx.pdf är fortfarande alfa/beta | Använd EpubNavigatorFragment via AndroidFragment (produktion) och ha PdfiumAndroidKt som PDF‑fallback; byt när biblioteken når stabil |
| Postgres FTS räcker inte för sökkänslan | `SearchBackend`‑gränssnitt; Meilisearch som valfri tjänst |
| Licenser | Licensval i fas 0; AGPL‑beroenden (PyMuPDF, ebooklib) byts ut om licensen är permissiv; ursprung dokumenteras i `NOTICE` |
| Projektet uppfattas som piratverktyg | Anskaffning är ett avstängt tillval med egen dokumentation; kärnan är bibliotek, matchning och läsning |
| Publik delning | Inga domäner, nycklar eller personuppgifter i kod, tester eller fixtures; byline tas bort ur den publika exporten |
