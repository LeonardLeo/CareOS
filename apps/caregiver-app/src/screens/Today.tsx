import type { MyVisit } from "@/lib/api";
import type { Translator } from "@/lib/i18n";
import type { OutboxAction } from "@/lib/outbox";
import { splitByToday } from "@/lib/schedule";

/**
 * Today's schedule.
 *
 * Sorted by start time and nothing else, because the only question this screen answers is
 * "where am I going next". The next incomplete visit is the one loud card; completed visits
 * stay in the list rather than disappearing, so a caregiver can confirm what they have already
 * done without navigating anywhere.
 *
 * A queued action shows on its visit rather than only in the connection bar. The bar answers
 * "is anything unsent", this answers "is *this visit* unsent", and at the end of a shift the
 * second question is the one being asked.
 */
function timeOf(iso: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

function stateOf(
  visit: MyVisit,
  queued: OutboxAction[],
): "queued" | "done" | "active" | "upcoming" {
  if (queued.some((a) => a.visitId === visit.id)) return "queued";
  if (visit.clock_out_time) return "done";
  if (visit.clock_in_time) return "active";
  return "upcoming";
}

export function Today({
  visits,
  queued,
  cachedAt,
  onOpen,
  onSignOut,
  t,
  locale,
}: {
  visits: MyVisit[];
  queued: OutboxAction[];
  cachedAt: string | null;
  onOpen: (visit: MyVisit) => void;
  onSignOut: () => void;
  t: Translator;
  locale: string;
}) {
  const { today: ordered, laterCount } = splitByToday(visits);
  const nextId = ordered.find((v) => !v.clock_out_time)?.id ?? null;

  return (
    <>
      <header className="topbar">
        <div className="topbar__brand">
          {t("appName")}
          <span>{t("appSubtitle")}</span>
        </div>
        <button className="iconbutton" type="button" onClick={onSignOut}>
          {t("signOut")}
        </button>
      </header>

      <div className="page">
        <h1 className="page__title">{t("today")}</h1>
        {/* The date is shown whether or not the data is cached. How stale the schedule is and
            which day it covers are different questions, and the second one is the one a
            caregiver looking at a list of times needs answered. */}
        <p className="page__sub">
          {new Date().toLocaleDateString(locale, {
            weekday: "long",
            month: "long",
            day: "numeric",
          })}
          {cachedAt ? ` · ${t("scheduleFrom", { time: timeOf(cachedAt, locale) })}` : ""}
        </p>

        {cachedAt && (
          <div className="note note--queued" style={{ marginBottom: "var(--space-4)" }}>
            {t("showingCached")}
          </div>
        )}

        {ordered.length === 0 ? (
          <div className="note">{t("noVisitsToday")}</div>
        ) : (
          <div className="stack">
            {ordered.map((visit) => {
              const state = stateOf(visit, queued);
              const modifier =
                state === "queued"
                  ? "visit--queued"
                  : state === "done"
                    ? "visit--done"
                    : visit.id === nextId
                      ? "visit--next"
                      : "";
              return (
                <button
                  key={visit.id}
                  className={`visit ${modifier}`}
                  type="button"
                  onClick={() => onOpen(visit)}
                >
                  <div className="visit__time">
                    {timeOf(visit.scheduled_start, locale)} – {timeOf(visit.scheduled_end, locale)}
                  </div>
                  <div className="visit__name">{visit.client.legal_name}</div>
                  <div className="visit__meta">
                    {visit.client.address ?? t("noAddress")}
                  </div>
                  <div className="visit__meta">
                    {state === "queued" && <span className="chip chip--queued">{t("willSync")}</span>}
                    {state === "done" && <span className="chip chip--done">{t("visitComplete")}</span>}
                    {state === "active" && visit.clock_in_time && (
                      <span className="chip chip--done">
                        {t("clockedInAt", { time: timeOf(visit.clock_in_time, locale) })}
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* Says the quiet part out loud: the app is holding days this screen is not showing.
            Without it, a caregiver whose today is empty cannot tell an empty day from an app
            that failed to load anything. */}
        {laterCount > 0 && (
          <p className="page__sub">{t("laterVisits", { count: String(laterCount) })}</p>
        )}
      </div>
    </>
  );
}
