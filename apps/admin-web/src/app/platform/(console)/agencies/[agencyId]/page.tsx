/**
 * One agency's operational state, and the two actions CareOS can take on it.
 *
 * The suspension form is deliberately at the bottom, behind its own heading, with the
 * consequence written out above the button: nobody at the agency can sign in, tokens already
 * issued stop working, and caregivers cannot clock in. That last one is the sentence that
 * matters — for a Medicaid-billed visit it means an unpaid shift and a compliance exception —
 * and an operator should read it every time rather than remember it.
 *
 * The reason field is required and long. It is shown to the agency on their own sign-in
 * screen and written into their own audit trail, so "non-payment" alone is a support call
 * CareOS could have avoided.
 */

import Link from "next/link";
import { Card, ErrorNote, SeverityBadge, formatDateTime } from "@/components/ui";
import { ApiError, type AgencyHealth, platformApi } from "@/lib/api";
import { type Translator, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getPlatformSession } from "@/lib/platform-session";

export const dynamic = "force-dynamic";

export default async function PlatformAgencyPage({
  params,
  searchParams,
}: {
  params: Promise<{ agencyId: string }>;
  searchParams: Promise<{ suspended?: string; reinstated?: string; error?: string }>;
}) {
  const session = await getPlatformSession();
  if (!session) return null;
  const { agencyId } = await params;
  const { suspended, reinstated, error } = await searchParams;
  const locale = await getLocale();
  const t = translatorFor(locale);

  let agency: AgencyHealth;
  try {
    agency = await platformApi.agency(session.token, agencyId);
  } catch (err) {
    const detail = err instanceof ApiError ? err.message : t("somethingWentWrong");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("platformFleetTitle")}</h1>
        </header>
        <ErrorNote title={t("platformCouldNotLoad")} detail={detail} />
      </>
    );
  }

  const isSuspended = agency.status === "suspended";
  const canAct = session.role === "platform_admin";

  return (
    <>
      <header className="page-header">
        <div>
          <p className="small">
            <Link href="/platform">{t("platformBackToFleet")}</Link>
          </p>
          <h1 className="page-title">{agency.legal_name}</h1>
          <p className="page-subtitle">{t("platformAgencySubtitle")}</p>
        </div>
        <div>
          {isSuspended ? (
            <SeverityBadge severity="critical">{t("platformStatusSuspended")}</SeverityBadge>
          ) : (
            <SeverityBadge severity="good">{t("platformStatusActive")}</SeverityBadge>
          )}
        </div>
      </header>

      {suspended && (
        <div className="notice">
          <SeverityBadge severity="warning">{t("platformStatusSuspended")}</SeverityBadge>
          <span>{t("platformSuspendedNotice")}</span>
        </div>
      )}
      {reinstated && (
        <div className="notice">
          <SeverityBadge severity="good">{t("platformStatusActive")}</SeverityBadge>
          <span>{t("platformReinstatedNotice")}</span>
        </div>
      )}
      {error && <ErrorNote title={t("platformActionFailed")} detail={error} />}

      {isSuspended && (
        <div className="notice">
          <SeverityBadge severity="critical">{t("platformStatusSuspended")}</SeverityBadge>
          <span>
            {agency.suspended_at
              ? t("platformSuspendedSince", { when: formatDateTime(agency.suspended_at) })
              : t("platformStatusSuspended")}
            {agency.suspended_reason
              ? ` — ${t("platformSuspendedBecause", { reason: agency.suspended_reason })}`
              : ""}
          </span>
        </div>
      )}

      <div className="grid-2">
        <Card title={t("platformSectionPeople")}>
          <dl className="summary">
            <dt>{t("platformUsersActive")}</dt>
            <dd className="num">{agency.users_active}</dd>
            <dt>{t("platformOwnerAdmins")}</dt>
            <dd className="num">{agency.owner_admins_active}</dd>
            <dt>{t("platformUsersMissingMfa")}</dt>
            <dd className={agency.users_missing_mfa > 0 ? "num userrow__warn" : "num"}>
              {agency.users_missing_mfa}
            </dd>
            <dt>{t("platformCaregiversActive")}</dt>
            <dd className="num">{agency.caregivers_active}</dd>
            <dt>{t("platformClientsActive")}</dt>
            <dd className="num">{agency.clients_active}</dd>
          </dl>
        </Card>

        <Card title={t("platformSectionSchedule")}>
          <dl className="summary">
            <dt>{t("platformVisitsNext7")}</dt>
            <dd className="num">{agency.visits_next_7d}</dd>
            <dt>{t("platformVisitsUnfilled")}</dt>
            <dd className={agency.visits_unfilled_next_7d > 0 ? "num userrow__warn" : "num"}>
              {agency.visits_unfilled_next_7d}
            </dd>
            <dt>{t("platformColActivity")}</dt>
            <dd>
              {agency.last_user_login_at
                ? formatDateTime(agency.last_user_login_at)
                : t("platformNeverSignedIn")}
            </dd>
            <dt>{t("platformColStates")}</dt>
            <dd className="mono">{agency.service_states.join(", ")}</dd>
          </dl>
        </Card>

        <Card title={t("platformSectionEvv")}>
          <dl className="summary">
            <dt>{t("platformEvvPending")}</dt>
            <dd className="num">{agency.evv_pending}</dd>
            <dt>{t("platformEvvTransmitted")}</dt>
            <dd className="num">{agency.evv_transmitted}</dd>
            <dt>{t("platformEvvAcknowledged")}</dt>
            <dd className="num">{agency.evv_acknowledged}</dd>
            <dt>{t("platformEvvRejected")}</dt>
            <dd className={agency.evv_rejected > 0 ? "num userrow__revoked" : "num"}>
              {agency.evv_rejected}
            </dd>
          </dl>
          <p className="small muted">
            {/* Age, not depth. Ten records queued this minute are a healthy worker; one
                queued on Tuesday is a wedged one, and the count cannot tell them apart. */}
            {agency.evv_oldest_pending_at
              ? t("platformEvvOldestPending", {
                  when: formatDateTime(agency.evv_oldest_pending_at),
                })
              : t("platformEvvNothingPending")}
          </p>
        </Card>

        <Card title={t("platformSectionCompliance")}>
          <dl className="summary">
            <dt>{t("platformExceptionsCritical")}</dt>
            <dd className={agency.exceptions_open_critical > 0 ? "num userrow__revoked" : "num"}>
              {agency.exceptions_open_critical}
            </dd>
            <dt>{t("platformExceptionsWarning")}</dt>
            <dd className="num">{agency.exceptions_open_warning}</dd>
            <dt>{t("platformExceptionsInfo")}</dt>
            <dd className="num">{agency.exceptions_open_info}</dd>
            <dt>{t("platformCredentialsExpired")}</dt>
            <dd className={agency.credentials_expired > 0 ? "num userrow__warn" : "num"}>
              {agency.credentials_expired}
            </dd>
            <dt>{t("platformCredentialsExpiring")}</dt>
            <dd className="num">{agency.credentials_expiring_30d}</dd>
          </dl>
        </Card>
      </div>

      {canAct ? (
        <SuspensionCard agencyId={agencyId} isSuspended={isSuspended} t={t} />
      ) : (
        <Card
          title={isSuspended ? t("platformReinstateTitle") : t("platformSuspendTitle")}
          subtitle={t("platformOperatorAdminOnly")}
        >
          <p className="small muted">{t("platformOperatorReadOnlyNote")}</p>
        </Card>
      )}
    </>
  );
}

