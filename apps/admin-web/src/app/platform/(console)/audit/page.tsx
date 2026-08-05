/**
 * The platform's own access log.
 *
 * Every action *and every screen opened*, which is the half people leave out. Nothing this
 * console can reach is PHI — the database role has no permission on any table that holds it
 * — but "which CareOS employee looked at which customer, and when" is the question this
 * surface exists to make answerable, and a log of writes alone cannot answer it.
 *
 * Readable by both roles on purpose. A log only its authors may read is one nobody
 * independent ever checks.
 */

import Link from "next/link";
import { Card, EmptyState, ErrorNote, Table, formatDateTime } from "@/components/ui";
import { ApiError, platformApi } from "@/lib/api";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getPlatformSession } from "@/lib/platform-session";

export const dynamic = "force-dynamic";

export default async function PlatformAuditPage() {
  const session = await getPlatformSession();
  if (!session) return null;
  const locale = await getLocale();
  const t = translatorFor(locale);

  let entries;
  try {
    entries = await platformApi.audit(session.token);
  } catch (error) {
    const detail = error instanceof ApiError ? error.message : t("somethingWentWrong");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("platformAuditTitle")}</h1>
        </header>
        <ErrorNote title={t("platformCouldNotLoad")} detail={detail} />
      </>
    );
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">{t("platformAuditTitle")}</h1>
          <p className="page-subtitle">{t("platformAuditSubtitle")}</p>
        </div>
      </header>

      <Card title={t("platformAuditTitle")} subtitle={t("platformAuditSubtitle")}>
        {entries.length === 0 ? (
          <EmptyState title={t("platformAuditEmpty")} />
        ) : (
          <Table
            caption={t("platformAuditSubtitle")}
            headers={[
              t("platformColWhen"),
              t("platformColWho"),
              t("platformColAction"),
              t("platformColSubject"),
            ]}
          >
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td>{formatDateTime(entry.occurred_at)}</td>
                <td>{entry.actor_display_name ?? t("none")}</td>
                {/* The dotted action name, unlocalised and on purpose: it is the value stored
                    in the row, and an access log whose entries do not match what is in the
                    database is one an auditor cannot cross-reference. */}
                <td className="mono">{entry.action}</td>
                <td>
                  {entry.subject_agency_id ? (
                    <Link href={`/platform/agencies/${entry.subject_agency_id}`}>
                      {entry.subject_agency_name ?? entry.subject_agency_id}
                    </Link>
                  ) : (
                    <span className="muted">{t("none")}</span>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
