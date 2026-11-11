# Offline Field Library — Project Handoff

Last reviewed: November 4, 2026  
Library location: External volume named Extreme SSD  
Project folder: Offline Field Library

This document is the durable project record for future maintenance or AI-assisted changes. Read it together with README.html, app/README.md, UPDATE GUIDE.md, and the SOURCES.md notes inside content categories before changing the system.

## Purpose and decisions

This is a personal offline reference library for emergency preparedness and everyday technical reference. The user lives in Albemarle, North Carolina; parents live in Harrisburg, North Carolina; the regional map emphasis is Charlotte and surrounding counties. The vehicle-specific references are for a 2017 Toyota Tacoma Sport, long bed, 3.5L V6, 4WD, automatic transmission.

The system was designed to:

- Run from the external SSD and keep app files separate from reference content.
- Work offline after the runtime packages and reference files are present.
- Provide a local browser dashboard, category browsing, local document search, system status, and Kiwix access to ZIM archives.
- Favor open formats and trusted public sources, especially government agencies, universities, recognized standards bodies, and established safety organizations.
- Preserve existing data: the SSD must never be formatted, repartitioned, erased, or have existing reference files overwritten as part of routine maintenance.
- Make the library easy to back up and move. The SQLite search index can be rebuilt; the original references and application are the important data.

A 6–12 month review of large offline snapshots is reasonable. A new Wikipedia ZIM is a complete large archive, not a small patch, so update only after checking the current release and available space.

## Start the application

- macOS: double-click Start Library.command.
- Windows: double-click Start Library.bat.
- Keep the launcher window open while using the library. On Windows, press Ctrl+C in that window to stop it.
- Dashboard: http://127.0.0.1:8765
- Kiwix: http://127.0.0.1:8081
- The Python dashboard binds to localhost. Kiwix defaults to all interfaces, so both launchers now pass --address=127.0.0.1 to keep it local too. A Kiwix process already running from an older launcher must be stopped and restarted for this setting to take effect.
- If the dashboard is already running, the launchers open the existing dashboard rather than starting a duplicate.

Python does not need to be installed on the host computer. Compressed private Python runtime packages live under app/runtime/packages/. On first launch, a launcher unpacks the matching runtime into the computer's user cache; this is not a system-wide Python installation. macOS caches are under ~/Library/Caches/OfflineFieldLibrary/. Windows caches are under %LOCALAPPDATA%\OfflineFieldLibrary\. This uses local computer storage (allow roughly 250 MB free). The runtime archives are kept compressed on the SSD because exFAT uses much more space for thousands of small files than their logical sizes suggest.

Platform coverage currently packaged:

- macOS: Intel x86_64 and Apple Silicon arm64.
- Windows: x64 Intel/AMD. Windows ARM may run the x64 package only when that Windows version supports x64 emulation.
- First launch may show macOS or Windows security prompts for bundled tools. The launchers are not a signed/notarized commercial installer.
- The Windows launcher and runtime package were prepared and checksummed on macOS; they have not yet been run on a physical Windows computer.

Runtime versions and checksums are recorded in app/runtime/README.md. The dashboard uses Python's standard library, SQLite FTS5, and the vendored pure-Python pypdf package. Kiwix binaries are separately packaged for the relevant operating systems.

## Architecture and important paths

| Path | Role |
|---|---|
| Start Library.command | macOS launcher; selects Intel or Apple Silicon runtime |
| Start Library.bat | Windows double-click entry point |
| Start Library.ps1 | Windows runtime extraction, Kiwix startup, dashboard lifecycle |
| app/server.py | Local HTTP server, category listing, storage status, search index |
| app/index.html, app/style.css, app/app.js | Browser dashboard |
| app/vendor/pypdf/ | Bundled PDF text extraction library |
| app/bin/ and app/runtime/packages/ | Kiwix executables and compressed platform runtimes |
| content/<category>/ | References and category SOURCES.md files |
| index/library.sqlite3 | SQLite FTS5 index, automatically rebuilt at app startup |
| backups/ | Existing backups and safe staging area for large updates |

Application layout is intentionally simple: Python's built-in HTTP server serves the dashboard and files from content/, while SQLite FTS5 indexes text extracted from PDF, HTML, Markdown, and text documents. Kiwix runs as a separate local server for ZIM files. The dashboard does not index all Wikipedia articles; browse those through Kiwix.

PDF search has limits: embedded text is indexed up to 100 MiB, 800 pages, and 1 million characters per PDF. Scanned/image-only PDFs require OCR and will not produce text search hits. Large local map sheets are indexed by filename/source notes rather than parsing the map artwork. The application presents map files for download/opening; it does not currently render offline map tiles or GIS datasets as an interactive map.

## Current content inventory

