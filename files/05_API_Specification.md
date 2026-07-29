# CareOS — API Specification

**Document owner:** Engineering
**Status:** Foundational — REST/JSON over HTTPS; versioned from `v1`
**Audience:** Backend engineers, frontend/mobile engineers, third-party integrators (Phase 3 Epic 3.6)

---

## 1. Conventions

- Base path: `https://api.careos.example/v1`
- Auth: OAuth2 bearer tokens (short-lived access token + refresh token); every request scoped to a single `agency_id` derived from the token claims, never accepted as a client-supplied parameter for tenant-scoping decisions.
- All list endpoints support `?page`, `?page_size`, and cursor-based pagination for large collections (e.g., visits, claims).
- All timestamps are ISO 8601 UTC.
- Errors follow a consistent envelope:
```json
{
  "error": {
    "code": "EVV_TRANSMISSION_FAILED",
    "message": "Human-readable description",
    "details": { }
  }
}
```
- Idempotency: all mutating endpoints that trigger external side effects (EVV transmission, claim submission, background-check initiation) require an `Idempotency-Key` header.

## 2. Auth & Agency (Phase 1 foundation)

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Exchange credentials for tokens |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/agencies` | Create a new agency tenant (onboarding wizard) |
| GET | `/agencies/{agency_id}` | Get agency profile/settings |
| PATCH | `/agencies/{agency_id}` | Update service states, service lines, payer types |
| POST | `/agencies/{agency_id}/users` | Invite a user with a role |
| GET | `/agencies/{agency_id}/users` | List users |
| PATCH | `/users/{user_id}/role` | Change a user's role |

## 3. Recruiting & Onboarding (Phase 1)

| Method | Path | Description |
|---|---|---|
| POST | `/job-postings` | Create/syndicate an open role |
| GET | `/job-postings/{id}/applicants` | List applicants with AI ranking scores and explanatory factors |
| POST | `/applicants/{id}/screen` | Trigger automated screening flow |
| POST | `/applicants/{id}/hire` | Convert applicant to caregiver record, kicking off onboarding |
| POST | `/caregivers/{id}/onboarding-documents` | Submit signed onboarding paperwork |
| POST | `/caregivers/{id}/background-check` | Initiate background/exclusion-list/credential checks (async; see webhook section) |
| GET | `/caregivers/{id}/credentials` | List credential status/expirations |

**Example response — applicant ranking:**
```json
{
  "applicant_id": "a1b2c3",
  "ranking_score": 0.87,
  "ranking_factors": [
    { "factor": "certification_match", "weight": 0.4 },
    { "factor": "geo_proximity_to_open_shifts", "weight": 0.35 },
    { "factor": "availability_overlap", "weight": 0.25 }
  ]
}
```

## 4. Scheduling & EVV (Phase 1)

| Method | Path | Description |
|---|---|---|
| POST | `/clients` | Create client record |
| POST | `/clients/{id}/care-plans` | Create care plan (authorized tasks, recurrence rule) |
| POST | `/care-plans/{id}/generate-visits` | Materialize `scheduled_visit` rows from the recurrence rule |
| GET | `/visits?status=open&date_range=...` | List visits (filterable by status, caregiver, date range) |
| POST | `/visits/{id}/assign` | Assign a caregiver (manual or accept an AI suggestion) |
| GET | `/visits/{id}/suggested-caregivers` | AI-ranked replacement/assignment suggestions |
| POST | `/visits/{id}/clock-in` | Caregiver clock-in (mobile app); triggers EVV record creation |
| POST | `/visits/{id}/clock-out` | Caregiver clock-out; triggers EVV transmission job |
| GET | `/visits/{id}/evv-status` | Transmission status to the state aggregator |
| POST | `/visits/{id}/gap-alert` | System/internal — triggered on no-show detection, fans out replacement offers |

**Example — clock-in payload (offline-capable):**
```json
{
  "visit_id": "v123",
  "caregiver_id": "cg456",
  "timestamp": "2026-07-29T14:02:00Z",
  "geo": { "lat": 40.712, "lng": -74.006 },
  "capture_method": "mobile_gps",
  "client_local_uuid": "offline-generated-uuid-for-sync-dedup"
}
```

## 5. Documentation & Compliance (Phase 2)

| Method | Path | Description |
|---|---|---|
| POST | `/visits/{id}/ambient-sessions` | Start an ambient documentation session (requires `consent_captured: true`) |
| POST | `/ambient-sessions/{id}/finalize` | Trigger STT + extraction, producing a draft `visit_note` |
| GET | `/visit-notes/{id}` | Retrieve draft/final visit note with compliance flags |
| POST | `/visit-notes/{id}/sign` | Caregiver signs off |
| POST | `/visit-notes/{id}/supervisor-review` | Supervisor reviews/co-signs |
| GET | `/agencies/{id}/compliance-score` | Rolling audit-readiness score |
| POST | `/agencies/{id}/compliance-rules` | Configure agency-specific documentation rules (no-code rules config, PRD US-2.2.3) |

## 6. Billing & Revenue (Phase 3)

| Method | Path | Description |
|---|---|---|
| POST | `/clients/{id}/eligibility-check` | Real-time X12 270/271 eligibility check |
| POST | `/care-plans/{id}/authorizations` | Record a payer authorization (units, date range) |
| POST | `/claims/generate` | Batch-generate draft claims from EVV + documentation + authorization data |
| POST | `/claims/{id}/scrub` | Run claim-scrubbing checks |
| POST | `/claims/{id}/submit` | Submit to clearinghouse (X12 837) |
| GET | `/claims/{id}` | Claim status |
| POST | `/remittances/webhook` | Inbound remittance (X12 835) ingestion endpoint |
| GET | `/denials?status=open` | Denial-management queue |
| GET | `/reports/ar-aging` | AR aging report |
| GET | `/reports/payer-mix` | Payer-mix profitability analytics |

## 7. Webhooks (outbound, for async external processes)

| Event | Payload summary |
|---|---|
| `background_check.completed` | Result status, flagged items |
| `evv.transmission_acknowledged` / `evv.transmission_rejected` | Aggregator response |
| `claim.status_changed` | New status, payer response summary |
| `credential.expiring_soon` | Caregiver ID, credential type, days until expiration |

## 8. Versioning & deprecation policy

- Breaking changes require a new version prefix (`/v2`); non-breaking additive changes ship within `/v1`.
- Deprecated endpoints carry a `Sunset` HTTP header with a minimum 90-day notice before removal, given that agency operations depend on integration stability.

## 9. Rate limits

- Default: 100 requests/minute per agency for standard endpoints.
- EVV clock-in/out endpoints are exempt from standard rate limiting (never throttle a legally time-sensitive action) but are protected by abuse-detection heuristics instead (e.g., anomalous volume from a single device).
