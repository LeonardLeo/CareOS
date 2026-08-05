/**
 * The CareOS operator's session.
 *
 * **Different cookies from the tenant session, on purpose.** The two are different
 * principals against different endpoints, and sharing a cookie name would mean signing into
 * the operator console silently signed you out of an agency — or worse, that a stale agency
 * token and a live operator token could be present at once with the server picking whichever
 * arrived. Separate names make "which am I?" a question with one answer, and let a CareOS
 * employee hold an operator session and a test-agency session in the same browser without
 * either interfering with the other.
 *
 * Same flags and the same reasoning as `lib/session.ts`: httpOnly, so page JavaScript cannot
 * read the token. The console shows no PHI — the database role behind it cannot reach any —
 * but this token can suspend a customer, which is worth at least as much protection.
 *
 * The claims are decoded here only to render the right nav and to know whether to send
 * someone to the enrolment screen. Nothing security-relevant depends on it: the API verifies
 * the signature, enforces the role, and enforces MFA unconditionally.
 */

import { cookies } from "next/headers";

const ACCESS_COOKIE = "careos_platform_access";
const REFRESH_COOKIE = "careos_platform_refresh";

export type PlatformRole = "platform_admin" | "platform_support";

export interface PlatformSessionClaims {
  operatorId: string;
  role: PlatformRole;
  expiresAt: number;
  /** False until the operator has proved a code. Such a session reaches enrolment only. */
  mfaSatisfied: boolean;
}

export interface PlatformSession extends PlatformSessionClaims {
  token: string;
}

function decodeClaims(token: string): PlatformSessionClaims | null {
  const parts = token.split(".");
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const json = Buffer.from(parts[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
    const payload = JSON.parse(json) as {
      sub?: string;
      principal_type?: string;
      role?: string;
      exp?: number;
      mfa_satisfied?: boolean;
    };
    // A tenant token in the platform cookie is not a platform session. It cannot happen
    // through any route handler here, and reading it as one would render a console for
    // somebody the API will refuse on every request.
    if (payload.principal_type !== "platform") return null;
    if (!payload.sub || !payload.exp) return null;
    if (payload.role !== "platform_admin" && payload.role !== "platform_support") return null;
    return {
      operatorId: payload.sub,
      role: payload.role,
      expiresAt: payload.exp,
      // Absent reads as *not* satisfied, the opposite of the tenant side's `mfa_pending`.
      // There is no legacy operator token to stay compatible with, and for this principal
      // the safe reading of a missing claim is the strict one.
      mfaSatisfied: payload.mfa_satisfied === true,
    };
  } catch {
    return null;
  }
}

export async function setPlatformSession(
  accessToken: string,
  refreshToken: string,
): Promise<void> {
  const store = await cookies();
  const secure = process.env.NODE_ENV === "production";
  for (const [name, value] of [
    [ACCESS_COOKIE, accessToken],
    [REFRESH_COOKIE, refreshToken],
  ] as const) {
    store.set(name, value, {
      httpOnly: true,
      secure,
      sameSite: "lax",
      // Scoped to the console's own routes. A cookie sent on every agency page view would be
      // an operator credential travelling with requests that have no use for it.
      path: "/platform",
    });
  }
}

export async function clearPlatformSession(): Promise<void> {
  const store = await cookies();
  store.delete({ name: ACCESS_COOKIE, path: "/platform" });
  store.delete({ name: REFRESH_COOKIE, path: "/platform" });
}

export async function getPlatformSession(): Promise<PlatformSession | null> {
  const store = await cookies();
  const token = store.get(ACCESS_COOKIE)?.value;
  if (!token) return null;

  const claims = decodeClaims(token);
  if (!claims) return null;
  if (claims.expiresAt * 1000 <= Date.now()) return null;
  return { ...claims, token };
}
