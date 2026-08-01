/**
 * TOTP, so an audit harness can get past MFA the way a person does.
 *
 * Thirty lines of RFC 6238 rather than a dependency, because the alternative was to sign the
 * audit in as a role that does not require MFA — which would have meant the screens behind the
 * strictest login were the ones nobody looked at, and would have quietly stopped working the
 * moment another role was added to `MFA_REQUIRED_ROLES`.
 *
 * Test and audit tooling only. The server's implementation is the one that matters.
 */

import { createHmac } from "node:crypto";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/** RFC 4648 base32, which is how an `otpauth://` secret is transported. */
export function decodeBase32(secret) {
  const clean = secret.toUpperCase().replace(/=+$/, "").replace(/\s/g, "");
  let bits = 0;
  let value = 0;
  const bytes = [];
  for (const char of clean) {
    const index = ALPHABET.indexOf(char);
    if (index === -1) throw new Error(`not base32: ${char}`);
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      bytes.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(bytes);
}

export function totp(secret, { at = Date.now(), step = 30, digits = 6 } = {}) {
  const counter = Math.floor(at / 1000 / step);
  const message = Buffer.alloc(8);
  message.writeUInt32BE(Math.floor(counter / 2 ** 32), 0);
  message.writeUInt32BE(counter >>> 0, 4);

  const digest = createHmac("sha1", decodeBase32(secret)).update(message).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    (digest[offset + 1] << 16) |
    (digest[offset + 2] << 8) |
    digest[offset + 3];
  return String(binary % 10 ** digits).padStart(digits, "0");
}
