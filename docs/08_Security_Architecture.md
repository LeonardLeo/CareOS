# CareOS — Security Architecture

**Document owner:** Engineering / Security lead (dedicated hire recommended by Phase 2)
**Status:** Foundational — implements the controls referenced in `06_Compliance_and_Regulatory_Requirements.md`
**Audience:** Engineering, security/compliance reviewers

---

## 1. Identity & Access Management

- **Authentication:** OAuth2/OIDC via a managed identity provider (e.g., Auth0, AWS Cognito, or equivalent) rather than a custom auth system — reduces the surface area for a compliance-sensitive product to get wrong.
- **Multi-factor authentication (MFA):** required for all Owner/Admin, Clinical Supervisor, and Billing/RCM roles; strongly recommended (and should become required) for Scheduler roles given their access to PHI-adjacent data.
- **Role-based access control (RBAC):** enforced at the API layer (not just hidden in the UI) for every role defined in the data model (`owner_admin`, `scheduler`, `clinical_supervisor`, `caregiver`, `billing_rcm`, `auditor`). Every endpoint declares its minimum required role(s); a shared middleware — not per-endpoint ad hoc checks — enforces this.
- **Minimum-necessary access (HIPAA requirement):** caregivers can only access their own schedule/clients' data for visits assigned to them; scheduling coordinators see agency-wide operational data but should not have blanket access to full clinical documentation unless their role requires it; the `auditor` role is read-only across the tenant for compliance review purposes.

## 2. Multi-tenant isolation

- **Application layer:** every data-access function requires an explicit `agency_id` scope derived from the authenticated session — never trust a client-supplied tenant ID for authorization decisions (only for informational display).
- **Database layer:** PostgreSQL Row-Level Security policies on every tenant-scoped table, keyed on `agency_id`, as a second independent enforcement layer beneath the application code (see `04_Data_Model_and_Schema.md`, Section 1).
- **Testing:** automated CI tests that attempt cross-tenant reads/writes using a second tenant's credentials must pass before merge — treat a cross-tenant leak as a Sev-1 security bug, not a normal bug.

## 3. Encryption

- **At rest:** database-level encryption (e.g., AWS RDS encryption or equivalent) plus field-level encryption for the most sensitive PII (SSN/tax ID, DOB, precise home address) so that a database-layer compromise alone does not expose these fields in plaintext.
- **In transit:** TLS 1.2+ enforced everywhere, including internal service-to-service traffic, not just external API calls.
- **Object storage (S3):** server-side encryption on all buckets holding documents, signed onboarding paperwork, and ambient-documentation transcripts/audio.

## 4. Audit logging

- The `audit_log` table (see `04_Data_Model_and_Schema.md`, Section 7) captures actor, action, entity, before/after state, and timestamp for every clinically or financially significant action: visit note signing, EVV record transmission, claim submission, credential verification, role changes, and PHI access to another user's record (even read-only access, given HIPAA's audit-control requirement).
- Audit log writes are append-only at the database permission level — the application role has no UPDATE or DELETE grant on this table.
- Audit logs are retained per the state-specific minimum retention periods identified in `06_Compliance_and_Regulatory_Requirements.md`, Section 8, and are themselves included in the SOC 2 control evidence.

## 5. Application security practices

- Dependency and static-analysis scanning as a required CI check (see `11_Engineering_Handoff_Guide.md`).
- Secrets management via a dedicated secrets manager (e.g., AWS Secrets Manager/Vault) — never in source control or plain environment files committed to a repo.
- Input validation and output encoding standards to prevent injection classes of vulnerability, enforced via shared middleware/libraries rather than per-endpoint discipline alone.
- Principle of least privilege for all service-to-service credentials and cloud IAM roles — the AI/ML service, for example, should not have direct database write access to billing tables it doesn't need to touch.

## 6. Incident response

- A documented incident-response plan must exist before Phase 1 launch, given HIPAA's short breach-notification timelines. At minimum, define: detection/triage process, an on-call escalation path, a communication plan (including agency-customer notification obligations, which may be contractually and legally required), and a post-incident review process.
- Any suspected PHI breach involving a vendor triggers a review of that vendor's BAA obligations (see `06_Compliance_and_Regulatory_Requirements.md`, Section 2).

## 7. Mobile app specific security (caregiver app)

- Offline-cached data on the caregiver device (schedule, care-plan details, draft visit notes) must be encrypted at rest on the device, given that field devices are more easily lost or stolen than a data-center server.
- Remote wipe / session revocation capability so an agency admin can immediately cut off access for a terminated caregiver, including any offline-cached PHI on their device.
- Device-level authentication (biometric/PIN unlock in addition to app login) recommended given the sensitivity of client home-address and schedule data on the device.

## 8. Vendor/subprocessor security review

- Every vendor integrated per `07_Integration_Specifications.md` is reviewed for: BAA availability (if touching PHI), SOC 2 or equivalent attestation, and data-residency/retention terms, before integration work begins — not after.
- Maintain a subprocessor list as part of the SOC 2 program and as a transparency artifact for agency customers who ask (increasingly common in enterprise/mid-market healthcare sales).

## 9. Path to SOC 2 Type II (see also `06_Compliance_and_Regulatory_Requirements.md`, Section 7)

| Milestone | Timing guidance |
|---|---|
| Controls implemented (access management, change management, encryption, logging — all described above) | From Phase 1 build, since HIPAA requires most of the same controls |
| Formal readiness assessment | Around Phase 2 launch |
| Type I audit (point-in-time control design review) | Around Phase 2 launch window |
| Type II audit (controls operating effectively over 6–12 months) | Complete before or around Phase 3 launch, timed to when CareOS begins handling claims/financial data and enterprise sales conversations require it |
