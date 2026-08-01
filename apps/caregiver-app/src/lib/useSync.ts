/**
 * The React binding for the outbox.
 *
 * All the interesting logic lives in `outbox.ts`, which knows nothing about React. This hook
 * only decides *when* to ask it to flush, and exposes enough state for the UI to be honest
 * about what has and has not reached the server.
 *
 * When to flush, in order of how often each one actually saves a caregiver:
 *
 * 1. The `online` event — walking out of a building is the common case.
 * 2. Returning to the foreground (`visibilitychange`). A phone that regained signal while the
 *    screen was off fires no `online` event, so without this the queue would sit until the
 *    caregiver happened to tap something.
 * 3. A timer, as the backstop. `navigator.onLine` reports the network interface, not whether
 *    anything is reachable — a captive portal or a dead cell site reads as online — so the
 *    only reliable test is trying.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { HttpOutboxTransport } from "./api";
import { Outbox, type OutboxAction, type QueueRequest, delayBefore, isEscalated } from "./outbox";
import { readToken } from "./session";
import { IndexedDbOutboxStorage } from "./storage";

const POLL_INTERVAL_MS = 20_000;

export interface SyncState {
  online: boolean;
  pending: OutboxAction[];
  escalated: OutboxAction[];
  syncing: boolean;
}

export interface SyncApi extends SyncState {
  queue(request: QueueRequest): Promise<OutboxAction>;
  flushNow(): Promise<void>;
}

export function useSync(onAccepted?: () => void): SyncApi {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );
  const [pending, setPending] = useState<OutboxAction[]>([]);
  const [syncing, setSyncing] = useState(false);

  const outboxRef = useRef<Outbox | null>(null);
  if (outboxRef.current === null) {
    outboxRef.current = new Outbox(new IndexedDbOutboxStorage(), new HttpOutboxTransport(readToken));
  }
  const outbox = outboxRef.current;

  // Held in a ref so the flush loop below never has to be torn down and rebuilt when the
  // callback identity changes, which would restart the timer on every render.
  const onAcceptedRef = useRef(onAccepted);
  onAcceptedRef.current = onAccepted;

  const refresh = useCallback(async () => {
    setPending(await outbox.pending());
  }, [outbox]);

  const flushNow = useCallback(async () => {
    setSyncing(true);
    try {
      const summary = await outbox.flush();
      await outbox.pruneSynced();
      await refresh();
      if (summary.accepted > 0) onAcceptedRef.current?.();
    } finally {
      setSyncing(false);
    }
  }, [outbox, refresh]);

  const queue = useCallback(
    async (request: QueueRequest) => {
      const action = await outbox.queue(request);
      await refresh();
      // Fire and forget: the caregiver has already been told it is saved, so a failure here
      // changes nothing they need to act on. The retry loop will pick it up.
      void flushNow();
      return action;
    },
    [outbox, refresh, flushNow],
  );

  useEffect(() => {
    void refresh();

    const goOnline = () => {
      setOnline(true);
      void flushNow();
    };
    const goOffline = () => setOnline(false);
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        setOnline(navigator.onLine);
        void flushNow();
      }
    };

    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [flushNow, refresh]);

  // Backstop retry, paced by the most-attempted item so a long outage backs off instead of
  // retrying every 20 seconds for an hour.
  useEffect(() => {
    // Paced by the longest wait any queued action is owed, so a server that asked for a
    // specific delay gets it and a long outage backs off instead of retrying every 20 seconds.
    const owed = pending.reduce((max, action) => Math.max(max, delayBefore(action)), 0);
    const delay = pending.length === 0 ? POLL_INTERVAL_MS : Math.max(POLL_INTERVAL_MS, owed);
    const timer = window.setTimeout(() => void flushNow(), delay);
    return () => window.clearTimeout(timer);
  }, [pending, flushNow]);

  return {
    online,
    pending,
    escalated: pending.filter(isEscalated),
    syncing,
    queue,
    flushNow,
  };
}
