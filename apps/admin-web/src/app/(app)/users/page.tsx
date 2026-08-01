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
 *
 * **Ending sessions and disabling the account are two buttons, not one.** They read similarly
 * and they are not the same thing: ending sessions signs someone out of every device and lets
 * them sign back in with the password they know, which is what a lost phone needs; disabling
 * also stops them signing in at all, which is what leaving needs. Collapsing them into one
 * control would mean either a lost phone locking someone out of their shift, or an offboarding
 * that quietly left the door open. The row states which one has happened, and a disabled
 * account shows the reason it was given rather than the session note — an administrator reading
 * "they can sign in again" under a disabled account would be reading something untrue.
 */

import { Card, EmptyState, ErrorNote, SeverityBadge, formatDate, formatDateTime } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { roleLabel, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

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
  searchParams: Promise<{
    invited?: string;
    revoked?: string;
    changed?: string;
    disabled?: string;
    enabled?: string;
    error?: string;
  }>;
}) {
  const session = await getSession();
  if (!session) return null;
  const locale = await getLocale();
  const t = translatorFor(locale);
  const { invited, revoked, changed, disabled, enabled, error } = await searchParams;

  try {
    const users = await api.users(session.token, session.agencyId);
    const canAdminister = session.role === "owner_admin";
    // "Able to sign in" rather than "has a live session": a revoked user can sign back
    // in, a disabled one cannot, and it is the second fact an owner is counting.
    const live = users.filter((u) => u.status !== "suspended").length;

    return (
      <>
        <header className="page-header">
          <div>
            <h1 className="page-title">{t("usersTitle")}</h1>
            <p className="page-subtitle">
              {t("usersOverview", { count: users.length, live })}
            </p>
          </div>
        </header>

        {invited && (
          <div className="notice">
            <SeverityBadge severity="good">{t("invited")}</SeverityBadge>
            <span>{t("canSignInNow")}</span>
          </div>
        )}
        {changed && (
          <div className="notice">
            <SeverityBadge severity="good">{t("updated")}</SeverityBadge>
            <span>{t("roleChangedNote")}</span>
          </div>
        )}
        {revoked && (
          <div className="notice">
            <SeverityBadge severity="good">{t("accessEnded")}</SeverityBadge>
            <span>
              {t("accessEndedNote")}
            </span>
          </div>
        )}
        {disabled && (
          <div className="notice">
            <SeverityBadge severity="good">{t("accountDisabled")}</SeverityBadge>
            <span>{t("accountDisabledNote")}</span>
          </div>
        )}
        {enabled && (
          <div className="notice">
            <SeverityBadge severity="good">{t("accountEnabled")}</SeverityBadge>
            <span>{t("accountEnabledNote")}</span>
          </div>
        )}
        {error && <ErrorNote title={t("couldNotCompleteStep")} detail={error} />}

        <div className="grid-2">
          <Card
            title={t("everyoneWithAccess")}
            subtitle={t("everyoneWithAccessSubtitle")}
          >
            {users.length === 0 ? (
              <EmptyState title={t("noUsersYet")} />
            ) : (
              <div className="stack">
                {users.map((user) => (
                  <div key={user.id} className="userrow">
                    <div className="userrow__main">
                      <div className="userrow__email">
                        {user.email}
                        {user.id === session.userId && (
                          <span className="userrow__you">{t("you")}</span>
                        )}
                      </div>
                      <div className="small muted">
                        {roleLabel(locale, user.role)} · {user.status} · added{" "}
                        {formatDate(user.created_at)}
                        {MFA_REQUIRED.includes(user.role) && !user.mfa_enrolled && (
                          // Enrolment is tracked but not yet enforced at login. Showing the gap
                          // is better than leaving it invisible until an auditor finds it.
                          <>
                            {" · "}
                            <span className="userrow__warn">{t("mfaNotEnrolled")}</span>
                          </>
                        )}
                      </div>
                      {user.disabled_reason && (
                        // Shown above the session note, because it is the stronger statement:
                        // a disabled account cannot sign in at all, and an administrator
                        // reading "they can sign in again" underneath it would be misled.
                        <div className="small userrow__revoked">
                          {t("disabledBecause", { reason: user.disabled_reason })}
                        </div>
                      )}
                      {user.sessions_revoked_at && !user.disabled_reason && (
                        <div className="small userrow__revoked">
                          {t("sessionsEndedAt", {
                            when: formatDateTime(user.sessions_revoked_at),
                          })}
                        </div>
                      )}
                    </div>

                    {canAdminister && (
                      <div className="userrow__actions">
                        <form method="post" action="/api/users/role" className="userrow__form">
                          <input type="hidden" name="user_id" value={user.id} />
                          <label className="hidden-label" htmlFor={`role-${user.id}`}>
                            {t("roleForUser", { email: user.email })}
                          </label>
                          <select
                            className="field__input field__input--compact"
                            id={`role-${user.id}`}
                            name="role"
                            defaultValue={user.role}
                          >
                            {ASSIGNABLE_ROLES.map((role) => (
                              <option key={role} value={role}>
                                {roleLabel(locale, role)}
                              </option>
                            ))}
                          </select>
                          <button className="button button--small button--secondary" type="submit">
                            {t("saveRole")}
                          </button>
                        </form>

                        <form method="post" action="/api/users/revoke" className="userrow__form">
                          <input type="hidden" name="user_id" value={user.id} />
                          <label className="hidden-label" htmlFor={`reason-${user.id}`}>
                            {t("endSessionsReasonLabel", { email: user.email })}
                          </label>
                          <input
                            className="field__input field__input--compact"
                            id={`reason-${user.id}`}
                            name="reason"
                            placeholder={t("reasonRecorded")}
                            minLength={3}
                            required
                          />
                          <button className="button button--small button--danger" type="submit">
                            {t("endSessions")}
                          </button>
                        </form>

                        {user.status === "suspended" ? (
                          <form method="post" action="/api/users/enable" className="userrow__form">
                            <input type="hidden" name="user_id" value={user.id} />
                            <button className="button button--small button--secondary" type="submit">
                              {t("enableAccount")}
                            </button>
                          </form>
                        ) : (
                          user.id !== session.userId && (
                            // Hidden for yourself because the API refuses it. Offering a button
                            // whose only outcome is an error message is worse than not offering
                            // it: the owner learns the rule by being told off.
                            <form
                              method="post"
                              action="/api/users/disable"
                              className="userrow__form"
                            >
                              <input type="hidden" name="user_id" value={user.id} />
                              <label
                                className="hidden-label"
                                htmlFor={`disable-reason-${user.id}`}
                              >
                                {t("disableReasonLabel", { email: user.email })}
                              </label>
                              <input
                                className="field__input field__input--compact"
                                id={`disable-reason-${user.id}`}
                                name="reason"
                                placeholder={t("reasonRecorded")}
                                minLength={3}
                                required
                              />
                              <button
                                className="button button--small button--danger"
                                type="submit"
                              >
                                {t("disableAccount")}
                              </button>
                            </form>
                          )
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>

          {canAdminister ? (
            <Card title={t("inviteSomeone")} subtitle={t("theySignInWithPassword")}>
              <form method="post" action="/api/users/invite">
                <div className="field">
                  <label className="field__label" htmlFor="email">
                    {t("email")}
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
                    {t("role")}
                  </label>
                  <select className="field__input" id="role" name="role" defaultValue="scheduler">
                    {ASSIGNABLE_ROLES.map((role) => (
                      <option key={role} value={role}>
                        {roleLabel(locale, role)}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label className="field__label" htmlFor="initial_password">
                    {t("initialPassword")}
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
                    {t("initialPasswordHint")}
                  </p>
                </div>

                <button className="button" type="submit">
                  {t("sendInvitation")}
                </button>
              </form>
            </Card>
          ) : (
            <Card title={t("inviteSomeone")} subtitle={t("ownerAdminOnly")}>
              <p className="small muted">
                {t("canSeeNotChange")}
              </p>
            </Card>
          )}
        </div>
      </>
    );
  } catch (err) {
    const message = err instanceof ApiError ? err.message : t("couldNotLoadUsers");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("usersTitle")}</h1>
        </header>
        <ErrorNote title={t("couldNotLoadUsers")} detail={message} />
      </>
    );
  }
}
