#!/usr/bin/env python3
"""make_masks.py - regenerate landfix mask PNGs from Natural Earth shapefiles.

  pip install numpy pillow pyshp
  # place ne_10m_land.shp/.dbf/.shx (+ optionally ne_10m_lakes.*,
  # ne_10m_rivers_lake_centerlines.*) in this directory, then:
  python3 make_masks.py

Tunables live in the LandRouter class below: BUILTIN_SEAS (Caspian), the
CANALS list, river corridor width, and the one-cell coastal buffer.
"""
import os, sys
import numpy as np

class LandRouter:
    """Reroutes hourly chords that cross land through water instead, via A* on a
    coarse ocean grid. Policy (canal/river safe):
      - a segment is only rerouted if BOTH endpoints are in water cells AND the
        straight chord touches land: ships with fixes in canals, rivers, or
        harbors are never altered, because their on-land fixes exempt them.
      - if no water path exists (or the segment wraps the dateline), the
        original chord is kept.
    Mask is rasterized from Natural Earth land polygons (equirect shapefile)
    onto the web-mercator grid; results cached beside the shapefile."""

    # Seas absent from NE land holes/lakes: carved as water in routing AND validity
    BUILTIN_SEAS = {
        "caspian": [(47.1,45.9),(48.6,46.7),(50.0,46.9),(51.5,46.6),(52.6,45.4),
                    (53.2,43.8),(53.6,42.3),(54.0,41.0),(53.9,39.6),(53.8,38.0),
                    (53.9,37.2),(53.0,36.85),(51.5,36.75),(50.0,36.9),(49.1,37.4),
                    (48.9,38.3),(49.0,39.5),(48.9,40.8),(49.4,42.2),(48.6,43.5),(47.6,44.6)],
    }

    def __init__(self, shp_path, W_render, grid=2048, lakes_shp=None, rivers_shp=None,
                 extra_water=None):
        """shp_path: NE land polygons. Optional lakes_shp (polygons, carved as
        water into BOTH routing and validity) and rivers_shp (centerlines,
        carved as valid corridors only). If lakes/rivers files sit beside the
        land shapefile with standard NE names they are found automatically."""
        self.W = W_render
        self.G = grid
        self.s = W_render / grid
        base = os.path.dirname(os.path.abspath(shp_path))
        if lakes_shp is None:
            p = os.path.join(base, "ne_10m_lakes.shp")
            lakes_shp = p if os.path.exists(p) else None
        if rivers_shp is None:
            p = os.path.join(base, "ne_10m_rivers_lake_centerlines.shp")
            rivers_shp = p if os.path.exists(p) else None
        if lakes_shp is None:
            print("WARNING: ne_10m_lakes.shp not found beside land shapefile - "
                  "ALL lakes will be treated as land (Great Lakes etc. blocked)", file=sys.stderr)
        if rivers_shp is None:
            print("WARNING: ne_10m_rivers_lake_centerlines.shp not found beside land shapefile - "
                  "ALL rivers will be treated as land (Parana, Amazon etc. blocked)", file=sys.stderr)
        landF, validF = self._masks(shp_path, lakes_shp, rivers_shp, grid*2, extra_water)
        # routing grid: land if any of the 2x2 fine cells is land (conservative)
        self.land = landF.reshape(grid,2,grid,2).any(axis=(1,3))
        self.valid = validF          # validity checked at fine resolution
        self.Gv = grid*2
        self.sv = W_render / self.Gv
        self.cache = {}

    @staticmethod
    def _merc(G):
        R = G / (2*np.pi)
        def f(lon, lat):
            lat = np.clip(lat, -85.051, 85.051)
            x = (lon + 180.0) / 360.0 * G
            y = G/2 - R*np.log(np.tan(np.pi/4 + np.radians(lat)/2))
            return x, y
        return f

    def _masks(self, land_shp, lakes_shp, rivers_shp, G, extra_water=None):
        tag = f"{'L' if lakes_shp else ''}{'R' if rivers_shp else ''}v3"
        if extra_water:
            import hashlib
            tag += hashlib.md5(open(extra_water,'rb').read()).hexdigest()[:6]
        cpath = f"{land_shp}.mask{G}{tag}.npz"
        if os.path.exists(cpath):
            z = np.load(cpath); return z["land"], z["valid"]
        import shapefile
        from PIL import Image as _I, ImageDraw as _D
        merc = self._merc(G)
        im = _I.new("1", (G, G), 0)
        dr = _D.Draw(im)
        def draw_polys(path, fill):
            sf = shapefile.Reader(path)
            for sh in sf.shapes():
                pts = np.asarray(sh.points)
                parts = list(sh.parts) + [len(pts)]
                for i in range(len(parts)-1):
                    ring = pts[parts[i]:parts[i+1]]
                    if len(ring) < 3: continue
                    x, y = merc(ring[:,0], ring[:,1])
                    dr.polygon(list(zip(x.tolist(), y.tolist())), fill=fill)
        draw_polys(land_shp, 1)
        if lakes_shp:
            draw_polys(lakes_shp, 0)          # lakes are water for routing & validity
        land = np.asarray(im, bool)

        # validity = water, dilated ~1 cell (harbors/estuaries), plus river corridors
        water = ~land
        v = water.copy()
        v[1:,:] |= water[:-1,:]; v[:-1,:] |= water[1:,:]
        v[:,1:] |= water[:,:-1]; v[:,:-1] |= water[:,1:]
        rim = _I.new("1", (G, G), 0)
        rdr = _D.Draw(rim)
        if rivers_shp:
            sf = shapefile.Reader(rivers_shp)
            for sh in sf.shapes():
                pts = np.asarray(sh.points)
                parts = list(sh.parts) + [len(pts)]
                for i in range(len(parts)-1):
                    seg = pts[parts[i]:parts[i+1]]
                    if len(seg) < 2: continue
                    x, y = merc(seg[:,0], seg[:,1])
                    rdr.line(list(zip(x.tolist(), y.tolist())), fill=1, width=2)
        # major ship canals (absent from NE rivers): lon/lat waypoint chains
        CANALS = [
            [(32.32,31.28),(32.35,30.85),(32.33,30.58),(32.45,30.35),(32.55,30.05),(32.57,29.92)],  # Suez
            [(-79.92,9.32),(-79.80,9.20),(-79.70,9.10),(-79.62,9.02),(-79.55,8.93)],                # Panama
            [(9.14,54.36),(9.70,54.20),(10.15,53.90)],                                              # Kiel
            [(22.98,37.95),(23.00,37.93)],                                                          # Corinth
            [(-79.25,43.23),(-79.21,42.88)],                                                        # Welland
        ]
        for chain in CANALS:
            xs, ys = merc(np.array([p[0] for p in chain]), np.array([p[1] for p in chain]))
            rdr.line(list(zip(xs.tolist(), ys.tolist())), fill=1, width=3)
        v |= np.asarray(rim, bool)

        # built-in seas + user extra-water: carve into validity AND routing land
        wim = _I.new("1", (G, G), 0)
        wdr = _D.Draw(wim)
        def carve_poly(chain):
            xs, ys = merc(np.array([p[0] for p in chain]), np.array([p[1] for p in chain]))
            wdr.polygon(list(zip(xs.tolist(), ys.tolist())), fill=1)
        def carve_line(chain, width_px):
            xs, ys = merc(np.array([p[0] for p in chain]), np.array([p[1] for p in chain]))
            wdr.line(list(zip(xs.tolist(), ys.tolist())), fill=1, width=max(1,int(width_px)))
        for chain in self.BUILTIN_SEAS.values():
            carve_poly(chain)
        if extra_water:
            # file format, one region per line:
            #   box lon0 lat0 lon1 lat1
            #   poly lon,lat lon,lat lon,lat ...
            #   line WIDTH_KM lon,lat lon,lat ...
            km_per_px = 40075.0 / G   # equator; good enough for corridor widths
            for ln in open(extra_water):
                ln = ln.split("#")[0].strip()
                if not ln: continue
                parts = ln.split()
                kind = parts[0].lower()
                if kind == "box":
                    lo0,la0,lo1,la1 = map(float, parts[1:5])
                    carve_poly([(lo0,la0),(lo1,la0),(lo1,la1),(lo0,la1)])
                elif kind == "poly":
                    carve_poly([tuple(map(float,p.split(","))) for p in parts[1:]])
                elif kind == "line":
                    wkm = float(parts[1])
                    carve_line([tuple(map(float,p.split(","))) for p in parts[2:]], wkm/km_per_px)
        wmask = np.asarray(wim, bool)
        land = land & ~wmask     # navigable for routing
        v |= wmask         # and valid for fixes
        np.savez_compressed(cpath, land=land, valid=v)
        return land, v

    def validate(self, xy):
        """NaN-out fixes that sit on deep land (not water/lake/river/harbor
        buffer). Fabricated gap-fill tracks across continents dissolve; real
        river, lake, canal, and harbor fixes survive. Returns a copy."""
        out = xy.copy()
        x = xy[...,0]; y = xy[...,1]
        okf = ~np.isnan(x)
        xi = np.clip((x[okf]/self.sv).astype(int), 0, self.Gv-1)
        yi = np.clip((y[okf]/self.sv).astype(int), 0, self.Gv-1)
        bad = ~self.valid[yi, xi]
        idx = np.where(okf)
        out[idx[0][bad], idx[1][bad], :] = np.nan if out.ndim==3 else np.nan
        return out

    def _cell(self, p):
        return (int(np.clip(p[1]/self.s, 0, self.G-1)),
                int(np.clip(p[0]/self.s, 0, self.G-1)))

    def crossing(self, aa, bb):
        """Bool per segment: both endpoints water AND chord samples touch land.
        Segments unwrapped beyond [0,W) (dateline) are excluded."""
        n = len(aa)
        out = np.zeros(n, bool)
        if n == 0: return out
        inb = (bb[:,0] >= 0) & (bb[:,0] < self.W)
        ga = (aa/self.s); gb = (bb/self.s)
        ia = np.clip(ga.astype(int), 0, self.G-1); ib = np.clip(gb.astype(int), 0, self.G-1)
        a_water = ~self.land[ia[:,1], ia[:,0]]
        b_water = ~self.land[ib[:,1], ib[:,0]]
        cand = inb & a_water & b_water
        idx = np.where(cand)[0]
        if len(idx) == 0: return out
        steps = 24
        f = np.linspace(0, 1, steps+1)[1:-1]
        P = ga[idx,None,:] + (gb[idx]-ga[idx])[:,None,:]*f[None,:,None]
        xi = np.clip(P[...,0].astype(int), 0, self.G-1)
        yi = np.clip(P[...,1].astype(int), 0, self.G-1)
        out[idx] = self.land[yi, xi].any(axis=1)
        return out

    def _snap(self, c):
        """Nearest water cell to (row,col) within a small radius (BFS rings)."""
        r0, c0 = c
        if not self.land[r0, c0]: return c
        for r in range(1, 8):
            for dr in range(-r, r+1):
                for dc in (-r, r):
                    rr, cc = r0+dr, c0+dc
                    if 0<=rr<self.G and 0<=cc<self.G and not self.land[rr,cc]: return (rr,cc)
            for dc in range(-r+1, r):
                for dr in (-r, r):
                    rr, cc = r0+dr, c0+dc
                    if 0<=rr<self.G and 0<=cc<self.G and not self.land[rr,cc]: return (rr,cc)
        return None

    def route(self, a, b):
        """A* water path a->b in render px, or None. Cached by cell pair."""
        ca, cb = self._cell(a), self._cell(b)
        key = (ca, cb)
        if key in self.cache: return self.cache[key]
        ca, cb = self._snap(ca), self._snap(cb)
        if ca is None or cb is None:
            self.cache[key] = None; return None
        import heapq
        land = self.land; G = self.G
        SQRT2 = 1.4142135
        openh = [(0.0, 0.0, ca, None)]
        best = {ca: (0.0, None)}
        goal = cb
        found = False
        maxpop = 200000
        while openh and maxpop:
            maxpop -= 1
            fscore, g, cur, par = heapq.heappop(openh)
            if cur == goal:
                found = True; break
            if best.get(cur, (1e18,))[0] < g - 1e-9: continue
            r0, c0 = cur
            for dr in (-1,0,1):
                for dc in (-1,0,1):
                    if dr==0 and dc==0: continue
                    rr, cc = r0+dr, c0+dc
                    if not (0<=rr<G and 0<=cc<G) or land[rr,cc]: continue
                    ng = g + (SQRT2 if dr and dc else 1.0)
                    if ng < best.get((rr,cc), (1e18,))[0]:
                        best[(rr,cc)] = (ng, cur)
                        h = np.hypot(rr-goal[0], cc-goal[1])
                        heapq.heappush(openh, (ng+h, ng, (rr,cc), cur))
        if not found:
            self.cache[key] = None; return None
        path = [goal]
        while best[path[-1]][1] is not None:
            path.append(best[path[-1]][1])
        path.reverse()
        # decimate: keep every 2nd cell + ends; convert to render px (cell centers)
        pts = np.array([( (c+0.5)*self.s, (r+0.5)*self.s ) for r,c in path[::2] + [path[-1]]], np.float32)
        pts[0] = a; pts[-1] = b   # pin exact endpoints
        self.cache[key] = pts
        return pts



if __name__ == "__main__":
    from PIL import Image
    r = LandRouter("ne_10m_land.shp", 65536, grid=2048)
    Image.fromarray(r.valid.astype(np.uint8)*255).convert("1").save("valid_water_4096.png", optimize=True)
    Image.fromarray(r.land.astype(np.uint8)*255).convert("1").save("land_2048.png", optimize=True)
    print("wrote valid_water_4096.png (validity) and land_2048.png (routing)")
