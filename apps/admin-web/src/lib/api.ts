/**
 * Typed client for the CareOS API.
 *
 * Every call runs server-side — from a Server Component or a route handler — never from the
 * browser. That is what lets the access token live in an httpOnly cookie that page
 * JavaScript cannot read, which matters more than usual here: this app displays PHI, and an
 * XSS that can exfiltrate a token is a reportable breach rather than a bug.
 *
 * Errors are normalized into `ApiError` from the single envelope in
 * `05_API_Specification.md` Section 1, so screens branch on a stable `code` rather than
 * parsing messages.
 */

const API_URL = process.env.CAREOS_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** A compliance gate refused this, e.g. an uncleared exclusion check (PRD US-1.3.2). */
  get isComplianceGate(): boolean {
    return this.code === "COMPLIANCE_GATE_FAILED";
  }

  get isAuthError(): boolean {
    return this.status === 401;
  }

  /**
   * Valid credentials, disabled account.
   *
   * Worth telling apart from a bad password: someone whose account was disabled types the
   * right password, is told it is wrong, and calls the agency to have a password reset that
   * was never the problem.
   */
  get isAccountInactive(): boolean {
    return this.code === "ACCOUNT_INACTIVE";
  }

  /**
   * The credentials are fine and CareOS has suspended the whole tenant.
   *
   * Distinct from `isAccountInactive`, which is one person disabled by their own
   * administrator. This one is nobody in the agency, done from outside it, and the two need
   * different messages: an owner told their account was disabled goes looking for a change
   * nobody in the agency made.
   */
  get isAgencySuspended(): boolean {
    return this.code === "AGENCY_SUSPENDED";
  }

  /** Right password, and the account has a second factor the request did not carry. */
  get isMfaRequired(): boolean {
    return this.code === "MFA_REQUIRED";
  }

  /** The role requires MFA and this user has not finished enrolling. */
  get isMfaEnrolmentRequired(): boolean {
    return this.code === "MFA_ENROLMENT_REQUIRED";
  }
}

interface RequestOptions {
  token?: string;
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  idempotencyKey?: string;
  /** Seconds to cache. Omit for no caching, which is the right default for PHI. */
  revalidate?: number;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.token) headers["Authorization"] = `Bearer ${options.token}`;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  const response = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    // Default to no caching. Caching a response containing client or caregiver data risks
    // serving one agency's PHI from another's request.
    cache: options.revalidate === undefined ? "no-store" : undefined,
    next: options.revalidate === undefined ? undefined : { revalidate: options.revalidate },
  });

  if (response.status === 204) return undefined as T;

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const envelope =
      payload && typeof payload === "object" && "error" in payload
        ? (payload as { error: { code: string; message: string; details?: Record<string, unknown> } })
            .error
        : null;
    throw new ApiError(
      response.status,
      envelope?.code ?? "UNKNOWN_ERROR",
      envelope?.message ?? `Request failed with status ${response.status}`,
      envelope?.details ?? {},
    );
  }
  return payload as T;
}

/* --- Types mirroring the API schemas ------------------------------------------------ */

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface MfaEnrolmentStarted {
  secret: string;
  otpauth_uri: string;
  /** Shown once, at enrolment. Not retrievable afterwards from any endpoint. */
  recovery_codes: string[];
}

export interface Agency {
  id: string;
  legal_name: string;
  service_states: string[];
  service_lines: string[];
  accepted_payer_types: string[];
  created_at: string;
  /** `active` or `suspended`. A suspension is set by CareOS, never from inside the agency. */
  status: string;
}

/* --- Platform console -------------------------------------------------------------- */

export interface PlatformOperator {
  id: string;
  email: string;
  display_name: string;
  role: string;
  status: string;
  mfa_enrolled: boolean;
  created_at: string;
  last_login_at: string | null;
  sessions_revoked_at: string | null;
  disabled_reason: string | null;
}

/**
 * One agency as a CareOS operator sees it.
 *
 * Every field is a status, a count, or a timestamp. There is deliberately no client,
 * caregiver, or user named here — and that is enforced two layers down, by the database role
 * behind these endpoints holding no permission on the tables those live in.
 */
export interface AgencyHealth {
  agency_id: string;
  legal_name: string;
  status: string;
  suspended_at: string | null;
  suspended_reason: string | null;
  service_states: string[];
  service_lines: string[];
  created_at: string;

