/**
 * User administration.
 *
 * Both endpoints behind this screen already existed and neither had a UI, which meant an agency
 * owner could not add their own scheduler without a terminal. Worse, the API just gained the
 * ability to cut off a departing caregiver's access with no way to operate it — and a security
 * control nobody can reach is not a control.
 *
 * The screen is arranged around the two questions an owner opens it with: "who can reach my
 * agency's PHI right now", and "how do I take that away". So the roster leads, the invite form
 * sits beside it rather than behind a modal, and ending sessions is on the row of the person it
 * concerns rather than in a settings page elsewhere.
 *
 * Ending sessions asks for a reason before it will proceed. That is not friction for its own
 * sake: the reason lands in the audit log, and "we removed their access when they left" is a
 * claim an agency has to be able to evidence.
 */

import { Card, EmptyState, ErrorNote, SeverityBadge, formatDate, formatDateTime } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

const ROLE_LABEL: Record<string, string> = {
  owner_admin: "Owner / Admin",
  scheduler: "Scheduler",
  clinical_supervisor: "Clinical Supervisor",
  caregiver: "Caregiver",
  billing_rcm: "Billing / RCM",
  auditor: "Auditor",
};

/** Assignable roles. `owner_admin` is included so administration can be handed over. */
const ASSIGNABLE_ROLES = [
  "scheduler",
  "clinical_supervisor",
  "caregiver",
  "billing_rcm",
  "auditor",
  "owner_admin",
] as const;

/** MFA is mandatory for these roles (`08_Security_Architecture.md` Section 1). */
const MFA_REQUIRED = ["owner_admin", "clinical_supervisor", "billing_rcm"];

export default async function UsersPage({
  searchParams,
}: {
  searchParams: Promise<{ invited?: string; revoked?: string; changed?: string; error?: string }>;
}) {
  const session = await getSession();
  if (!session) return null;
  const { invited, revoked, changed, error } = await searchParams;

  try {
    const users = await api.users(session.token, session.agencyId);
    const canAdminister = session.role === "owner_admin";
    const live = users.filter((u) => u.sessions_revoked_at === null).length;

    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">Users</h1>
            <p className="page-subtitle">
              {users.length} account{users.length === 1 ? "" : "s"}, {live} with live sessions.
              Ending someone&apos;s sessions signs them out everywhere and makes the caregiver
              app clear the client details saved on their phone.
            </p>
          </div>
        </header>

        {invited && (
          <div className="notice">
            <SeverityBadge severity="good">Invited</SeverityBadge>
            <span>They can sign in now with the password you set.</span>
          </div>
        )}
        {changed && (
          <div className="notice">
            <SeverityBadge severity="good">Updated</SeverityBadge>
            <span>Role changed, and the change is recorded in the audit log.</span>
          </div>
        )}
        {revoked && (
          <div className="notice">
            <SeverityBadge severity="good">Access ended</SeverityBadge>
            <span>
              Every device they were signed in on stops working on its next request, and cached
              client details are cleared.
            </span>
          </div>
        )}
        {error && <ErrorNote title="Could not complete that step" detail={error} />}

        <div className="grid-2">
          <Card
            title="Everyone with access"
            subtitle="Role decides what each person can reach; ending sessions does not delete the account"
          >
            {users.length === 0 ? (
              <EmptyState title="No users yet" />
            ) : (
              <div className="stack">
                {users.map((user) => (
                  <div key={user.id} className="userrow">
                    <div className="userrow__main">
                      <div className="userrow__email">
                        {user.email}
                        {user.id === session.userId && <span className="userrow__you">you</span>}
                      </div>
                      <div className="small muted">
                        {ROLE_LABEL[user.role] ?? user.role} · {user.status} · added{" "}
                        {formatDate(user.created_at)}
                        {MFA_REQUIRED.includes(user.role) && !user.mfa_enrolled && (
                          // Enrolment is tracked but not yet enforced at login. Showing the gap
                          // is better than leaving it invisible until an auditor finds it.
                          <>
                            {" · "}
                            <span className="userrow__warn">MFA not enrolled</span>
                          </>
                        )}
                      </div>
                      {user.sessions_revoked_at && (
                        <div className="small userrow__revoked">
                          Sessions ended {formatDateTime(user.sessions_revoked_at)}. They can sign
                          in again — this ends sessions, it does not disable the account.
                        </div>
                      )}
                    </div>

                    {canAdminister && (
                      <div className="userrow__actions">
                        <form method="post" action="/api/users/role" className="userrow__form">
                          <input type="hidden" name="user_id" value={user.id} />
                          <label className="hidden-label" htmlFor={`role-${user.id}`}>
                            Role for {user.email}
                          </label>
                          <select
                            className="field__input field__input--compact"
                            id={`role-${user.id}`}
                            name="role"
                            defaultValue={user.role}
                          >
                            {ASSIGNABLE_ROLES.map((role) => (
                              <option key={role} value={role}>
                                {ROLE_LABEL[role]}
                              </option>
                            ))}
                          </select>
                          <button className="button button--small button--secondary" type="submit">
                            Save role
                          </button>
                        </form>

                        <form method="post" action="/api/users/revoke" className="userrow__form">
                          <input type="hidden" name="user_id" value={user.id} />
                          <label className="hidden-label" htmlFor={`reason-${user.id}`}>
                            Reason for ending {user.email}&apos;s sessions
                          </label>
                          <input
                            className="field__input field__input--compact"
                            id={`reason-${user.id}`}
                            name="reason"
                            placeholder="Reason (recorded)"
                            minLength={3}
                            required
                          />
                          <button className="button button--small button--danger" type="submit">
                            End sessions
                          </button>
                        </form>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>

          {canAdminister ? (
            <Card title="Invite someone" subtitle="They sign in with the password you set here">
              <form method="post" action="/api/users/invite">
                <div className="field">
                  <label className="field__label" htmlFor="email">
                    Email
                  </label>
                  <input
                    className="field__input"
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="off"
                    required
                  />
                </div>

                <div className="field">
                  <label className="field__label" htmlFor="role">
                    Role
                  </label>
                  <select className="field__input" id="role" name="role" defaultValue="scheduler">
                    {ASSIGNABLE_ROLES.map((role) => (
                      <option key={role} value={role}>
                        {ROLE_LABEL[role]}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label className="field__label" htmlFor="initial_password">
                    Initial password
                  </label>
                  {/* Deliberately type=text: whoever is inviting has to read this out or paste
                      it to the new person, and a masked field they cannot check invites typos
                      that lock the invitee out. This whole step disappears with the managed
                      identity provider. */}
                  <input
                    className="field__input"
                    id="initial_password"
                    name="initial_password"
                    type="text"
                    minLength={12}
                    required
                  />
                  <p className="small muted" style={{ marginTop: "var(--space-2)" }}>
                    At least 12 characters. Shown rather than hidden so you can pass it on
                    without a typo — they should change it after signing in.
                  </p>
                </div>

                <button className="button" type="submit">
                  Send invitation
                </button>
              </form>
            </Card>
          ) : (
            <Card title="Invite someone" subtitle="Owner / Admin only">
              <p className="small muted">
                Your role can see who has access but not change it.
              </p>
            </Card>
          )}
        </div>
      </>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Could not load users.";
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">Users</h1>
        </header>
        <ErrorNote title="Could not load users" detail={message} />
      </>
    );
  }
}
