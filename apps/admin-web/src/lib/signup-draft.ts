/**
 * The half-finished sign-up, carried between steps.
 *
 * The wizard is three server-rendered pages with no client JavaScript, so the answers from
 * step one have to survive until step three. They live in an httpOnly cookie, the same place
 * and with the same flags as the pending MFA enrolment next door.
 *
 * **The password is deliberately not in here.** That is why the account step is last rather
 * than first: an owner's password would otherwise sit in a cookie for the length of the
 * wizard, on whatever machine they started it on. Ordering the steps so the only secret is
 * posted once and consumed immediately costs nothing and removes the question entirely.
 *
 * Nothing in the draft is authority. It is a form's contents, and every value in it is
 * validated again by the API when the agency is created — a tampered cookie produces a 422,
 * not a differently-shaped agency.
 *
 * Thirty minutes. Long enough to look up a licence number and come back; short enough that a
 * shared browser is not holding a half-filled form tomorrow. An expired draft restarts at
 * step one with a message saying so, rather than silently discarding what was typed.
 */

import { cookies } from "next/headers";

const DRAFT_COOKIE = "careos_signup_draft";
const DRAFT_MAX_AGE_SECONDS = 30 * 60;

export interface SignupDraft {
  legalName: string;
  serviceStates: string[];
  serviceLines: string[];
  payerTypes: string[];
}

export const EMPTY_DRAFT: SignupDraft = {
  legalName: "",
  serviceStates: [],
  serviceLines: [],
  payerTypes: [],
};

/**
 * Every US state plus DC, as postal codes.
 *
 * Codes rather than names, and that is a choice rather than laziness. `NY` is what a US
 * home-care operator writes on every form they touch, it is what the EVV aggregator registry
 * is keyed on, and it is identical in English and Spanish — so the control needs no
 * translated label per state and cannot end up half-translated. The legend and the hint above
 * the grid carry the meaning.
 */
export const US_STATES = [
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
  "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
  "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
  "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
  "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
] as const;

export const SERVICE_LINES = ["home_care", "home_health", "hospice"] as const;

export const PAYER_TYPES = [
  "medicaid_waiver",
  "medicare_advantage",
  "private_pay",
  "other",
] as const;

export async function setSignupDraft(draft: SignupDraft): Promise<void> {
  const store = await cookies();
  store.set(DRAFT_COOKIE, JSON.stringify(draft), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: DRAFT_MAX_AGE_SECONDS,
  });
}

export async function getSignupDraft(): Promise<SignupDraft | null> {
  const store = await cookies();
  const raw = store.get(DRAFT_COOKIE)?.value;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<SignupDraft>;
    return {
      legalName: typeof parsed.legalName === "string" ? parsed.legalName : "",
      serviceStates: sanitize(parsed.serviceStates, US_STATES),
      serviceLines: sanitize(parsed.serviceLines, SERVICE_LINES),
      payerTypes: sanitize(parsed.payerTypes, PAYER_TYPES),
    };
  } catch {
    // A malformed cookie is treated as no draft: the wizard restarts, which is the same
    // outcome as it having expired and is the only honest thing to do with unreadable input.
    return null;
  }
}

export async function clearSignupDraft(): Promise<void> {
  const store = await cookies();
  store.delete(DRAFT_COOKIE);
}

/**
 * Keep only values from the closed set, in the set's own order.
 *
 * An allowlist rather than a length check. The cookie is httpOnly and not a security
 * boundary, and the API validates everything again — but a draft that can only ever hold
 * recognised values means the review step shows what will actually be created rather than
 * whatever was pasted in.
 */
function sanitize(value: unknown, allowed: readonly string[]): string[] {
  if (!Array.isArray(value)) return [];
  const chosen = new Set(value.filter((v): v is string => typeof v === "string"));
  return allowed.filter((option) => chosen.has(option));
}