Each of the following categories has a SOURCES.md note except encyclopedia, whose ZIM has a SHA-256 sidecar. There are approximately 81 reference files, plus source notes and the Wikipedia checksum file. “Other references” is an empty catch-all category.

| Category | Current coverage |
|---|---|
| Encyclopedia & general knowledge | English Wikipedia full “maxi” ZIM, wikipedia_en_all_maxi_2026-08.zim, about 119 GiB; SHA-256 sidecar beside it. |
| Medical & first aid | CDC wound care and practical emergency health PDFs; Red Cross first aid steps, burns, and severe bleeding static pages. |
| Wilderness survival | NPS trip planning and outdoor emergency plan; USGS map-and-compass guide. |
| Water procurement & purification | CDC water safety and emergency water storage quick references; EPA private wells guide. |
| Food storage & preservation | USDA Complete Guide to Home Canning (intro and guides 1–7); CDC power-outage food safety; UGA emergency food storage; NCHFP drying and storage guidance. |
| Agriculture & gardening | North Carolina central planting calendar and NC State vegetable gardening handbook, including soil, planting, pest, and seed-saving guidance. |
| Automotive maintenance | 2017 Tacoma owner’s manual, quick reference, warranty/maintenance guide, NHTSA tire reference, roadside quick reference, Tacoma manual index, and Toyota TIS link. The full factory repair manual is not stored. |
| Electrical systems | CPSC household wiring hazard/safety references and USFA electrical fire safety. Safety material is included; this is not a DIY live-wiring course. |
| Plumbing & home repair | EPA septic homeowner guide and NC State preventative home maintenance. This remains a relatively small category. |
| Generators & alternative energy | CPSC and USFA portable-generator safety, DOE residential renewable energy and solar/resilience material. |
| Amateur radio & emergency communications | FCC Part 97 rules, ARRL ARES, IARU emergency communications, NOAA weather radio materials, a Charlotte-region NOAA quick reference, and a saved NWS GSP page. |
| Navigation & topographic maps | About 25 local/state/county map references, including Albemarle, Harrisburg, Charlotte, Concord, Cabarrus, Mecklenburg, Stanly, and nearby areas; includes USGS GeoPDFs. These are mostly static files, not live routing. |
| Emergency preparedness & evacuation | CDC preparedness/supply PDFs, saved ReadyNC planning, evacuation and kit pages, and a print-friendly household emergency plan worksheet. Live alerts, current shelter status, and linked maps still need internet. |

The library grew in phases: the original dashboard and category shell; fixes to the overlapping “Explore the library” link and the menu-closing interaction; addition of a large English Wikipedia ZIM and local map/reference material; PDF text search and source notes; Tacoma-specific references; then category gap-filling and portable launchers. Saved webpage snapshots are useful offline for their text, but embedded links may lead to online-only resources.

Notable deliberate gaps: no full Toyota factory repair manual was copied because Toyota's service information is accessed through its official Techinfo service and may require a subscription; no claim is made that emergency guidance or live information is complete.

## Map implementation update — November 8, 2026

The dashboard links to `app/map.html`, which uses vendored MapLibre GL JS, PMTiles JS, Protomaps basemap styles, local glyphs/sprites, and a local vector archive. It supports quick jumps and coordinate readout and lists the static map PDFs alongside it. It is a reference map rather than live routing, GPS navigation, traffic, or current road status. The original Charlotte-area archive remains on the SSD as a fallback.

The initial Charlotte archive was extracted with PMTiles CLI 1.31.2 from the Protomaps snapshot dated 2026-11-07. On 2026-11-08, the viewer expanded to North Carolina using bounds -84.4, 33.7, -75.3, 36.7, zoom 0–14. The statewide file is about 388 MB, SHA-256 `25e85890683a14482ba15159031c6f12075b6e835aa1589acd51527f8d27dc58`. Remote extraction transferred about 427 MB without downloading the 129 GB planet archive. The old 57 MB Charlotte map remains at `content/maps/charlotte-region.pmtiles`. See `app/MAP GUIDE.md` and `content/maps/SOURCES.md` for source, attribution, and update steps. The server supports byte-range requests so the browser reads only needed sections of PMTiles.

## Military Field Manuals collection — November 9, 2026

On November 9, 2026, a separate `military` category linked to the T.REX ARMS Field Manual Vault and `content/military/SOURCES.md` recorded its reported catalog size. At that point the project had not downloaded Vault documents. The user later supplied a collection from a friend; see the November 10 update below for the current local collection and application behavior. The source website's general public-domain description has not been independently confirmed for every item.

## Incremental search indexing and local manuals — November 10, 2026

The user supplied a collection received from a friend who downloaded it from the T.REX ARMS Vault. The SSD now contains 4,215 PDF and 4,215 EPUB files (about 67 GB total), grouped by collection, branch, and publication series. The user's report is the provenance; individual source URLs and distribution statements have not been independently verified. `content/military/SOURCES.md` records this limitation and inventory. The content itself is user data and remains outside GitHub.

