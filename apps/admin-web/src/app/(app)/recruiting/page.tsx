/**
 * Recruiting funnel and applicant pipeline (Epic 1.2).
 *
 * Applicant rankings are shown with their factors inline, per `09_UX...` principle 4. That
 * matters more here than anywhere else in the product: this score influences who gets hired,
 * and `06_Compliance_and_Regulatory_Requirements.md` Section 5 requires AI use in hiring to
 * be explainable and auditable. A scheduler must be able to see why someone ranked where
 * they did — and so must a regulator, later.
 */

import { Card, EmptyState, ErrorNote, FactorList, SeverityBadge, Table, formatDate } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

const STAGE_SEVERITY: Record<string, "success" | "info" | "warning" | "neutral"> = {
  hired: "success",
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
          <h1 className="page-title">Recruiting</h1>
          <p className="page-subtitle">Pipeline health and applicant ranking.</p>
        </header>

        <Card title="Funnel" subtitle="Conversion is measured from the preceding stage">
          <Table headers={["Stage", "Reached", "Conversion"]} caption="Recruiting funnel">
            {funnel.map((stage) => (
              <tr key={stage.stage}>
                <td style={{ textTransform: "capitalize" }}>{stage.stage}</td>
                <td>{stage.count}</td>
                <td>
                  {stage.conversion_from_previous === null ? (
                    <span className="muted">—</span>
                  ) : (
                    `${Math.round(stage.conversion_from_previous * 100)}%`
                  )}
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title="Job postings" subtitle={`${postings.length} total`}>
          {postings.length === 0 ? (
            <EmptyState title="No job postings yet" detail="Create one to start collecting applicants." />
          ) : (
            <Table headers={["Title", "State", "Required credentials", "Created", ""]} caption="Job postings">
              {postings.map((post) => (
                <tr key={post.id}>
                  <td>{post.title}</td>
                  <td>{post.service_state ?? <span className="muted">—</span>}</td>
                  <td>{post.required_credential_types.join(", ") || <span className="muted">Any</span>}</td>
                  <td>{formatDate(post.created_at)}</td>
                  <td>
                    <a
                      className={selected?.id === post.id ? "button button--small" : "button button--secondary button--small"}
                      href={`/recruiting?posting=${post.id}`}
                    >
                      {selected?.id === post.id ? "Viewing" : "View applicants"}
                    </a>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        {selected && (
          <Card
            title={`Applicants — ${selected.title}`}
            subtitle="Ranked on certification match, proximity to open shifts, and availability. Protected attributes are never used."
          >
            {applicants.length === 0 ? (
              <EmptyState title="No applicants yet for this posting" />
            ) : (
              applicants.map((applicant) => (
                <div key={applicant.id} className="suggestion">
                  <div className="suggestion__head">
                    <span className="suggestion__name">{applicant.full_name}</span>
                    <span className="suggestion__score">
                      {applicant.ranking_score === null ? (
                        <span className="muted small">Not ranked</span>
                      ) : (
                        <>
                          {Math.round(applicant.ranking_score * 100)}
                          <span className="visually-hidden"> out of 100 match score</span>
                        </>
                      )}
                    </span>
                  </div>

                  <div className="small muted" style={{ marginTop: "var(--space-1)" }}>
                    <SeverityBadge severity={STAGE_SEVERITY[applicant.pipeline_stage] ?? "neutral"}>
                      {applicant.pipeline_stage}
                    </SeverityBadge>{" "}
                    via {applicant.source}
                    {applicant.claimed_credentials.length > 0 &&
                      ` · claims ${applicant.claimed_credentials.join(", ")}`}
                  </div>

                  <FactorList factors={applicant.ranking_factors} />

                  {applicant.ranking_model_version && (
                    <p className="small muted" style={{ marginTop: "var(--space-3)" }}>
                      Ranked by model {applicant.ranking_model_version}. Scores are advisory —
                      hiring decisions remain with your team.
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
    const message = error instanceof ApiError ? error.message : "Could not load recruiting data.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Recruiting</h1>
        </header>
        <ErrorNote title={message} />
      </>
    );
  }
}
