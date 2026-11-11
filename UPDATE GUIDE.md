# Updating the Offline Field Library

Updates require an internet connection. The dashboard itself remains local and usable offline; only downloading fresh references or software needs connectivity.

## Safe update routine

1. Connect to the internet and mount the SSD.
2. Check the source, publication date, license, and file size before downloading. Prefer government or recognized public institutions for safety-critical references.
3. Download new material to a temporary folder outside `content/` (for example, `backups/_incoming/`). The app scans `content/`, so do not stage partial files there. Do not replace the working copy yet.
4. Verify the publisher's checksum when provided. Open the downloaded file and confirm it is readable.
5. Move the new version into the relevant `content/<category>/` folder under a new, dated filename. Keep the previous version until you have confirmed the replacement works.
6. New or changed local PDFs, HTML, text, and Markdown files are detected and added to the search index in the background when the dashboard next starts. The dashboard is available while indexing runs; its search status shows progress. An unchanged file keeps its existing index entry. Deleted files are removed from search on the next start.
7. Keep the superseded file in a backup/archive folder until the owner explicitly decides otherwise. Do not delete or overwrite existing files as part of a routine update.

## Kiwix archives

Wikipedia ZIM archives are complete files; Kiwix does not currently provide incremental updates. The detailed no-overwrite replacement and rollback steps are in [PROJECT HANDOFF.md](PROJECT%20HANDOFF.md#updating-the-wikipedia-zim-safely).

Browse the [Kiwix Library](https://library.kiwix.org/) or official [download tree](https://download.kiwix.org/zim/) and compare variants. `mini` is compact; `nopic` contains full articles without pictures; `maxi` includes pictures and takes more space. Check the archive date, language, and listed size before downloading. Large files can take time; use Kiwix's torrent option if available and useful for resumable transfers. Keep the existing ZIM until the updated archive starts correctly in Kiwix Server.

## Maps

Select areas you may realistically need, such as home, likely evacuation destinations, and routes between them. Save offline-capable map files or print-ready maps with source and date in the filename or a companion note. OpenStreetMap-derived data is useful for roads, trails, and places, but map completeness and freshness vary by location. Keep essential routes and topographic maps in a format you can open without a network connection.

## Other references

Check official publishers for updated PDFs or offline packages. Preserve citation/source URLs and publication dates in filenames or a simple notes file. Review licenses and terms before redistributing materials. Maintain a second backup of the `content/` folder; the SSD is one physical device and can fail or be lost.

For a large new PDF collection, expect its first indexing pass to take longer. The dashboard starts before indexing finishes. Military manuals have a dedicated local search and collection/branch filters; the main search excludes them by default, with an option to include them. EPUB files are available from their content folder but are not currently full-text indexed.
