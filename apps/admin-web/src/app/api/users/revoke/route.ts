import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { clearSession, getSession } from "@/lib/session";

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const userId = String(form.get("user_id") ?? "");
  const reason = String(form.get("reason") ?? "").trim();

  try {
    await api.revokeSessions(session.token, userId, reason);
    // Revoking your own sessions is permitted — it is what someone whose laptop was stolen
    // needs — but this browser's cookie now holds a dead token, so clear it here and send them
    // to sign in again. Redirecting to the logout route would not work: it only accepts POST,
    // and a 303 turns the follow-up into a GET.
    if (userId === session.userId) {
      await clearSession();
      return NextResponse.redirect(new URL("/login?revoked=1", request.url), { status: 303 });
    }
    return NextResponse.redirect(new URL("/users?revoked=1", request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not end those sessions.";
    return NextResponse.redirect(
      new URL(`/users?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
