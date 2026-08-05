/**
 * Login route handler.
 *
 * Exists so the browser never receives the access token. The form posts here, this runs
 * server-side, and the token goes straight into an httpOnly cookie — see lib/session.ts for
 * why that matters for a PHI-bearing app.
 */
import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { decodeSessionClaims, setSession } from "@/lib/session";

export async function POST(request: Request) {
  const form = await request.formData();
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");
  const mfaCode = String(form.get("mfa_code") ?? "").trim();

  try {
    const tokens = await api.login(email, password, mfaCode || undefined);
    await setSession(tokens.access_token, tokens.refresh_token);
    // A privileged user who has not enrolled holds a session that can reach the enrolment
    // screen and nothing else, so send them there rather than to a dashboard that will
    // refuse them and leave them guessing which of their permissions disappeared.
    const claims = decodeSessionClaims(tokens.access_token);
    const destination = claims?.mfaPending ? "/security?required=1" : "/dashboard";
    return NextResponse.redirect(new URL(destination, request.url), { status: 303 });
  } catch (error) {
    // A code is needed and was not given, or was wrong. Ask for it rather than reporting a
    // failure: the password was correct, and telling someone their password is wrong when it
    // is not is how they end up resetting it.
    if (error instanceof ApiError && error.isMfaRequired) {
      return NextResponse.redirect(new URL("/login?error=mfa", request.url), { status: 303 });
    }
    // A code rather than a sentence, so the sign-in page renders it in the reader's language.
    // Putting English prose in the query string was how the one screen a Spanish-speaking
    // caregiver definitely sees ended up answering in English.
    //
    // The API deliberately returns the same response for an unknown email and a wrong
    // password, so this must not distinguish them either. A disabled account is the one case
    // it does distinguish, and only after the password has been verified — so saying so tells
    // the person something they can act on without telling anyone else anything new.
    const reason =
      error instanceof ApiError && error.isAgencySuspended
        ? "suspended"
        : error instanceof ApiError && error.isAccountInactive
          ? "disabled"
          : error instanceof ApiError && error.isAuthError
            ? "invalid"
            : "failed";
    return NextResponse.redirect(new URL(`/login?error=${reason}`, request.url), { status: 303 });
  }
}
