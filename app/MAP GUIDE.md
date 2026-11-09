# Offline North Carolina map guide

## What is included

The dashboard's **Offline Map** button opens a zoomable, pan-able vector map covering all of North Carolina and a small buffer across nearby state borders. Quick-jump buttons show the full state, Albemarle, Harrisburg, and Charlotte. The side panel lists the existing local NCDOT and USGS map-sheet PDFs. Clicking the map displays WGS84 latitude/longitude coordinates.

All browser code and visual assets live under `app/map-assets/`: MapLibre GL JS 6.17.0, PMTiles JS 4.5.0, Protomaps basemaps 5.7.2, a local worker, CSS, sprites, and Noto Sans glyph ranges for Latin labels. Runtime code uses no CDN, API key, outside map service, or online font server. The Python server serves `.pmtiles` byte ranges so MapLibre can read only tile data needed for the current view.

The statewide dataset lives at `content/maps/north-carolina.pmtiles`. The archive is about 388 MB and spans `-84.4,33.7,-75.3,36.7` (WGS84), zoom 0–14, with OpenStreetMap data dated 2026-11-07. The rectangle includes nearby areas across state borders so roads do not stop at the boundary. This is a general road, place, land, and water basemap. It does not include live conditions, turn-by-turn routing, satellite imagery, or GPS from the Mac. The previous 57 MB Charlotte-area archive remains at `content/maps/charlotte-region.pmtiles` as a fallback.

## Refreshing the basemap

The Protomaps source is a large global PMTiles file. Use the `pmtiles` CLI's remote `extract` function to download only North Carolina; do not download the planet archive in full. Statewide extraction transferred about 427 MB and produced a 388 MB archive.

1. While online, get the current `pmtiles` CLI binary for the computer from the official [Protomaps releases](https://github.com/protomaps/go-pmtiles/releases). The CLI is needed to build an update, not to run the library.
2. Check the current daily build at [Protomaps basemap downloads](https://docs.protomaps.com/basemaps/downloads). Use its advertised build date in the source URL and record the date in `content/maps/SOURCES.md`.
3. Extract a candidate into `backups/_incoming/north-carolina-CANDIDATE.pmtiles` with the state bounds and max zoom:

   ```sh
   pmtiles extract https://build.protomaps.com/YYYYMMDD.pmtiles backups/_incoming/north-carolina-CANDIDATE.pmtiles --bbox=-84.4,33.7,-75.3,36.7 --maxzoom=14
   ```

4. Inspect and verify the candidate before touching the current archive:

   ```sh
   pmtiles show backups/_incoming/north-carolina-CANDIDATE.pmtiles --header-json
   pmtiles verify backups/_incoming/north-carolina-CANDIDATE.pmtiles
   shasum -a 256 backups/_incoming/north-carolina-CANDIDATE.pmtiles
   ```

   Confirm that bounds, tile type (`mvt`), and zoom range are sensible. Record the new checksum and source date.
5. Stop the library. Keep the current file as a dated fallback or replace `content/maps/north-carolina.pmtiles` only after verifying the candidate; preserve the last working archive until the new map opens correctly.
6. Start the library, open **Offline Map**, check each quick-jump location and several zoom levels, then disconnect the network and reload the map. If it fails, stop the library and restore the previous archive.

The current statewide archive's SHA-256 is `25e85890683a14482ba15159031c6f12075b6e835aa1589acd51527f8d27dc58`. Its source details and exact build command are recorded in `content/maps/SOURCES.md`.

## Data licensing and attribution

Keep the visible OpenStreetMap credit and link on the map. The OSM data is ODbL-licensed; see <https://www.openstreetmap.org/copyright>. Browser library versions and their licenses are recorded in `app/map-assets/THIRD_PARTY_NOTICES.md`; the Noto Sans font license is bundled at `app/map-assets/fonts/OFL.txt`.

Both map archives are excluded from the GitHub source repository along with the rest of `content/`. Copy them separately when restoring or migrating the full portable library.
