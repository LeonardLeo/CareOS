/**
 * API client and outbox transport.
 *
 * This app talks to the API directly from the device, unlike the admin web app which proxies
 * through server components. That is forced by the offline requirement: a service worker and
 * an IndexedDB queue on the device can only replay a request the device is able to make
 * itself. The consequence is that the access token lives in JavaScript reach here, which is a
 * real weakening versus the admin app's httpOnly cookie — recorded honestly in BUILD_STATUS
 * rather than papered over. It is mitigated by a short access-token TTL (15 minutes per
 * `05_API_Specification.md` Section 1) and by the cached PHI being wiped on sign-out.
 */

import type { OutboxAction, OutboxTransport, SendOutcome } from "./outbox";

export const API_URL = import.meta.env.VITE_CAREOS_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export interface MyVisitClient {
  id: string;
  legal_name: string;
  address: string | null;
  geo_lat: number | null;
  geo_lng: number | null;
}

export interface AuthorizedTask {
  code?: string;
  label?: string;
}

export interface MyVisit {
  id: string;
  care_plan_id: string;
  scheduled_start: string;
  scheduled_end: string;
  status: string;
  service_type_code: string | null;
  service_state: string | null;
  client: MyVisitClient;
  authorized_tasks: AuthorizedTask[];
  clock_in_time: string | null;
  clock_out_time: string | null;
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  token?: string;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.token) headers["Authorization"] = `Bearer ${options.token}`;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  const response = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    // Never let a stale cached response stand in for a client's schedule; the app's own
    // IndexedDB cache is the offline story, and it knows how old its data is.
    cache: "no-store",
  });

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const envelope =
      payload && typeof payload === "object" && "error" in payload
        ? (payload as { error: { code: string; message: string } }).error
        : null;
    throw new ApiError(
      response.status,
      envelope?.code ?? "UNKNOWN_ERROR",
      envelope?.message ?? `Request failed with status ${response.status}`,
    );
  }
  return payload as T;
}

export const api = {
  login: (email: string, password: string) =>
    request<TokenPair>("/v1/auth/login", { method: "POST", body: { email, password } }),

  myVisits: (token: string, from?: string, to?: string) => {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    const query = params.toString();
    return request<MyVisit[]>(`/v1/my-visits${query ? `?${query}` : ""}`, { token });
  },
};

/**
 * Delivers outbox actions to the API.
 *
 * The distinction this class exists to draw is between *rejected* and *unreachable*, because
 * they have opposite correct responses. A 4xx means the server understood and refused, so
 * retrying forever would spin against a wall; a network error or 5xx means the action is
 * probably still valid and must be preserved. Getting this backwards in either direction is
 * how offline queues either lose work or hammer a server, so the mapping is explicit.
 */
export class HttpOutboxTransport implements OutboxTransport {
  constructor(private readonly getToken: () => string | null) {}

  async send(action: OutboxAction): Promise<SendOutcome> {
    const token = this.getToken();
    if (!token) {
      // Not a rejection: the action is fine, we just have nobody to send it as yet.
      return { status: "unreachable", message: "Not signed in" };
    }

    const path =
      action.kind === "clock_in"
        ? `/v1/visits/${action.visitId}/clock-in`
        : `/v1/visits/${action.visitId}/clock-out`;

    const body: Record<string, unknown> = {
      timestamp: action.timestamp,
      client_local_uuid: action.clientLocalUuid,
    };
    if (action.geo) body.geo = { lat: action.geo.lat, lng: action.geo.lng };
    // Only clock-in carries the capture method; clock-out inherits the record's.
    if (action.kind === "clock_in") body.capture_method = action.captureMethod;

    try {
      await request(path, {
        method: "POST",
        body,
        token,
        // The device-generated uuid doubles as the idempotency key, so a replay of a request
        // that actually succeeded returns the original response instead of clocking in twice.
        idempotencyKey: action.clientLocalUuid,
      });
      return { status: "accepted" };
    } catch (error) {
      if (error instanceof ApiError) {
        // 408/429 are the server asking us to come back, not refusing on the merits.
        if (error.status >= 500 || error.status === 408 || error.status === 429) {
          return { status: "unreachable", message: error.message };
        }
        if (error.status === 401) {
          return { status: "unreachable", message: "Session expired — sign in to sync" };
        }
        return { status: "rejected", message: error.message };
      }
      return {
        status: "unreachable",
        message: error instanceof Error ? error.message : "Network unavailable",
      };
    }
  }
}
