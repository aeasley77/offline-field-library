# GitHub source backup and sharing

Public source repository: <https://github.com/aeasley77/offline-field-library>

## What GitHub contains

The repository contains the application source, macOS and Windows launchers, category `SOURCES.md` provenance notes, project maintenance documents, the technical case-study PDF, and the small vendored `pypdf` package used for PDF text search.

It does not contain the approximately 119 GiB Wikipedia ZIM, downloaded reference PDFs and maps (including the 388 MB statewide PMTiles archive and 57 MB Charlotte fallback), generated SQLite search index, backups, compressed Python runtimes, or Kiwix platform binaries. The `.gitignore` excludes those data and binary paths. Keep the reference library backed up separately on another physical drive; GitHub is not a backup of the offline content.

The repository is a source and documentation copy, not a full portable application package. To run the finished library, use the full directory on the external SSD and its bundled launchers, Python runtimes, Kiwix executables, and local content data. Those runtime and content files are intentionally omitted from GitHub.

The dashboard's **Military Field Manuals** category searches local PDFs and includes collection/branch filters. The main search excludes military manuals by default and has a toggle to include them. The user's 4,215 PDF and 4,215 EPUB copies remain on the SSD and are excluded from GitHub. Their user-reported provenance and inventory are documented in `content/military/SOURCES.md`.

## Share it with coworkers

The repository is public, so coworkers can view and clone the source at the link above. Share the technical case-study PDF from `docs/` as well, or download it for a presentation. The large reference collection and runtime packages remain excluded.

## Continue development

Clone the repository when making source changes. Keep code, launchers, documentation, and category provenance notes under version control. Keep downloaded library content and platform runtime packages on the SSD. Before refreshing Wikipedia, follow the checksum and rollback steps in `PROJECT HANDOFF.md` and `UPDATE GUIDE.md`; a ZIM refresh is a complete large-archive replacement, not a routine Git update.
