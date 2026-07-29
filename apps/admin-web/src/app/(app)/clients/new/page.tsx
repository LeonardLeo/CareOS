import Link from "next/link";
import { Card } from "@/components/ui";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function NewClientPage() {
  const session = await getSession();
  if (!session) return null;

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Add client</h1>
          <p className="page-subtitle">
            Date of birth and street address are encrypted before they are stored. Coordinates
            are held separately and coarsely, because the visit geofence rule computes against
            them.
          </p>
        </div>
        <Link className="button button--secondary" href="/clients">
          Cancel
        </Link>
      </header>

      <Card title="Client details">
        <form method="post" action="/api/clients" style={{ maxWidth: "34rem" }}>
          <div className="field">
            <label className="field__label" htmlFor="legal_name">
              Legal name
            </label>
            <input className="field__input" id="legal_name" name="legal_name" required />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="dob">
              Date of birth
            </label>
            <input className="field__input" id="dob" name="dob" type="date" />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="address">
              Street address
            </label>
            <input className="field__input" id="address" name="address" />
          </div>

          <div className="row" style={{ gap: "var(--space-4)", alignItems: "flex-start" }}>
            <div className="field" style={{ flex: 1 }}>
              <label className="field__label" htmlFor="geo_lat">
                Latitude
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
                Longitude
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
              Service state
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
              Selects the EVV aggregator and the compliance rule set that apply.
            </p>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="primary_payer_type">
              Primary payer
            </label>
            <select className="field__input" id="primary_payer_type" name="primary_payer_type">
              <option value="medicaid_waiver">Medicaid waiver</option>
              <option value="medicare_advantage">Medicare Advantage</option>
              <option value="private_pay">Private pay</option>
              <option value="other">Other</option>
            </select>
            <p className="small muted">
              Publicly-funded payers require a cleared OIG/GSA exclusion check before any
              caregiver can be assigned.
            </p>
          </div>

          <button className="button" type="submit">
            Create client
          </button>
        </form>
      </Card>
    </>
  );
}
