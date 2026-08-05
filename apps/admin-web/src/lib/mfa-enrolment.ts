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

const PENDING_MAX_AGE_SECONDS = 15 * 60;

export interface PendingEnrolment {
  secret: string;
  otpauthUri: string;
  recoveryCodes: string[];
}

/**
 * The three operations, bound to one cookie.
 *
 * Two enrolments can be in flight in one browser — an agency user's and a CareOS operator's
 * — and they must not overwrite each other's secret. Rather than a second copy of this
 * module with a different constant, the cookie is a parameter and each surface names its
 * own. The operator's is scoped to `/platform` for the same reason its session cookie is.
 */
function enrolmentStore(name: string, path: string) {
  return {
    async set(pending: PendingEnrolment): Promise<void> {
      const store = await cookies();
      store.set(name, JSON.stringify(pending), {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path,
        maxAge: PENDING_MAX_AGE_SECONDS,
      });
    },

    async get(): Promise<PendingEnrolment | null> {
      const store = await cookies();
      const raw = store.get(name)?.value;
      if (!raw) return null;
      try {
        const parsed = JSON.parse(raw) as Partial<PendingEnrolment>;
        if (!parsed.secret || !parsed.otpauthUri || !Array.isArray(parsed.recoveryCodes)) {
          return null;
        }
        return {
          secret: parsed.secret,
          otpauthUri: parsed.otpauthUri,
          recoveryCodes: parsed.recoveryCodes,
        };
      } catch {
        // A malformed cookie is treated as no enrolment in progress: the user starts again
        // and gets a fresh secret, which is the same outcome as it having expired.
        return null;
      }
    },

    async clear(): Promise<void> {
      const store = await cookies();
      store.delete({ name, path });
    },
  };
}

const tenantEnrolment = enrolmentStore("careos_mfa_pending", "/");
const platformEnrolment = enrolmentStore("careos_platform_mfa_pending", "/platform");

export const setPendingEnrolment = tenantEnrolment.set;
export const getPendingEnrolment = tenantEnrolment.get;
export const clearPendingEnrolment = tenantEnrolment.clear;

export const setPendingPlatformEnrolment = platformEnrolment.set;
export const getPendingPlatformEnrolment = platformEnrolment.get;
export const clearPendingPlatformEnrolment = platformEnrolment.clear;
