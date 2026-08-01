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
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
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
  const t = translatorFor(await getLocale());
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
            <h1 className="page-title">{t("exceptionsTitle")}</h1>
            <p className="page-subtitle">
              {t("exceptionsSubtitle")}
            </p>
          </div>
        </header>

        {resolved && (
          <div className="notice">
            <SeverityBadge severity="good">{t("resolved")}</SeverityBadge>
            <span>{t("exceptionClosedNote")}</span>
          </div>
        )}
        {error && <ErrorNote title={t("couldNotResolveException")} detail={error} />}

        <div className="stat-grid">
          <StatTile
            label={t("open")}
            value={summary.total_open}
            severity={summary.total_open > 0 ? "warning" : "good"}
          />
          <StatTile
            label={t("critical")}
            value={summary.by_severity["critical"] ?? 0}
            severity={(summary.by_severity["critical"] ?? 0) > 0 ? "critical" : "good"}
            hint={t("blocksBillingOrScheduling")}
          />
          <StatTile label={t("warning")} value={summary.by_severity["warning"] ?? 0} />
          <StatTile label={t("info")} value={summary.by_severity["info"] ?? 0} />
        </div>

        <Card
          title={t("queue")}
          subtitle={t("queueSubtitle")}
        >
          {exceptions.length === 0 ? (
            <EmptyState
              title={t("noOpenExceptions")}
              detail={t("noOpenExceptionsDetail")}
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
                        placeholder={t("whatWasDone")}
                        style={{ minWidth: "18rem" }}
                        aria-label={t("resolutionNote")}
                      />
                      <button className="button button--secondary button--small" type="submit">
                        {t("markResolved")}
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
    const message = err instanceof ApiError ? err.message : t("couldNotLoadExceptions");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("exceptionsTitle")}</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
