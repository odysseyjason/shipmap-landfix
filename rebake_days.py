#!/usr/bin/env python3
"""
rebake_days.py - produce corrected shipmap.org day files, and optionally
sparse route sidecars that fix corner-cutting.

TIER 1 (default): fabricated over-land fixes -> missing sentinel (0xFFFF).
  python3 rebake_days.py --in data --out data_fixed

TIER 1.5 (--routes-sidecar): additionally, for each hourly segment whose two
endpoints are genuine water fixes but whose straight chord crosses land
(corner-cutting around headlands), compute an A* water detour and write it to
a sparse sidecar file {day}.routes.bin. Main day files stay byte-compatible;
an unmodified client ignores sidecars and renders exactly as today.
  python3 rebake_days.py --in data --out data_fixed --routes-sidecar

Sidecar format (big-endian, matching the day-file convention):
  header:  "SMRT" | u16 version=1 | u16 reserved | u32 entry_count
  entry:   u16 ship_index | u8 hour(0-23) | u8 n_waypoints |
           n_waypoints x (u16 x, u16 y)
Waypoints are INTERIOR bend points between the two hourly fixes (endpoints are
not repeated), resampled at equal ARC-LENGTH spacing so implicit even timing
across the hour yields physically uniform speed along the detour.

Requires: numpy, pillow. Masks: valid_water_4096.png (validity),
land_2048.png (routing) - shipped with this package; regenerate via
make_masks.py.
"""
import argparse, heapq, os, struct, sys
import numpy as np
from PIL import Image

MISSING = 0xFFFF
WORLD = 65536  # native coordinate grid

def load_bits(path):
    a = np.asarray(Image.open(path).convert("L")) > 127
    assert a.shape[0] == a.shape[1]
    return a

class Router:
    """Crossing detection + A* on the packaged PNG masks, native coords."""
    def __init__(self, valid_png, land_png, max_pop=200000):
        self.valid = load_bits(valid_png)          # True = valid water
        self.land = ~load_bits(land_png) == False  # PNG white = land
        self.land = load_bits(land_png)            # True = land (routing blocked)
        self.vshift = 16 - int(np.log2(self.valid.shape[0]))
        self.G = self.land.shape[0]
        self.rshift = 16 - int(np.log2(self.G))
        self.cache = {}
        self.max_pop = max_pop

    def cull(self, xy):
        """xy: (n,2) uint16 view; overwrite deep-land fixes with MISSING.
        Returns bool mask of culled."""
        x, y = xy[:,0], xy[:,1]
        present = ~((x == MISSING) & (y == MISSING))
        bad = present & ~self.valid[y >> self.vshift, x >> self.vshift]
        xy[bad] = MISSING
        return present, bad

    def crossing(self, ax, ay, bx, by):
        """Straight chord touches routing land? (endpoints assumed water)"""
        if abs(int(bx) - int(ax)) > WORLD // 2:
            return False                            # dateline wrap: leave as-is
        n = 24
        t = np.linspace(0.0, 1.0, n + 2)[1:-1]
        xs = (ax + (bx - ax) * t).astype(int) >> self.rshift
        ys = (ay + (by - ay) * t).astype(int) >> self.rshift
        return bool(self.land[ys, xs].any())

    def _snap(self, r, c):
        if not self.land[r, c]:
            return (r, c)
        for rad in range(1, 8):
            for dr in range(-rad, rad + 1):
                for dc in (-rad, rad):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < self.G and 0 <= cc < self.G and not self.land[rr, cc]:
                        return (rr, cc)
            for dc in range(-rad + 1, rad):
                for dr in (-rad, rad):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < self.G and 0 <= cc < self.G and not self.land[rr, cc]:
                        return (rr, cc)
        return None

    def route(self, ax, ay, bx, by):
        """A* water path in native coords (list of (x,y)) incl endpoints, or None."""
        ca = (ay >> self.rshift, ax >> self.rshift)
        cb = (by >> self.rshift, bx >> self.rshift)
        key = (ca, cb)
        if key in self.cache:
            p = self.cache[key]
            if p is None: return None
            out = [(ax, ay)] + p + [(bx, by)]
            return out
        sa, sb = self._snap(*ca), self._snap(*cb)
        if sa is None or sb is None:
            self.cache[key] = None; return None
        best = {sa: (0.0, None)}
        openh = [(0.0, 0.0, sa)]
        found = False
        pops = self.max_pop
        while openh and pops:
            pops -= 1
            f, g, cur = heapq.heappop(openh)
            if cur == sb:
                found = True; break
            if best[cur][0] < g - 1e-9: continue
            r0, c0 = cur
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0: continue
                    rr, cc = r0 + dr, c0 + dc
                    if not (0 <= rr < self.G and 0 <= cc < self.G) or self.land[rr, cc]:
                        continue
                    ng = g + (1.4142135 if dr and dc else 1.0)
                    if ng < best.get((rr, cc), (1e18,))[0]:
                        best[(rr, cc)] = (ng, cur)
                        h = ((rr - sb[0])**2 + (cc - sb[1])**2) ** 0.5
                        heapq.heappush(openh, (ng + h, ng, (rr, cc)))
        if not found:
            self.cache[key] = None; return None
        cells = [sb]
        while best[cells[-1]][1] is not None:
            cells.append(best[cells[-1]][1])
        cells.reverse()
        half = 1 << (self.rshift - 1)
        interior = [((c << self.rshift) + half, (r << self.rshift) + half) for r, c in cells[1:-1]]
        self.cache[key] = interior
        return [(ax, ay)] + interior + [(bx, by)]

