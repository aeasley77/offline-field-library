# Offline Field Library

A portable, local-first emergency and technical reference library for macOS and Windows. The dashboard runs on `127.0.0.1`; it serves categorized local references, searches text extracted from documents, reports system status, and links to Kiwix for ZIM archives.

## Start the library

- macOS: double-click `Start Library.command`.
- Windows 10 or newer, x64: double-click `Start Library.bat`.
- Open the dashboard at <http://127.0.0.1:8765>. Kiwix is at <http://127.0.0.1:8081> when a ZIM archive is installed.

The full portable package on the owner's SSD includes compressed platform Python runtimes and Kiwix builds. Those binary packages are intentionally excluded from this source repository. See [`app/README.md`](app/README.md) and [`app/runtime/README.md`](app/runtime/README.md) for runtime details.

## Data is separate from source

This GitHub repository contains application source, launchers, architecture/maintenance documentation, and per-category source manifests. It deliberately does **not** contain the downloaded reference collection, the Wikipedia ZIM, maps, local search database, backups, Python runtime archives, or Kiwix binaries. Keep those on the external SSD and back them up separately. The `.gitignore` protects those paths from accidental commits.

Empty content folders are represented by `.gitkeep` files. Put real documents into the matching `content/<category>/` folder on the SSD and document their provenance in that folder's `SOURCES.md`. Do not put the Wikipedia `.zim` or downloaded PDFs into GitHub.

## Project documentation

- [`PROJECT HANDOFF.md`](PROJECT%20HANDOFF.md): architecture, decisions, content inventory, history, safe update procedures, and future-agent notes.
- [`UPDATE GUIDE.md`](UPDATE%20GUIDE.md): practical content refresh and backup steps.
- [`app/MAP GUIDE.md`](app/MAP%20GUIDE.md): statewide offline map details and safe tile refresh steps.
- `content/military/SOURCES.md`: T.REX ARMS Vault reference and instructions for adding verified manuals.
- [`docs/Offline_Field_Library_Technical_Case_Study.pdf`](docs/Offline_Field_Library_Technical_Case_Study.pdf): shareable technical case study.
- `content/<category>/SOURCES.md`: provenance and coverage notes by category.

## Important limits

The library is for offline reference and does not provide live alerts, current shelter status, live routing, or GPS navigation. It includes a zoomable North Carolina reference map. Search indexes extractable PDF text; scanned image-only PDFs need OCR. Consult current official guidance when online and keep safety-critical references up to date.

## Development source checkout

The files here are the maintainable application source, not the complete ready-to-run SSD package. The portable runtimes, Kiwix executables, search database, backups, and downloaded reference collection are omitted from GitHub. The small pure-Python `pypdf` package is vendored under `app/vendor/` so PDF text search remains part of the application source. This source checkout is not the complete ready-to-run SSD package; use the external SSD for portable launchers and the full offline library.
