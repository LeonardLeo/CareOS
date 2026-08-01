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
import { type StringKey, type Translator, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

// Keys rather than English, so the review names translate with everything else. A review type
// the API adds before this map does falls back to its raw identifier rather than rendering
// blank — visible, and obviously a gap.
const REVIEW_LABEL: Record<string, StringKey> = {
  healthcare_counsel: "reviewHealthcareCounsel",
  consent_law_state: "reviewConsentLawState",
  billing_coding_consultant: "reviewBillingCodingConsultant",
  ai_hiring_bias_audit: "reviewAiHiringBiasAudit",
  cms_pps_rule_review: "reviewCmsPpsRuleReview",
  evv_vendor_review: "reviewEvvVendorReview",
  new_state_entry: "reviewNewStateEntry",
  security_penetration_test: "reviewSecurityPenetrationTest",
};

function reviewLabel(t: Translator, reviewType: string): string {
  const key = REVIEW_LABEL[reviewType];
  return key ? t(key) : reviewType;
}

export default async function CompliancePage() {
  const session = await getSession();
  if (!session) return null;
  const t = translatorFor(await getLocale());

  try {
    const reviews = await api.complianceReviews(session.token, session.agencyId);
    const outstanding = reviews.filter((r) => r.never_performed || r.is_overdue);

    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("navCompliance")}</h1>
          <p className="page-subtitle">
            {t("complianceSubtitle", {
              outstanding: outstanding.length,
              total: reviews.length,
            })}
          </p>
        </header>

        <Card
          title={t("reviewStanding")}
          subtitle={t("reviewStandingSubtitle")}
        >
          <Table
            headers={[
              t("reviewType"),
              t("lastPerformed"),
              t("colOutcome"),
              t("nextDue"),
              t("colStatus"),
            ]}
            caption={t("complianceTitle")}
          >
            {reviews.map((review) => (
              <tr key={review.review_type}>
<td>{reviewLabel(t, review.review_type)}</td>
                <td>
                  {review.last_performed_on ? (
                    formatDate(review.last_performed_on)
                  ) : (
                    <span className="muted">{t("never")}</span>
                  )}
                </td>
                <td>{review.last_outcome ?? <span className="muted">—</span>}</td>
                <td>
                  {review.next_due_on ? (
                    formatDate(review.next_due_on)
                  ) : (
                    <span className="muted">{t("eventTriggered")}</span>
                  )}
                </td>
                <td>
                  {review.never_performed ? (
                    <SeverityBadge severity="critical">{t("neverPerformed")}</SeverityBadge>
                  ) : review.is_overdue ? (
                    <SeverityBadge severity="warning">{t("overdue")}</SeverityBadge>
                  ) : (
                    <SeverityBadge severity="good">{t("current")}</SeverityBadge>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title={t("beforeGoingLive")}>
          <p className="small">
            {t("beforeGoingLiveBody", { command: "python -m careos.scripts.run_bias_audit" })}
          </p>
        </Card>
      </>
    );
  } catch (error) {
    const message =
      error instanceof ApiError ? error.message : t("couldNotLoadCompliance");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("navCompliance")}</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
