#!/usr/bin/env python3
"""
rebake_days.py — produce corrected shipmap.org day files with fabricated
over-land fixes replaced by the missing-data sentinel (0xFFFF,0xFFFF).

This is the zero-client-change deployment path: run once over data/, serve
the corrected files, and the existing site renders clean tracks untouched.

  python3 rebake_days.py --in data --out data_fixed --mask valid_water_4096.png

Requires: numpy, pillow. The mask PNG ships with this package (white = valid
water; derived from Natural Earth land/lakes/rivers + ship canals + Caspian,
with a ~10 km coastal harbor buffer). Regenerate or customize masks with
make_masks.py.

Format handled: {day}.bin = nShips x 25 hourly fixes x (uint16 x, uint16 y),
big-endian, web-mercator 65536-grid, 0xFFFF/0xFFFF = missing.
"""
import argparse, os, sys
import numpy as np
from PIL import Image

def load_mask(path):
    im = Image.open(path).convert("L")
    bits = (np.asarray(im) > 127)
    assert bits.shape[0] == bits.shape[1], "mask must be square"
    return bits

def rebake(in_path, out_path, bits):
    size = bits.shape[0]
    shift = 16 - int(np.log2(size))
    raw = np.fromfile(in_path, dtype=">u2")
    if raw.size % 50:
        raise ValueError(f"{in_path}: not a multiple of 100 bytes")
    xy = raw.reshape(-1, 2)
    x, y = xy[:, 0], xy[:, 1]
    present = ~((x == 0xFFFF) & (y == 0xFFFF))
    bad = present & ~bits[y >> shift, x >> shift]
    xy[bad] = 0xFFFF
    xy.astype(">u2").tofile(out_path)
    return int(present.sum()), int(bad.sum())

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", required=True)
    ap.add_argument("--out", dest="outdir", required=True)
    ap.add_argument("--mask", default="valid_water_4096.png")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    bits = load_mask(a.mask)
    tot_fix = tot_cull = files = 0
    for name in sorted(os.listdir(a.indir)):
        if not name.endswith(".bin") or not name[:-4].isdigit():
            continue
        n, c = rebake(os.path.join(a.indir, name), os.path.join(a.outdir, name), bits)
        tot_fix += n; tot_cull += c; files += 1
        print(f"{name}: culled {c} of {n} fixes ({100*c/max(n,1):.2f}%)", file=sys.stderr)
    print(f"\n{files} files: culled {tot_cull} of {tot_fix} fixes "
          f"({100*tot_cull/max(tot_fix,1):.2f}%)", file=sys.stderr)
