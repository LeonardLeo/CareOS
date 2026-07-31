/**
 * Credentialing dashboard (US-1.3.3).
 *
 * Grouped by urgency rather than listed flat, because the 60/30/7-day horizons in the story
 * exist to drive different actions: an expired credential means someone cannot work today,
 * while a 60-day notice is a reminder to start a renewal.
 */

import { Card, EmptyState, ErrorNote, SeverityBadge, Table, formatDate, relativeDays } from "@/components/ui";
import { ApiError, api, type ExpiringCredential } from "@/lib/api";
import { type Translator, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

function CredentialTable({ rows, t }: { rows: ExpiringCredential[]; t: Translator }) {
  return (
    <Table
      headers={[t("colCaregiver"), t("colCredential"), t("colExpiryDate"), t("colWhen")]}
      caption={t("navCredentialing")}
    >
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
  const t = translatorFor(await getLocale());

  try {
    const rows = await api.credentialExpirations(session.token, 60);
    const expired = rows.filter((r) => r.already_expired);
    const within7 = rows.filter((r) => !r.already_expired && r.bucket === 7);
    const within30 = rows.filter((r) => !r.already_expired && r.bucket === 30);
    const within60 = rows.filter((r) => !r.already_expired && r.bucket === 60);

    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("navCredentialing")}</h1>
          <p className="page-subtitle">{t("credentialingSubtitle")}</p>
        </header>

        <Card
          title={t("expired")}
          subtitle={t("blockingAssignmentNow")}
          action={<SeverityBadge severity={expired.length ? "critical" : "good"}>{expired.length}</SeverityBadge>}
        >
          {expired.length === 0 ? (
            <EmptyState title={t("noExpiredCredentials")} />
          ) : (
            <CredentialTable rows={expired} t={t} />
          )}
        </Card>

        <Card
          title={t("expiringWithin7")}
          action={<SeverityBadge severity={within7.length ? "warning" : "good"}>{within7.length}</SeverityBadge>}
        >
          {within7.length === 0 ? <EmptyState title={t("nothingExpiringThisWeek")} /> : <CredentialTable rows={within7} t={t} />}
        </Card>

        <Card title={t("expiringWithin30")} action={<SeverityBadge severity="info">{within30.length}</SeverityBadge>}>
          {within30.length === 0 ? <EmptyState title={t("nothingExpiringThisMonth")} /> : <CredentialTable rows={within30} t={t} />}
        </Card>

        <Card title={t("expiringWithin60")} action={<SeverityBadge severity="neutral">{within60.length}</SeverityBadge>}>
          {within60.length === 0 ? <EmptyState title={t("nothingOn60DayHorizon")} /> : <CredentialTable rows={within60} t={t} />}
        </Card>
      </>
    );
  } catch (error) {
    const message =
      error instanceof ApiError ? error.message : t("couldNotLoadCredentialing");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("navCredentialing")}</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
