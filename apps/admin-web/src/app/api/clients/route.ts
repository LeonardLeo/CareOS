import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

function numberOrNull(value: FormDataEntryValue | null): number | null {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const body = {
    legal_name: String(form.get("legal_name") ?? ""),
    dob: String(form.get("dob") ?? "") || null,
    address: String(form.get("address") ?? "") || null,
    geo_lat: numberOrNull(form.get("geo_lat")),
    geo_lng: numberOrNull(form.get("geo_lng")),
    service_state: String(form.get("service_state") ?? "").toUpperCase(),
    primary_payer_type: String(form.get("primary_payer_type") ?? "private_pay"),
  };

  try {
    const client = await api.createClient(session.token, body);
    return NextResponse.redirect(new URL(`/clients/${client.id}`, request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not create the client.";
    return NextResponse.redirect(
      new URL(`/clients?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
