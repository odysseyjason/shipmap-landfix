/* landfix-routes.js — parse sparse route sidecars ({day}.routes.bin) that fix
 * corner-cutting in shipmap.org's hourly interpolation.
 *
 * A sidecar contains, for the few thousand ship-hours per day whose straight
 * chord between two genuine water fixes crosses land, a short list of interior
 * waypoints along an A*-computed water detour. Waypoints are resampled at
 * equal arc length, so stepping through them with even timing across the hour
 * gives physically uniform speed. Everything else about the day file is
 * unchanged; clients that ignore sidecars render exactly as today.
 *
 * Format (big-endian): "SMRT" | u16 version | u16 reserved | u32 count |
 *   count x { u16 shipIndex | u8 hour | u8 n | n x (u16 x, u16 y) }
 *
 * Usage:
 *   const routes = LandFixRoutes.parse(await (await fetch(day+'.routes.bin')).arrayBuffer());
 *   const wps = routes.get(LandFixRoutes.key(shipIndex, hour));  // Uint16Array [x0,y0,x1,y1,...] or undefined
 *
 * Integration sketch (see README): position of an affected ship at time
 * fraction f within the hour = piecewise-linear along
 * [srcFix, wp0..wpN-1, dstFix] with N+1 equal time slices.
 *
 * MIT License.
 */
(function (root) {
  "use strict";

  function key(ship, hour) { return ship * 24 + hour; }

  function parse(buffer) {
    var dv = new DataView(buffer);
    if (dv.getUint32(0, false) !== 0x534D5254) throw new Error("bad sidecar magic");
    var version = dv.getUint16(4, false);
    if (version !== 1) throw new Error("unsupported sidecar version " + version);
    var count = dv.getUint32(8, false);
    var map = new Map();
    var off = 12;
    for (var i = 0; i < count; i++) {
      var ship = dv.getUint16(off, false);
      var hour = dv.getUint8(off + 2);
      var n = dv.getUint8(off + 3);
      off += 4;
      var wps = new Uint16Array(n * 2);
      for (var j = 0; j < n * 2; j++) { wps[j] = dv.getUint16(off, false); off += 2; }
      map.set(key(ship, hour), wps);
    }
    return map;
  }

  /** Position along the detour at time fraction f in [0,1) of the hour.
   *  src/dst: {x,y} native uint16 coords; wps: Uint16Array from parse(). */
  function positionAt(src, dst, wps, f) {
    var n = wps.length >> 1;
    var pts = new Float64Array((n + 2) * 2);
    pts[0] = src.x; pts[1] = src.y;
    for (var i = 0; i < n * 2; i++) pts[2 + i] = wps[i];
    pts[(n + 1) * 2] = dst.x; pts[(n + 1) * 2 + 1] = dst.y;
    var segs = n + 1;
    var t = f * segs;
    var i0 = Math.min(Math.floor(t), segs - 1);
    var ft = t - i0;
    return {
      x: pts[i0 * 2] + (pts[(i0 + 1) * 2] - pts[i0 * 2]) * ft,
      y: pts[i0 * 2 + 1] + (pts[(i0 + 1) * 2 + 1] - pts[i0 * 2 + 1]) * ft
    };
  }

  var api = { parse: parse, key: key, positionAt: positionAt };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LandFixRoutes = api;
})(this);
