import type { Metadata } from "next";

import { LegalPage } from "@/components/legal-page";
import { SECURITY_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Subprocessors",
  description:
    "Every company that could touch protected health information, what it does, and where. Published because an agency's compliance officer will ask for it.",
};

/**
 * The subprocessor list.
 *
 * Published because `06_Compliance_and_Regulatory_Requirements.md` requires an agency to be
 * able to see it, and because the first question a competent compliance officer asks is who
 * else touches the data. The honest answer today is short, and saying so is more useful than
 * a page of prospective vendors.
 */

const CURRENT = [
  {
    name: "Amazon Web Services",
    purpose: "Hosting, managed database, object storage, secrets",
    region: "United States",
    baa: "Required before any PHI is processed",
  },
];

const PLANNED = [
  {
    name: "EVV data aggregator (New York)",
    purpose: "Transmitting electronic visit verification to the state",
    region: "United States",
    baa: "Required before the first production transmission",
  },
  {
    name: "Background-check vendor",
    purpose: "OIG and GSA exclusion screening, criminal history",
    region: "United States",
    baa: "Required before any identity data is sent",
  },
  {
    name: "Identity provider",
    purpose: "Authentication for agency staff",
    region: "United States",
    baa: "Required before production sign-in moves to it",
  },
];

function Table({
  rows,
}: {
  rows: readonly { name: string; purpose: string; region: string; baa: string }[];
}) {
  return (
    <div className="scroller">
      <table>
        <thead>
          <tr>
            <th scope="col">Company</th>
            <th scope="col">Purpose</th>
            <th scope="col">Region</th>
            <th scope="col">Agreement</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name}>
              <th scope="row">{row.name}</th>
              <td>{row.purpose}</td>
              <td>{row.region}</td>
              <td>{row.baa}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SubprocessorsPage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="Subprocessors"
      lede="Every company that could touch protected health information, what it does, and where. Today the list is short, and that is a fact about our stage rather than a claim about our rigour."
      updated="31 July 2026"
    >
      <h2>In use today</h2>
      <p>
        No agency data is in production yet, so this list describes what is provisioned rather
        than what is processing.
      </p>
      <Table rows={CURRENT} />

      <h2>Named, not yet engaged</h2>
      <p>
        Each of these becomes a subprocessor at a known point, and in every case the
        countersigned business associate agreement comes before the first byte, not after the
        integration works.
      </p>
      <Table rows={PLANNED} />

      <h2>How this list changes</h2>
      <p>
        Agencies under contract are told before a new subprocessor begins handling their data,
        with enough notice to object. We do not add one and update this page afterwards.
      </p>
      <p>
        Questions, or a request for the underlying agreements, go to{" "}
        <a className="textlink" href={`mailto:${SECURITY_EMAIL}`}>
          {SECURITY_EMAIL}
        </a>
        .
      </p>
    </LegalPage>
  );
}
