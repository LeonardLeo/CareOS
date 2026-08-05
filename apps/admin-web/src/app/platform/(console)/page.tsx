/**
 * The fleet: every agency on CareOS, worst first.
 *
 * The ordering is the argument the screen makes. An operator opens this looking for the
 * tenant that needs a phone call — an aggregator rejecting every record, a queue that has
 * not moved since Tuesday, a suspension somebody needs to lift — and a list sorted by name
 * makes them read four hundred rows to find it. The API returns it ordered by suspension,
 * then open critical exceptions, then rejected EVV records, then the oldest thing waiting to
 * send; this page renders that order rather than imposing its own.
 *
 * The panel at the top says what the console can and cannot see, in plain words. It is not
 * decoration: the first question anyone asks about a vendor's internal console is whether
 * staff can read customer records, and the answer here is a mechanism — a database role with
 * no permission on those tables — that deserves to be stated where the people using it can
 * see it, not only in a security document.
 */

import Link from "next/link";
import { Card, EmptyState, ErrorNote, SeverityBadge, Table, formatDate } from "@/components/ui";
import { ApiError, type AgencyHealth, platformApi } from "@/lib/api";
import { type Translator, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getPlatformSession } from "@/lib/platform-session";

export const dynamic = "force-dynamic";

export default async function PlatformFleetPage() {
  const session = await getPlatformSession();
  if (!session) return null;
  const locale = await getLocale();
  const t = translatorFor(locale);

  let fleet;
  try {
    fleet = await platformApi.fleet(session.token);
  } catch (error) {
    const detail = error instanceof ApiError ? error.message : t("somethingWentWrong");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("platformFleetTitle")}</h1>
        </header>
        <ErrorNote title={t("platformCouldNotLoad")} detail={detail} />
      </>
    );
  }

  const { summary, agencies } = fleet;

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">{t("platformFleetTitle")}</h1>
          <p className="page-subtitle">{t("platformFleetSubtitle")}</p>
        </div>
      </header>

      <div className="info-note" role="note">
        <span className="info-note__icon" aria-hidden="true">
          i
        </span>
        <div>
          <p className="info-note__title">{t("platformScopeTitle")}</p>
          <p className="info-note__detail">{t("platformScopeBody")}</p>
        </div>
      </div>

      <div className="stat-grid">
        <Stat label={t("platformTotalAgencies")} value={summary.agencies_total} />
        <Stat
          label={t("platformSuspendedAgencies")}
          value={summary.agencies_suspended}
          tone={summary.agencies_suspended > 0 ? "warning" : undefined}
        />
        <Stat
          label={t("platformCriticalExceptions")}
          value={summary.open_critical_exceptions}
          tone={summary.open_critical_exceptions > 0 ? "critical" : "good"}
        />
        <Stat
          label={t("platformRejectedEvv")}
          value={summary.agencies_with_rejected_evv}
          tone={summary.agencies_with_rejected_evv > 0 ? "critical" : "good"}
        />
        <Stat
          label={t("platformStalledEvv")}
          value={summary.agencies_with_stalled_evv}
          tone={summary.agencies_with_stalled_evv > 0 ? "warning" : "good"}
        />
      </div>

      <Card title={t("platformFleetTitle")} subtitle={t("platformFleetSubtitle")}>
        {agencies.length === 0 ? (
          <EmptyState title={t("platformNoAgencies")} detail={t("platformNoAgenciesDetail")} />
        ) : (
          <Table
            caption={t("platformFleetSubtitle")}
            headers={[
              t("platformColAgency"),
              t("platformColStates"),
              t("platformColPeople"),
              t("platformColSchedule"),
              t("platformColEvv"),
              t("platformColExceptions"),
              t("platformColCredentials"),
              t("platformColActivity"),
            ]}
          >
            {agencies.map((agency) => (
              <FleetRow key={agency.agency_id} agency={agency} t={t} />
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

function FleetRow({ agency, t }: { agency: AgencyHealth; t: Translator }) {
  const suspended = agency.status === "suspended";
  return (
    <tr>
      <td>
        <Link href={`/platform/agencies/${agency.agency_id}`}>{agency.legal_name}</Link>
        <div className="small muted">
          {suspended ? (
            <SeverityBadge severity="critical">{t("platformStatusSuspended")}</SeverityBadge>
          ) : (
            <SeverityBadge severity="good">{t("platformStatusActive")}</SeverityBadge>
          )}
        </div>
      </td>
      <td className="mono">{agency.service_states.join(" ")}</td>
      <td className="num">
        {agency.users_active} / {agency.caregivers_active} / {agency.clients_active}
      </td>
      <td className="num">
        {agency.visits_next_7d}
        {agency.visits_unfilled_next_7d > 0 && (
          <span className="userrow__warn"> · {agency.visits_unfilled_next_7d}</span>
        )}
      </td>
      <td className="num">
        {/* Rejected first, because it is the number that changes what an operator does next:
            a rejection is a filing the state refused, and it stays refused until somebody
            acts. Pending and sent-not-acknowledged are queue depth, which drains itself. */}
        {agency.evv_rejected > 0 ? (
          <span className="userrow__revoked">{agency.evv_rejected}</span>
        ) : (
          <span className="muted">{agency.evv_pending + agency.evv_transmitted}</span>
        )}
      </td>
      <td className="num">
        {agency.exceptions_open_critical > 0 ? (
          <span className="userrow__revoked">{agency.exceptions_open_critical}</span>
        ) : (
          <span className="muted">{agency.exceptions_open_warning}</span>
        )}
      </td>
      <td className="num">
        {agency.credentials_expired > 0 ? (
          <span className="userrow__warn">{agency.credentials_expired}</span>
        ) : (
          <span className="muted">{agency.credentials_expiring_30d}</span>
        )}
      </td>
      <td>
        {agency.last_user_login_at ? (
          formatDate(agency.last_user_login_at)
        ) : (
          <span className="muted">{t("platformNeverSignedIn")}</span>
        )}
      </td>
    </tr>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "critical" | "warning" | "good";
}) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className={tone ? `stat__value stat__value--${tone}` : "stat__value"}>{value}</div>
    </div>
  );
}
