/**
 * Decodes the enrolment QR back to the URI it was made from.
 *
 * A QR code is the one thing on that screen nobody can proofread. It either scans or it does
 * not, and the failure mode — a code that renders beautifully and decodes to nothing — looks
 * identical to a working one until someone is standing there with a phone. So this renders the
 * modules to a bitmap the way a camera sees them and reads them back with a real decoder.
 *
 * Run with `npm run check:qr`.
 */

import QRCode from "qrcode";
import jsQRModule from "jsqr";

const jsQR = jsQRModule.default ?? jsQRModule;

// The shapes an `otpauth://` URI actually takes: a plain address, one with a `+` tag, and one
// whose issuer has a space in it. The last is the one that breaks naive encoders.
const CASES = [
  "otpauth://totp/CareOS:owner@bayridgecare.demo?secret=JBSWY3DPEHPK3PXP&issuer=CareOS",
  "otpauth://totp/CareOS:dana+scheduler@bayridgecare.demo?secret=MFRGGZDFMZTWQ2LKNNWG23TP&issuer=CareOS",
  "otpauth://totp/Bay%20Ridge%20Care:rn.supervisor@bayridgecare.demo?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&issuer=Bay%20Ridge%20Care",
];

const SCALE = 6;
const QUIET = 4;

function bitmap(uri) {
  const code = QRCode.create(uri, {});
  const size = code.modules.size;
  const dim = (size + QUIET * 2) * SCALE;
  const data = new Uint8ClampedArray(dim * dim * 4).fill(255);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      if (!code.modules.get(x, y)) continue;
      for (let dy = 0; dy < SCALE; dy += 1) {
        for (let dx = 0; dx < SCALE; dx += 1) {
          const px = ((y + QUIET) * SCALE + dy) * dim + ((x + QUIET) * SCALE + dx);
          data[px * 4] = 0;
          data[px * 4 + 1] = 0;
          data[px * 4 + 2] = 0;
        }
      }
    }
  }
  return { data, dim };
}

let failures = 0;
for (const uri of CASES) {
  const { data, dim } = bitmap(uri);
  const decoded = jsQR(data, dim, dim);
  const ok = decoded?.data === uri;
  if (!ok) failures += 1;
  console.log(`${ok ? "ok  " : "FAIL"} ${uri.slice(0, 62)}…`);
  if (!ok) console.log(`       decoded instead: ${decoded?.data ?? "(nothing)"}`);
}

// The component renders SVG, so assert that path produces something too — a decoder cannot
// read an SVG directly, but an empty one is the failure worth catching here.
const svg = await QRCode.toString(CASES[0], { type: "svg", margin: 1 });
if (!svg.includes("<path") || svg.length < 500) {
  console.log("FAIL svg output is empty or pathless");
  failures += 1;
} else {
  console.log("ok   svg output has drawable paths");
}

console.log(failures ? `\n${failures} failure(s)` : "\nQR codes decode to the URI they encode");
process.exit(failures ? 1 : 0);
