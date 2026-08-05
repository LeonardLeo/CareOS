import { NextResponse } from "next/server";
import { ApiError, platformApi } from "@/lib/api";
import { getPlatformSession } from "@/lib/platform-session";

/**
 * Offboard a CareOS operator.
 *
 * Disabling and revoking are one action here rather than two, unlike the agency Users
 * screen. The distinction there exists because a lost phone is common and reversible — you
 * revoke sessions and the caregiver signs back in. There is no equivalent case for a CareOS
 * employee: an operator account is either in use or it is not, and the reversible half would
 * only be a way to half-offboard someone.
 */
export async function POST(request: Request) {
  const session = await getPlatformSession();
  if (!session) {
    return NextResponse.redirect(new URL("/platform/login", request.url), { status: 303 });
  }

  const form = await request.formData();
  const operatorId = String(form.get("operator_id") ?? "");
  const reason = String(form.get("reason") ?? "").trim();

  try {
    await platformApi.disableOperator(session.token, operatorId, reason);
    return NextResponse.redirect(new URL("/platform/operators?disabled=1", request.url), {
      status: 303,
    });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not disable that operator.";
    return NextResponse.redirect(
      new URL(`/platform/operators?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
