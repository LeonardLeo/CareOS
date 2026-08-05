import { NextResponse } from "next/server";
import { ApiError, platformApi } from "@/lib/api";
import { setPendingPlatformEnrolment } from "@/lib/mfa-enrolment";
import { getPlatformSession } from "@/lib/platform-session";

/**
 * Mint the operator's secret, once.
 *
 * Same reasoning as the agency version: the API replaces any previous secret on every call,
 * so calling it from a render would invalidate the secret the user had just scanned on every
 * refresh. It is called from a POST and the result is held in an httpOnly cookie until it is
 * confirmed. A separate cookie from the agency one, so a CareOS employee enrolling both
 * accounts in one browser does not overwrite one with the other.
 */
export async function POST(request: Request) {
  const session = await getPlatformSession();
  if (!session) {
    return NextResponse.redirect(new URL("/platform/login", request.url), { status: 303 });
  }

  const form = await request.formData();
  const currentCode = String(form.get("current_code") ?? "").trim();

  try {
    const started = await platformApi.startMfaEnrolment(session.token, currentCode || undefined);
    await setPendingPlatformEnrolment({
      secret: started.secret,
      otpauthUri: started.otpauth_uri,
      recoveryCodes: started.recovery_codes,
    });
    return NextResponse.redirect(new URL("/platform/security", request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not start enrolment.";
    return NextResponse.redirect(
      new URL(`/platform/security?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
