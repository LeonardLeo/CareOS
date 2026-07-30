/**
 * Outbox behaviour under the conditions this app exists for.
 *
 * These are the tests that matter most in the repository. A bug here does not produce a broken
 * screen — it produces a caregiver who worked a shift the payroll system has no record of, or
 * a duplicate EVV transmission that the state aggregator rejects and an agency has to
 * reconcile by hand. So each test names the real-world situation it stands for.
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  ATTEMPTS_BEFORE_ESCALATION,
  Outbox,
  type OutboxAction,
  type OutboxStorage,
  type OutboxTransport,
  type SendOutcome,
  backoffFor,
  delayBefore,
  isEscalated,
} from "../src/lib/outbox";

class MemoryStorage implements OutboxStorage {
  rows = new Map<string, OutboxAction>();
  private sequence = 0;

  async all(): Promise<OutboxAction[]> {
    return [...this.rows.values()];
  }
  async put(action: OutboxAction): Promise<void> {
    this.rows.set(action.clientLocalUuid, action);
  }
  async delete(id: string): Promise<void> {
    this.rows.delete(id);
  }
  async nextSequence(): Promise<number> {
    this.sequence += 1;
    return this.sequence;
  }
}

class ScriptedTransport implements OutboxTransport {
  sent: OutboxAction[] = [];
  constructor(private outcomes: SendOutcome[] = []) {}

  async send(action: OutboxAction): Promise<SendOutcome> {
    this.sent.push({ ...action });
    return this.outcomes.shift() ?? { status: "accepted" };
  }
}

let clock = new Date("2026-07-29T09:00:00.000Z");
const now = () => clock;
let counter = 0;
const uuid = () => `uuid-${++counter}`;

beforeEach(() => {
  clock = new Date("2026-07-29T09:00:00.000Z");
  counter = 0;
});

function makeOutbox(transport: OutboxTransport, storage = new MemoryStorage()) {
  return { outbox: new Outbox(storage, transport, now, uuid), storage };
}

describe("queueing", () => {
  it("stores the action before anything is sent, so a dead phone has not lost the clock-in", async () => {
    // The transport is never called here at all — queue() must not depend on it.
    const transport = new ScriptedTransport();
    const { outbox, storage } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "visit-1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: { lat: 40.7, lng: -74 },
    });

    expect(transport.sent).toHaveLength(0);
    expect(storage.rows.size).toBe(1);
    expect([...storage.rows.values()][0]!.syncedAt).toBeNull();
  });

  it("records the moment of the tap, not the moment of delivery", async () => {
    const { outbox } = makeOutbox(new ScriptedTransport());
    const tappedAt = "2026-07-29T09:00:00.000Z";

    const action = await outbox.queue({
      kind: "clock_in",
      visitId: "visit-1",
      timestamp: tappedAt,
      captureMethod: "mobile_gps",
      geo: null,
    });

    // Two hours pass in a basement before a signal returns.
    clock = new Date("2026-07-29T11:00:00.000Z");
    await outbox.flush();

    // For EVV the visit began when the caregiver arrived. Delivery time is irrelevant.
    expect(action.timestamp).toBe(tappedAt);
  });

  it("gives every action a distinct dedup key", async () => {
    const { outbox } = makeOutbox(new ScriptedTransport());
    const a = await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });
    const b = await outbox.queue({
      kind: "clock_out",
      visitId: "v1",
      timestamp: "2026-07-29T10:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });
    expect(a.clientLocalUuid).not.toBe(b.clientLocalUuid);
  });

  it("keeps a clock-in without a location fix, marked with why", async () => {
    // The no-GPS path is a first-class capture method, not a failure (US-1.4.3).
    const { outbox } = makeOutbox(new ScriptedTransport());
    const action = await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "manual_exception",
      geo: null,
      exceptionReason: "No location fix available (indoors or no signal)",
    });

    expect(action.geo).toBeNull();
    expect(action.captureMethod).toBe("manual_exception");
    expect(action.exceptionReason).toContain("indoors");
  });
});

describe("flushing", () => {
  it("sends in the order the caregiver acted", async () => {
    const transport = new ScriptedTransport();
    const { outbox } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });
    await outbox.queue({
      kind: "clock_out",
      visitId: "v1",
      timestamp: "2026-07-29T10:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    await outbox.flush();

    expect(transport.sent.map((a) => a.kind)).toEqual(["clock_in", "clock_out"]);
  });

  it("stops at the first unreachable action instead of skipping past it", async () => {
    // A clock-out that arrives before its clock-in would be rejected on the merits, turning a
    // temporary network problem into permanent lost data. One barrier prevents that.
    const transport = new ScriptedTransport([{ status: "unreachable", message: "offline" }]);
    const { outbox } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });
    await outbox.queue({
      kind: "clock_out",
      visitId: "v1",
      timestamp: "2026-07-29T10:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    const summary = await outbox.flush();

    expect(transport.sent.map((a) => a.kind)).toEqual(["clock_in"]);
    expect(summary.accepted).toBe(0);
    expect(summary.deferred).toBe(2);
  });

  it("retries a deferred action on the next flush and then succeeds", async () => {
    const transport = new ScriptedTransport([
      { status: "unreachable", message: "offline" },
      { status: "accepted" },
    ]);
    const { outbox } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    await outbox.flush();
    expect(await outbox.pending()).toHaveLength(1);

    await outbox.flush();
    expect(await outbox.pending()).toHaveLength(0);
    // Sent twice; the server dedups on the idempotency key, which is why this is safe.
    expect(transport.sent).toHaveLength(2);
    expect(transport.sent[0]!.clientLocalUuid).toBe(transport.sent[1]!.clientLocalUuid);
  });

  it("reuses one dedup key across every retry of the same action", async () => {
    // This is the property that makes replay safe. If the key changed per attempt, a request
    // that actually succeeded but whose response was lost would clock the caregiver in twice.
    const transport = new ScriptedTransport([
      { status: "unreachable", message: "timeout" },
      { status: "unreachable", message: "timeout" },
      { status: "accepted" },
    ]);
    const { outbox } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    await outbox.flush();
    await outbox.flush();
    await outbox.flush();

    const keys = new Set(transport.sent.map((a) => a.clientLocalUuid));
    expect(transport.sent).toHaveLength(3);
    expect(keys.size).toBe(1);
  });

  it("does not resend an action the server already accepted", async () => {
    const transport = new ScriptedTransport();
    const { outbox } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    await outbox.flush();
    await outbox.flush();
    await outbox.flush();

    expect(transport.sent).toHaveLength(1);
  });
});

describe("failures that need a human", () => {
  it("stops retrying a rejected action but never deletes it", async () => {
    // A 4xx will not become a 2xx. But the record that the caregiver acted is exactly what an
    // agency needs when reconciling a disputed timesheet, so it stays on the device.
    const transport = new ScriptedTransport([
      { status: "rejected", message: "Visit is not assigned to you" },
    ]);
    const { outbox, storage } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    const summary = await outbox.flush();
    expect(summary.rejected).toBe(1);
    expect(storage.rows.size).toBe(1);

    const stored = [...storage.rows.values()][0]!;
    expect(stored.lastError).toBe("Visit is not assigned to you");
    expect(isEscalated(stored)).toBe(true);
  });

  it("escalates after a long outage rather than retrying forever in silence", async () => {
    const outcomes: SendOutcome[] = Array.from({ length: ATTEMPTS_BEFORE_ESCALATION }, () => ({
      status: "unreachable" as const,
      message: "offline",
    }));
    const transport = new ScriptedTransport(outcomes);
    const { outbox } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    for (let i = 0; i < ATTEMPTS_BEFORE_ESCALATION; i += 1) await outbox.flush();

    const pending = await outbox.pending();
    expect(pending).toHaveLength(1);
    expect(isEscalated(pending[0]!)).toBe(true);
  });

  it("backs off further on each attempt, and stops growing at a ceiling", async () => {
    expect(backoffFor(0)).toBe(0);
    expect(backoffFor(1)).toBeGreaterThan(0);
    for (let i = 1; i < 5; i += 1) {
      expect(backoffFor(i + 1)).toBeGreaterThanOrEqual(backoffFor(i));
    }
    // A caregiver's battery has to last the shift, so the interval plateaus.
    expect(backoffFor(50)).toBe(backoffFor(5));
  });
});

describe("pruning", () => {
  it("forgets synced actions once the UI no longer needs them, keeping unsynced ones", async () => {
    const transport = new ScriptedTransport([
      { status: "accepted" },
      { status: "unreachable", message: "offline" },
    ]);
    const { outbox, storage } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });
    await outbox.flush();

    await outbox.queue({
      kind: "clock_out",
      visitId: "v1",
      timestamp: "2026-07-29T10:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });
    await outbox.flush();

    clock = new Date("2026-07-29T12:00:00.000Z");
    const pruned = await outbox.pruneSynced();

    expect(pruned).toBe(1);
    expect(storage.rows.size).toBe(1);
    expect([...storage.rows.values()][0]!.kind).toBe("clock_out");
  });
});

describe("concurrency", () => {
  /** A transport that reports when send() has been entered and blocks until released. */
  function blockingTransport() {
    const sent: OutboxAction[] = [];
    let release: ((outcome: SendOutcome) => void) | null = null;
    let entered: (() => void) | null = null;
    const firstSend = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const transport: OutboxTransport = {
      send(action) {
        sent.push({ ...action });
        entered?.();
        return new Promise<SendOutcome>((resolve) => {
          release = resolve;
        });
      },
    };
    return {
      transport,
      sent,
      firstSend,
      release: (outcome: SendOutcome) => release?.(outcome),
    };
  }

  it("does not send the same action twice when two flushes overlap", async () => {
    // The bug this pins: queue() starts a flush, and the reconnect event, the foreground
    // event, and the retry timer can each start another. Two overlapping flushes read the same
    // pending row and both POST it with the same Idempotency-Key, and the server answers the
    // loser with 409 "still in progress". CI's timing overlapped them; a local run against a
    // loopback finished each request before the next flush began, so it never showed up.
    const { transport, sent, firstSend, release } = blockingTransport();
    const { outbox } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    // Both started while the first request is still in flight.
    const first = outbox.flush();
    await firstSend;
    const second = outbox.flush();

    release({ status: "accepted" });
    await Promise.all([first, second]);

    expect(sent).toHaveLength(1);
    expect(await outbox.pending()).toHaveLength(0);
  });

  it("a second flush joins the one in progress rather than starting another", async () => {
    const { transport, firstSend, release } = blockingTransport();
    const { outbox } = makeOutbox(transport);
    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    const a = outbox.flush();
    await firstSend;
    const b = outbox.flush();
    release({ status: "accepted" });

    // The same summary object, because it is the same run rather than a queued second one.
    expect(await a).toBe(await b);
  });

  it("keeps retrying after an in-progress conflict instead of escalating", async () => {
    // A 409 means the server is already processing this exact action. Treating it as a
    // rejection told a caregiver "could not send, call the office" about a clock-in that had
    // succeeded — the worst failure this app can produce, because it errs in the direction of
    // the caregiver believing they will not be paid.
    const transport = new ScriptedTransport([
      {
        status: "unreachable",
        message: "A request with this Idempotency-Key is still in progress",
      },
      { status: "accepted" },
    ]);
    const { outbox } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });

    await outbox.flush();
    const stillPending = await outbox.pending();
    expect(stillPending).toHaveLength(1);
    expect(isEscalated(stillPending[0]!)).toBe(false);

    await outbox.flush();
    expect(await outbox.pending()).toHaveLength(0);
  });
});

