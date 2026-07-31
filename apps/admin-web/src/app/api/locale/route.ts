import { NextResponse } from "next/server";
import { isLocale } from "@/lib/locale";
import { LOCALE_COOKIE, LOCALE_COOKIE_MAX_AGE } from "@/lib/locale";

/**
 * Set the language and return to the page the user was on.
 *
 * A form POST rather than client-side state, matching sign-out next to it. The whole app is
 * server-rendered, so switching language means asking the server for the page again — and
 * doing it this way means the switcher works with JavaScript disabled and needs no hydration
 * on a page that otherwise ships none.
 *
 * 303 rather than 302, so the browser follows with GET. A 302 after a POST leaves older
 * clients re-posting the form on refresh.
 */
export async function POST(request: Request) {
  const form = await request.formData();
  const requested = form.get("locale");
  const returnTo = form.get("returnTo");

  const locale = typeof requested === "string" && isLocale(requested) ? requested : "en";

  // Only same-origin paths, and never a protocol-relative `//evil.example` — which a browser
  // reads as an absolute URL. An open redirect on an authenticated app is a phishing primitive,
  // and this parameter comes from a form field.
  const path =
    typeof returnTo === "string" && returnTo.startsWith("/") && !returnTo.startsWith("//")
      ? returnTo
      : "/dashboard";

  const response = NextResponse.redirect(new URL(path, request.url), { status: 303 });
  response.cookies.set(LOCALE_COOKIE, locale, {
    path: "/",
    maxAge: LOCALE_COOKIE_MAX_AGE,
    sameSite: "lax",
    // Not httpOnly on purpose: this selects a language and carries no authority. The session
    // cookie beside it is httpOnly for the opposite reason.
    httpOnly: false,
  });
  return response;
}
