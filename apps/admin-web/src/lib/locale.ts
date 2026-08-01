/**
 * Which language to render in, resolved on the server.
 *
 * The caregiver app reads `localStorage` and `navigator.language`, which is right for a
 * client-rendered PWA and impossible here: this app renders on the server, so by the time any
 * browser API exists the HTML has already been sent. Reading the locale from a cookie instead
 * means the first paint is in the right language rather than flashing English and correcting
 * itself, which matters more than it sounds — a scheduler working a gap does not want the page
 * to rewrite itself under them.
 *
 * Order of preference:
 *
 * 1. **The `careos_locale` cookie**, set by the language switcher. An explicit choice wins.
 * 2. **`Accept-Language`**, so a Spanish-speaking user gets Spanish before they have chosen
 *    anything. Parsed with quality values, because `es;q=0.9, en;q=1.0` means English.
 * 3. **English.**
 *
 * The cookie is deliberately *not* httpOnly. It carries no authority — it selects a language —
 * and leaving it readable lets client components pick up the same value without a round trip.
 * The session cookie next to it is httpOnly for the opposite reason.
 */

import { cookies, headers } from "next/headers";
import { LOCALES, type Locale } from "@/lib/i18n";

export const LOCALE_COOKIE = "careos_locale";

/** A year: a language preference is not a session, and should outlive one. */
export const LOCALE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

export function isLocale(value: string | undefined | null): value is Locale {
  return value !== null && value !== undefined && (LOCALES as readonly string[]).includes(value);
}

/**
 * Best match from an `Accept-Language` header.
 *
 * Quality values are honoured rather than taking the first tag, because browsers send lists
 * like `en-US,es;q=0.9` where order alone is not the answer. Region subtags are dropped:
 * `es-MX` and `es-419` are both served by the same Spanish here, and matching exactly would
 * mean falling back to English for most Spanish speakers.
 */
export function localeFromAcceptLanguage(header: string | null): Locale | null {
  if (!header) return null;

  const ranked = header
    .split(",")
    .map((part) => {
      const [tag = "", ...params] = part.trim().split(";");
      const q = params
        .map((p) => p.trim())
        .find((p) => p.startsWith("q="))
        ?.slice(2);
      const quality = q === undefined ? 1 : Number.parseFloat(q);
      return {
        base: tag.trim().toLowerCase().split("-")[0] ?? "",
        quality: Number.isFinite(quality) ? quality : 0,
      };
    })
    // Highest quality first. A stable sort keeps header order as the tie-break, which is what
    // a client means by listing one tag before another at the same weight.
    .sort((a, b) => b.quality - a.quality);

  for (const { base, quality } of ranked) {
    if (quality <= 0) continue; // `q=0` is an explicit refusal of that language
    if (isLocale(base)) return base;
  }
  return null;
}

/** The locale for this request. Server components call this; nothing else needs to. */
export async function getLocale(): Promise<Locale> {
  const stored = (await cookies()).get(LOCALE_COOKIE)?.value;
  if (isLocale(stored)) return stored;

  const accepted = localeFromAcceptLanguage((await headers()).get("accept-language"));
  return accepted ?? "en";
}
