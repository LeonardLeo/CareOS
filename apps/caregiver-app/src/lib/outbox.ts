/**
 * The outbox: durable, ordered, exactly-once-per-action queue of writes waiting for a network.
 *
 * `03_Technical_Architecture.md` Section 2 says the offline-first library choice — not the UI
 * framework — is the critical decision on this surface, so this module is the centre of the
 * app and everything else is arranged around it.
 *
 * Three properties it has to hold, because EVV clock-in is legally time-sensitive
 * (`02_Product_Requirements_Document.md` US-1.4.3):
 *
 * 1. **An action survives losing the app.** It is written to durable storage before the UI
 *    acknowledges it, not after the request succeeds. A caregiver who clocks in in a basement
 *    and then has their phone die must still have clocked in.
 * 2. **Replay is not duplication.** Every action carries a `clientLocalUuid` generated on
 *    device, sent both as the API's `client_local_uuid` and as the `Idempotency-Key`. The
 *    server recognises the second delivery of one clock-in as the same clock-in
 *    (`05_API_Specification.md` Section 4), so retrying is always safe.
 * 3. **Nothing is silently dropped.** An action that cannot be sent stays queued and visible,
 *    with its attempt count and last error, until it succeeds or a human deals with it.
 *
 * Deliberately free of React, DOM, and `fetch` imports: storage and transport arrive as
 * interfaces. That keeps it unit-testable without a browser, and it is what would let a React
 * Native shell reuse this file verbatim with a SQLite-backed `OutboxStorage`.
 */

export type ActionKind = "clock_in" | "clock_out";

/** How the six EVV elements were captured. Mirrors the API's `CaptureMethod`. */
export type CaptureMethod = "mobile_gps" | "telephony" | "manual_exception";

export interface GeoPoint {
  lat: number;
  lng: number;
}

export interface OutboxAction {
  /** Generated on device, before connectivity exists. The dedup key end to end. */
  clientLocalUuid: string;
  kind: ActionKind;
  visitId: string;
  /** When the caregiver actually acted — never when the request was eventually sent. */
  timestamp: string;
  captureMethod: CaptureMethod;
  geo: GeoPoint | null;
  /** Why GPS was not used, when it was not. Surfaced to the agency as an EVV exception. */
  exceptionReason: string | null;
  /** Monotonic per-device sequence, so a clock-out can never be sent before its clock-in. */
  sequence: number;
  attempts: number;
  lastError: string | null;
  /** Set once the server has accepted it. Retained briefly for the "synced" UI state. */
  syncedAt: string | null;
  /**
   * Seconds the server asked us to wait, when it said so (a rate limit's `Retry-After`).
   *
   * Optional rather than required because rows written by an earlier version of the app do not
   * have it — this store survives upgrades, so every field added here has to tolerate its own
   * absence.
   */
  retryAfterSeconds?: number | null;
  createdAt: string;
}

export interface OutboxStorage {
  all(): Promise<OutboxAction[]>;
  put(action: OutboxAction): Promise<void>;
  delete(clientLocalUuid: string): Promise<void>;
  nextSequence(): Promise<number>;
}

/** Result of trying to deliver one action. */
export type SendOutcome =
  | { status: "accepted" }
  /** The server rejected it on its merits — retrying cannot help. */
  | { status: "rejected"; message: string }
  /** Could not reach the server, or the server failed transiently. Retry later. */
  | { status: "unreachable"; message: string; retryAfterSeconds?: number };

export interface OutboxTransport {
  send(action: OutboxAction): Promise<SendOutcome>;
}

/**
 * Retry backoff, in milliseconds, by attempt count.
 *
 * Front-loaded deliberately: the overwhelmingly common case is a caregiver walking out of a
 * building with thick walls, where connectivity returns within seconds and the first retry
 * should not be sitting out a long sleep. It then widens so a genuinely long outage does not
 * drain a battery that the caregiver may need for the rest of a shift.
 */
const BACKOFF_MS = [0, 2_000, 5_000, 15_000, 60_000, 300_000];

/**
 * How long to wait before the next attempt on this action.
 *
 * The server's instruction wins when there is one. Our own backoff is a guess about a network;
 * a `Retry-After` is the server stating when it will accept the request, and retrying sooner
 * only adds to the load that produced the limit.
 */
export function delayBefore(action: OutboxAction): number {
  const asked = action.retryAfterSeconds;
  if (typeof asked === "number" && asked > 0) return asked * 1000;
  return backoffFor(action.attempts);
}


export function backoffFor(attempts: number): number {
  const clamped = Math.min(Math.max(attempts, 0), BACKOFF_MS.length - 1);
  // The `?? last` is not dead code under a negative or NaN `attempts`: clamping handles the
  // range, this handles the type, and the ceiling is the safe answer either way.
  return BACKOFF_MS[clamped] ?? BACKOFF_MS[BACKOFF_MS.length - 1]!;
}

