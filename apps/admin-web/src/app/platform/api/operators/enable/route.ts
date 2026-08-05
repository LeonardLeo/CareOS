import { NextResponse } from "next/server";
import { ApiError, platformApi } from "@/lib/api";
import { getPlatformSession } from "@/lib/platform-session";

/**
 * Return a disabled operator to service.
 *
 * The revocation watermark set when they were disabled is deliberately left where it is, so
 * tokens issued before the disablement stay dead. Clearing it would revive whatever session
 * was open on the laptop that was handed back.
 */
export async function POST(request: Request) {
  const session = await getPlatformSession();
  if (!session) {
    return NextResponse.redirect(new URL("/platform/login", request.url), { status: 303 });
  }

  const form = await request.formData();
  const operatorId = String(form.get("operator_id") ?? "");

  try {
    await platformApi.enableOperator(session.token, operatorId);
    return NextResponse.redirect(new URL("/platform/operators?enabled=1", request.url), {
      status: 303,
    });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not enable that operator.";
    return NextResponse.redirect(
      new URL(`/platform/operators?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
