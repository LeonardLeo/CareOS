import type { Translator } from "@/lib/i18n";
import type { SyncApi } from "@/lib/useSync";

/**
 * Permanent connection and queue status.
 *
 * `09_UX_Design_and_User_Flows.md` design principle 2: offline is a state to be shown, not an
 * error to be raised. So this is always on screen and never a toast — a caregiver walking
 * between a car and a front door should be able to glance down at any moment and know whether
 * their last clock-in has actually left the phone.
 *
 * It reports the queue even when online, because "connected" and "everything has been sent"
 * are different facts and conflating them is how a caregiver ends a shift believing their
 * hours were submitted.
 */
export function ConnectionBar({ sync, t }: { sync: SyncApi; t: Translator }) {
  const waiting = sync.pending.length;
  const hasTrouble = sync.escalated.length > 0;
  const tone = hasTrouble || !sync.online || waiting > 0 ? "conn--offline" : "";

  let label: string;
  if (hasTrouble) label = t("needsHelp");
  else if (sync.syncing) label = t("syncing");
  else if (waiting > 0) label = t("pendingCount", { count: waiting });
  else if (!sync.online) label = t("offline");
  else label = t("online");

  return (
    <div
      className={`conn ${tone}`}
      // Announced when it changes, so a screen-reader user learns they went offline without
      // having to go looking for the bar.
      role="status"
      aria-live="polite"
    >
      <span className="conn__left">
        <span className="conn__dot" aria-hidden="true" />
        {label}
      </span>
      {waiting > 0 && sync.online && !sync.syncing && (
        <button className="conn__retry" type="button" onClick={() => void sync.flushNow()}>
          {t("retryNow")}
        </button>
      )}
    </div>
  );
}
