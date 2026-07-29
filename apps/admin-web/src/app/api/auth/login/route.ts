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
    // The API deliberately returns the same response for an unknown email and a wrong
    // password, so this message must not distinguish them either.
    const message =
      error instanceof ApiError && error.isAuthError
        ? "Invalid email or password"
        : "Could not sign in. Please try again.";
    return NextResponse.redirect(
      new URL(`/login?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