/**
 * Attempts after which an action stops being retried automatically and is surfaced for help.
 *
 * It is never deleted. A clock-in that cannot reach the server is a payroll and compliance
 * problem, and the caregiver needs to be told to call the office rather than have the app
 * quietly give up on their shift.
 */
export const ATTEMPTS_BEFORE_ESCALATION = 8;

export function isEscalated(action: OutboxAction): boolean {
  return action.syncedAt === null && action.attempts >= ATTEMPTS_BEFORE_ESCALATION;
}

export interface QueueRequest {
  kind: ActionKind;
  visitId: string;
  timestamp: string;
  captureMethod: CaptureMethod;
  geo: GeoPoint | null;
  exceptionReason?: string | null;
}

export interface SyncSummary {
  accepted: number;
  rejected: number;
  deferred: number;
}

export class Outbox {
  constructor(
    private readonly storage: OutboxStorage,
    private readonly transport: OutboxTransport,
    private readonly now: () => Date = () => new Date(),
    private readonly newUuid: () => string = defaultUuid,
  ) {}

  /**
   * Record an action durably. Resolves once it is safe to tell the caregiver it happened —
   * which is when it is stored, not when it is sent.
   */
  async queue(request: QueueRequest): Promise<OutboxAction> {
    const action: OutboxAction = {
      clientLocalUuid: this.newUuid(),
      kind: request.kind,
      visitId: request.visitId,
      timestamp: request.timestamp,
      captureMethod: request.captureMethod,
      geo: request.geo,
      exceptionReason: request.exceptionReason ?? null,
      sequence: await this.storage.nextSequence(),
      attempts: 0,
      lastError: null,
      syncedAt: null,
      createdAt: this.now().toISOString(),
    };
    await this.storage.put(action);
    return action;
  }

  async pending(): Promise<OutboxAction[]> {
    const all = await this.storage.all();
    return all.filter((a) => a.syncedAt === null).sort((a, b) => a.sequence - b.sequence);
  }

  /**
   * Try to deliver everything pending, oldest first.
   *
   * Serialized: a call made while a flush is already running joins the one in progress rather
   * than starting a second. Without this the app really did send one action twice at once —
   * `queue()` kicks off a flush, and the reconnect event, the foreground event, and the retry
   * timer can each kick off another — and the server correctly answered the loser with
   * 409 "a request with this Idempotency-Key is still in progress". CI's timing exposed it;
   * a local run with a fast loopback never overlapped.
   */
  flush(): Promise<SyncSummary> {
    if (this.inFlight !== null) return this.inFlight;
    const run = this.flushOnce().finally(() => {
      if (this.inFlight === run) this.inFlight = null;
    });
    this.inFlight = run;
    return run;
  }

  private inFlight: Promise<SyncSummary> | null = null;

  /**
   * One pass over the queue.
   *
   * Stops at the first unreachable action rather than continuing down the queue. Ordering
   * matters here: sending a clock-out for a visit whose clock-in has not landed would have
   * the server reject the clock-out on its merits, turning a recoverable network problem into
   * a permanent failure. One barrier keeps the queue in order for a whole visit.
   */
  private async flushOnce(): Promise<SyncSummary> {
    const summary: SyncSummary = { accepted: 0, rejected: 0, deferred: 0 };
    const queue = await this.pending();

    for (let i = 0; i < queue.length; i += 1) {
      const action = queue[i]!;
      const outcome = await this.transport.send(action);

      if (outcome.status === "accepted") {
        await this.storage.put({
          ...action,
          attempts: action.attempts + 1,
          lastError: null,
          syncedAt: this.now().toISOString(),
        });
        summary.accepted += 1;
        continue;
      }

      if (outcome.status === "rejected") {
        // Retrying will not change the answer, so stop counting attempts against it and keep
        // it visible with the server's reason. Still not deleted: the record of the caregiver
        // having acted is the thing an agency needs when reconciling a disputed timesheet.
        await this.storage.put({
          ...action,
          attempts: ATTEMPTS_BEFORE_ESCALATION,
          lastError: outcome.message,
        });
        summary.rejected += 1;
        continue;
      }

      await this.storage.put({
        ...action,
        attempts: action.attempts + 1,
        lastError: outcome.message,
        retryAfterSeconds: outcome.retryAfterSeconds ?? null,
      });
      summary.deferred += queue.length - i;
      break;
    }

    return summary;
  }

  /** Forget actions the server has accepted, once the UI no longer needs to show them. */
  async pruneSynced(olderThanMs = 60_000): Promise<number> {
    const cutoff = this.now().getTime() - olderThanMs;
    const all = await this.storage.all();
    let pruned = 0;
    for (const action of all) {
      if (action.syncedAt !== null && new Date(action.syncedAt).getTime() < cutoff) {
        await this.storage.delete(action.clientLocalUuid);
        pruned += 1;
      }
    }
    return pruned;
  }
}

function defaultUuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // A device without crypto.randomUUID still needs a dedup key it will never reuse.
  return `local-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}
