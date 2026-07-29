/**
 * Client detail: create a care plan, then generate its recurring visits.
 *
 * The recurrence rule is an iCalendar RRULE, which is what `care_plan.visit_frequency_rule`
 * holds. Presets cover the common home-care patterns; the raw field stays editable because
 * real schedules are irregular and a fixed dropdown would force agencies to lie about them.
 */

import Link from "next/link";
import { Card, ErrorNote, SeverityBadge, formatDate } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function ClientDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ plan?: string; generated?: string; error?: string }>;
}) {
  const session = await getSession();
  if (!session) return null;
  const { id } = await params;
  const { plan: planId, generated, error } = await searchParams;

  try {
    const [client, carePlans] = await Promise.all([
      api.client(session.token, id),
      api.carePlans(session.token, id),
    ]);
    // Prefer the plan named in the URL (just created), otherwise the client's most recent
    // one — so returning to this page later still offers visit generation.
    const activePlanId = planId ?? carePlans[0]?.id ?? null;
    const activePlan = carePlans.find((p) => p.id === activePlanId) ?? null;
    const today = new Date().toISOString().slice(0, 10);
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    const inAMonth = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);

    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">{client.legal_name}</h1>
            <p className="page-subtitle">
              {client.service_state} · {client.primary_payer_type.replace(/_/g, " ")} · added{" "}
              {formatDate(client.created_at)}
            </p>
          </div>
          <Link className="button button--secondary" href="/clients">
            Back to clients
          </Link>
        </header>

        {generated && (
          <div className="notice">
            <SeverityBadge severity="good">Generated</SeverityBadge>
            <span>
              {generated} visit{generated === "1" ? "" : "s"} created. They are unfilled until
              a caregiver is assigned — see the scheduling board.
            </span>
          </div>
        )}
        {error && <ErrorNote title="Could not complete that step" detail={error} />}

        <div className="grid-2">
          <Card
            title="1. Care plan"
            subtitle={
              carePlans.length
                ? `${carePlans.length} existing plan${carePlans.length === 1 ? "" : "s"} — creating another adds to them`
                : "Authorized tasks and how often visits recur"
            }
          >
            <form method="post" action="/api/care-plans">
              <input type="hidden" name="client_id" value={client.id} />

              <div className="field">
                <label className="field__label" htmlFor="rrule">
                  Recurrence
                </label>
                <select className="field__input" id="rrule" name="rrule">
                  <option value="FREQ=DAILY;COUNT=30">Daily, 30 visits</option>
                  <option value="FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=24">
                    Mon / Wed / Fri, 24 visits
                  </option>
                  <option value="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=40">
                    Weekdays, 40 visits
                  </option>
                  <option value="FREQ=WEEKLY;BYDAY=SA,SU;COUNT=16">Weekends, 16 visits</option>
                </select>
              </div>

              <div className="row" style={{ gap: "var(--space-4)", alignItems: "flex-start" }}>
                <div className="field" style={{ flex: 1 }}>
                  <label className="field__label" htmlFor="start_hour">
                    Start hour
                  </label>
                  <input
                    className="field__input"
                    id="start_hour"
                    name="start_hour"
                    type="number"
                    min="0"
                    max="23"
                    defaultValue="9"
                  />
                </div>
                <div className="field" style={{ flex: 1 }}>
                  <label className="field__label" htmlFor="effective_start">
                    Effective from
                  </label>
                  <input
                    className="field__input"
                    id="effective_start"
                    name="effective_start"
                    type="date"
                    defaultValue={today}
                  />
                </div>
              </div>

              <div className="field">
                <label className="field__label" htmlFor="service_code">
                  Service code
                </label>
                <input
                  className="field__input"
                  id="service_code"
                  name="service_code"
                  defaultValue="T1019"
                />
                <p className="small muted">
                  Must exist in the reference table for this state and payer. Codes vary by
                  state and waiver program, so an unconfigured code is rejected with an
                  explanation rather than silently accepted.
                </p>
              </div>

              <div className="field">
                <label className="field__label" htmlFor="task_label">
                  Authorized task
                </label>
                <input
                  className="field__input"
                  id="task_label"
                  name="task_label"
                  defaultValue="Assist with bathing"
                />
              </div>

              <div className="field">
                <label className="field__label" htmlFor="task_credential">
                  Credential this task requires
                </label>
                <input
                  className="field__input"
                  id="task_credential"
                  name="task_credential"
                  defaultValue="HHA"
                />
                <p className="small muted">
                  Used by shift matching: a caregiver without a valid credential of this type
                  is not suggested.
                </p>
              </div>

              <button className="button" type="submit">
                Create care plan
              </button>
            </form>
          </Card>

          <Card
            title="2. Generate visits"
            subtitle="Materialize the recurrence into concrete, assignable visits"
          >
            {!activePlanId ? (
              <p className="small muted">
                Create a care plan first. Its recurrence rule is what visits are generated
                from.
              </p>
            ) : (
              <form method="post" action="/api/care-plans/generate">
                <input type="hidden" name="care_plan_id" value={activePlanId} />
                <input type="hidden" name="client_id" value={client.id} />

                {activePlan && (
                  <div className="plan-summary">
                    <div className="plan-summary__rule">
                      {typeof activePlan.visit_frequency_rule?.rrule === "string"
                        ? String(activePlan.visit_frequency_rule.rrule)
                        : "No recurrence rule on this plan"}
                    </div>
                    <div className="small muted">
                      Effective {formatDate(activePlan.effective_start)}
                      {activePlan.effective_end
                        ? ` – ${formatDate(activePlan.effective_end)}`
                        : " onward"}
                      {activePlan.default_service_type_code
                        ? ` · billed as ${activePlan.default_service_type_code}`
                        : " · no default service code"}
                      {carePlans.length > 1
                        ? ` · newest of ${carePlans.length} plans`
                        : ""}
                    </div>
                  </div>
                )}

                <div className="row" style={{ gap: "var(--space-4)", alignItems: "flex-start" }}>
                  <div className="field" style={{ flex: 1 }}>
                    <label className="field__label" htmlFor="window_start">
                      From
                    </label>
                    <input
                      className="field__input"
                      id="window_start"
                      name="window_start"
                      type="date"
                      defaultValue={tomorrow}
                    />
                  </div>
                  <div className="field" style={{ flex: 1 }}>
                    <label className="field__label" htmlFor="window_end">
                      To
                    </label>
                    <input
                      className="field__input"
                      id="window_end"
                      name="window_end"
                      type="date"
                      defaultValue={inAMonth}
                    />
                  </div>
                </div>

                <div className="field">
                  <label className="field__label" htmlFor="duration_minutes">
                    Visit length (minutes)
                  </label>
                  <input
                    className="field__input"
                    id="duration_minutes"
                    name="duration_minutes"
                    type="number"
                    min="15"
                    max="1440"
                    step="15"
                    defaultValue="90"
                  />
                </div>

                <button className="button" type="submit">
                  Generate visits
                </button>
                <p className="small muted" style={{ marginTop: "var(--space-3)" }}>
                  Safe to re-run: visits already generated for the same start time are
                  skipped rather than duplicated.
                </p>
              </form>
            )}
          </Card>
        </div>
      </>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Could not load this client.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Client</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
