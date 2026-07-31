import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { clearPendingEnrolment } from "@/lib/mfa-enrolment";
import { getSession, setSession } from "@/lib/session";

/**
 * Finish enrolment and adopt the session the API hands back.
 *
 * That swap is the point: the cookie currently holds a token minted before the user could
 * produce a code, and the API marks such a token as pending. Keeping it would leave someone
 * who has just enrolled still locked to this screen, which reads exactly like the feature not
 * working.
 *
 * A wrong code leaves the pending enrolment in place. It has to: re-minting on the error path
 * would mean the authenticator the user already paired can never produce an accepted code, so
 * one typo would become a permanent failure.
 */
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const code = String(form.get("code") ?? "").trim();

  try {
    const tokens = await api.confirmMfaEnrolment(session.token, code);
    await setSession(tokens.access_token, tokens.refresh_token);
    // The secret is now on the user's phone and in the database; the copy in this cookie is
    // the one that has no reason to exist any more.
    await clearPendingEnrolment();
    return NextResponse.redirect(new URL("/security?done=1", request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not confirm that code.";
    return NextResponse.redirect(
      new URL(`/security?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
