/**
 * What the Today screen is allowed to show.
 *
 * The bug these pin was found by signing in as a real caregiver rather than by reading the
 * code: the screen listed nine visits spanning two weeks under the heading "Today", with only
 * times on the cards, so six of them appeared to overlap each other. Nothing failed. The
 * schedule was simply wrong in a way that would have sent someone to the wrong address.
 */

import { describe, expect, it } from "vitest";
import { isSameLocalDay, splitByToday } from "../src/lib/schedule";

/** An ISO timestamp at local midday on a day offset from `now`, so no test sits near a boundary. */
function localMidday(now: Date, dayOffset: number): string {
  const d = new Date(now);
  d.setDate(d.getDate() + dayOffset);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
}

describe("splitByToday", () => {
  const now = new Date("2026-07-31T14:00:00");

  it("drops visits cached for later days", () => {
    const visits = [
      { id: "today", scheduled_start: localMidday(now, 0) },
      { id: "tomorrow", scheduled_start: localMidday(now, 1) },
      { id: "next-week", scheduled_start: localMidday(now, 7) },
    ];
    const { today, laterCount } = splitByToday(visits, now);
    expect(today.map((v) => v.id)).toEqual(["today"]);
    expect(laterCount).toBe(2);
  });

  it("drops visits from previous days, which a caregiver can no longer work", () => {
    const visits = [
      { id: "three-days-ago", scheduled_start: localMidday(now, -3) },
      { id: "yesterday", scheduled_start: localMidday(now, -1) },
      { id: "today", scheduled_start: localMidday(now, 0) },
    ];
    expect(splitByToday(visits, now).today.map((v) => v.id)).toEqual(["today"]);
  });

  it("orders today's visits earliest first, whatever order they arrived in", () => {
    const visits = [
      { id: "afternoon", scheduled_start: "2026-07-31T15:00:00" },
      { id: "morning", scheduled_start: "2026-07-31T07:30:00" },
      { id: "midday", scheduled_start: "2026-07-31T12:00:00" },
    ];
    expect(splitByToday(visits, now).today.map((v) => v.id)).toEqual([
      "morning",
      "midday",
      "afternoon",
    ]);
  });

  it("reports an empty day as empty rather than borrowing from the lookahead", () => {
    const visits = [{ id: "tomorrow", scheduled_start: localMidday(now, 1) }];
    const { today, laterCount } = splitByToday(visits, now);
    expect(today).toEqual([]);
    // The count is what lets the screen say "nothing today, 1 saved for later" instead of
    // leaving a caregiver unable to tell an empty day from an app that loaded nothing.
    expect(laterCount).toBe(1);
  });
});

describe("isSameLocalDay", () => {
  it("compares in the device's timezone, not UTC", () => {
    // 23:30 local on the 31st. Depending on the offset this is a different UTC date, and a
    // UTC comparison would put an evening visit on tomorrow's schedule.
    const late = new Date("2026-07-31T23:30:00");
    expect(isSameLocalDay(late.toISOString(), new Date("2026-07-31T09:00:00"))).toBe(true);
  });

  it("does not treat the same clock time on a different day as today", () => {
    expect(
      isSameLocalDay(new Date("2026-08-01T09:00:00").toISOString(), new Date("2026-07-31T09:00:00")),
    ).toBe(false);
  });
});