The previous server rebuilt all full-text entries synchronously before binding port 8765. The macOS launcher waits five minutes for the dashboard and then gives up, so large PDF additions could prevent startup. The server now binds first and starts index reconciliation on a background thread. SQLite `file_state` stores each indexed path, size, modification time, and indexed time. Existing FTS entries migrate into this manifest so unchanged content can be retained; changed/new files are extracted in small batches, deleted files are removed, and progress/error state is exposed at `/api/index-status`. Search can read the last committed index while batches are processed. If the manifest is missing or empty, the first pass may still take a long time, but the dashboard is available throughout.

The military category uses a dedicated local PDF full-text search with collection and branch filters. It does not send all thousands of file paths to the browser. The main search excludes the military category by default and offers an explicit **Include military manuals** checkbox. EPUB files remain available from the SSD folder but their contents are not indexed by this implementation. A later development option is EPUB indexing if it proves valuable.

## Updating the Wikipedia ZIM safely

The current file is the August 2026 English Wikipedia maxi archive, around 119 GiB. Kiwix describes maxi as the full version; nopic is smaller but removes pictures. Kiwix currently says incremental ZIM updates are not available, so plan for downloading a complete replacement, not a small delta. See the [Kiwix catalog FAQ](https://get.kiwix.org/en/solutions/catalog/) and the [official Kiwix library](https://library.kiwix.org/).

At the last capacity check, the SSD had about 762 GiB free, enough to stage another approximately 119 GiB file while keeping the current one. Check again before every update because other content may have been added.

1. Connect to the internet and confirm the SSD is mounted. Make a separate backup of irreplaceable data if one is not already current.
2. Browse the Kiwix library/catalog and select the current English Wikipedia all_maxi ZIM. Check the release month, exact filename, size, language, and variant. Download the matching SHA-256 file when available.
3. Download to a staging folder outside content/, for example backups/_incoming/. Do not download a partial file into content/encyclopedia/; the app scans that content tree.
4. Verify the checksum before changing the current archive. On macOS, from the staging folder, run shasum -a 256 -c <downloaded-checksum-file>. On Windows, compare Get-FileHash <zim-file> -Algorithm SHA256 against the publisher's value.
5. Keep the old ZIM until the new file's checksum is correct. Stop the library launcher before swapping archives so Kiwix is not reading the file.
6. Preserve the old ZIM under backups/zim-archive/ (or on a separate backup drive) and place the new, versioned ZIM plus checksum in content/encyclopedia/. Do not overwrite a different version using the same filename.
7. Start the library. Confirm the encyclopedia category lists the new file, open Kiwix at port 8081, and open several pages. If it fails, stop the launcher and restore the old ZIM from the backup.
8. Keep the old copy until the replacement has worked and another backup exists. The search index does not index Wikipedia article bodies; it only lists the ZIM and lets Kiwix read it.

The download can take hours. Use a resumable download/torrent option if available, maintain power, and avoid disconnecting the SSD during transfer. Kiwix's current catalog notes that English Wikipedia archives are very large and that ZIM files are not incrementally updated.

## Adding or refreshing other references

1. Choose a trustworthy source and record the publisher, source URL, publication/update date, retrieval date, and license/terms where relevant.
2. Download to a staging location outside content/. Check file size, checksum if provided, and readability.
3. Give it a descriptive stable filename; put the reference in the matching content/<category>/ folder.
4. Add a note to that folder's SOURCES.md. This records provenance and helps a future maintainer decide whether to refresh or remove it.
5. Restart the launcher so the search index is rebuilt. Check the document appears in the intended category and search a distinctive phrase from its text.
6. Keep a second copy before replacing or removing existing files. Do not store temporary downloads or unfinished files in content/.

Prefer official local government, state extension, federal agency, established safety organization, and manufacturer sources. Avoid copying copyrighted paid manuals or proprietary service databases. Local hazards, alerts, routes, contacts, and medical information should be reviewed periodically because saved snapshots become stale.

## Backup and future-agent instructions

- Back up the whole app/ and content/ folders plus root launcher/documentation files to a second physical drive. The index/ folder can be regenerated, but it is small and may be copied for convenience.
- Before changing the SSD, inspect mounted volumes and confirm the target volume. Never format, partition, erase, or repartition it.
- Do not overwrite or delete the Wikipedia ZIM, reference files, source notes, or existing backups without the owner’s explicit approval, an explicit plan, and a verified separate copy.
- Keep application code, runtimes, and reference content separated as they are now.
- Use versioned filenames for large replacements. Stage first, verify checksums, and preserve rollback copies.
- When an AI agent resumes this project, have it read this document and the relevant README/SOURCES.md files first. State the exact requested change and preserve all unrelated files.
