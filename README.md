# shipmap-landfix

Ships don't sail across the Sahara — or through France.

![before/after](landfix_before_after.png)

Coverage gaps in the 2012 AIS data behind [shipmap.org](https://www.shipmap.org)
were filled upstream by straight-line interpolation, fabricating hourly ship
positions marching across continents. This repo removes them: a 180 KB
land/water mask plus either a ~40-line client-side patch (`landfix.js`, no
shader or renderer changes) or a one-shot server-side re-bake of the day files
(`rebake_days.py`, zero client changes). Verified byte-identical output from
both paths; real canal, river, lake, and harbor traffic is preserved by
construction. Day 121 result: deep-interior track density −72%, Suez/Panama/
Mississippi within a few percent of untouched, total density −3.3%.
