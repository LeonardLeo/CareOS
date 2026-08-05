import { NextResponse } from "next/server";
import { ApiError, platformApi } from "@/lib/api";
import { getPlatformSession } from "@/lib/platform-session";

export async function POST(request: Request) {
  const session = await getPlatformSession();
  if (!session) {
    return NextResponse.redirect(new URL("/platform/login", request.url), { status: 303 });
  }

  const form = await request.formData();
  try {
    await platformApi.createOperator(session.token, {
      email: String(form.get("email") ?? "").trim(),
      display_name: String(form.get("display_name") ?? "").trim(),
      role: String(form.get("role") ?? "platform_support"),
      initial_password: String(form.get("initial_password") ?? ""),
    });
    return NextResponse.redirect(new URL("/platform/operators?created=1", request.url), {
      status: 303,
    });
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not add that operator.";
    return NextResponse.redirect(
      new URL(`/platform/operators?error=${encodeURIComponent(message)}`, request.url),
      { status: 303 },
    );
  }
}