  users_total: number;
  users_active: number;
  owner_admins_active: number;
  users_missing_mfa: number;
  caregivers_active: number;
  clients_active: number;

  visits_next_7d: number;
  visits_unfilled_next_7d: number;

  evv_pending: number;
  evv_transmitted: number;
  evv_acknowledged: number;
  evv_rejected: number;
  evv_oldest_pending_at: string | null;

  exceptions_open_critical: number;
  exceptions_open_warning: number;
  exceptions_open_info: number;

  credentials_expired: number;
  credentials_expiring_30d: number;

  last_user_login_at: string | null;
}

export interface FleetSummary {
  agencies_total: number;
  agencies_suspended: number;
  agencies_with_rejected_evv: number;
  agencies_with_stalled_evv: number;
  agencies_with_critical_exceptions: number;
  open_critical_exceptions: number;
}

export interface Fleet {
  summary: FleetSummary;
  agencies: AgencyHealth[];
}

export interface PlatformAuditEntry {
  id: string;
  action: string;
  actor_display_name: string | null;
  subject_agency_id: string | null;
  subject_agency_name: string | null;
  subject_operator_id: string | null;
  details: Record<string, unknown>;
  source_ip: string | null;
  occurred_at: string;
}

export interface Visit {
  id: string;
  care_plan_id: string;
  caregiver_id: string | null;
  scheduled_start: string;
  scheduled_end: string;
  status: string;
  service_type_code: string | null;
  service_state: string | null;
  payer_type: string | null;
}

export interface VisitPage {
  items: Visit[];
  page: { page: number; page_size: number; total: number };
}

export interface RankingFactor {
  factor: string;
  weight: number;
  rationale: string;
}

export interface CaregiverSuggestion {
  caregiver_id: string;
  caregiver_name: string;
  score: number;
  factors: RankingFactor[];
  warnings: string[];
}

export interface Caregiver {
  id: string;
  legal_name: string;
  employment_status: string;
  exclusion_check_status: string;
  exclusion_checked_at: string | null;
  created_at: string;
}

export interface ComplianceFinding {
  rule_key: string;
  severity: string;
  message: string;
  details: Record<string, unknown>;
}

export interface ExpiringCredential {
  credential_id: string;
  caregiver_id: string;
  caregiver_name: string;
  credential_type: string;
  expiration_date: string;
  days_until_expiry: number;
  bucket: number;
  already_expired: boolean;
}

export interface Applicant {
  id: string;
  job_posting_id: string | null;
  source: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  claimed_credentials: string[];
  pipeline_stage: string;
  ranking_score: number | null;
  ranking_factors: RankingFactor[];
  ranking_model_version: string | null;
  created_at: string;
  /**
   * False while the agency is in its ranking shadow period. The three fields above are then
   * null and empty whatever is stored server-side, and the list arrives in application order.
   * Carried explicitly because "withheld" and "not scored yet" look identical otherwise, and
   * they mean opposite things to whoever is reading the screen.
   */
  ranking_displayed: boolean;
}

export interface JobPosting {
  id: string;
  title: string;
  description: string | null;
  required_credential_types: string[];
  service_state: string | null;
  status: string;
  created_at: string;
}

export interface FunnelStage {
  stage: string;
  count: number;
  conversion_from_previous: number | null;
}

export interface ComplianceException {
  id: string;
  rule_key: string;
  severity: string;
  entity_type: string;
  entity_id: string;
  message: string;
  details: Record<string, unknown>;
  created_at: string;
  resolved_at: string | null;
}

export interface ExceptionSummary {
  total_open: number;
  by_severity: Record<string, number>;
}

export interface Client {
  id: string;
  legal_name: string;
  service_state: string;
  primary_payer_type: string;
  status: string;
  created_at: string;
}

export interface CarePlan {
  id: string;
  client_id: string;
  authorized_tasks: unknown[];
  /** Holds an iCalendar RRULE under `rrule`. Shape is open — see `CarePlanCreate`. */
  visit_frequency_rule: Record<string, unknown>;
  effective_start: string;
  effective_end: string | null;
  default_service_type_code: string | null;
}

export interface AgencyUser {
  id: string;
  email: string;
  role: string;
  status: string;
  mfa_enrolled: boolean;
  created_at: string;
  /** Set once an administrator has ended this user's sessions. */
  sessions_revoked_at: string | null;
  /** Why the account was disabled, when it is. Null for an account in service. */
  disabled_reason: string | null;
}

