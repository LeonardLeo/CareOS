import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

/** Return a disabled account to service. No reason required — see the API handler for why. */
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const userId = String(form.get("user_id") ?? "");

  try {
    await api.enableUser(session.token, userId);
    return NextResponse.redirect(new URL("/users?enabled=1", request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not enable that account.";
    return NextResponse.redirect(
      new URL(`/users?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
