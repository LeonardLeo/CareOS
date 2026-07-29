/**
 * Credentialing dashboard (US-1.3.3).
 *
 * Grouped by urgency rather than listed flat, because the 60/30/7-day horizons in the story
 * exist to drive different actions: an expired credential means someone cannot work today,
 * while a 60-day notice is a reminder to start a renewal.
 */

import { Card, EmptyState, ErrorNote, SeverityBadge, Table, formatDate, relativeDays } from "@/components/ui";
import { ApiError, api, type ExpiringCredential } from "@/lib/api";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

function CredentialTable({ rows }: { rows: ExpiringCredential[] }) {
  return (
    <Table headers={["Caregiver", "Credential", "Expiry date", "When"]} caption="Credentials">
      {rows.map((row) => (
        <tr key={row.credential_id}>
          <td>{row.caregiver_name}</td>
          <td>{row.credential_type}</td>
          <td>{formatDate(row.expiration_date)}</td>
          <td>{relativeDays(row.days_until_expiry)}</td>
        </tr>
      ))}
    </Table>
  );
}

export default async function CredentialingPage() {
  const session = await getSession();
  if (!session) return null;

  try {
    const rows = await api.credentialExpirations(session.token, 60);
    const expired = rows.filter((r) => r.already_expired);
    const within7 = rows.filter((r) => !r.already_expired && r.bucket === 7);
    const within30 = rows.filter((r) => !r.already_expired && r.bucket === 30);
    const within60 = rows.filter((r) => !r.already_expired && r.bucket === 60);

    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Credentialing</h1>
          <p className="page-subtitle">
            Renewal queue. A caregiver whose credential has expired cannot be assigned to
            visits on or after the expiry date.
          </p>
        </header>

        <Card
          title="Expired"
          subtitle="Blocking assignment right now"
          action={<SeverityBadge severity={expired.length ? "critical" : "success"}>{expired.length}</SeverityBadge>}
        >
          {expired.length === 0 ? (
            <EmptyState title="No expired credentials" />
          ) : (
            <CredentialTable rows={expired} />
          )}
        </Card>

        <Card
          title="Expiring within 7 days"
          action={<SeverityBadge severity={within7.length ? "warning" : "success"}>{within7.length}</SeverityBadge>}
        >
          {within7.length === 0 ? <EmptyState title="Nothing expiring this week" /> : <CredentialTable rows={within7} />}
        </Card>

        <Card title="Expiring within 30 days" action={<SeverityBadge severity="info">{within30.length}</SeverityBadge>}>
          {within30.length === 0 ? <EmptyState title="Nothing expiring this month" /> : <CredentialTable rows={within30} />}
        </Card>

        <Card title="Expiring within 60 days" action={<SeverityBadge severity="neutral">{within60.length}</SeverityBadge>}>
          {within60.length === 0 ? <EmptyState title="Nothing on the 60-day horizon" /> : <CredentialTable rows={within60} />}
        </Card>
      </>
    );
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not load credentialing data.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Credentialing</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
