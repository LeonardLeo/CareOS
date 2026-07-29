/**
 * Session handling.
 *
 * The access token is kept in an httpOnly, sameSite cookie and is never exposed to page
 * JavaScript. This app renders PHI — client names, addresses, schedules — so a cross-site
 * scripting bug that could read a token would be a reportable breach rather than an
 * inconvenience. httpOnly means the token is not reachable from `document.cookie` at all.
 *
 * The JWT payload is decoded here only to read the caller's role and agency for rendering
 * decisions. It is deliberately **not verified** client-side, and nothing security-relevant
 * depends on it: the API verifies the signature on every request and enforces RBAC and RLS
 * server-side. Hiding a nav link the user's role cannot use is a usability nicety; the actual
 * boundary is `careos.core.rbac` and the Postgres policies underneath it.
 */

import { cookies } from "next/headers";

const ACCESS_COOKIE = "careos_access";
const REFRESH_COOKIE = "careos_refresh";

export interface SessionClaims {
  userId: string;
  agencyId: string;
  role: string;
  expiresAt: number;
}

export interface Session extends SessionClaims {
  token: string;
}

function decodeClaims(token: string): SessionClaims | null {
  const parts = token.split(".");
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const json = Buffer.from(parts[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
    const payload = JSON.parse(json) as {
      sub?: string;
      agency_id?: string;
      role?: string;
      exp?: number;
    };
    if (!payload.sub || !payload.agency_id || !payload.role || !payload.exp) return null;
    return {
      userId: payload.sub,
      agencyId: payload.agency_id,
      role: payload.role,
      expiresAt: payload.exp,
    };
  } catch {
    return null;
  }
}

export async function setSession(accessToken: string, refreshToken: string): Promise<void> {
  const store = await cookies();
  const secure = process.env.NODE_ENV === "production";
  store.set(ACCESS_COOKIE, accessToken, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
  });
  store.set(REFRESH_COOKIE, refreshToken, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
  });
}

export async function clearSession(): Promise<void> {
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
}

export async function getSession(): Promise<Session | null> {
  const store = await cookies();
  const token = store.get(ACCESS_COOKIE)?.value;
  if (!token) return null;

  const claims = decodeClaims(token);
  if (!claims) return null;
  // Treat an expired token as no session rather than letting the request fail deeper in with
  // a confusing error.
  if (claims.expiresAt * 1000 <= Date.now()) return null;
  return { ...claims, token };
}

/** Roles permitted to see each navigation area, mirroring the API's declarations. */
export const NAV_ACCESS: Record<string, readonly string[]> = {
  dashboard: ["owner_admin", "scheduler", "clinical_supervisor", "billing_rcm", "auditor"],
  scheduling: ["owner_admin", "scheduler", "clinical_supervisor", "auditor"],
  recruiting: ["owner_admin", "scheduler", "auditor"],
  credentialing: ["owner_admin", "scheduler", "clinical_supervisor", "auditor"],
  exceptions: ["owner_admin", "scheduler", "clinical_supervisor", "auditor"],
  compliance: ["owner_admin", "auditor"],
};

export function canSee(area: keyof typeof NAV_ACCESS, role: string): boolean {
  return NAV_ACCESS[area]?.includes(role) ?? false;
}