def resample_arclen(path, max_wp=12, spacing=96.0):
    """Equal arc-length interior waypoints from a polyline (native px)."""
    p = np.asarray(path, float)
    seg = np.hypot(*np.diff(p, axis=0).T)
    L = seg.sum()
    if L <= 0: return []
    n = int(np.clip(round(L / spacing), 1, max_wp))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    targets = L * (np.arange(n) + 1) / (n + 1)
    out = []
    for t in targets:
        i = int(np.searchsorted(cum, t) - 1)
        i = min(max(i, 0), len(seg) - 1)
        f = (t - cum[i]) / max(seg[i], 1e-9)
        q = p[i] + (p[i + 1] - p[i]) * f
        out.append((int(round(q[0])) & 0xFFFF, int(round(q[1])) & 0xFFFF))
    return out

def rebake(in_path, out_dir, router, sidecar):
    raw = np.fromfile(in_path, dtype=">u2")
    if raw.size % 50:
        raise ValueError(f"{in_path}: not a multiple of 100 bytes")
    xy = raw.reshape(-1, 2)
    present, bad = router.cull(xy)
    n_ships = raw.size // 50
    day = raw.reshape(n_ships, 25, 2)
    entries = []
    if sidecar:
        for s in range(n_ships):
            trk = day[s]
            for h in range(24):
                ax, ay = int(trk[h, 0]), int(trk[h, 1])
                bx, by = int(trk[h + 1, 0]), int(trk[h + 1, 1])
                if ax == MISSING or bx == MISSING: continue
                if not router.crossing(ax, ay, bx, by): continue
                path = router.route(ax, ay, bx, by)
                if path is None or len(path) < 3: continue
                wps = resample_arclen(path)
                if wps: entries.append((s, h, wps))
    name = os.path.basename(in_path)
    day.astype(">u2").tofile(os.path.join(out_dir, name))
    if sidecar:
        sp = os.path.join(out_dir, name[:-4] + ".routes.bin")
        with open(sp, "wb") as f:
            f.write(b"SMRT" + struct.pack(">HHI", 1, 0, len(entries)))
            for s, h, wps in entries:
                f.write(struct.pack(">HBB", s, h, len(wps)))
                for x, y in wps:
                    f.write(struct.pack(">HH", x, y))
    return int(present.sum()), int(bad.sum()), len(entries)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", required=True)
    ap.add_argument("--out", dest="outdir", required=True)
    ap.add_argument("--valid-mask", default="valid_water_4096.png")
    ap.add_argument("--land-mask", default="land_2048.png")
    ap.add_argument("--routes-sidecar", action="store_true",
                    help="also emit sparse {day}.routes.bin corner-fix sidecars")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    router = Router(a.valid_mask, a.land_mask)
    tf = tc = tr = files = 0
    for name in sorted(os.listdir(a.indir)):
        if not name.endswith(".bin") or not name[:-4].isdigit(): continue
        n, c, r = rebake(os.path.join(a.indir, name), a.outdir, router, a.routes_sidecar)
        tf += n; tc += c; tr += r; files += 1
        msg = f"{name}: culled {c}/{n} fixes"
        if a.routes_sidecar: msg += f", {r} route entries"
        print(msg, file=sys.stderr)
    print(f"\n{files} files: culled {tc}/{tf} ({100*tc/max(tf,1):.2f}%), "
          f"{tr} total route entries", file=sys.stderr)
