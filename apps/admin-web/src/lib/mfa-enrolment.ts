/**
 * The half-finished enrolment, held between the request that starts it and the one that
 * confirms it.
 *
 * **This exists because the obvious version is broken.** Rendering the enrolment screen by
 * calling `POST /auth/mfa/enroll` means every render mints a *new* secret — and the API
 * replaces the stored one each time, by design, so an abandoned enrolment cannot leave a live
 * secret behind. So a page refresh silently invalidates the secret the user has just scanned,
 * and the redirect after a mistyped code does the same thing, which turns one wrong code into
 * an authenticator that can never produce a right one. Verified against the running API: two
 * consecutive calls return two different secrets.
 *
 * So the secret is minted exactly once, by a POST, and carried here until it is confirmed.
 *
 * **In an httpOnly cookie**, the same place and with the same flags as the access token. It is
 * a credential, so page JavaScript must not be able to read it — and the recovery codes travel
 * with it, since they are shown once and the API cannot re-issue them.
 *
 * **With a fifteen-minute lifetime.** Long enough to find a phone and scan; short enough that
 * a shared or forgotten browser is not holding a usable second factor tomorrow. An enrolment
 * that expires costs one click to restart, and the secret it referred to is replaced by that
 * restart anyway.
 */

import { cookies } from "next/headers";

const PENDING_COOKIE = "careos_mfa_pending";
const PENDING_MAX_AGE_SECONDS = 15 * 60;

export interface PendingEnrolment {
  secret: string;
  otpauthUri: string;
  recoveryCodes: string[];
}

export async function setPendingEnrolment(pending: PendingEnrolment): Promise<void> {
  const store = await cookies();
  store.set(PENDING_COOKIE, JSON.stringify(pending), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: PENDING_MAX_AGE_SECONDS,
  });
}

export async function getPendingEnrolment(): Promise<PendingEnrolment | null> {
  const store = await cookies();
  const raw = store.get(PENDING_COOKIE)?.value;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PendingEnrolment>;
    if (!parsed.secret || !parsed.otpauthUri || !Array.isArray(parsed.recoveryCodes)) return null;
    return {
      secret: parsed.secret,
      otpauthUri: parsed.otpauthUri,
      recoveryCodes: parsed.recoveryCodes,
    };
  } catch {
    // A malformed cookie is treated as no enrolment in progress: the user starts again and
    // gets a fresh secret, which is the same outcome as it having expired.
    return null;
  }
}

export async function clearPendingEnrolment(): Promise<void> {
  const store = await cookies();
  store.delete(PENDING_COOKIE);
}
