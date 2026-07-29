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

  try {
    const clients = await api.clients(session.token);

    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">Clients</h1>
            <p className="page-subtitle">
              People your agency serves. Each needs a care plan before visits can be
              generated.
            </p>
          </div>
          <Link className="button" href="/clients/new">
            Add client
          </Link>
        </header>

        {created && (
          <div className="notice">
            <SeverityBadge severity="good">Created</SeverityBadge>
            <span>Client added. Create a care plan next so visits can be generated.</span>
          </div>
        )}
        {error && <ErrorNote title="Could not save that client" detail={error} />}

        <Card title="Roster" subtitle={`${clients.length} client${clients.length === 1 ? "" : "s"}`}>
          {clients.length === 0 ? (
            <EmptyState
              title="No clients yet"
              detail="Add a client, give them a care plan, then generate their recurring visits."
            />
          ) : (
            <Table
              headers={["Name", "State", "Payer", "Status", "Added", ""]}
              caption="Client roster"
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
                      Care plan
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
    const message = err instanceof ApiError ? err.message : "Could not load clients.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Clients</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
