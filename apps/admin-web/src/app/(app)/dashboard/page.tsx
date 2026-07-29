/**
 * Agency dashboard (US-1.5.1).
 *
 * `09_UX_Design_and_User_Flows.md` describes the owner/admin as time-poor and wanting
 * dashboards rather than data entry, and principle 3 says default views should surface what
 * needs attention rather than complete lists. So this leads with the things that require
 * action — unfilled shifts, expired credentials, uncleared screenings — and only then shows
 * volume.
 */

import Link from "next/link";
import {
  Card,
  EmptyState,
  ErrorNote,
  SeverityBadge,
  StatTile,
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
      api.visits(session.token, "?page_size=1"),
    ]);

    const expired = expiring.filter((c) => c.already_expired);
    const unscreened = caregivers.filter((c) => c.exclusion_check_status !== "cleared");
    const activeCaregivers = caregivers.filter((c) => c.employment_status === "active");

    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Operational health across your agency.</p>
        </header>

        <div className="stat-grid">
          <StatTile
            label="Unfilled shifts"
            value={gaps.length}
            hint="Next 72 hours"
            severity={gaps.length > 0 ? "warning" : "success"}
          />
          <StatTile
            label="Expired credentials"
            value={expired.length}
            hint="Blocks assignment now"
            severity={expired.length > 0 ? "critical" : "success"}
          />
          <StatTile
            label="Awaiting screening"
            value={unscreened.length}
            hint="Cannot work Medicaid visits"
            severity={unscreened.length > 0 ? "warning" : "success"}
          />
          <StatTile label="Active caregivers" value={activeCaregivers.length} />
          <StatTile label="Scheduled visits" value={visits.page.total} hint="All time" />
        </div>

        <Card
          title="Shifts needing a caregiver"
          subtitle="Soonest first — the most urgent gap is at the top"
          action={
            <Link className="button button--small" href="/scheduling">
              Open scheduling
            </Link>
          }
        >
          {gaps.length === 0 ? (
            <EmptyState
              title="Every upcoming shift is assigned"
              detail="Nothing needs attention in the next 72 hours."
            />
          ) : (
            <Table
              headers={["When", "Service", "Payer", "Action"]}
              caption="Unfilled shifts in the next 72 hours"
            >
              {gaps.slice(0, 8).map((visit) => (
                <tr key={visit.id}>
                  <td>{formatDateTime(visit.scheduled_start)}</td>
                  <td>{visit.service_type_code ?? <span className="muted">Not set</span>}</td>
                  <td>{visit.payer_type ?? <span className="muted">—</span>}</td>
                  <td>
                    <Link
                      className="button button--secondary button--small"
                      href={`/scheduling?visit=${visit.id}`}
                    >
                      Find caregiver
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
        >
          {expiring.length === 0 ? (
            <EmptyState title="No credentials expiring in the next 60 days" />
          ) : (
            <Table
              headers={["Caregiver", "Credential", "Expires", "Status"]}
              caption="Credentials expiring within 60 days"
            >
              {expiring.slice(0, 8).map((credential) => (
                <tr key={credential.credential_id}>
                  <td>{credential.caregiver_name}</td>
                  <td>{credential.credential_type}</td>
                  <td>{relativeDays(credential.days_until_expiry)}</td>
                  <td>
                    {credential.already_expired ? (
                      <SeverityBadge severity="critical">Expired</SeverityBadge>
                    ) : credential.bucket <= 7 ? (
                      <SeverityBadge severity="warning">Within 7 days</SeverityBadge>
                    ) : (
                      <SeverityBadge severity="info">
                        Within {credential.bucket} days
                      </SeverityBadge>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
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
