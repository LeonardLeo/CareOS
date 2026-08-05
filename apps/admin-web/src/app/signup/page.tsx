/**
 * Self-serve sign-up.
 *
 * **Why it lives in the admin console and not on the marketing site.** `apps/site` is a
 * static export with no server and no third-party request of any kind — that is what lets it
 * stay up when the API is down and say so. A sign-up form there would have to call the API
 * from the browser, which would end the property, and it would have to receive a token in
 * page JavaScript, which this product does not do. The console already owns the pattern that
 * makes that safe: the form posts to a route handler, the token goes straight into an
 * httpOnly cookie, and nothing security-relevant reaches the browser. So the site links here.
 *
 * **Three steps rather than one form**, and the ordering is the design. Step one is who you
 * are, step two is what you do — both are agency configuration that decides which compliance
 * rules apply, and both are recoverable from a draft cookie if the tab is closed. Step three
 * is the owner's password, and it is last precisely so it never lands in that cookie.
 *
 * Everything works without JavaScript. Each step is a plain form post to a route handler that
 * validates, stores, and redirects — so a slow connection, a blocked script, or a screen
 * reader driving the page all behave the same way.
 */

import Link from "next/link";
import { redirect } from "next/navigation";
import { LanguageSwitcher } from "@/components/language-switcher";
import { ErrorNote } from "@/components/ui";
import { type StringKey, type Translator, translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";
import {
  EMPTY_DRAFT,
  PAYER_TYPES,
  SERVICE_LINES,
  US_STATES,
  getSignupDraft,
} from "@/lib/signup-draft";

export const dynamic = "force-dynamic";

const TOTAL_STEPS = 3;

/** Error codes a route handler may redirect back with, mapped to their string keys. */
const ERROR_KEYS: Record<string, StringKey> = {
  name: "signUpErrorNoName",
  states: "signUpErrorNoStates",
  lines: "signUpErrorNoServiceLines",
  payers: "signUpErrorNoPayers",
  mismatch: "signUpErrorPasswordMismatch",
  short: "signUpErrorPasswordShort",
  taken: "signUpErrorEmailTaken",
  invalid: "signUpErrorInvalid",
  limited: "signUpErrorRateLimited",
  expired: "signUpErrorExpired",
  unavailable: "signUpErrorUnavailable",
};

/**
 * Keyed by the literal unions rather than by `string`.
 *
 * `noUncheckedIndexedAccess` is on, so a `Record<string, …>` lookup is `… | undefined` and
 * every call site would need a fallback for a case that cannot happen. Typing the maps
 * against the closed lists instead makes an option added to one and forgotten in the other a
 * compile error — which is the same guarantee `ES` gets from being a `Record<StringKey, …>`.
 */
const SERVICE_LINE_KEYS: Record<(typeof SERVICE_LINES)[number], StringKey> = {
  home_care: "serviceLineHomeCare",
  home_health: "serviceLineHomeHealth",
  hospice: "serviceLineHospice",
};

const PAYER_KEYS: Record<(typeof PAYER_TYPES)[number], StringKey> = {
  medicaid_waiver: "payerMedicaidWaiver",
  medicare_advantage: "payerMedicareAdvantage",
  private_pay: "payerPrivatePay",
  other: "payerOther",
};

type ServiceLine = (typeof SERVICE_LINES)[number];
type PayerType = (typeof PAYER_TYPES)[number];

const isServiceLine = (value: string): value is ServiceLine =>
  (SERVICE_LINES as readonly string[]).includes(value);

const isPayerType = (value: string): value is PayerType =>
  (PAYER_TYPES as readonly string[]).includes(value);

export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ step?: string; error?: string }>;
}) {
  // Someone already signed in has an agency. Sending them to the dashboard rather than
  // letting them create a second one is the same courtesy `/login` does.
  if (await getSession()) redirect("/dashboard");

  const { step: rawStep, error } = await searchParams;
  const locale = await getLocale();
  const t = translatorFor(locale);

  const draft = (await getSignupDraft()) ?? EMPTY_DRAFT;
  // Steps are clamped rather than trusted, and a step nobody has the answers for falls back.
  // Deep-linking to step three with an empty draft would otherwise render a review of
  // nothing and then fail validation at the API, which is a worse way to learn the same fact.
  const requested = Number.parseInt(rawStep ?? "1", 10);
  const step = furthestReachable(draft, Number.isFinite(requested) ? requested : 1);
  // An unrecognised code renders no banner rather than the key itself. A redirect can only
  // carry one of these, so this is belt and braces against a handler being edited alone.
  const errorKey = error ? ERROR_KEYS[error] : undefined;

  return (
    <main className="login">
      <div className="login__panel login__panel--wide">
        <div className="login__brand">
          <span className="brand__mark" aria-hidden="true">
            C
          </span>
          <div>
            <h1 className="login__title">{t("signUpTitle")}</h1>
            <p className="login__subtitle">{t("stepOf", { current: step, total: TOTAL_STEPS })}</p>
          </div>
        </div>

        <Steps current={step} t={t} />

        {errorKey && <ErrorNote title={t("signUpFailedTitle")} detail={t(errorKey)} />}

        {step === 1 && <AgencyStep draft={draft} t={t} />}
        {step === 2 && <ServiceStep draft={draft} t={t} />}
        {step === 3 && <AccountStep draft={draft} t={t} />}

        <p className="small muted" style={{ marginTop: "var(--space-5)" }}>
          {t("haveAccount")}{" "}
          <Link href="/login">{t("signIn")}</Link>
        </p>

        <div style={{ marginTop: "var(--space-4)" }}>
          <LanguageSwitcher locale={locale} returnTo="/signup" />
        </div>
      </div>
    </main>
  );
}

