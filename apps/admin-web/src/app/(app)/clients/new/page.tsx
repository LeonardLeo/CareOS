import Link from "next/link";
import { Card } from "@/components/ui";
import { translatorFor } from "@/lib/i18n";
import { getLocale } from "@/lib/locale";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function NewClientPage() {
  const session = await getSession();
  if (!session) return null;
  const t = translatorFor(await getLocale());

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">{t("addClient")}</h1>
          <p className="page-subtitle">
            {t("newClientSubtitle")}
          </p>
        </div>
        <Link className="button button--secondary" href="/clients">
          {t("cancel")}
        </Link>
      </header>

      <Card title={t("clientDetails")}>
        <form method="post" action="/api/clients" style={{ maxWidth: "34rem" }}>
          <div className="field">
            <label className="field__label" htmlFor="legal_name">
              {t("clientName")}
            </label>
            <input className="field__input" id="legal_name" name="legal_name" required />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="dob">
              {t("clientDob")}
            </label>
            <input className="field__input" id="dob" name="dob" type="date" />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="address">
              {t("streetAddress")}
            </label>
            <input className="field__input" id="address" name="address" />
          </div>

          <div className="row" style={{ gap: "var(--space-4)", alignItems: "flex-start" }}>
            <div className="field" style={{ flex: 1 }}>
              <label className="field__label" htmlFor="geo_lat">
                {t("latitude")}
              </label>
              <input
                className="field__input"
                id="geo_lat"
                name="geo_lat"
                type="number"
                step="0.000001"
                min="-90"
                max="90"
              />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label className="field__label" htmlFor="geo_lng">
                {t("longitude")}
              </label>
              <input
                className="field__input"
                id="geo_lng"
                name="geo_lng"
                type="number"
                step="0.000001"
                min="-180"
                max="180"
              />
            </div>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="service_state">
              {t("serviceState")}
            </label>
            <input
              className="field__input"
              id="service_state"
              name="service_state"
              maxLength={2}
              minLength={2}
              placeholder="NY"
              required
            />
            <p className="small muted">
              {t("serviceStateHint")}
            </p>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="primary_payer_type">
              {t("primaryPayer")}
            </label>
            <select className="field__input" id="primary_payer_type" name="primary_payer_type">
              <option value="medicaid_waiver">{t("payerMedicaidWaiver")}</option>
              <option value="medicare_advantage">{t("payerMedicareAdvantage")}</option>
              <option value="private_pay">{t("payerPrivatePay")}</option>
              <option value="other">{t("payerOther")}</option>
            </select>
            <p className="small muted">
              {t("primaryPayerHint")}
            </p>
          </div>

          <button className="button" type="submit">
            {t("createClient")}
          </button>
        </form>
      </Card>
    </>
  );
}
