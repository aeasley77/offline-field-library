# Charlotte–Harrisburg–Albemarle map pack

- `north-carolina.pmtiles` — 388 MB Protomaps vector basemap clipped to bounds -84.4, 33.7, -75.3, 36.7 (WGS84), covering North Carolina and a small buffer across neighboring state borders. Snapshot: OpenStreetMap through 2026-11-07. Zoom levels 0–14. Built from the official Protomaps daily archive with PMTiles CLI 1.31.2 using `pmtiles extract https://build.protomaps.com/20261107.pmtiles north-carolina.pmtiles --bbox=-84.4,33.7,-75.3,36.7 --maxzoom=14`. Remote extraction transferred about 427 MB; the 129 GB planet archive was not downloaded in full. Verified with `pmtiles verify`. SHA-256: `25e85890683a14482ba15159031c6f12075b6e835aa1589acd51527f8d27dc58`.
- `charlotte-region.pmtiles` — 57 MB prior regional map retained on the SSD as a fallback. Its checksum and regional extraction details are in the previous Git history; see commit `14616de4a1528ac294fe26aed8d4fb45c2e92d74`.
- Data source: [Protomaps basemap downloads](https://docs.protomaps.com/basemaps/downloads), derived from OpenStreetMap and Natural Earth. OpenStreetMap data is licensed under ODbL. The dashboard displays `© OpenStreetMap contributors` attribution and a license link. Map archives are not stored in GitHub; keep and back them up on the external SSD alongside the other map files.
- The archive is a street/place/water vector map, not satellite imagery or a route graph. It has no current road closures, alerts, or turn-by-turn directions. The existing county maps and GeoPDF quadrangles remain useful static local references.

Retrieved 2026-11-04 from official North Carolina Department of Transportation (NCDOT) and U.S. Geological Survey (USGS) sources.

## NCDOT road maps

- `2025-2026-state-map-front.pdf` and `2025-2026-state-map-back.pdf` — North Carolina Official State Transportation Map, 2025–26. Source: https://www.ncdot.gov/travel-maps/maps/Pages/state-transportation-map.aspx
- `Mecklenburg_CountyMap_OneSheet.pdf`, `Cabarrus_CountyMap_OneSheet.pdf`, `Stanly_CountyMap_OneSheet.pdf`, and `Union_CountyMap_OneSheet.pdf` — NCDOT county one-sheet maps. Source directory: https://xfer.services.ncdot.gov/imgdot/DOTCountyMaps/PDF_CountyOneSheet/

## USGS topographic maps

These are official US Topo GeoPDF quadrangles. The date in each filename is the publication date. Sheets downloaded:

- Albemarle (2022-08-17), Badin (2022-08-30), Charlotte East (2022-08-30), Charlotte West (2022-08-30)
- Concord (2022-08-30), Concord SE (2022-08-30), Derita (2022-08-17), Harrisburg, NC (2022-08-17)
- Kannapolis (2022-08-30), Lake Norman North (2023-07-27), Locust (2022-08-17), Matthews (2022-08-30)
- Mint Hill (2022-08-17), Morrow Mountain (2022-08-30), Mount Pleasant, NC (2022-08-17), Oakboro (2022-09-01)
- Stanfield, NC (2022-08-17), Weddington (2022-08-30), Fort Mill, SC (2024-07-23), Lake Wylie, SC (2024-04-12)

USGS map source and product information: https://www.usgs.gov/programs/national-geospatial-program/topographic-maps
USGS availability index: https://index.nationalmap.gov/arcgis/rest/services/USTopoAvailability/MapServer

## Use notes

The NCDOT state and county maps provide regional road context; the USGS GeoPDFs provide detailed topographic context and may support geolocation in a compatible PDF reader. These are static maps, not live navigation: they do not show current closures, construction, hazards, or changing access conditions. Check the publication dates printed in the filenames and maps. Keep a paper map and compass available as backup.
