# Offline Field Library

The library runs from this external SSD and keeps its reference files separate from the application. The launchers select a matching runtime for the computer and do not require Python to be installed.

## Start

- macOS: double-click Start Library.command. It supports 64-bit Intel and Apple Silicon Macs.
- Windows: double-click Start Library.bat. It supports 64-bit Intel/AMD Windows 10 and newer.
- Keep the launcher window open while using the library. It opens the dashboard at http://127.0.0.1:8765. Kiwix is at http://127.0.0.1:8081 when ZIM files are present.
- On first launch, the matching Python runtime is unpacked to that computer's local cache. This does not install Python system-wide and needs about 250 MB of free local disk space. Windows also extracts Kiwix to its local cache. Later launches reuse those files. Initial indexing can take a few minutes on a slower computer; the launcher waits for the dashboard before opening the browser.
- macOS may show a first-run security confirmation for the launcher or bundled tools; use Finder's Open action if you trust this library. Windows may also show a first-run SmartScreen warning for bundled tools. These platform prompts are outside the launcher's control.

## Contents and data

- Dashboard and server: app/
- References: content/<category>/
- SQLite full-text index: index/library.sqlite3
- Runtime archives and provenance: app/runtime/
- Backups: backups/

The dashboard and Kiwix are configured to bind to 127.0.0.1, so they are available only on the computer running them. Restart any Kiwix process launched before this loopback setting was added. It uses Python's standard library and SQLite FTS5; PDF search uses the vendored pure-Python pypdf package. No internet connection is needed at runtime.

The dashboard indexes embedded PDF text up to 100 MiB, 800 pages, and 1 million characters per PDF, plus HTML, text, and Markdown. Scanned image-only PDFs need OCR. Large map sheets are indexed by filename and source notes. Supported reference files include PDF, HTML, text, Markdown, images, ZIM, GeoJSON, GPX, and KML. A separate map viewer renders the bundled PMTiles regional basemap; it does not render arbitrary raw GIS datasets or live map services.

## Platform limits

Windows runtime is x64. Windows ARM devices may run it only if their Windows version supports x64 emulation. macOS supports Intel x86_64 and Apple Silicon arm64. Very old macOS releases may not support the bundled Python build. The current bundled Kiwix tools are separate per platform.

## Updating and backup

See UPDATE GUIDE.md for refreshing references and PROJECT HANDOFF.md for the full project history, architecture, content inventory, and Wikipedia replacement procedure. Keep a second copy of irreplaceable references and configuration. Back up app/ and content/; the search index can be regenerated. Do not unplug the SSD while the server or browser is using it.

## Troubleshooting

- If a launcher reports a missing runtime archive, check that app/runtime/packages is present.
- If first launch cannot unpack Python, free local disk space and launch again.
- If the dashboard does not open, keep the launcher running and visit http://127.0.0.1:8765. Check whether port 8765 is already in use.
- If ZIM files do not open, check that a ZIM file exists under content/encyclopedia/ and visit http://127.0.0.1:8081.
- If PDF search finds nothing, restart to rebuild the index. Scanned image-only PDFs need OCR; Poppler's pdftotext is an optional fallback.
- If the drive status is wrong, ensure the external SSD is mounted before launching. Do not remove it while the application is running.

## Offline North Carolina map

Open **Offline Map** in the dashboard for an interactive map covering all of North Carolina, with quick views for Albemarle, Harrisburg, and Charlotte. Viewer code, MapLibre GL JS, PMTiles client, Protomaps style package, fonts, and sprites are served locally. The statewide archive is stored at `content/maps/north-carolina.pmtiles`. The local server supports HTTP byte-range responses so the browser can read only needed PMTiles sections. It works with Wi-Fi and Ethernet disconnected. It is a browse-and-coordinate map, not turn-by-turn navigation, live traffic, or closure data.

The statewide archive is `content/maps/north-carolina.pmtiles`; its source, bounds, snapshot date, checksum, and safe update steps are in [`../content/maps/SOURCES.md`](../content/maps/SOURCES.md) and [`MAP GUIDE.md`](MAP%20GUIDE.md). The earlier `charlotte-region.pmtiles` remains as a fallback. Map archives are user data and excluded from GitHub with the rest of the map/reference collection.

## Military Field Manuals

The dashboard has a separate **Military Field Manuals** category linking to the T.REX ARMS Field Manual Vault. The catalog currently reports 4,215 publications and offers individual PDF and EPUB downloads. This is an online link, not a full offline mirror. The website robots policy disallows internal API/data endpoints, and no bulk archive is provided. Add selected items to `content/military/` only after checking their distribution statements and document each source in `content/military/SOURCES.md`. The Vault's public-domain description has not been independently confirmed for every document or embedded element.