/**
 * How far into the wizard this draft can honestly support.
 *
 * Not a security control — the API validates everything again — but it is what keeps the
 * review on step three from describing an agency the draft does not contain.
 */
function furthestReachable(
  draft: { legalName: string; serviceStates: string[]; serviceLines: string[]; payerTypes: string[] },
  requested: number,
): 1 | 2 | 3 {
  const hasAgency = draft.legalName.trim().length > 0 && draft.serviceStates.length > 0;
  const hasServices = draft.serviceLines.length > 0 && draft.payerTypes.length > 0;
  const ceiling = hasAgency ? (hasServices ? 3 : 2) : 1;
  const clamped = Math.min(Math.max(requested, 1), ceiling);
  return clamped as 1 | 2 | 3;
}

function Steps({ current, t }: { current: number; t: Translator }) {
  const labels: StringKey[] = ["stepAgencyLabel", "stepServiceLabel", "stepAccountLabel"];
  return (
    <ol className="steps">
      {labels.map((label, index) => {
        const number = index + 1;
        const state = number < current ? "done" : number === current ? "current" : "todo";
        return (
          <li key={label} className="steps__item" data-state={state}>
            {/* The number is decoration: `aria-current` and the visible label carry the
                state, and a screen reader announcing "1 Agency 2 Services" as content would
                read the ordinal twice. */}
            <span className="steps__marker" aria-hidden="true">
              {number}
            </span>
            <span aria-current={state === "current" ? "step" : undefined}>{t(label)}</span>
          </li>
        );
      })}
    </ol>
  );
}

