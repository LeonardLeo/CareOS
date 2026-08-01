import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const id = String(form.get("exception_id") ?? "");
  const note = String(form.get("note") ?? "").trim() || null;

  try {
    await api.resolveException(session.token, id, note);
    return NextResponse.redirect(new URL("/exceptions?resolved=1", request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not resolve.";
    return NextResponse.redirect(
      new URL(`/exceptions?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
