import { NextResponse } from "next/server";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

/**
 * Disable an account: end its sessions *and* stop it signing in again.
 *
 * The sibling of `../revoke`, and the difference is the whole reason both exist. Revoking ends
 * the sessions someone holds and leaves them able to sign straight back in — right for a lost
 * phone, wrong for someone who no longer works here.
 *
 * No self-disable branch, unlike revoke: the API refuses to disable the caller's own account,
 * so this never has to clear the cookie. The refusal arrives as a 403 and is shown on the page.
 */
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });

  const form = await request.formData();
  const userId = String(form.get("user_id") ?? "");
  const reason = String(form.get("reason") ?? "").trim();

  try {
    await api.disableUser(session.token, userId, reason);
    return NextResponse.redirect(new URL("/users?disabled=1", request.url), { status: 303 });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not disable that account.";
    return NextResponse.redirect(
      new URL(`/users?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
