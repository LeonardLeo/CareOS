/**
 * Who can open this console.
 *
 * Readable by both operator roles and editable by one. That asymmetry is the same as the
 * agency Users screen and exists for the same reason: "who holds this access" is the first
 * question of any access review, and a list only the people who can change it may read makes
 * the review depend on the reviewer being one of them.
 *
 * There is no way to add the *first* operator here, by design — creating one requires being
 * one. That account is bootstrapped with database access
 * (`python -m careos.scripts.create_platform_operator`), which whoever stands the system up
 * has and nobody on the internet does. Everyone after them is created here, so the creation
 * has an actor and an audit row.
 */

import { Card, EmptyState, ErrorNote, SeverityBadge, formatDate, formatDateTime } from "@/components/ui";
import { ApiError, platformApi } from "@/lib/api";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getPlatformSession } from "@/lib/platform-session";

export const dynamic = "force-dynamic";

export default async function PlatformOperatorsPage({
  searchParams,
}: {
  searchParams: Promise<{ created?: string; disabled?: string; enabled?: string; error?: string }>;
}) {
  const session = await getPlatformSession();
  if (!session) return null;
  const locale = await getLocale();
  const t = translatorFor(locale);
  const { created, disabled, enabled, error } = await searchParams;

  let operators;
  try {
    operators = await platformApi.operators(session.token);
  } catch (err) {
    const detail = err instanceof ApiError ? err.message : t("somethingWentWrong");
    return (
      <>
        <header className="page-header">
          <h1 className="page-title">{t("platformOperatorsTitle")}</h1>
        </header>
        <ErrorNote title={t("platformCouldNotLoad")} detail={detail} />
      </>
    );
  }

  const canAdminister = session.role === "platform_admin";

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">{t("platformOperatorsTitle")}</h1>
          <p className="page-subtitle">{t("platformOperatorsSubtitle")}</p>
        </div>
      </header>

      {created && (
        <div className="notice">
          <SeverityBadge severity="good">{t("platformOperatorCreated")}</SeverityBadge>
          <span>{t("platformOperatorCreatedNote")}</span>
        </div>
      )}
      {disabled && (
        <div className="notice">
          <SeverityBadge severity="good">{t("platformOperatorDisabled")}</SeverityBadge>
          <span>{t("platformOperatorDisabledNote")}</span>
        </div>
      )}
      {enabled && (
        <div className="notice">
          <SeverityBadge severity="good">{t("platformOperatorEnabled")}</SeverityBadge>
          <span>{t("platformOperatorEnabledNote")}</span>
        </div>
      )}
      {error && <ErrorNote title={t("platformActionFailed")} detail={error} />}

      <div className="grid-2">
        <Card title={t("platformOperatorsTitle")} subtitle={t("platformOperatorsSubtitle")}>
          {operators.length === 0 ? (
            <EmptyState
              title={t("platformNoOperators")}
              detail={t("platformNoOperatorsDetail")}
            />
          ) : (
            <div className="stack">
              {operators.map((operator) => (
                <div key={operator.id} className="userrow">
                  <div className="userrow__main">
                    <div className="userrow__email">
                      {operator.display_name}
                      {operator.id === session.operatorId && (
                        <span className="userrow__you">{t("you")}</span>
                      )}
                    </div>
                    <div className="small muted">
                      {operator.email} ·{" "}
                      {t(
                        operator.role === "platform_admin"
                          ? "platformOperatorRoleAdmin"
                          : "platformOperatorRoleSupport",
                      )}{" "}
                      · {formatDate(operator.created_at)}
                      {!operator.mfa_enrolled && (
                        <>
                          {" · "}
                          <span className="userrow__warn">{t("platformMfaNotEnrolled")}</span>
                        </>
                      )}
                    </div>
                    <div className="small muted">
                      {operator.last_login_at
                        ? t("platformLastSignIn", {
                            when: formatDateTime(operator.last_login_at),
                          })
                        : t("platformNeverSignedIn")}
                    </div>
                    {operator.disabled_reason && (
                      <div className="small userrow__revoked">
                        {t("disabledBecause", { reason: operator.disabled_reason })}
                      </div>
                    )}
                  </div>

                  {canAdminister && (
                    <div className="userrow__actions">
                      {operator.status === "suspended" ? (
                        <form
                          method="post"
                          action="/platform/api/operators/enable"
                          className="userrow__form"
                        >
                          <input type="hidden" name="operator_id" value={operator.id} />
                          <button className="button button--small button--secondary" type="submit">
                            {t("platformEnableOperator")}
                          </button>
                        </form>
                      ) : (
                        operator.id !== session.operatorId && (
                          // Hidden for yourself because the API refuses it: an operator who
                          // disabled their own account would need database access to undo it.
                          <form
                            method="post"
                            action="/platform/api/operators/disable"
                            className="userrow__form"
                          >
                            <input type="hidden" name="operator_id" value={operator.id} />
                            <label
                              className="hidden-label"
                              htmlFor={`operator-reason-${operator.id}`}
                            >
                              {t("disableReasonLabel", { email: operator.email })}
                            </label>
                            <input
                              className="field__input field__input--compact"
                              id={`operator-reason-${operator.id}`}
                              name="reason"
                              placeholder={t("reasonRecorded")}
                              minLength={3}
                              required
                            />
                            <button className="button button--small button--danger" type="submit">
                              {t("platformDisableOperator")}
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
          <Card title={t("platformAddOperator")} subtitle={t("platformAddOperatorSubtitle")}>
            <form method="post" action="/platform/api/operators/create">
              <div className="field">
                <label className="field__label" htmlFor="display_name">
                  {t("platformOperatorName")}
                </label>
                <input
                  className="field__input"
                  id="display_name"
                  name="display_name"
                  type="text"
                  autoComplete="off"
                  required
                />
              </div>

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
                <select
                  className="field__input"
                  id="role"
                  name="role"
                  defaultValue="platform_support"
                >
                  {/* Support first and pre-selected. The role that can take a customer
                      offline should be the deliberate choice, not the default. */}
                  <option value="platform_support">{t("platformOperatorRoleSupport")}</option>
                  <option value="platform_admin">{t("platformOperatorRoleAdmin")}</option>
                </select>
              </div>

              <div className="field">
                <label className="field__label" htmlFor="initial_password">
                  {t("initialPassword")}
                </label>
                <input
                  className="field__input"
                  id="initial_password"
                  name="initial_password"
                  type="text"
                  minLength={16}
                  required
                />
                <p className="small muted">{t("platformOperatorPasswordHint")}</p>
              </div>

              <button className="button" type="submit">
                {t("platformCreateOperator")}
              </button>
            </form>
          </Card>
        ) : (
          <Card title={t("platformAddOperator")} subtitle={t("platformOperatorAdminOnly")}>
            <p className="small muted">{t("platformOperatorReadOnlyNote")}</p>
          </Card>
        )}
      </div>
    </>
  );
}
