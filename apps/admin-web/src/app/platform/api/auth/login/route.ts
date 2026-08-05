/**
 * Operator sign-in.
 *
 * Under `/platform/api` rather than the app's usual `/api`, because the operator session
 * cookie is scoped to `/platform`. A handler outside that path would set a cookie the
 * browser would then never send back to it, and the first suspend would fail with an
 * authentication error nobody could explain.
 */
import { NextResponse } from "next/server";
import { ApiError, platformApi } from "@/lib/api";
import { setPlatformSession } from "@/lib/platform-session";

export async function POST(request: Request) {
  const form = await request.formData();
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");
  const mfaCode = String(form.get("mfa_code") ?? "").trim();

  try {
    const tokens = await platformApi.login(email, password, mfaCode || undefined);
    await setPlatformSession(tokens.access_token, tokens.refresh_token);
    // An operator with no authenticator holds a session that reaches enrolment and nothing
    // else, so send them there. Unlike the agency side this is every operator's first
    // sign-in, because MFA here has no configuration flag that can leave it off.
    return NextResponse.redirect(new URL("/platform/security", request.url), { status: 303 });
  } catch (error) {
    if (error instanceof ApiError && error.isMfaRequired) {
      return back(request, "mfa");
    }
    const reason =
      error instanceof ApiError && error.isAuthError
        ? error.message.includes("disabled")
          ? "disabled"
          : "invalid"
        : "failed";
    return back(request, reason);
  }
}

function back(request: Request, reason: string) {
  // A code rather than a sentence, so the sign-in page renders it in the reader's language.
  return NextResponse.redirect(new URL(`/platform/login?error=${reason}`, request.url), {
    status: 303,
  });
}
