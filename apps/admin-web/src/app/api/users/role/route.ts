import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  try {
    await api.changeRole(
      session.token,
      String(form.get("user_id") ?? ""),
      String(form.get("role") ?? ""),
    );
    return NextResponse.redirect(new URL("/users?changed=1", request.url), { status: 303 });
  } catch (error) {
    // Includes the API's refusal to let an owner demote themselves, which would otherwise
    // leave the agency with nobody able to administer it.
    const message = error instanceof ApiError ? error.message : "Could not change that role.";
    return NextResponse.redirect(
      new URL(`/users?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
