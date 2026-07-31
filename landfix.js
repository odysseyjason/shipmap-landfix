/* landfix.js — remove fabricated over-land ship tracks from shipmap.org day data.
 *
 * Problem: gaps in 2012 AIS coverage were filled upstream by interpolating
 * hourly positions in a straight line between distant fixes, which marches
 * "ships" across continents (e.g. straight across the Sahara). Those fixes
 * are fabrications, not observations.
 *
 * Fix: a fix that lies on deep land — not ocean, lake, major river corridor,
 * ship canal (Suez, Panama, Kiel, Corinth, Welland), or a ~10 km coastal
 * harbor buffer — is overwritten with the format's existing missing-data
 * sentinel (0xFFFF,0xFFFF). The renderer already skips missing fixes, so no
 * shader or rendering changes are required. Real river/lake/canal/harbor
 * traffic is preserved by the mask, not by heuristics.
 *
 * Data cost: one 4096x4096 1-bit mask PNG (~180 KB, cached forever).
 * CPU cost: ~730k array lookups per day file — well under 1 ms.
 *
 * Usage:
 *   const mask = await LandFix.loadMask('valid_water_4096.png');
 *   // after fetching a day's ArrayBuffer, before uploading to GL:
 *   const report = LandFix.cullDayBuffer(dayArrayBuffer, mask);
 *   // report = {fixesTotal, fixesCulled}
 *
 * Mask semantics: white (255) = valid water, black = deep land.
 * Coordinates: day-file x,y are big-endian uint16 in a 65536x65536
 * web-mercator world grid; mask cell = (x >> 4, y >> 4) for a 4096 mask.
 *
 * MIT License. Mask derived from Natural Earth (public domain) land, lakes,
 * and river-centerline layers, plus hand-carved ship canals and the Caspian.
 */
(function (root) {
  "use strict";

  var MISSING = 0xFFFF;

  /** Decode the mask PNG into {bits: Uint8Array, size: int, shift: int}.
   *  Browser only (uses Image + canvas). For Node/tests, build the same
   *  object from raw bytes and pass it directly to cullDayBuffer. */
  function loadMask(url) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = function () {
        var size = img.width;                      // square, power of two
        var cv = document.createElement("canvas");
        cv.width = cv.height = size;
        var cx = cv.getContext("2d", { willReadFrequently: true });
        cx.drawImage(img, 0, 0);
        var px = cx.getImageData(0, 0, size, size).data;
        var bits = new Uint8Array(size * size);
        for (var i = 0, j = 0; i < bits.length; i++, j += 4) {
          bits[i] = px[j] > 127 ? 1 : 0;           // red channel: white=valid
        }
        resolve({ bits: bits, size: size, shift: 16 - Math.log2(size) });
      };
      img.onerror = reject;
      img.src = url;
    });
  }

  /** Cull deep-land fixes in a shipmap day buffer, in place.
   *  buffer: ArrayBuffer of the day file (nShips * 25 * 4 bytes, big-endian).
   *  mask:   object from loadMask().
   *  Returns {fixesTotal, fixesCulled}. */
  function cullDayBuffer(buffer, mask) {
    var dv = new DataView(buffer);
    var n = buffer.byteLength >> 2;                // number of (x,y) fixes
    var bits = mask.bits, size = mask.size, sh = mask.shift;
    var culled = 0, total = 0;
    for (var i = 0; i < n; i++) {
      var off = i << 2;
      var x = dv.getUint16(off, false);
      var y = dv.getUint16(off + 2, false);
      if (x === MISSING && y === MISSING) continue;
      total++;
      var mx = x >> sh, my = y >> sh;
      if (!bits[my * size + mx]) {
        dv.setUint16(off, MISSING, false);
        dv.setUint16(off + 2, MISSING, false);
        culled++;
      }
    }
    return { fixesTotal: total, fixesCulled: culled };
  }

  var LandFix = { loadMask: loadMask, cullDayBuffer: cullDayBuffer, MISSING: MISSING };
  if (typeof module !== "undefined" && module.exports) module.exports = LandFix;
  else root.LandFix = LandFix;
})(this);
