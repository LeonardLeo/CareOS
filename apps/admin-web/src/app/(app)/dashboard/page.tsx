/**
 * Agency dashboard (US-1.5.1).
 *
 * `09_UX_Design_and_User_Flows.md` describes the owner/admin as time-poor and wanting
 * dashboards rather than data entry, and principle 3 says default views surface what needs
 * attention rather than complete lists.
 *
 * So the page leads with a **hero figure** — the one number that decides whether today is a
 * good day — and coverage as a **meter**, since a single ratio against a limit is a meter and
 * not a two-slice pie. Volume counts come after, as stat tiles. Exactly one hero per view.
 */

import Link from "next/link";
import { HeroFigure, Meter, StatTile } from "@/components/charts";
import {
  Card,
  EmptyState,
  ErrorNote,
  SeverityBadge,
  Table,
  formatDateTime,
  relativeDays,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const session = await getSession();
  if (!session) return null;
  const t = translatorFor(await getLocale());

  try {
    const [gaps, expiring, caregivers, visits] = await Promise.all([
      api.gaps(session.token, 72),
      api.credentialExpirations(session.token, 60),
      api.caregivers(session.token),
      api.visits(session.token, "?page_size=200"),
    ]);

    const expired = expiring.filter((c) => c.already_expired);
    const unscreened = caregivers.filter((c) => c.exclusion_check_status !== "cleared");
    const activeCaregivers = caregivers.filter((c) => c.employment_status === "active");

    const upcoming = visits.items.filter((v) => new Date(v.scheduled_start) >= new Date());
    const filled = upcoming.filter((v) => v.caregiver_id !== null).length;

    // A genuine 14-day series from the visit rows we already hold — not a snapshot table
    // and not fabricated. It answers "is our schedule growing or thinning", which is the
    // question a count alone cannot.
    const dailyVisits = Array.from({ length: 14 }, (_, offset) => {
      const day = new Date();
      day.setHours(0, 0, 0, 0);
      day.setDate(day.getDate() - (13 - offset));
      return visits.items.filter(
        (v) => new Date(v.scheduled_start).toDateString() === day.toDateString(),
      ).length;
    });
    // Only plot a trend once there is something to see; a flat line at zero is noise
    // dressed up as information.
    const visitTrend = dailyVisits.some((n) => n > 0) ? dailyVisits : undefined;

    // Attention is the sum of things a person must act on today. It is the hero because it
    // is the number that decides whether anything else on this page matters right now.
    const attention = gaps.length + expired.length + unscreened.length;

    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">{t("dashboardTitle")}</h1>
            <p className="page-subtitle">{t("dashboardSubtitle")}</p>
          </div>
        </header>

        <div className="grid-2" style={{ marginBottom: "var(--space-4)" }}>
          <Card title={t("needsAttention")}>
            <HeroFigure
              value={attention}
              label={attention === 0 ? t("nothingNeedsAction") : t("itemsNeedAction")}
              severity={attention === 0 ? "good" : attention > 3 ? "critical" : "warning"}
              detail={
                attention === 0 ? (
                  t("allClearDetail")
                ) : (
                  <span className="row">
                    {gaps.length > 0 && (
                      <SeverityBadge severity="critical">
                        {t("countUnfilled", { count: gaps.length })}
                      </SeverityBadge>
                    )}
                    {expired.length > 0 && (
                      <SeverityBadge severity="critical">
                        {t("countExpiredCredential", { count: expired.length })}
                      </SeverityBadge>
                    )}
                    {unscreened.length > 0 && (
                      <SeverityBadge severity="warning">
                        {t("countUnscreened", { count: unscreened.length })}
                      </SeverityBadge>
                    )}
                  </span>
                )
              }
            />
          </Card>

          <Card title={t("coverageTitle")} subtitle={t("coverageSubtitle")}>
            <Meter
              label={t("shiftsCovered")}
              value={filled}
              total={upcoming.length}
              severity={
                upcoming.length === 0 || filled === upcoming.length
                  ? "good"
                  : filled / upcoming.length < 0.8
                    ? "critical"
                    : "warning"
              }
              caption={t("shiftsCoveredCaption")}
            />
            <Meter
              label={t("caregiversCleared")}
              value={caregivers.length - unscreened.length}
              total={caregivers.length}
              severity={unscreened.length === 0 ? "good" : "warning"}
              caption={t("caregiversClearedCaption")}
            />
          </Card>
        </div>

        <div className="stat-grid">
          <StatTile
            label={t("activeCaregivers")}
            value={activeCaregivers.length}
            href="/credentialing"
          />
          <StatTile
            label={t("scheduledVisits")}
            value={visits.page.total}
            hint={t("last14DaysPlotted")}
            trend={visitTrend}
          />
          <StatTile
            label={t("expiringIn60Days")}
            value={expiring.length - expired.length}
            severity={expiring.length - expired.length > 0 ? "warning" : "neutral"}
            href="/credentialing"
          />
          <StatTile
            label={t("unfilledNext72h")}
            value={gaps.length}
            severity={gaps.length > 0 ? "critical" : "good"}
            href="/scheduling"
          />
        </div>

        <div className="grid-2">
          <Card
            title={t("shiftsNeedingCaregiver")}
            subtitle={t("next72SoonestFirst")}
            action={
              <Link className="button button--secondary button--small" href="/scheduling">
                {t("openBoard")}
              </Link>
            }
          >
            {gaps.length === 0 ? (
              <EmptyState
                title={t("everyShiftAssigned")}
                detail={t("nothingNext72")}
              />
            ) : (
              <Table
                headers={[t("colWhen"), t("colService"), ""]}
                caption={t("unfilledNext72Caption")}
              >
                {gaps.slice(0, 6).map((visit) => (
                  <tr key={visit.id}>
                    <td>{formatDateTime(visit.scheduled_start)}</td>
                    <td className="muted small">{visit.service_type_code ?? t("noServiceCode")}</td>
                    <td>
                      <Link
                        className="button button--secondary button--small"
                        href={`/scheduling?visit=${visit.id}`}
                      >
                        {t("fill")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          <Card
            title={t("credentialsNeedingRenewal")}
            subtitle={t("expiredBlockAssignment")}
            action={
              <Link className="button button--secondary button--small" href="/credentialing">
                {t("viewAll")}
              </Link>
            }
          >
            {expiring.length === 0 ? (
              <EmptyState title={t("noCredentialsExpiring60")} />
            ) : (
              <Table
                headers={[t("colCaregiver"), t("colCredential"), t("colExpires"), t("colStatus")]}
                caption={t("credentialsExpiring60Caption")}
              >
                {expiring.slice(0, 6).map((credential) => (
                  <tr key={credential.credential_id}>
                    <td>{credential.caregiver_name}</td>
                    <td className="muted small">{credential.credential_type}</td>
                    <td className="small">{relativeDays(credential.days_until_expiry)}</td>
                    <td>
                      {credential.already_expired ? (
                        <SeverityBadge severity="critical">{t("expired")}</SeverityBadge>
                      ) : credential.bucket <= 7 ? (
                        <SeverityBadge severity="warning">{t("sevenDays")}</SeverityBadge>
                      ) : (
                        <SeverityBadge severity="neutral">
                          {t("daysCount", { count: credential.bucket })}
                        </SeverityBadge>
                      )}
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </div>
      </>
    );
  } catch (error) {
    const message = error instanceof ApiError ? error.message : t("couldNotLoadDashboard");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("dashboardTitle")}</h1>
        </header>
        <ErrorNote
          title={message}
          detail={t("checkApiReachable")}
        />
      </>
    );
  }
}
