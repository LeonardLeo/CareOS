import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession, setSession } from "@/lib/session";

/**
 * Finish enrolment and adopt the session the API hands back.
 *
 * That swap is the point: the cookie currently holds a token minted before the user could
 * produce a code, and the API marks such a token as pending. Keeping it would leave someone
 * who has just enrolled still locked to this screen, which reads exactly like the feature not
 * working.
 */
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const code = String(form.get("code") ?? "").trim();

  try {
    const tokens = await api.confirmMfaEnrolment(session.token, code);
    await setSession(tokens.access_token, tokens.refresh_token);
    return NextResponse.redirect(new URL("/security?done=1", request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not confirm that code.";
    return NextResponse.redirect(
      // Back to `started=1`, so the user lands on the step they were on rather than at the
      // beginning with a new secret their authenticator does not have.
      new URL(`/security?started=1&error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
