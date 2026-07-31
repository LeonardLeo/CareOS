import { NextResponse } from "next/server";
import { getSession } from "@/lib/session";

/**
 * Begin enrolment.
 *
 * A POST that redirects to the page with `?started=1`, rather than the page minting a secret
 * on load: a GET that issued a new secret every time it was rendered would invalidate the one
 * the user is part-way through scanning, including on a refresh or a back button.
 */
export async function POST(request: Request) {
  const session = await getSession();
  if (!session) return NextResponse.redirect(new URL("/login", request.url), { status: 303 });
  return NextResponse.redirect(new URL("/security?started=1", request.url), { status: 303 });
}
