import { useState } from "react";
import type { MyVisit } from "@/lib/api";
import { captureLocation } from "@/lib/geo";
import type { Translator } from "@/lib/i18n";
import type { OutboxAction } from "@/lib/outbox";
import type { SyncApi } from "@/lib/useSync";

/**
 * One visit: who, where, what was authorized, and the clock.
 *
 * The design rule this screen follows is that **the clock never waits on anything**. Tapping
 * clock in attempts a location fix with a short timeout, then writes the action to durable
 * storage and tells the caregiver it is saved — regardless of whether there was a fix, and
 * regardless of whether there is a network. `09_UX...` Flow B step 2 requires the no-GPS path
 * to be as usable as the GPS path, and Flow B step 4 requires "will sync when connected"
 * rather than an error. Both fall out of queueing first and syncing later.
 *
 * The timestamp recorded is the moment of the tap, not the moment the request is eventually
 * sent. For EVV that distinction is the whole point: the visit began when the caregiver
 * arrived, not when they next found a cell tower.
 */
function timeOf(iso: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

export function Visit({
  visit,
  sync,
  onBack,
  t,
  locale,
}: {
  visit: MyVisit;
  sync: SyncApi;
  onBack: () => void;
  t: Translator;
  locale: string;
}) {
  const [busy, setBusy] = useState(false);
  const [justQueued, setJustQueued] = useState<OutboxAction | null>(null);

  const queuedForThisVisit = sync.pending.filter((a) => a.visitId === visit.id);
  const queuedKinds = new Set(queuedForThisVisit.map((a) => a.kind));

  // Server state, then anything queued on top of it. A clock-in sitting in the outbox counts
  // as clocked in from the caregiver's point of view — telling them otherwise would invite a
  // second tap and a duplicate record.
  const clockedIn = Boolean(visit.clock_in_time) || queuedKinds.has("clock_in");
  const clockedOut = Boolean(visit.clock_out_time) || queuedKinds.has("clock_out");

  async function act(kind: "clock_in" | "clock_out") {
    setBusy(true);
    try {
      const at = new Date().toISOString();
      const location = await captureLocation();
      const action = await sync.queue({
        kind,
        visitId: visit.id,
        timestamp: at,
        captureMethod: location.captureMethod,
        geo: location.geo,
        exceptionReason: location.exceptionReason,
      });
      setJustQueued(action);
    } finally {
      setBusy(false);
    }
  }

  const tasks = visit.authorized_tasks.filter((task) => task && (task.label || task.code));

  return (
    <>
      <div className="page">
        <button className="back" type="button" onClick={onBack}>
          ← {t("back")}
        </button>

        <h1 className="page__title">{visit.client.legal_name}</h1>
        <p className="page__sub">
          {timeOf(visit.scheduled_start, locale)} – {timeOf(visit.scheduled_end, locale)}
        </p>

        <div className="stack">
          {clockedOut && (
            <div className="note note--done">
              <div className="note__title">{t("visitComplete")}</div>
              {visit.clock_in_time && (
                <div className="small">
                  {t("clockedInAt", { time: timeOf(visit.clock_in_time, locale) })}
                </div>
              )}
              {visit.clock_out_time && (
                <div className="small">
                  {t("clockedOutAt", { time: timeOf(visit.clock_out_time, locale) })}
                </div>
              )}
            </div>
          )}

          {/* The outcome of the last action taken in this session, whether or not it is still
              queued. Showing this only while pending was wrong: a clock-in that syncs
              instantly still needs to tell the caregiver it went in without a location, since
              that is the thing an agency may ask them about days later. The "will send" line
              is the part that depends on it still being queued. */}
          {justQueued && (
            <div
              className={`note ${queuedForThisVisit.length > 0 ? "note--queued" : "note--done"}`}
              role="status"
            >
              <div className="note__title">
                {queuedForThisVisit.length > 0 ? t("willSync") : t("synced")}
              </div>
              {justQueued.exceptionReason ? (
                <>
                  <div className="small">{t("locationOff")}</div>
                  <div className="small">
                    {t("locationReason", { reason: justQueued.exceptionReason })}
                  </div>
                  <div className="small">{t("locationExplainer")}</div>
                </>
              ) : (
                <div className="small">{t("locationOn")}</div>
              )}
            </div>
          )}

          {sync.escalated.some((a) => a.visitId === visit.id) && (
            <div className="note note--danger" role="alert">
              <div className="note__title">{t("needsHelp")}</div>
            </div>
          )}

          <div className="card">
            <div className="card__label">{t("address")}</div>
            {visit.client.address ? (
              <>
                <div>{visit.client.address}</div>
                {/* A geo: link hands off to whatever map app the caregiver actually uses,
                    rather than assuming one. Falls back to the address as a query. */}
                <a
                  className="action action--secondary"
                  style={{ marginTop: "var(--space-3)", textDecoration: "none" }}
                  href={
                    visit.client.geo_lat !== null && visit.client.geo_lng !== null
                      ? `geo:${visit.client.geo_lat},${visit.client.geo_lng}?q=${encodeURIComponent(visit.client.address)}`
                      : `geo:0,0?q=${encodeURIComponent(visit.client.address)}`
                  }
                >
                  {t("getDirections")}
                </a>
              </>
            ) : (
              <div className="muted">{t("noAddress")}</div>
            )}
          </div>

          <div className="card">
            <div className="card__label">{t("tasks")}</div>
            {tasks.length === 0 ? (
              <div className="muted">{t("noTasks")}</div>
            ) : (
              <ul className="tasks">
                {tasks.map((task, index) => (
                  <li key={task.code ?? index}>{task.label ?? task.code}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <div className="action-bar">
        {clockedOut ? (
          <div className="action action--done">{t("visitComplete")}</div>
        ) : clockedIn ? (
          <button className="action" type="button" disabled={busy} onClick={() => void act("clock_out")}>
            {busy ? t("clockingOut") : t("clockOut")}
          </button>
        ) : (
          <button className="action" type="button" disabled={busy} onClick={() => void act("clock_in")}>
            {busy ? t("clockingIn") : t("clockIn")}
          </button>
        )}
      </div>
    </>
  );
}
