/**
 * Compliance exception queue (US-1.4.6).
 *
 * `09_UX_Design_and_User_Flows.md` principle 3 makes exception queues the scheduler's
 * default view: surface what needs attention rather than a complete list. This is that
 * queue as a first-class screen rather than a dashboard tile.
 *
 * Ordering is most-severe first, then **oldest first within a severity**. An exception that
 * has sat unresolved for a week is a worse problem than one raised an hour ago, and a
 * newest-first queue buries exactly the ones that have been ignored.
 *
 * Resolving is an audited act by a named person, not a dismissal — an auditor may later ask
 * who decided this was handled, and the audit log answers that.
 */

import { Card, EmptyState, ErrorNote, SeverityBadge, formatDateTime } from "@/components/ui";
import { StatTile } from "@/components/charts";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

const RULE_LABEL: Record<string, string> = {
  "evv.missing_clock_time": "Missing clock time",
  "evv.outside_geofence": "Clock-in outside geofence",
  "evv.missing_service_code": "No service code",
  "evv.transmission_rejected": "EVV rejected by aggregator",
  "evv.transmission_unacknowledged": "EVV not acknowledged",
  "evv.transmission_exhausted": "EVV retries exhausted",
  "credentialing.expired_at_visit": "Credential expired at visit",
  "credentialing.exclusion_not_cleared": "Exclusion check not cleared",
};

function severityOf(value: string): "critical" | "warning" | "info" | "neutral" {
  if (value === "critical") return "critical";
  if (value === "warning") return "warning";
  if (value === "info") return "info";
  return "neutral";
}

export default async function ExceptionsPage({
  searchParams,
}: {
  searchParams: Promise<{ resolved?: string; error?: string }>;
}) {
  const session = await getSession();
  if (!session) return null;
  const { resolved, error } = await searchParams;

  try {
    const [exceptions, summary] = await Promise.all([
      api.exceptions(session.token, false),
      api.exceptionSummary(session.token),
    ]);

    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">Compliance exceptions</h1>
            <p className="page-subtitle">
              Open findings from the rules engine and the EVV transmission worker. Critical
              items block billing or mean a caregiver cannot legally work the visit.
            </p>
          </div>
        </header>

        {resolved && (
          <div className="notice">
            <SeverityBadge severity="good">Resolved</SeverityBadge>
            <span>That exception has been closed and the action recorded in the audit log.</span>
          </div>
        )}
        {error && <ErrorNote title="Could not resolve that exception" detail={error} />}

        <div className="stat-grid">
          <StatTile
            label="Open"
            value={summary.total_open}
            severity={summary.total_open > 0 ? "warning" : "good"}
          />
          <StatTile
            label="Critical"
            value={summary.by_severity["critical"] ?? 0}
            severity={(summary.by_severity["critical"] ?? 0) > 0 ? "critical" : "good"}
            hint="Blocks billing or scheduling"
          />
          <StatTile label="Warning" value={summary.by_severity["warning"] ?? 0} />
          <StatTile label="Info" value={summary.by_severity["info"] ?? 0} />
        </div>

        <Card
          title="Queue"
          subtitle="Most severe first, then oldest first — an exception that has sat for a week outranks one raised an hour ago"
        >
          {exceptions.length === 0 ? (
            <EmptyState
              title="No open compliance exceptions"
              detail="Every visit's EVV record, credentials and screening are in order. This queue is empty most of the time — that is the intended state, not a missing page."
            />
          ) : (
            <div style={{ margin: "calc(var(--space-4) * -1)" }}>
              {exceptions.map((exception) => (
                <div key={exception.id} className="suggestion">
                  <div className="suggestion__head">
                    <div>
                      <div className="suggestion__name">
                        {RULE_LABEL[exception.rule_key] ?? exception.rule_key}
                      </div>
                      <div className="suggestion__meta">
                        Raised {formatDateTime(exception.created_at)} · {exception.entity_type}
                      </div>
                    </div>
                    <SeverityBadge severity={severityOf(exception.severity)}>
                      {exception.severity}
                    </SeverityBadge>
                  </div>

                  <p className="small" style={{ marginTop: "var(--space-2)" }}>
                    {exception.message}
                  </p>

                  <div className="suggestion__actions">
                    <form method="post" action="/api/exceptions/resolve" className="row">
                      <input type="hidden" name="exception_id" value={exception.id} />
                      <input
                        className="field__input"
                        name="note"
                        placeholder="What was done? (optional)"
                        style={{ minWidth: "18rem" }}
                        aria-label="Resolution note"
                      />
                      <button className="button button--secondary button--small" type="submit">
                        Mark resolved
                      </button>
                    </form>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Could not load the exception queue.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Compliance exceptions</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
