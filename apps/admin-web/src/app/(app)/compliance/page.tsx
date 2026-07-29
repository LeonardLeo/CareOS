/**
 * Compliance review standing (`06_Compliance_and_Regulatory_Requirements.md` Section 9).
 *
 * Shows every review the cadence requires, including those never performed. A review that
 * has never happened is the more serious state and is labelled as such rather than being
 * absent from the list — an empty compliance page would read as "all clear" when it means
 * "nothing has been checked".
 */

import { Card, ErrorNote, SeverityBadge, Table, formatDate } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

const REVIEW_LABEL: Record<string, string> = {
  healthcare_counsel: "Healthcare compliance counsel review",
  consent_law_state: "State consent-law review (ambient documentation)",
  billing_coding_consultant: "Certified billing / coding consultant review",
  ai_hiring_bias_audit: "AI hiring bias audit",
  cms_pps_rule_review: "CMS Home Health PPS rule review",
  evv_vendor_review: "State EVV vendor assignment review",
  new_state_entry: "New state entry check",
  security_penetration_test: "Security penetration test",
};

export default async function CompliancePage() {
  const session = await getSession();
  if (!session) return null;

  try {
    const reviews = await api.complianceReviews(session.token, session.agencyId);
    const outstanding = reviews.filter((r) => r.never_performed || r.is_overdue);

    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Compliance</h1>
          <p className="page-subtitle">
            Review cadence from the compliance requirements. {outstanding.length} of{" "}
            {reviews.length} need attention.
          </p>
        </header>

        <Card
          title="Review standing"
          subtitle="A review that has never been performed is listed, not omitted"
        >
          <Table headers={["Review", "Last performed", "Outcome", "Next due", "Status"]} caption="Compliance reviews">
            {reviews.map((review) => (
              <tr key={review.review_type}>
                <td>{REVIEW_LABEL[review.review_type] ?? review.review_type}</td>
                <td>
                  {review.last_performed_on ? (
                    formatDate(review.last_performed_on)
                  ) : (
                    <span className="muted">Never</span>
                  )}
                </td>
                <td>{review.last_outcome ?? <span className="muted">—</span>}</td>
                <td>
                  {review.next_due_on ? (
                    formatDate(review.next_due_on)
                  ) : (
                    <span className="muted">Event-triggered</span>
                  )}
                </td>
                <td>
                  {review.never_performed ? (
                    <SeverityBadge severity="critical">Never performed</SeverityBadge>
                  ) : review.is_overdue ? (
                    <SeverityBadge severity="warning">Overdue</SeverityBadge>
                  ) : (
                    <SeverityBadge severity="success">Current</SeverityBadge>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title="Before going live">
          <p className="small">
            Healthcare-compliance counsel must review the EVV and HIPAA implementation before
            Phase 1 launch, and the AI hiring bias audit must be run on real outcomes before
            ranking influences hiring decisions. Run the audit with{" "}
            <code>python -m careos.scripts.run_bias_audit</code>; it records its outcome here
            automatically.
          </p>
        </Card>
      </>
    );
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Could not load compliance data.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Compliance</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
