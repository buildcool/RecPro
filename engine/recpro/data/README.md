# Data shipped with the engine

## places.npz

The offline place table: every town of 1,000+ people and every district seat (about 172,000),
with its state, country, position and population. RecPro names where a photo was taken from it,
so no position is ever sent anywhere.

- Source: [GeoNames](https://www.geonames.org) `cities1000.zip`, `admin1CodesASCII.txt` and
  `countryInfo.txt` from https://download.geonames.org/export/dump/
- License: [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
  Place names © GeoNames contributors.
- Rebuild: download the three files to `.cache/geonames`, then
  `engine/.venv/Scripts/python -I scripts/build_places.py .cache/geonames engine/recpro/data/places.npz`

The map's country outlines come from [Natural Earth](https://www.naturalearthdata.com) (public
domain), through the `world-atlas` package in the UI.
