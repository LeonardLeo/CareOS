/**
 * Scheduling board and gap-fill — Flow A in `09_UX_Design_and_User_Flows.md`, the
 * highest-frequency flow in Phase 1.
 *
 * The flow: a scheduler sees a gap, opens the visit, sees ranked caregivers with visible
 * reasoning, and offers the shift in one action.
 *
 * The timeline is the centrepiece rather than a table, because occupancy over time is the
 * actual shape of a scheduler's problem. A list sorted by start time answers "what's next"
 * but hides clustering — three unfilled visits at the same hour on Thursday is a different
 * problem from three spread across the week, and only the spatial layout shows that at a
 * glance. The table stays underneath as the accessible twin and the place you click.
 *
 * Other rules this page follows, all from that document:
 *
 * - **Exceptions over data entry** (principle 3). The default view is what needs filling.
 * - **Explainable AI, always visible** (principle 4). Every score is a bar you can compare
 *   by length, with its factors listed underneath. No bare numbers.
 * - **Actionable suggestions only.** The API omits anyone who would fail a compliance gate,
 *   so every name here can actually be assigned.
 */

import Link from "next/link";
import { ScoreBar, ScheduleTimeline, type TimelineVisit } from "@/components/charts";
import {
  Card,
  EmptyState,
  ErrorNote,
  FactorList,
  SeverityBadge,
  Table,
  formatDateTime,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

function timeOnly(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export default async function SchedulingPage({
  searchParams,
}: {
  searchParams: Promise<{ visit?: string; error?: string; assigned?: string }>;
}) {
  const session = await getSession();
  if (!session) return null;
  const { visit: selectedVisitId, error, assigned } = await searchParams;
  const t = translatorFor(await getLocale());

  try {
    // Two weeks of gaps for the queue; all visits in the window for the timeline, so the
    // gaps are seen against the schedule they sit in rather than in isolation.
    const [gaps, allVisits] = await Promise.all([
      api.gaps(session.token, 24 * 14),
      api.visits(session.token, "?page_size=200"),
    ]);

    const selected = selectedVisitId
      ? (gaps.find((v) => v.id === selectedVisitId) ?? null)
      : null;
    const suggestions = selected ? await api.suggestions(session.token, selected.id) : [];

    const timeline: TimelineVisit[] = allVisits.items.map((v) => ({
      id: v.id,
      start: v.scheduled_start,
      end: v.scheduled_end,
      assigned: v.caregiver_id !== null,
      label: `${timeOnly(v.scheduled_start)}–${timeOnly(v.scheduled_end)}`,
      detail: [
        v.caregiver_id ? "Caregiver assigned" : "Unfilled",
        v.service_type_code ?? "No service code",
        v.payer_type?.replace(/_/g, " ") ?? "No payer",
      ].join(" · "),
    }));

    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">{t("schedulingTitle")}</h1>
            <p className="page-subtitle">
              {t("schedulingSubtitle")}
            </p>
          </div>
          <div className="row">
            <SeverityBadge severity={gaps.length ? "critical" : "good"}>
              {gaps.length} unfilled
            </SeverityBadge>
          </div>
        </header>

        {assigned && (
          <div className="notice">
            <SeverityBadge severity="good">{t("assigned")}</SeverityBadge>
            <span>{t("caregiverAssignedNote")}</span>
          </div>
        )}

        {error && (
          <ErrorNote
            title={t("couldNotAssign")}
            // The API names the rule that blocked it — an uncleared exclusion check, an
            // expired credential — which is exactly what the scheduler needs to act on.
            detail={error}
          />
        )}

        <Card
          title={t("next7Days")}
          subtitle={t("next7DaysSubtitle")}
        >
          <ScheduleTimeline visits={timeline} days={7} selectedId={selected?.id} t={t} />
        </Card>

        <div className="grid-2">
          <Card title={t("unfilledShifts")} subtitle={t("soonestFirst")}>
            {gaps.length === 0 ? (
              <EmptyState
                title={t("noUnfilledShifts")}
                detail={t("everyVisitAssigned2Weeks")}
              />
            ) : (
              <Table
                headers={[t("colWhen"), t("colService"), t("colPayer"), ""]}
                caption={t("unfilledShifts2WeeksCaption")}
              >
                {gaps.map((visit) => (
                  <tr key={visit.id} data-selected={selected?.id === visit.id}>
                    <td>{formatDateTime(visit.scheduled_start)}</td>
                    <td>
                      {visit.service_type_code ?? (
                        <SeverityBadge severity="warning">{t("noServiceCode")}</SeverityBadge>
                      )}
                    </td>
                    <td className="muted small">
                      {visit.payer_type?.replace(/_/g, " ") ?? "—"}
                    </td>
                    <td>
                      <Link
                        className={
                          selected?.id === visit.id
                            ? "button button--small"
                            : "button button--secondary button--small"
                        }
                        href={`/scheduling?visit=${visit.id}`}
                      >
                        {selected?.id === visit.id ? t("viewing") : t("fill")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          <Card
            title={selected ? t("suggestedCaregivers") : t("suggestions")}
            subtitle={
              selected
                ? t("onlyCompliantListed", {
                    when: formatDateTime(selected.scheduled_start),
                  })
                : undefined
            }
          >
            {!selected ? (
              <EmptyState
                title={t("selectUnfilledShift")}
                detail={t("selectShiftDetail")}
              />
            ) : suggestions.length === 0 ? (
              <EmptyState
                title={t("nobodyCanTakeVisit")}
                detail={t("nobodyCanTakeDetail")}
              />
            ) : (
              <div style={{ margin: "calc(var(--space-4) * -1)" }}>
                {suggestions.map((suggestion) => (
                  <div key={suggestion.caregiver_id} className="suggestion">
                    <div className="suggestion__head">
                      <div>
                        <div className="suggestion__name">{suggestion.caregiver_name}</div>
                        <div className="suggestion__meta">
                          {t("factorsConsidered", { count: suggestion.factors.length })}
                        </div>
                      </div>
                      {/* Magnitude as length, so candidates are compared by bar rather than
                          by reading two numbers. Segments sum to the score. */}
                      <ScoreBar
                        score={suggestion.score}
                        segments={suggestion.factors.map((f) => f.weight)}
                        t={t}
                      />
                    </div>

                    <FactorList factors={suggestion.factors} />

                    {suggestion.warnings.map((warning) => (
                      <p key={warning} className="suggestion__warning">
                        <span aria-hidden="true">⚠</span>
                        <span>{warning}</span>
                      </p>
                    ))}

                    <div className="suggestion__actions">
                      <form method="post" action="/api/visits/assign">
                        <input type="hidden" name="visit_id" value={selected.id} />
                        <input
                          type="hidden"
                          name="caregiver_id"
                          value={suggestion.caregiver_id}
                        />
                        <button className="button button--small" type="submit">
                          {t("assignNamed", {
                            name: suggestion.caregiver_name.split(" ")[0] ?? "",
                          })}
                        </button>
                      </form>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : t("couldNotLoadScheduling");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("schedulingTitle")}</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
