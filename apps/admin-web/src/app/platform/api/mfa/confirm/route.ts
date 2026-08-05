import { NextResponse } from "next/server";
import { ApiError, platformApi } from "@/lib/api";
import { clearPendingPlatformEnrolment } from "@/lib/mfa-enrolment";
import { getPlatformSession, setPlatformSession } from "@/lib/platform-session";

/**
 * Finish enrolment and adopt the session the API hands back.
 *
 * The cookie currently holds a token minted before the operator could produce a code, and
 * the API marks such a token unsatisfied. Keeping it would leave someone who has just
 * enrolled still confined to this screen, which reads exactly like the feature not working —
 * and here there is no configuration flag that would let them past it.
 *
 * A wrong code leaves the pending enrolment in place, for the same reason as the agency
 * version: re-minting on the error path would make the authenticator they already paired
 * permanently unable to produce an accepted code.
 */
export async function POST(request: Request) {
  const session = await getPlatformSession();
  if (!session) {
    return NextResponse.redirect(new URL("/platform/login", request.url), { status: 303 });
  }

  const form = await request.formData();
  const code = String(form.get("code") ?? "").trim();

  try {
    const tokens = await platformApi.confirmMfaEnrolment(session.token, code);
    await setPlatformSession(tokens.access_token, tokens.refresh_token);
    await clearPendingPlatformEnrolment();
    return NextResponse.redirect(new URL("/platform/security?done=1", request.url), {
      status: 303,
    });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not confirm that code.";
    return NextResponse.redirect(
      new URL(`/platform/security?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
