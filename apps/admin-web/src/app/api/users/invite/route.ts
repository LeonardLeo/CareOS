import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  try {
    await api.inviteUser(session.token, session.agencyId, {
      email: String(form.get("email") ?? ""),
      role: String(form.get("role") ?? "scheduler"),
      initial_password: String(form.get("initial_password") ?? ""),
    });
    return NextResponse.redirect(new URL("/users?invited=1", request.url), { status: 303 });
  } catch (error) {
    // A duplicate email is the common failure here, and the API's message names it.
    const message = error instanceof ApiError ? error.message : "Could not invite that user.";
    return NextResponse.redirect(
      new URL(`/users?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
