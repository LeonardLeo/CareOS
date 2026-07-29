/**
 * Builds a real tenant with a real caregiver login and a real assigned visit, over HTTP.
 *
 * Nothing here is mocked. The point of these tests is that a clock-in taken with the network
 * off reaches the actual API exactly once, and a stubbed backend cannot demonstrate that: the
 * dedup happens in the server's idempotency table, so the server has to be present.
 */

const API = process.env.CAREOS_API_URL ?? "http://localhost:8000";

export interface SeededCaregiver {
  email: string;
  password: string;
  agencyId: string;
  caregiverId: string;
  visitId: string;
  clientName: string;
  ownerToken: string;
}

async function call<T>(
  path: string,
  init: { method?: string; body?: unknown; token?: string; idempotencyKey?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (init.token) headers["Authorization"] = `Bearer ${init.token}`;
  if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;

  const response = await fetch(`${API}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`${init.method ?? "GET"} ${path} → ${response.status}: ${text}`);
  }
  return (text ? JSON.parse(text) : undefined) as T;
}

function isoDate(offsetDays: number): string {
  return new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 10);
}

export async function seedCaregiver(): Promise<SeededCaregiver> {
  const suffix = Math.random().toString(36).slice(2, 10);
  const password = "a-sufficiently-long-password";
  const ownerEmail = `owner-${suffix}@e2e.example.com`;
  const caregiverEmail = `caregiver-${suffix}@e2e.example.com`;
  const clientName = `Ada Whitfield ${suffix.slice(0, 4)}`;

  const agency = await call<{ id: string }>("/v1/agencies", {
    method: "POST",
    body: {
      legal_name: `E2E Home Care ${suffix}`,
      service_states: ["NY"],
      service_lines: ["home_care"],
      accepted_payer_types: ["medicaid_waiver"],
      owner_email: ownerEmail,
      owner_password: password,
      owner_full_name: "E2E Owner",
    },
  });

  const ownerTokens = await call<{ access_token: string }>("/v1/auth/login", {
    method: "POST",
    body: { email: ownerEmail, password },
  });
  const ownerToken = ownerTokens.access_token;

  // The caregiver's own login. `POST /caregivers` then links the caregiver record to it via
  // app_user_id, which is what puts caregiver_id into their token at login — and that is what
  // scopes /my-visits to them.
  const caregiverUser = await call<{ id: string }>(`/v1/agencies/${agency.id}/users`, {
    method: "POST",
    body: {
      email: caregiverEmail,
      role: "caregiver",
      initial_password: password,
    },
    token: ownerToken,
  });

  const caregiver = await call<{ id: string }>("/v1/caregivers", {
    method: "POST",
    body: {
      legal_name: "Grace Caregiver",
      app_user_id: caregiverUser.id,
      geo_lat: 43.1566,
      geo_lng: -77.6088,
    },
    token: ownerToken,
  });

  // Assignment requires a cleared exclusion check (US-1.3.2), so the seed has to do this or
  // the assign call below is refused — the same gate a real agency passes through.
  await call(`/v1/caregivers/${caregiver.id}/exclusion-check`, {
    method: "POST",
    body: { status: "cleared", vendor_key: "e2e-seed", vendor_reference: "seeded-for-tests" },
    token: ownerToken,
    // The endpoint calls an external screening vendor, so the API requires a key. The seed
    // supplies one exactly as a real client would rather than the gate being relaxed for tests.
    idempotencyKey: `seed-exclusion-${suffix}`,
  });

  const careClient = await call<{ id: string }>("/v1/clients", {
    method: "POST",
    body: {
      legal_name: clientName,
      dob: "1948-03-11",
      address: "412 Ashbury Lane, Rochester NY",
      geo_lat: 43.1566,
      geo_lng: -77.6088,
      service_state: "NY",
      primary_payer_type: "medicaid_waiver",
    },
    token: ownerToken,
  });

  const plan = await call<{ id: string }>(`/v1/clients/${careClient.id}/care-plans`, {
    method: "POST",
    body: {
      authorized_tasks: [
        { code: "bathing", label: "Assist with bathing" },
        { code: "meal_prep", label: "Meal preparation" },
      ],
      visit_frequency_rule: { rrule: "FREQ=DAILY;COUNT=1", start_hour: 9 },
      effective_start: isoDate(-1),
      default_service_type_code: "T1019",
    },
    token: ownerToken,
  });

  const visits = await call<{ id: string }[]>(`/v1/care-plans/${plan.id}/generate-visits`, {
    method: "POST",
    body: { window_start: isoDate(0), window_end: isoDate(2), duration_minutes: 90 },
    token: ownerToken,
  });
  if (visits.length === 0) throw new Error("seed produced no visits");
  const visitId = visits[0]!.id;

  await call(`/v1/visits/${visitId}/assign`, {
    method: "POST",
    body: { caregiver_id: caregiver.id },
    token: ownerToken,
  });

  return {
    email: caregiverEmail,
    password,
    agencyId: agency.id,
    caregiverId: caregiver.id,
    visitId,
    clientName,
    ownerToken,
  };
}

/** EVV state straight from the API, for asserting what actually landed server-side. */
export async function evvStatus(
  visitId: string,
  token: string,
): Promise<{ id: string; clock_in_time: string | null; clock_out_time: string | null } | null> {
  try {
    return await call(`/v1/visits/${visitId}/evv-status`, { token });
  } catch {
    return null;
  }
}

/**
 * Re-send a clock-in exactly as the device would on a retry, and return the resulting record.
 *
 * Used to demonstrate the dedup rather than assume it. The realistic failure this stands for is
 * a request that reached the server and was processed, whose response was lost before the
 * device saw it — the device cannot tell that apart from a request that never arrived, so it
 * retries, and the only thing preventing a second EVV record is the server honouring the key.
 */
export async function replayClockIn(
  visitId: string,
  token: string,
  clientLocalUuid: string,
  timestamp: string,
): Promise<{ id: string; clock_in_time: string | null }> {
  return call(`/v1/visits/${visitId}/clock-in`, {
    method: "POST",
    body: {
      timestamp,
      capture_method: "mobile_gps",
      geo: { lat: 43.1566, lng: -77.6088 },
      client_local_uuid: clientLocalUuid,
    },
    token,
    idempotencyKey: clientLocalUuid,
  });
}

export async function caregiverToken(email: string, password: string): Promise<string> {
  const tokens = await call<{ access_token: string }>("/v1/auth/login", {
    method: "POST",
    body: { email, password },
  });
  return tokens.access_token;
}

export { API };