function SuspensionCard({
  agencyId,
  isSuspended,
  t,
}: {
  agencyId: string;
  isSuspended: boolean;
  t: Translator;
}) {
  if (isSuspended) {
    return (
      <Card title={t("platformReinstateTitle")}>
        <p className="small muted" style={{ marginBottom: "var(--space-4)" }}>
          {t("platformReinstateBody")}
        </p>
        <form method="post" action="/platform/api/agencies/reinstate">
          <input type="hidden" name="agency_id" value={agencyId} />
          <div className="field">
            <label className="field__label" htmlFor="note">
              {t("platformReinstateNoteLabel")}
            </label>
            <input className="field__input" id="note" name="note" minLength={3} required />
          </div>
          <button className="button" type="submit">
            {t("platformReinstateAction")}
          </button>
        </form>
      </Card>
    );
  }

  return (
    <Card title={t("platformSuspendTitle")}>
      <p className="small muted" style={{ marginBottom: "var(--space-4)" }}>
        {t("platformSuspendBody")}
      </p>
      <form method="post" action="/platform/api/agencies/suspend">
        <input type="hidden" name="agency_id" value={agencyId} />
        <div className="field">
          <label className="field__label" htmlFor="reason">
            {t("platformSuspendReasonLabel")}
          </label>
          {/* Ten characters minimum, matching the API. A reason that reads as a shrug is
              worse than none: it is shown to the agency and stored in their audit trail. */}
          <input
            className="field__input"
            id="reason"
            name="reason"
            minLength={10}
            maxLength={500}
            required
          />
        </div>
        <button className="button button--danger" type="submit">
          {t("platformSuspendAction")}
        </button>
      </form>
    </Card>
  );
}
