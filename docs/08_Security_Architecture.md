# CareOS — Security Architecture

**Document owner:** Engineering / Security lead (dedicated hire recommended by Phase 2)
**Status:** Foundational — implements the controls referenced in `06_Compliance_and_Regulatory_Requirements.md`
**Audience:** Engineering, security/compliance reviewers

---

## 1. Identity & Access Management

**Authentication.** OAuth2/OIDC via a managed identity provider such as Auth0 or AWS Cognito,
rather than a custom auth system. Less surface for a compliance-sensitive product to get wrong.

**Multi-factor authentication.** Required for Owner/Admin, Clinical Supervisor, and Billing/RCM.
Recommended for Scheduler, and should become required, given that role's access to PHI-adjacent
data.

**Role-based access control.** Enforced at the API layer, not hidden in the UI, for every role
in the data model: `owner_admin`, `scheduler`, `clinical_supervisor`, `caregiver`, `billing_rcm`,
`auditor`. Every endpoint declares its minimum required roles. Shared middleware enforces them;
per-endpoint checks do not.

**Minimum-necessary access.** A HIPAA requirement.

| Role | Access |
|---|---|
| Caregiver | Own schedule, and client data only for visits assigned to them |
| Scheduling coordinator | Agency-wide operational data. Not blanket access to full clinical documentation unless the role requires it |
| Auditor | Read-only across the tenant, for compliance review |

## 2. Multi-tenant isolation

**Application layer.** Every data-access function requires an explicit `agency_id` scope taken
from the authenticated session. A client-supplied tenant ID is never used for authorization,
only for display.

**Database layer.** PostgreSQL Row-Level Security policies on every tenant-scoped table, keyed
on `agency_id`. A second enforcement layer, independent of application code
(`04_Data_Model_and_Schema.md` Section 1).

**Testing.** Automated CI tests attempt cross-tenant reads and writes using a second tenant's
credentials, and must pass before merge. A cross-tenant leak is a Sev-1.

## 3. Encryption

| Scope | Requirement |
|---|---|
| At rest | Database-level encryption (AWS RDS or equivalent), plus field-level encryption for SSN and tax ID, DOB, and precise home address, so a database-layer compromise alone does not expose them |
| In transit | TLS 1.2+ everywhere, including internal service-to-service traffic |
| Object storage | Server-side encryption on all buckets holding documents, signed onboarding paperwork, and ambient-documentation transcripts and audio |

## 4. Audit logging

The `audit_log` table (`04_Data_Model_and_Schema.md` Section 7) captures actor, action, entity,
before and after state, and timestamp for every clinically or financially significant action:

- Visit note signing
- EVV record transmission
- Claim submission
- Credential verification
- Role changes
- PHI access to another user's record, including read-only access, per HIPAA's audit-control
  requirement

Writes are append-only at the database permission level: the application role holds no UPDATE or
DELETE grant on the table.

Retention follows the state-specific minimums in
`06_Compliance_and_Regulatory_Requirements.md` Section 8. The logs are themselves SOC 2 control
evidence.

## 5. Application security practices

| Practice | Detail |
|---|---|
| Dependency and static-analysis scanning | Required CI check (`12_Engineering_Handoff_Guide.md`) |
| Secrets management | A dedicated secrets manager such as AWS Secrets Manager or Vault. Never source control, never a committed environment file |
| Input validation and output encoding | Enforced through shared middleware and libraries, not per-endpoint discipline |
| Least privilege | For all service-to-service credentials and cloud IAM roles. The AI/ML service holds no write access to billing tables it does not touch |

## 6. Incident response

A documented incident-response plan is required before Phase 1 launch, given HIPAA's
breach-notification timelines. Minimum contents:

- Detection and triage process
- On-call escalation path
- Communication plan, including agency-customer notification obligations, which may be both
  contractual and legal
- Post-incident review process

A suspected PHI breach involving a vendor triggers a review of that vendor's BAA obligations
(`06_Compliance_and_Regulatory_Requirements.md` Section 2).

## 7. Mobile app specific security

Caregiver app.

| Control | Reason |
|---|---|
| Offline-cached data encrypted at rest on the device: schedule, care-plan details, draft visit notes | Field devices are lost and stolen more often than data-center servers |
| Remote wipe and session revocation | An agency admin can cut off a terminated caregiver immediately, including offline-cached PHI on their device |
| Device-level authentication: biometric or PIN unlock in addition to app login | Recommended, given client home addresses and schedules held on the device |

## 8. Vendor/subprocessor security review

Every vendor integrated per `07_Integration_Specifications.md` is reviewed before integration
work begins, not after. The review covers:

- BAA availability, where the vendor touches PHI
- SOC 2 or equivalent attestation
- Data-residency and retention terms

A subprocessor list is maintained as part of the SOC 2 program, and as a transparency artifact
for agency customers who ask. Enterprise and mid-market healthcare buyers increasingly do.

## 9. Path to SOC 2 Type II

See also `06_Compliance_and_Regulatory_Requirements.md` Section 7.

| Milestone | Timing guidance |
|---|---|
| Controls implemented: access management, change management, encryption, logging | From Phase 1 build. HIPAA requires most of the same controls |
| Formal readiness assessment | Around Phase 2 launch |
| Type I audit — point-in-time control design review | Around the Phase 2 launch window |
| Type II audit — controls operating effectively over 6–12 months | Before or around Phase 3 launch, when CareOS begins handling claims and financial data and enterprise sales require it |
