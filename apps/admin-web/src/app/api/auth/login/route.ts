/**
 * Login route handler.
 *
 * Exists so the browser never receives the access token. The form posts here, this runs
 * server-side, and the token goes straight into an httpOnly cookie — see lib/session.ts for
 * why that matters for a PHI-bearing app.
 */
import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { setSession } from "@/lib/session";

export async function POST(request: Request) {
  const form = await request.formData();
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");

  try {
    const tokens = await api.login(email, password);
    await setSession(tokens.access_token, tokens.refresh_token);
    return NextResponse.redirect(new URL("/dashboard", request.url), { status: 303 });
  } catch (error) {
    // A code rather than a sentence, so the sign-in page renders it in the reader's language.
    // Putting English prose in the query string was how the one screen a Spanish-speaking
    // caregiver definitely sees ended up answering in English.
    //
    // The API deliberately returns the same response for an unknown email and a wrong
    // password, so this must not distinguish them either. A disabled account is the one case
    // it does distinguish, and only after the password has been verified — so saying so tells
    // the person something they can act on without telling anyone else anything new.
    const reason =
      error instanceof ApiError && error.isAccountInactive
        ? "disabled"
        : error instanceof ApiError && error.isAuthError
          ? "invalid"
          : "failed";
    return NextResponse.redirect(new URL(`/login?error=${reason}`, request.url), { status: 303 });
  }
}