export interface ReviewStatus {
  review_type: string;
  last_performed_on: string | null;
  last_outcome: string | null;
  next_due_on: string | null;
  is_overdue: boolean;
  never_performed: boolean;
}

/* --- Endpoint wrappers --------------------------------------------------------------- */

export const api = {
  me: (token: string) => apiFetch<AgencyUser>("/v1/auth/me", { token }),

  /**
   * Public self-serve sign-up. The one call in this client with no token, by necessity:
   * there is no tenant to authenticate against until it returns.
   */
  createAgency: (body: Record<string, unknown>) =>
    apiFetch<Agency>("/v1/agencies", { method: "POST", body }),

  startMfaEnrolment: (token: string, currentCode?: string) =>
    apiFetch<MfaEnrolmentStarted>("/v1/auth/mfa/enroll", {
      token,
      method: "POST",
      body: { current_code: currentCode ?? null },
    }),

  confirmMfaEnrolment: (token: string, code: string) =>
    apiFetch<TokenPair>("/v1/auth/mfa/confirm", { token, method: "POST", body: { code } }),

  login: (email: string, password: string, mfaCode?: string) =>
    apiFetch<TokenPair>("/v1/auth/login", {
      method: "POST",
      // Omitted rather than sent empty: the API distinguishes "no code supplied" from "wrong
      // code", and an empty string would turn the first into the second.
      body: mfaCode ? { email, password, mfa_code: mfaCode } : { email, password },
    }),

  agency: (token: string, agencyId: string) =>
    apiFetch<Agency>(`/v1/agencies/${agencyId}`, { token }),

  visits: (token: string, query = "") =>
    apiFetch<VisitPage>(`/v1/visits${query}`, { token }),

  gaps: (token: string, withinHours = 48) =>
    apiFetch<Visit[]>(`/v1/visits/gaps?within_hours=${withinHours}`, { token }),

  suggestions: (token: string, visitId: string) =>
    apiFetch<CaregiverSuggestion[]>(`/v1/visits/${visitId}/suggested-caregivers`, { token }),

  assign: (token: string, visitId: string, caregiverId: string) =>
    apiFetch<Visit>(`/v1/visits/${visitId}/assign`, {
      token,
      method: "POST",
      body: { caregiver_id: caregiverId },
    }),

  caregivers: (token: string) => apiFetch<Caregiver[]>("/v1/caregivers", { token }),

  visitCompliance: (token: string, visitId: string) =>
    apiFetch<ComplianceFinding[]>(`/v1/visits/${visitId}/compliance`, { token }),

  credentialExpirations: (token: string, horizonDays = 60) =>
    apiFetch<ExpiringCredential[]>(
      `/v1/reports/credential-expirations?horizon_days=${horizonDays}`,
      { token },
    ),

  jobPostings: (token: string) => apiFetch<JobPosting[]>("/v1/job-postings", { token }),

  applicantsFor: (token: string, postingId: string) =>
    apiFetch<Applicant[]>(`/v1/job-postings/${postingId}/applicants`, { token }),

  funnel: (token: string) => apiFetch<FunnelStage[]>("/v1/reports/recruiting-funnel", { token }),

  complianceReviews: (token: string, agencyId: string) =>
    apiFetch<ReviewStatus[]>(`/v1/agencies/${agencyId}/compliance-reviews`, { token }),

  exceptions: (token: string, includeResolved = false) =>
    apiFetch<ComplianceException[]>(
      `/v1/compliance-exceptions?include_resolved=${includeResolved}`,
      { token },
    ),

  exceptionSummary: (token: string) =>
    apiFetch<ExceptionSummary>("/v1/compliance-exceptions/summary", { token }),

  resolveException: (token: string, id: string, note: string | null) =>
    apiFetch<ComplianceException>(`/v1/compliance-exceptions/${id}/resolve`, {
      token,
      method: "POST",
      body: { note },
    }),

  users: (token: string, agencyId: string) =>
    apiFetch<AgencyUser[]>(`/v1/agencies/${agencyId}/users`, { token }),

  inviteUser: (token: string, agencyId: string, body: Record<string, unknown>) =>
    apiFetch<AgencyUser>(`/v1/agencies/${agencyId}/users`, { token, method: "POST", body }),

  changeRole: (token: string, userId: string, role: string) =>
    apiFetch<AgencyUser>(`/v1/users/${userId}/role`, {
      token,
      method: "PATCH",
      body: { role },
    }),

  revokeSessions: (token: string, userId: string, reason: string) =>
    apiFetch<AgencyUser>(`/v1/users/${userId}/revoke-sessions`, {
      token,
      method: "POST",
      body: { reason },
    }),

  disableUser: (token: string, userId: string, reason: string) =>
    apiFetch<AgencyUser>(`/v1/users/${userId}/disable`, {
      token,
      method: "POST",
      body: { reason },
    }),

  enableUser: (token: string, userId: string) =>
    apiFetch<AgencyUser>(`/v1/users/${userId}/enable`, { token, method: "POST" }),

  clients: (token: string) => apiFetch<Client[]>("/v1/clients", { token }),

  client: (token: string, id: string) => apiFetch<Client>(`/v1/clients/${id}`, { token }),

  createClient: (token: string, body: Record<string, unknown>) =>
    apiFetch<Client>("/v1/clients", { token, method: "POST", body }),

  carePlans: (token: string, clientId: string) =>
    apiFetch<CarePlan[]>(`/v1/clients/${clientId}/care-plans`, { token }),

  createCarePlan: (token: string, clientId: string, body: Record<string, unknown>) =>
    apiFetch<CarePlan>(`/v1/clients/${clientId}/care-plans`, { token, method: "POST", body }),

  generateVisits: (token: string, carePlanId: string, body: Record<string, unknown>) =>
    apiFetch<Visit[]>(`/v1/care-plans/${carePlanId}/generate-visits`, {
      token,
      method: "POST",
      body,
    }),
};

