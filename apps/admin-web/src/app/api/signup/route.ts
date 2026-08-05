/**
 * Sign-up, final step: create the tenant and sign the owner in.
 *
 * Three things happen here and they are all server-side, which is the point of the route
 * handler existing at all: the owner's password never reaches page JavaScript, and neither
 * does the access token it is exchanged for.
 *
 * 1. `POST /v1/agencies` creates the agency and its first `owner_admin` in one transaction.
 *    A tenant with nobody able to administer it would be unusable and invisible, so the API
 *    does both or neither.
 * 2. `POST /v1/auth/login` with the credentials just set. Deliberately not a token returned
 *    by the create call: sign-up should exercise the same authentication path everyone else
 *    uses, so a change that breaks sign-in cannot leave sign-up quietly working.
 * 3. The pair goes into the httpOnly session cookies, and the draft cookie is cleared.
 *
 * The destination is the security screen, not the dashboard. `owner_admin` is an
 * MFA-required role, so the session that comes back is a real one that can reach the
 * enrolment endpoints and nothing else — sending them to a dashboard first would mean their
 * first experience of CareOS is a screen refusing them for a reason nothing has explained.
 */
import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { setSession } from "@/lib/session";
import { clearSignupDraft, getSignupDraft } from "@/lib/signup-draft";

/** Matches `AgencyCreate.owner_password` on the API, so the two cannot disagree. */
const MIN_PASSWORD_LENGTH = 12;

export async function POST(request: Request) {
  const draft = await getSignupDraft();
  if (
    !draft ||
    !draft.legalName ||
    draft.serviceStates.length === 0 ||
    draft.serviceLines.length === 0 ||
    draft.payerTypes.length === 0
  ) {
    return back(request, 1, "expired");
  }

  const form = await request.formData();
  const email = String(form.get("owner_email") ?? "").trim();
  const password = String(form.get("owner_password") ?? "");
  const confirmation = String(form.get("confirm_password") ?? "");

  if (password.length < MIN_PASSWORD_LENGTH) return back(request, 3, "short");
  // Checked here rather than left to the browser: `minlength` is advisory, and a mistyped
  // password on the only account that can administer the agency is a support call on day one.
  if (password !== confirmation) return back(request, 3, "mismatch");

  try {
    await api.createAgency({
      legal_name: draft.legalName,
      service_states: draft.serviceStates,
      service_lines: draft.serviceLines,
      accepted_payer_types: draft.payerTypes,
      owner_email: email,
      owner_password: password,
    });
  } catch (error) {
    return back(request, 3, signupErrorCode(error));
  }

  try {
    const tokens = await api.login(email, password);
    await setSession(tokens.access_token, tokens.refresh_token);
  } catch {
    // The agency exists and the sign-in did not land — a slow API, or a limiter that counted
    // the sign-up and then the sign-in. Send them to the sign-in screen rather than back into
    // the wizard, which would try to create the agency a second time and fail on the email.
    await clearSignupDraft();
    return NextResponse.redirect(new URL("/login", request.url), { status: 303 });
  }

  await clearSignupDraft();
  return NextResponse.redirect(new URL("/security?required=1&welcome=1", request.url), {
    status: 303,
  });
}

/**
 * Which message the sign-up screen should show.
 *
 * `CONFLICT` is the interesting one. It means the address already has an account, and saying
 * so is a deliberate trade: it tells a returning owner to sign in instead of filling the form
 * again, and it confirms to anyone else that the address is registered. The sign-up rate
 * limit — five an hour per address — is what bounds the second, and BUILD_STATUS records the
 * exposure rather than leaving it looking accidental.
 */
function signupErrorCode(error: unknown): string {
  if (!(error instanceof ApiError)) return "unavailable";
  if (error.code === "CONFLICT") return "taken";
  if (error.code === "VALIDATION_ERROR") return "invalid";
  if (error.code === "RATE_LIMIT_EXCEEDED") return "limited";
  return "unavailable";
}

function back(request: Request, step: number, error: string) {
  return NextResponse.redirect(new URL(`/signup?step=${step}&error=${error}`, request.url), {
    status: 303,
  });
}