describe("honouring the server's retry timing", () => {
  it("waits as long as the server asked, overriding its own backoff", async () => {
    // A 429 carries Retry-After, and the server knows when it will accept the request better
    // than a client-side guess does. Retrying sooner than instructed turns a rate limit into
    // more of the load that caused it.
    const transport = new ScriptedTransport([
      { status: "unreachable", message: "Too many requests", retryAfterSeconds: 45 },
    ]);
    const { outbox, storage } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });
    await outbox.flush();

    const stored = [...storage.rows.values()][0]!;
    expect(stored.retryAfterSeconds).toBe(45);
    // One attempt in, our own backoff would be seconds; the server said 45.
    expect(delayBefore(stored)).toBe(45_000);
    expect(delayBefore(stored)).toBeGreaterThan(backoffFor(stored.attempts));
  });

  it("falls back to its own backoff when the server said nothing", async () => {
    const transport = new ScriptedTransport([{ status: "unreachable", message: "offline" }]);
    const { outbox, storage } = makeOutbox(transport);

    await outbox.queue({
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
    });
    await outbox.flush();

    const stored = [...storage.rows.values()][0]!;
    expect(stored.retryAfterSeconds).toBeNull();
    expect(delayBefore(stored)).toBe(backoffFor(stored.attempts));
  });

  it("tolerates a row written before this field existed", async () => {
    // The outbox lives in IndexedDB and survives app upgrades, so an action stored by an older
    // build has no retryAfterSeconds at all — not null, absent.
    const legacy: OutboxAction = {
      clientLocalUuid: "old-1",
      kind: "clock_in",
      visitId: "v1",
      timestamp: "2026-07-29T09:00:00.000Z",
      captureMethod: "mobile_gps",
      geo: null,
      exceptionReason: null,
      sequence: 1,
      attempts: 2,
      lastError: "offline",
      syncedAt: null,
      createdAt: "2026-07-29T09:00:00.000Z",
    };
    expect(delayBefore(legacy)).toBe(backoffFor(2));
  });
});
