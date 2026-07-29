/**
 * Scheduling board and gap-fill — Flow A in `09_UX_Design_and_User_Flows.md`, the
 * highest-frequency flow in Phase 1.
 *
 * The flow it implements: a scheduler sees a gap, opens the visit, sees AI-ranked caregivers
 * with visible reasoning, and offers the shift in one action.
 *
 * Three things the design has to get right, all from that document:
 *
 * - **Exceptions over data entry** (principle 3). The default view is unfilled shifts, not a
 *   complete calendar.
 * - **Explainable AI, always visible** (principle 4). Every suggestion shows its factors
 *   inline; there is no bare score anywhere on this page.
 * - **Actionable suggestions only.** The API omits caregivers who would fail a compliance
 *   gate, so every name here can actually be assigned. Where one carries a caveat — overtime
 *   exposure, a long drive — it is shown next to the button, not hidden behind a tooltip.
 */

import Link from "next/link";
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
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function SchedulingPage({
  searchParams,
}: {
  searchParams: Promise<{ visit?: string; error?: string; assigned?: string }>;
}) {
  const session = await getSession();
  if (!session) return null;
  const { visit: selectedVisitId, error, assigned } = await searchParams;

  try {
    const gaps = await api.gaps(session.token, 24 * 14);
    const selected = selectedVisitId
      ? (gaps.find((v) => v.id === selectedVisitId) ?? null)
      : null;
    const suggestions = selected ? await api.suggestions(session.token, selected.id) : [];

    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Scheduling</h1>
          <p className="page-subtitle">
            Unfilled shifts over the next two weeks, most urgent first.
          </p>
        </header>

        {assigned && (
          <Card>
            <p>
              <SeverityBadge severity="success">Assigned</SeverityBadge>{" "}
              The caregiver has been assigned to that visit.
            </p>
          </Card>
        )}

        {error && (
          <ErrorNote
            title="That caregiver could not be assigned"
            // The API states which rule blocked it — an uncleared exclusion check, an expired
            // credential — and that is precisely what the scheduler needs to act on.
            detail={error}
          />
        )}

        <Card title="Open shifts" subtitle={`${gaps.length} unfilled`}>
          {gaps.length === 0 ? (
            <EmptyState
              title="No unfilled shifts"
              detail="Every visit in the next two weeks has a caregiver assigned."
            />
          ) : (
            <Table
              headers={["When", "Service", "Payer", "State", ""]}
              caption="Unfilled shifts in the next two weeks"
            >
              {gaps.map((visit) => (
                <tr key={visit.id}>
                  <td>{formatDateTime(visit.scheduled_start)}</td>
                  <td>
                    {visit.service_type_code ?? (
                      <span className="muted">
                        Not set{" "}
                        <SeverityBadge severity="warning">Unbillable later</SeverityBadge>
                      </span>
                    )}
                  </td>
                  <td>{visit.payer_type ?? <span className="muted">—</span>}</td>
                  <td>{visit.service_state ?? <span className="muted">—</span>}</td>
                  <td>
                    <Link
                      className={
                        selected?.id === visit.id
                          ? "button button--small"
                          : "button button--secondary button--small"
                      }
                      href={`/scheduling?visit=${visit.id}`}
                    >
                      {selected?.id === visit.id ? "Viewing" : "Find caregiver"}
                    </Link>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        {selected && (
          <Card
            title="Suggested caregivers"
            subtitle={`For the visit on ${formatDateTime(selected.scheduled_start)}. Only caregivers who pass every compliance gate are listed.`}
          >
            {suggestions.length === 0 ? (
              <EmptyState
                title="No caregiver can currently take this visit"
                detail="Everyone is either unavailable, double-booked, or blocked by a compliance gate — an uncleared exclusion check or an expired credential. Check the credentialing queue."
              />
            ) : (
              suggestions.map((suggestion) => (
                <div key={suggestion.caregiver_id} className="suggestion">
                  <div className="suggestion__head">
                    <span className="suggestion__name">{suggestion.caregiver_name}</span>
                    <span className="suggestion__score">
                      {Math.round(suggestion.score * 100)}
                      <span className="visually-hidden"> out of 100 match score</span>
                    </span>
                  </div>

                  {/* Principle 4: the reasoning is always on screen, never behind a hover. */}
                  <FactorList factors={suggestion.factors} />

                  {suggestion.warnings.map((warning) => (
                    <p key={warning} className="suggestion__warning">
                      <span aria-hidden="true">⚠</span>
                      <span>{warning}</span>
                    </p>
                  ))}

                  <form
                    method="post"
                    action="/api/visits/assign"
                    style={{ marginTop: "var(--space-4)" }}
                  >
                    <input type="hidden" name="visit_id" value={selected.id} />
                    <input type="hidden" name="caregiver_id" value={suggestion.caregiver_id} />
                    <button className="button button--small" type="submit">
                      Assign {suggestion.caregiver_name}
                    </button>
                  </form>
                </div>
              ))
            )}
          </Card>
        )}
      </>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Could not load scheduling data.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Scheduling</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
