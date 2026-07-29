/**
 * Token storage for the caregiver app.
 *
 * Unlike the admin app, this cannot use an httpOnly cookie: the device replays queued
 * clock-ins itself, from its own JavaScript, so the token has to be reachable from there. That
 * is a genuine reduction in defence against XSS and is recorded as such in BUILD_STATUS rather
 * than presented as equivalent.
 *
 * What is done about it: the access token is held in `sessionStorage`, not `localStorage`, so
 * it does not outlive the browsing session, and the refresh token is not stored at all — an
 * expired session is a re-login rather than a long-lived credential sitting on the device.
 * Cached PHI is wiped on sign-out.
 */

import { clearCachedPhi } from "./storage";

const TOKEN_KEY = "careos:access";
const NAME_KEY = "careos:name";

export function storeSession(accessToken: string, displayName?: string): void {
  sessionStorage.setItem(TOKEN_KEY, accessToken);
  if (displayName) sessionStorage.setItem(NAME_KEY, displayName);
}

export function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function endSession(): Promise<void> {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(NAME_KEY);
  await clearCachedPhi();
}

interface JwtClaims {
  role?: string;
  exp?: number;
}

/** Decoded for display and expiry only. The API verifies the signature on every request. */
export function readClaims(token: string): JwtClaims | null {
  const parts = token.split(".");
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const json = atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as JwtClaims;
  } catch {
    return null;
  }
}

export function isExpired(token: string): boolean {
  const claims = readClaims(token);
  if (!claims?.exp) return true;
  return claims.exp * 1000 <= Date.now();
}
