import { NextResponse } from "next/server";
import { ApiError, platformApi } from "@/lib/api";
import { getPlatformSession } from "@/lib/platform-session";

/**
 * Take an agency offline.
 *
 * No client-side confirmation dialog, and that is deliberate rather than an omission. A
 * `confirm()` is JavaScript this app does not otherwise need, it is dismissed reflexively,
 * and it protects nothing the required ten-character reason does not already protect: an
 * operator cannot reach this handler without having typed a sentence explaining themselves
 * into a field labelled "shown to the agency".
 */
export async function POST(request: Request) {
  const session = await getPlatformSession();
  if (!session) {
    return NextResponse.redirect(new URL("/platform/login", request.url), { status: 303 });
  }

  const form = await request.formData();
  const agencyId = String(form.get("agency_id") ?? "");
  const reason = String(form.get("reason") ?? "").trim();

  try {
    await platformApi.suspendAgency(session.token, agencyId, reason);
    return NextResponse.redirect(
      new URL(`/platform/agencies/${agencyId}?suspended=1`, request.url),
      { status: 303 },
    );
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not suspend that agency.";
    return NextResponse.redirect(
      new URL(
        `/platform/agencies/${agencyId}?error=${encodeURIComponent(message)}`,
        request.url,
      ),
      { status: 303 },
    );
  }
}
