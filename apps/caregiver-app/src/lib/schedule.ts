/**
 * Selecting the day a caregiver is actually working.
 *
 * This lives in `lib` rather than in the screen because the screen is not where it can be
 * tested — `vitest.config.ts` runs this directory in a node environment with no React — and
 * because it is the kind of logic that is wrong silently. The Today screen renders a time of
 * day with no date on it, so a visit from the wrong day does not look like a bug. It looks
 * like a shift the caregiver forgot about, at a client's address, overlapping the one they
 * are standing in.
 *
 * The cache holds more than one day on purpose, so tomorrow morning still works with no
 * signal. Splitting "what is cached" from "what is today" is what makes both possible.
 */

export interface DatedVisit {
  scheduled_start: string;
}

/** True when `iso` falls on the same calendar day as `now`, in the device's own timezone. */
export function isSameLocalDay(iso: string, now: Date = new Date()): boolean {
  const when = new Date(iso);
  return (
    when.getFullYear() === now.getFullYear() &&
    when.getMonth() === now.getMonth() &&
    when.getDate() === now.getDate()
  );
}

/**
 * Today's visits, earliest first, plus a count of everything cached for later days.
 *
 * The count is returned rather than discarded so the screen can distinguish an empty day from
 * a failed load. Those look identical otherwise, and they call for opposite actions.
 */
export function splitByToday<T extends DatedVisit>(
  visits: readonly T[],
  now: Date = new Date(),
): { today: T[]; laterCount: number } {
  const today = visits
    .filter((v) => isSameLocalDay(v.scheduled_start, now))
    .sort((a, b) => a.scheduled_start.localeCompare(b.scheduled_start));
  return { today, laterCount: visits.length - today.length };
}
