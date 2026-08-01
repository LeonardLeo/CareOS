/**
 * Recruiting funnel and applicant pipeline (Epic 1.2).
 *
 * Applicant rankings are shown with their factors inline, per `09_UX...` principle 4. That
 * matters more here than anywhere else in the product: this score influences who gets hired,
 * and `06_Compliance_and_Regulatory_Requirements.md` Section 5 requires AI use in hiring to
 * be explainable and auditable. A scheduler must be able to see why someone ranked where
 * they did — and so must a regulator, later.
 */

import { Funnel, ScoreBar } from "@/components/charts";
import {
  Card,
  EmptyState,
  ErrorNote,
  FactorList,
  InfoNote,
  SeverityBadge,
  Table,
  formatDate,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

const STAGE_SEVERITY: Record<string, "good" | "info" | "warning" | "neutral"> = {
  hired: "good",
  offer: "info",
  screened: "info",
  applied: "neutral",
  rejected: "neutral",
};

export default async function RecruitingPage({
  searchParams,
}: {
  searchParams: Promise<{ posting?: string }>;
}) {
  const session = await getSession();
  if (!session) return null;
  const { posting: selectedPostingId } = await searchParams;
  const t = translatorFor(await getLocale());

  try {
    const [funnel, postings] = await Promise.all([
      api.funnel(session.token),
      api.jobPostings(session.token),
    ]);
    const selected = selectedPostingId
      ? (postings.find((p) => p.id === selectedPostingId) ?? null)
      : (postings[0] ?? null);
    const applicants = selected ? await api.applicantsFor(session.token, selected.id) : [];

    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("recruitingTitle")}</h1>
          <p className="page-subtitle">{t("recruitingSubtitle")}</p>
        </header>

        <Card
          title={t("funnel")}
          subtitle={t("funnelSubtitle")}
        >
          {/* Ordered stages, so the validated ordinal ramp carries the sequence. Nominal
              categories would get a single color; these have a real order. */}
          <Funnel
            stages={funnel.map((s) => ({
              stage: s.stage,
              count: s.count,
              conversion: s.conversion_from_previous,
            }))}
          />
        </Card>

        <Card title={t("jobPostings")} subtitle={t("postingCount", { count: postings.length })}>
          {postings.length === 0 ? (
            <EmptyState title={t("noJobPostings")} detail={t("createOneToCollect")} />
          ) : (
            <Table
              headers={[
                t("colTitle"),
                t("colState"),
                t("colRequiredCredentials"),
                t("created"),
                "",
              ]}
              caption={t("jobPostings")}
            >
              {postings.map((post) => (
                <tr key={post.id}>
                  <td>{post.title}</td>
                  <td>{post.service_state ?? <span className="muted">—</span>}</td>
                  <td>{post.required_credential_types.join(", ") || <span className="muted">{t("any")}</span>}</td>
                  <td>{formatDate(post.created_at)}</td>
                  <td>
                    <a
                      className={selected?.id === post.id ? "button button--small" : "button button--secondary button--small"}
                      href={`/recruiting?posting=${post.id}`}
                    >
                      {selected?.id === post.id ? t("viewing") : t("viewApplicants")}
                    </a>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        {selected && (
          <Card
            title={t("applicantsFor", { posting: selected.title })}
            // The default subtitle promises a ranking. Printing it directly above a banner
            // saying the ranking is withheld puts two contradictory claims on one card.
            subtitle={
              applicants.some((a) => !a.ranking_displayed)
                ? t("rankingShadowSubtitle")
                : t("rankingSubtitle")
            }
          >
            {/* Says why the scores are missing. Without it the rows below read as "nobody has
                been scored yet", which is the opposite of what is happening and invites
                someone to go looking for the button that starts the scoring. */}
            {applicants.some((a) => !a.ranking_displayed) && (
              <InfoNote title={t("rankingShadowTitle")} detail={t("rankingShadowBody")} />
            )}
            {applicants.length === 0 ? (
              <EmptyState title={t("noApplicantsForPosting")} />
            ) : (
              applicants.map((applicant) => (
                <div key={applicant.id} className="suggestion">
                  <div className="suggestion__head">
                    <span className="suggestion__name">{applicant.full_name}</span>
                    {applicant.ranking_score === null ? (
                      // Only when ranking is on: during a shadow period the banner above has
                      // already explained the absence, and repeating "Not ranked" on every row
                      // states something untrue — they were ranked, it is being withheld.
                      applicant.ranking_displayed ? (
                        <span className="muted small">{t("notRanked")}</span>
                      ) : null
                    ) : (
                      <ScoreBar
                        score={applicant.ranking_score}
                        segments={applicant.ranking_factors.map((f) => f.weight)}
                        t={t}
                      />
                    )}
                  </div>

                  <div className="suggestion__meta row" style={{ marginTop: "var(--space-2)" }}>
                    <SeverityBadge severity={STAGE_SEVERITY[applicant.pipeline_stage] ?? "neutral"}>
                      {applicant.pipeline_stage}
                    </SeverityBadge>{" "}
                    {t("viaSource", { source: applicant.source })}
                    {applicant.claimed_credentials.length > 0 &&
                      t("claimsCredentials", {
                        credentials: applicant.claimed_credentials.join(", "),
                      })}
                  </div>

                  <FactorList factors={applicant.ranking_factors} />

                  {applicant.ranking_model_version && (
                    <p className="small muted" style={{ marginTop: "var(--space-3)" }}>
                      {t("rankedByModel", { version: applicant.ranking_model_version })}
                    </p>
                  )}
                </div>
              ))
            )}
          </Card>
        )}
      </>
    );
  } catch (error) {
    const message =
      error instanceof ApiError ? error.message : t("couldNotLoadRecruiting");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("recruitingTitle")}</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