function AgencyStep({
  draft,
  t,
}: {
  draft: { legalName: string; serviceStates: string[] };
  t: Translator;
}) {
  return (
    <form method="post" action="/api/signup/agency">
      <h2 className="signup__heading">{t("stepAgencyTitle")}</h2>
      <p className="small muted signup__lede">{t("stepAgencySubtitle")}</p>

      <div className="field">
        <label className="field__label" htmlFor="legal_name">
          {t("agencyLegalName")}
        </label>
        <input
          className="field__input"
          id="legal_name"
          name="legal_name"
          type="text"
          autoComplete="organization"
          defaultValue={draft.legalName}
          maxLength={300}
          required
        />
        <p className="small muted">{t("agencyLegalNameHint")}</p>
      </div>

      <fieldset className="fieldset">
        <legend className="field__label">{t("statesLegend")}</legend>
        <p className="small muted">{t("statesHint")}</p>
        <div className="checkgrid checkgrid--dense">
          {US_STATES.map((code) => (
            <label className="checkgrid__item" key={code} htmlFor={`state-${code}`}>
              <input
                type="checkbox"
                id={`state-${code}`}
                name="service_states"
                value={code}
                defaultChecked={draft.serviceStates.includes(code)}
              />
              <span>{code}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <button className="button" type="submit" style={{ width: "100%" }}>
        {t("continueStep")}
      </button>
    </form>
  );
}

function ServiceStep({
  draft,
  t,
}: {
  draft: { serviceLines: string[]; payerTypes: string[] };
  t: Translator;
}) {
  return (
    <form method="post" action="/api/signup/services">
      <h2 className="signup__heading">{t("stepServiceTitle")}</h2>
      <p className="small muted signup__lede">{t("stepServiceSubtitle")}</p>

      <fieldset className="fieldset">
        <legend className="field__label">{t("serviceLinesLegend")}</legend>
        <p className="small muted">{t("serviceLinesHint")}</p>
        <div className="checkgrid">
          {SERVICE_LINES.map((line) => (
            <label className="checkgrid__item" key={line} htmlFor={`line-${line}`}>
              <input
                type="checkbox"
                id={`line-${line}`}
                name="service_lines"
                value={line}
                defaultChecked={draft.serviceLines.includes(line)}
              />
              <span>{t(SERVICE_LINE_KEYS[line])}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="fieldset">
        <legend className="field__label">{t("payerTypesLegend")}</legend>
        <p className="small muted">{t("payerTypesHint")}</p>
        <div className="checkgrid">
          {PAYER_TYPES.map((payer) => (
            <label className="checkgrid__item" key={payer} htmlFor={`payer-${payer}`}>
              <input
                type="checkbox"
                id={`payer-${payer}`}
                name="payer_types"
                value={payer}
                defaultChecked={draft.payerTypes.includes(payer)}
              />
              <span>{t(PAYER_KEYS[payer])}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="signup__actions">
        <Link className="button button--secondary" href="/signup?step=1">
          {t("backStep")}
        </Link>
        <button className="button" type="submit">
          {t("continueStep")}
        </button>
      </div>
    </form>
  );
}

function AccountStep({
  draft,
  t,
}: {
  draft: {
    legalName: string;
    serviceStates: string[];
    serviceLines: string[];
    payerTypes: string[];
  };
  t: Translator;
}) {
  return (
    <form method="post" action="/api/signup">
      <h2 className="signup__heading">{t("stepAccountTitle")}</h2>
      <p className="small muted signup__lede">{t("stepAccountSubtitle")}</p>

      {/* The review sits above the fields being filled in, so the last thing someone reads
          before committing is what they are committing to rather than a password rule. */}
      <div className="plan-summary">
        <p className="field__label">{t("reviewTitle")}</p>
        <dl className="summary">
          <dt>{t("agencyLegalName")}</dt>
          <dd>{draft.legalName}</dd>
          <dt>{t("statesLegend")}</dt>
          <dd className="mono">{draft.serviceStates.join(", ")}</dd>
          <dt>{t("serviceLinesLegend")}</dt>
          <dd>
            {draft.serviceLines
              .filter(isServiceLine)
              .map((line) => t(SERVICE_LINE_KEYS[line]))
              .join(", ")}
          </dd>
          <dt>{t("payerTypesLegend")}</dt>
          <dd>
            {draft.payerTypes
              .filter(isPayerType)
              .map((payer) => t(PAYER_KEYS[payer]))
              .join(", ")}
          </dd>
        </dl>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="owner_email">
          {t("ownerEmailLabel")}
        </label>
        <input
          className="field__input"
          id="owner_email"
          name="owner_email"
          type="email"
          autoComplete="username"
          required
        />
        <p className="small muted">{t("ownerEmailHint")}</p>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="owner_password">
          {t("ownerPasswordLabel")}
        </label>
        <input
          className="field__input"
          id="owner_password"
          name="owner_password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          required
        />
        <p className="small muted">{t("ownerPasswordHint")}</p>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="confirm_password">
          {t("confirmPasswordLabel")}
        </label>
        <input
          className="field__input"
          id="confirm_password"
          name="confirm_password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          required
        />
      </div>

      <div className="signup__actions">
        <Link className="button button--secondary" href="/signup?step=2">
          {t("backStep")}
        </Link>
        <button className="button" type="submit">
          {t("createAgencyAction")}
        </button>
      </div>
    </form>
  );
}
