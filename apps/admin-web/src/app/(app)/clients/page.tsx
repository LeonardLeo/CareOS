/**
 * Client roster and creation.
 *
 * This closes the most obvious functional hole in the app: a client could only be created
 * through the API, so an agency could not actually onboard anyone without a developer.
 *
 * The form collects date of birth and street address, which are field-encrypted before they
 * reach the database (`08_Security_Architecture.md` Section 3). Coordinates are separate and
 * deliberately coarse — the geofence rule needs to compute against them, so they stay in the
 * clear while the precise address does not.
 */

import Link from "next/link";
import { Card, EmptyState, ErrorNote, SeverityBadge, Table, formatDate } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function ClientsPage({
  searchParams,
}: {
  searchParams: Promise<{ created?: string; error?: string }>;
}) {
  const session = await getSession();
  if (!session) return null;
  const { created, error } = await searchParams;
  const t = translatorFor(await getLocale());

  try {
    const clients = await api.clients(session.token);

    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">{t("clientsTitle")}</h1>
            <p className="page-subtitle">{t("clientsSubtitle")}</p>
          </div>
          <Link className="button" href="/clients/new">
            {t("addClient")}
          </Link>
        </header>

        {created && (
          <div className="notice">
            <SeverityBadge severity="good">{t("created")}</SeverityBadge>
            <span>{t("clientAddedNext")}</span>
          </div>
        )}
        {error && <ErrorNote title={t("couldNotSaveClient")} detail={error} />}

        <Card title={t("roster")} subtitle={t("clientCount", { count: clients.length })}>
          {clients.length === 0 ? (
            <EmptyState
              title={t("noClientsYet")}
              detail={t("noClientsDetail")}
            />
          ) : (
            <Table
              headers={[t("colName"), t("colState"), t("colPayer"), t("colStatus"), t("colAdded"), ""]}
              caption={t("clientRoster")}
            >
              {clients.map((client) => (
                <tr key={client.id}>
                  <td>{client.legal_name}</td>
                  <td>{client.service_state}</td>
                  <td className="muted small">
                    {client.primary_payer_type.replace(/_/g, " ")}
                  </td>
                  <td>
                    <SeverityBadge severity={client.status === "active" ? "good" : "neutral"}>
                      {client.status}
                    </SeverityBadge>
                  </td>
                  <td className="small muted">{formatDate(client.created_at)}</td>
                  <td>
                    <Link
                      className="button button--secondary button--small"
                      href={`/clients/${client.id}`}
                    >
                      {t("carePlan")}
                    </Link>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : t("couldNotLoadClients");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("clientsTitle")}</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
