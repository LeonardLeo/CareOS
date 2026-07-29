/**
 * IndexedDB storage for the outbox and the cached schedule.
 *
 * IndexedDB rather than localStorage for one reason that matters more than any other on this
 * surface: localStorage is synchronous and, on several mobile browsers, is cleared under
 * storage pressure ahead of IndexedDB. A clock-in must survive the OS reclaiming memory while
 * the caregiver is inside a client's home with the screen off.
 *
 * The schedule cache holds PHI — client names and addresses — so `08_Security_Architecture.md`
 * Section 6's remote-wipe requirement applies to it. `clearAll()` is the local half of that:
 * signing out, or a rejected token, wipes the cache. The server-side half (revoking a
 * terminated caregiver's session) is not built yet and is recorded as such in BUILD_STATUS.
 */

import type { OutboxAction, OutboxStorage } from "./outbox";

const DB_NAME = "careos-caregiver";
const DB_VERSION = 1;
const OUTBOX_STORE = "outbox";
const CACHE_STORE = "cache";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(OUTBOX_STORE)) {
        db.createObjectStore(OUTBOX_STORE, { keyPath: "clientLocalUuid" });
      }
      if (!db.objectStoreNames.contains(CACHE_STORE)) {
        db.createObjectStore(CACHE_STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function tx<T>(
  store: string,
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(store, mode);
        const request = run(transaction.objectStore(store));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        transaction.oncomplete = () => db.close();
      }),
  );
}

export class IndexedDbOutboxStorage implements OutboxStorage {
  async all(): Promise<OutboxAction[]> {
    return tx<OutboxAction[]>(OUTBOX_STORE, "readonly", (s) => s.getAll());
  }

  async put(action: OutboxAction): Promise<void> {
    await tx(OUTBOX_STORE, "readwrite", (s) => s.put(action));
  }

  async delete(clientLocalUuid: string): Promise<void> {
    await tx(OUTBOX_STORE, "readwrite", (s) => s.delete(clientLocalUuid));
  }

  /**
   * Next per-device sequence number.
   *
   * Derived from the highest sequence ever stored rather than from a count, so pruning synced
   * actions cannot hand out a number already used. Ordering only has to hold within a device.
   */
  async nextSequence(): Promise<number> {
    const stored = await tx<number | undefined>(CACHE_STORE, "readonly", (s) =>
      s.get("outbox:sequence"),
    );
    const next = (stored ?? 0) + 1;
    await tx(CACHE_STORE, "readwrite", (s) => s.put(next, "outbox:sequence"));
    return next;
  }
}

/** Cached schedule, so the app opens to a usable day with no network at all. */
export async function cacheSchedule(payload: unknown): Promise<void> {
  await tx(CACHE_STORE, "readwrite", (s) =>
    s.put({ payload, cachedAt: new Date().toISOString() }, "schedule"),
  );
}

export async function readCachedSchedule<T>(): Promise<{ payload: T; cachedAt: string } | null> {
  const row = await tx<{ payload: T; cachedAt: string } | undefined>(CACHE_STORE, "readonly", (s) =>
    s.get("schedule"),
  );
  return row ?? null;
}

/**
 * Wipe locally cached PHI. Called on sign-out and whenever the API rejects our token.
 *
 * The outbox is deliberately *not* wiped: unsent clock-ins are the caregiver's record of work
 * performed, and discarding them on a token expiry would silently destroy a timesheet.
 */
export async function clearCachedPhi(): Promise<void> {
  await tx(CACHE_STORE, "readwrite", (s) => s.delete("schedule"));
}
