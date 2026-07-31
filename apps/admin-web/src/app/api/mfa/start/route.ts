import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { setPendingEnrolment } from "@/lib/mfa-enrolment";
import { getSession } from "@/lib/session";

/**
 * Mint the secret, once.
 *
 * The API replaces any previous secret on every call — deliberately, so an abandoned enrolment
 * cannot leave a live one behind — which makes "call it again" the same as "invalidate what the
 * user just scanned". So it is called here, from a POST, and the result is held until it is
 * confirmed. See `lib/mfa-enrolment.ts`.
 */
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  // Sent only when replacing an authenticator that already exists. The API requires it in
  // that case: moving a second factor to a new device is an authentication, and a session
  // alone must not be enough to move it to somebody else's.
  const currentCode = String(form.get("current_code") ?? "").trim();

  try {
    const started = await api.startMfaEnrolment(session.token, currentCode || undefined);
    await setPendingEnrolment({
      secret: started.secret,
      otpauthUri: started.otpauth_uri,
      recoveryCodes: started.recovery_codes,
    });
    return NextResponse.redirect(new URL("/security", request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not start enrolment.";
    return NextResponse.redirect(
      new URL(`/security?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
