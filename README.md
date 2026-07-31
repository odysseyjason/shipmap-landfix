# shipmap-landfix

Removes fabricated over-land ship tracks from the [shipmap.org](https://www.shipmap.org)
2012 merchant-fleet visualization — the "ships" that sail in a straight line
across Africa, Arabia, or Central America.

**Cause.** Coverage gaps in the 2012 satellite AIS data were filled upstream by
straight-line interpolation between distant fixes, at hourly steps. A ship that
went dark in the Red Sea and reappeared off West Africa acquires days of hourly
fixes marching across the Sahara. These are fabrications, not observations.

**Fix.** Any fix on *deep land* is replaced with the format's existing missing-
data sentinel (`0xFFFF,0xFFFF`). "Deep land" excludes: ocean, lakes (incl. the
Caspian), major navigable river corridors, ship canals (Suez, Panama, Kiel,
Corinth, Welland), and a ~10 km coastal buffer for harbors/estuaries — so real
Great Lakes, Mississippi, Parana, Amazon, and canal traffic is untouched. The
renderer already skips missing fixes: **no shader or rendering changes needed.**

## Results (day 121, 2012-05-01)
- 70,066 of 550,552 fixes culled (12.7%) — overwhelmingly interpolation
  fabrications and inland-misplaced points
- Deep-interior (>60 km inland) track density: **−72%**
- Suez −3%, Panama −2%, Mississippi −1%, Great Lakes −6% (coastal-resolution
  trims), total world density −3.3%

## Contents
- `landfix.js` — browser module. `LandFix.loadMask(pngUrl)` once, then
  `LandFix.cullDayBuffer(arrayBuffer, mask)` on each downloaded day file before
  GL upload. ~80 ms per day file; mask PNG is 177 KB, cacheable forever.
- `valid_water_4096.png` — the validity mask (white = valid water), 4096²,
  ~10 km cells. `land_2048.png` — routing land mask (see A* note).
- `rebake_days.py` — zero-client-change alternative: re-bake corrected day
  files server-side once and deploy them; the live site needs no edits at all.
  Verified byte-identical output to `landfix.js`.
- `make_masks.py` — regenerate/customize masks from Natural Earth shapefiles
  (land, lakes, river centerlines; public domain). Canal carvings, the Caspian
  polygon, coastal buffer width, and river corridor width are explicit,
  tunable constants — our values are defaults, not gospel.

## Optional further step: within-hour rerouting
Culling removes fabricated fixes; a second class remains where a single hourly
chord between two genuine water fixes clips a headland (renderer interpolation,
not data). We have a working A* water-router (`land_2048.png` is its cost grid;
~1,800 cached routes serve a full day in ~1 s). It is not drop-in for the
current renderer, which lerps one src→dst attribute pair per hour; expressing a
multi-bend path needs sub-hour position attributes (~4× vertex buffer) or CPU
paths for the few thousand affected ships/day. Python reference implementation
available on request — we use it in our own offline renders.

## License / provenance
Code MIT. Masks derived from Natural Earth 10m land, lakes, and
rivers+lake-centerlines (public domain), with hand-added ship canals and
Caspian Sea. Built by reverse-engineering the shipmap day-file format
(25 hourly big-endian uint16 mercator pairs per ship per day) from the site's
own inline loader; no shipmap data is redistributed here.

Offered with admiration for the original work by Kiln and the UCL Energy
Institute. Contact: Jason Buchheim.
