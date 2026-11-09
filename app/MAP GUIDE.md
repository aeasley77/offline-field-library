# Offline regional map guide

## What is included

The dashboard's **Offline Map** button opens a zoomable, pan-able vector map centered on the Charlotte region. Quick-jump buttons mark Albemarle, Harrisburg, and Charlotte. The side panel lists the existing local NCDOT and USGS map-sheet PDFs. Clicking the map displays WGS84 latitude/longitude coordinates.

All browser code and visual assets live under `app/map-assets/`: MapLibre GL JS 6.17.0, PMTiles JS 4.5.0, Protomaps basemaps 5.7.2, a local worker, CSS, sprites, and Noto Sans glyph ranges for Latin labels. Runtime code uses no CDN, API key, outside map service, or online font server. The Python server serves `.pmtiles` byte ranges so MapLibre can read only tile data needed for the current view.

The regional dataset lives at `content/maps/charlotte-region.pmtiles`. The current archive is 60 MB and spans `-81.5,34.7,-79.5,36.0`, zoom 0–14, with OpenStreetMap data dated 2026-11-07. This is a general road, place, land, and water basemap. It does not include live conditions, turn-by-turn routing, satellite imagery, or GPS from the Mac.

## Refreshing the basemap

The Protomaps source is a large global PMTiles file. Use the `pmtiles` CLI's remote `extract` function to download only this region; do not download the 129 GB planet archive in full.

1. While online, get the current `pmtiles` CLI binary for the computer from the official [Protomaps releases](https://github.com/protomaps/go-pmtiles/releases). The CLI is needed to build an update, not to run the library.
2. Check the current daily build at [Protomaps basemap downloads](https://docs.protomaps.com/basemaps/downloads). Use its advertised build date in the source URL and record the date in `content/maps/SOURCES.md`.
3. Extract a candidate into `backups/_incoming/charlotte-region-CANDIDATE.pmtiles` with the same region and max zoom:

   ```sh
   pmtiles extract https://build.protomaps.com/YYYYMMDD.pmtiles backups/_incoming/charlotte-region-CANDIDATE.pmtiles --bbox=-81.5,34.7,-79.5,36.0 --maxzoom=14
   ```

4. Inspect and verify the candidate before touching the current archive:

   ```sh
   pmtiles show backups/_incoming/charlotte-region-CANDIDATE.pmtiles --header-json
   pmtiles verify backups/_incoming/charlotte-region-CANDIDATE.pmtiles
   shasum -a 256 backups/_incoming/charlotte-region-CANDIDATE.pmtiles
   ```

   Confirm that bounds, tile type (`mvt`), and zoom range are sensible. Record the new checksum and source date.
5. Stop the library. Move the existing `content/maps/charlotte-region.pmtiles` into a dated directory under `backups/regions/`, then copy the verified candidate to the canonical path. Keep the prior map until the new one has opened correctly.
6. Start the library, open **Offline Map**, check each quick-jump location and several zoom levels, then disconnect the network and reload the map. If it fails, stop the library and restore the previous archive.

The current archive's SHA-256 is `f375499abbb6b23f3d0789b484c58154ffc427424c3edf72a64f8dce66d29ca4`. Its source details and exact build command are recorded in `content/maps/SOURCES.md`.

## Data licensing and attribution

Keep the visible OpenStreetMap credit and link on the map. The OSM data is ODbL-licensed; see <https://www.openstreetmap.org/copyright>. Browser library versions and their licenses are recorded in `app/map-assets/THIRD_PARTY_NOTICES.md`; the Noto Sans font license is bundled at `app/map-assets/fonts/OFL.txt`.

The 60 MB regional archive is excluded from the GitHub source repository along with the rest of `content/`. Copy it separately when restoring or migrating the full portable library.
