import { NextResponse } from "next/server";
import { clearPendingPlatformEnrolment } from "@/lib/mfa-enrolment";
import { clearPlatformSession } from "@/lib/platform-session";

/**
 * Ends the operator session and drops any half-finished enrolment with it.
 *
 * The enrolment cookie holds a live TOTP secret and ten recovery codes. Leaving it behind on
 * sign-out would mean a shared machine keeps a usable second factor for the next fifteen
 * minutes, which is the one thing the short lifetime was chosen to prevent.
 *
 * The agency session, if this browser also has one, is deliberately untouched: they are
 * different principals, and signing out of the operator console is not a statement about the
 * agency account next to it.
 */
export async function POST(request: Request) {
  await clearPendingPlatformEnrolment();
  await clearPlatformSession();
  return NextResponse.redirect(new URL("/platform/login", request.url), { status: 303 });
}
