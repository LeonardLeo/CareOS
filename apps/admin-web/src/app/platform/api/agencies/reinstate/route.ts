import { NextResponse } from "next/server";
import { ApiError, platformApi } from "@/lib/api";
import { getPlatformSession } from "@/lib/platform-session";

/**
 * Return a suspended agency to service.
 *
 * A note is required here as well as on the suspension. The agency-side enable/disable pair
 * is deliberately asymmetric — a reason to remove access, nothing to restore it — which is
 * right when an administrator acts inside their own agency and wrong when CareOS acts on a
 * customer: "why did we turn this back on" is the question a dispute asks.
 */
export async function POST(request: Request) {
  const session = await getPlatformSession();
  if (!session) {
    return NextResponse.redirect(new URL("/platform/login", request.url), { status: 303 });
  }

  const form = await request.formData();
  const agencyId = String(form.get("agency_id") ?? "");
  const note = String(form.get("note") ?? "").trim();

  try {
    await platformApi.reinstateAgency(session.token, agencyId, note);
    return NextResponse.redirect(
      new URL(`/platform/agencies/${agencyId}?reinstated=1`, request.url),
      { status: 303 },
    );
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not reinstate that agency.";
    return NextResponse.redirect(
      new URL(
        `/platform/agencies/${agencyId}?error=${encodeURIComponent(message)}`,
        request.url,
      ),
      { status: 303 },
    );
  }
}
