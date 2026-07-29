import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const clientId = String(form.get("client_id") ?? "");
  const credential = String(form.get("task_credential") ?? "").trim().toUpperCase();

  const body = {
    authorized_tasks: [
      {
        code: "task_1",
        label: String(form.get("task_label") ?? "Care task"),
        // Shift matching reads this to decide who is qualified for the visit.
        ...(credential ? { required_credential: credential } : {}),
      },
    ],
    visit_frequency_rule: {
      rrule: String(form.get("rrule") ?? "FREQ=DAILY;COUNT=30"),
      start_hour: Number(form.get("start_hour") ?? 9),
    },
    effective_start: String(form.get("effective_start") ?? ""),
    default_service_type_code: String(form.get("service_code") ?? "").trim() || null,
  };

  try {
    const plan = await api.createCarePlan(session.token, clientId, body);
    return NextResponse.redirect(new URL(`/clients/${clientId}?plan=${plan.id}`, request.url), {
      status: 303,
    });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not create the care plan.";
    return NextResponse.redirect(
      new URL(`/clients/${clientId}?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
