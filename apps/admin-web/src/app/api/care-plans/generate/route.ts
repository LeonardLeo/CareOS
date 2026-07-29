import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const carePlanId = String(form.get("care_plan_id") ?? "");
  const clientId = String(form.get("client_id") ?? "");

  try {
    const visits = await api.generateVisits(session.token, carePlanId, {
      window_start: String(form.get("window_start") ?? ""),
      window_end: String(form.get("window_end") ?? ""),
      duration_minutes: Number(form.get("duration_minutes") ?? 60),
    });
    return NextResponse.redirect(
      new URL(`/clients/${clientId}?plan=${carePlanId}&generated=${visits.length}`, request.url),
      { status: 303 },
    );
  } catch (error) {
    // An unconfigured service code lands here with a message naming the code, the state and
    // the remediation — which is what the person filling the form needs.
    const message = error instanceof ApiError ? error.message : "Could not generate visits.";
    return NextResponse.redirect(
      new URL(
        `/clients/${clientId}?plan=${carePlanId}&error=${encodeURIComponent(message)}`,
        request.url,
      ),
      { status: 303 },
    );
  }
}
