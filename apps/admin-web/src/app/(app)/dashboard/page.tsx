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
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const session = await getSession();
  if (!session) return null;

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
            <h1 className="page-title">Dashboard</h1>
            <p className="page-subtitle">Operational health across your agency.</p>
          </div>
        </header>

        <div className="grid-2" style={{ marginBottom: "var(--space-4)" }}>
          <Card title="Needs attention">
            <HeroFigure
              value={attention}
              label={attention === 0 ? "Nothing needs action today" : "items need action"}
              severity={attention === 0 ? "good" : attention > 3 ? "critical" : "warning"}
              detail={
                attention === 0 ? (
                  "Every shift is covered, no credential has lapsed, and every caregiver is screened."
                ) : (
                  <span className="row">
                    {gaps.length > 0 && (
                      <SeverityBadge severity="critical">
                        {gaps.length} unfilled
                      </SeverityBadge>
                    )}
                    {expired.length > 0 && (
                      <SeverityBadge severity="critical">
                        {expired.length} expired credential{expired.length === 1 ? "" : "s"}
                      </SeverityBadge>
                    )}
                    {unscreened.length > 0 && (
                      <SeverityBadge severity="warning">
                        {unscreened.length} unscreened
                      </SeverityBadge>
                    )}
                  </span>
                )
              }
            />
          </Card>

          <Card title="Coverage" subtitle="Upcoming visits with a caregiver assigned">
            <Meter
              label="Shifts covered"
              value={filled}
              total={upcoming.length}
              severity={
                upcoming.length === 0 || filled === upcoming.length
                  ? "good"
                  : filled / upcoming.length < 0.8
                    ? "critical"
                    : "warning"
              }
              caption="A visit without a caregiver at its start time becomes a missed visit — and, for Medicaid clients, an EVV compliance exception."
            />
            <Meter
              label="Caregivers cleared to work"
              value={caregivers.length - unscreened.length}
              total={caregivers.length}
              severity={unscreened.length === 0 ? "good" : "warning"}
              caption="Only caregivers with a cleared OIG/GSA exclusion check may be scheduled for publicly-funded visits."
            />
          </Card>
        </div>

        <div className="stat-grid">
          <StatTile label="Active caregivers" value={activeCaregivers.length} href="/credentialing" />
          <StatTile
            label="Scheduled visits"
            value={visits.page.total}
            hint="Last 14 days plotted"
            trend={visitTrend}
          />
          <StatTile
            label="Expiring in 60 days"
            value={expiring.length - expired.length}
            severity={expiring.length - expired.length > 0 ? "warning" : "neutral"}
            href="/credentialing"
          />
          <StatTile
            label="Unfilled, next 72h"
            value={gaps.length}
            severity={gaps.length > 0 ? "critical" : "good"}
            href="/scheduling"
          />
        </div>

        <div className="grid-2">
          <Card
            title="Shifts needing a caregiver"
            subtitle="Next 72 hours, soonest first"
            action={
              <Link className="button button--secondary button--small" href="/scheduling">
                Open board
              </Link>
            }
          >
            {gaps.length === 0 ? (
              <EmptyState
                title="Every upcoming shift is assigned"
                detail="Nothing needs attention in the next 72 hours."
              />
            ) : (
              <Table headers={["When", "Service", ""]} caption="Unfilled shifts, next 72 hours">
                {gaps.slice(0, 6).map((visit) => (
                  <tr key={visit.id}>
                    <td>{formatDateTime(visit.scheduled_start)}</td>
                    <td className="muted small">{visit.service_type_code ?? "No code"}</td>
                    <td>
                      <Link
                        className="button button--secondary button--small"
                        href={`/scheduling?visit=${visit.id}`}
                      >
                        Fill
                      </Link>
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          <Card
            title="Credentials needing renewal"
            subtitle="Expired credentials block assignment immediately"
            action={
              <Link className="button button--secondary button--small" href="/credentialing">
                View all
              </Link>
            }
          >
            {expiring.length === 0 ? (
              <EmptyState title="No credentials expiring in the next 60 days" />
            ) : (
              <Table
                headers={["Caregiver", "Credential", "Expires", "Status"]}
                caption="Credentials expiring within 60 days"
              >
                {expiring.slice(0, 6).map((credential) => (
                  <tr key={credential.credential_id}>
                    <td>{credential.caregiver_name}</td>
                    <td className="muted small">{credential.credential_type}</td>
                    <td className="small">{relativeDays(credential.days_until_expiry)}</td>
                    <td>
                      {credential.already_expired ? (
                        <SeverityBadge severity="critical">Expired</SeverityBadge>
                      ) : credential.bucket <= 7 ? (
                        <SeverityBadge severity="warning">7 days</SeverityBadge>
                      ) : (
                        <SeverityBadge severity="neutral">
                          {credential.bucket} days
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
    const message = error instanceof ApiError ? error.message : "Could not load the dashboard.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Dashboard</h1>
        </header>
        <ErrorNote
          title={message}
          detail="Check that the CareOS API is running and reachable at CAREOS_API_URL."
        />
      </>
    );
  }
}