/**
 * The CareOS operator console.
 *
 * A separate object rather than more entries on `api`, so a tenant screen cannot reach a
 * platform endpoint by autocomplete. The tokens are different kinds — a platform token has
 * no `agency_id` and is refused by every tenant route — and keeping the two clients apart
 * makes that visible at the call site rather than only in the server's decoder.
 */
export const platformApi = {
  login: (email: string, password: string, mfaCode?: string) =>
    apiFetch<TokenPair>("/v1/platform/auth/login", {
      method: "POST",
      body: mfaCode ? { email, password, mfa_code: mfaCode } : { email, password },
    }),

  me: (token: string) => apiFetch<PlatformOperator>("/v1/platform/me", { token }),

  startMfaEnrolment: (token: string, currentCode?: string) =>
    apiFetch<MfaEnrolmentStarted>("/v1/platform/auth/mfa/enroll", {
      token,
      method: "POST",
      body: { current_code: currentCode ?? null },
    }),

  confirmMfaEnrolment: (token: string, code: string) =>
    apiFetch<TokenPair>("/v1/platform/auth/mfa/confirm", {
      token,
      method: "POST",
      body: { code },
    }),

  fleet: (token: string) => apiFetch<Fleet>("/v1/platform/agencies", { token }),

  agency: (token: string, agencyId: string) =>
    apiFetch<AgencyHealth>(`/v1/platform/agencies/${agencyId}`, { token }),

  suspendAgency: (token: string, agencyId: string, reason: string) =>
    apiFetch<AgencyHealth>(`/v1/platform/agencies/${agencyId}/suspend`, {
      token,
      method: "POST",
      body: { reason },
    }),

  reinstateAgency: (token: string, agencyId: string, note: string) =>
    apiFetch<AgencyHealth>(`/v1/platform/agencies/${agencyId}/reinstate`, {
      token,
      method: "POST",
      body: { note },
    }),

  operators: (token: string) =>
    apiFetch<PlatformOperator[]>("/v1/platform/operators", { token }),

  createOperator: (token: string, body: Record<string, unknown>) =>
    apiFetch<PlatformOperator>("/v1/platform/operators", { token, method: "POST", body }),

  disableOperator: (token: string, operatorId: string, reason: string) =>
    apiFetch<PlatformOperator>(`/v1/platform/operators/${operatorId}/disable`, {
      token,
      method: "POST",
      body: { reason },
    }),

  enableOperator: (token: string, operatorId: string) =>
    apiFetch<PlatformOperator>(`/v1/platform/operators/${operatorId}/enable`, {
      token,
      method: "POST",
    }),

  audit: (token: string, limit = 100) =>
    apiFetch<PlatformAuditEntry[]>(`/v1/platform/audit?limit=${limit}`, { token }),
};
