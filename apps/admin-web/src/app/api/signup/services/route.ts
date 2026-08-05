/**
 * Sign-up, step two: what the agency delivers and who pays for it.
 *
 * Both answers decide which compliance rules apply to every visit the agency will ever
 * record, which is why neither is optional and neither is deferred to a settings screen
 * nobody opens.
 */
import { NextResponse } from "next/server";
import {
  PAYER_TYPES,
  SERVICE_LINES,
  getSignupDraft,
  setSignupDraft,
} from "@/lib/signup-draft";

export async function POST(request: Request) {
  const existing = await getSignupDraft();
  // The draft expired, or the tab was open long enough for the cookie to lapse. Restarting
  // with a message beats posting a half-empty agency to the API and rendering its 422.
  if (!existing || !existing.legalName) {
    return back(request, 1, "expired");
  }

  const form = await request.formData();
  const lines = new Set(form.getAll("service_lines").map(String));
  const payers = new Set(form.getAll("payer_types").map(String));
  const serviceLines = SERVICE_LINES.filter((line) => lines.has(line));
  const payerTypes = PAYER_TYPES.filter((payer) => payers.has(payer));

  if (serviceLines.length === 0) return back(request, 2, "lines");
  if (payerTypes.length === 0) return back(request, 2, "payers");

  await setSignupDraft({
    ...existing,
    serviceLines: [...serviceLines],
    payerTypes: [...payerTypes],
  });
  return NextResponse.redirect(new URL("/signup?step=3", request.url), { status: 303 });
}

function back(request: Request, step: number, error: string) {
  return NextResponse.redirect(new URL(`/signup?step=${step}&error=${error}`, request.url), {
    status: 303,
  });
}
