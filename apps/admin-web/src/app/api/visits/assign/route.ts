/**
 * Assign a caregiver to a visit.
 *
 * A compliance gate refusal (an uncleared OIG/GSA exclusion check, an expired credential) is
 * surfaced to the scheduler verbatim rather than flattened into a generic failure. The API's
 * message states which rule blocked the assignment, and that is exactly what the scheduler
 * needs in order to resolve it.
 */
import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.redirect(new URL("/login", request.url), { status: 303 });
  }

  const form = await request.formData();
  const visitId = String(form.get("visit_id") ?? "");
  const caregiverId = String(form.get("caregiver_id") ?? "");

  try {
    await api.assign(session.token, visitId, caregiverId);
    return NextResponse.redirect(new URL("/scheduling?assigned=1", request.url), { status: 303 });
  } catch (error) {
    const message =
      error instanceof ApiError ? error.message : "Could not assign this caregiver.";
    return NextResponse.redirect(
      new URL(`/scheduling?visit=${visitId}&error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
