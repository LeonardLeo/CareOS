import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage } from "@/components/legal-page";
import { CONTACT_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Availability and support",
  description:
    "What CareOS commits to today, which is less than a service level agreement, said plainly rather than implied.",
};

/**
 * Availability and support.
 *
 * The temptation on a page like this is to publish a number — 99.9% — because every competitor
 * does. We hold that number as a design target and do not yet operate against it, because the
 * pager receivers are placeholders: an alert reaches a log line rather than a person. Publishing
 * an SLA we cannot detect a breach of would be the dishonest option, so the page says which one
 * this is.
 */

const SEVERITIES = [
  {
    level: "Urgent",
    meaning:
      "Caregivers cannot clock in, or the schedule is unreachable. Care is happening and cannot be recorded.",
    response: "Within 1 hour, any day, any time",
  },
  {
    level: "High",
    meaning:
      "A core workflow is broken for the whole agency — visits will not save, exports fail, EVV is not transmitting.",
    response: "Within 4 business hours",
  },
  {
    level: "Normal",
    meaning: "Something is wrong but there is a way around it.",
    response: "Within 1 business day",
  },
  {
    level: "Low",
    meaning: "A question, a request, or an annoyance.",
    response: "Within 3 business days",
  },
];

export default function AvailabilityPage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="Availability and support"
      lede="Clock-in is time-sensitive in a way most software is not: a caregiver standing in a doorway cannot wait for a maintenance window. This page says what we commit to today, and it is less than an SLA."
      updated="31 July 2026"
    >
      <h2>We do not offer a service level agreement yet</h2>
      <p>
        The system is designed to a 99.9% availability target on the two paths that matter —
        scheduling and electronic visit verification clock-in. Designed to is not the same as
        operated against, and the gap is specific rather than vague: alerting rules, routing, and
        suppression are built and tested, but the receivers are placeholders. An alert currently
        reaches a log line in a container rather than a person&rsquo;s phone.
      </p>
      <p>
        Until that is wired to a real pager, publishing an availability guarantee would mean
        promising something we could not reliably notice ourselves breaking. So we do not. When it
        is wired, this page changes and the commitment becomes contractual rather than a number on
        a marketing site.
      </p>

      <h2>What happens when something is down</h2>
      <p>
        Some of this is already built into how the product behaves, and it is worth knowing
        because it changes what an outage costs you.
      </p>
      <ul>
        <li>
          <strong>The caregiver app works offline.</strong> A caregiver whose phone has no signal
          — or whose signal is fine while our API is not — can still clock in, complete tasks, and
          clock out. The visit is held on the device and syncs when the connection returns, with
          the original timestamps intact rather than the time of the sync.
        </li>
        <li>
          <strong>EVV transmission is queued, not fired and forgotten.</strong> If the
          state&rsquo;s aggregator is unavailable, the visit sits in an outbox and is retried.
          Nothing is lost because a third party had an outage, and nightly reconciliation reports
          anything still unacknowledged.
        </li>
        <li>
          <strong>A rejected transmission becomes a compliance exception</strong>, which is a
          thing on a screen with a reason attached, not an error in a log nobody reads.
        </li>
      </ul>

      <h2>Support</h2>
      <p>
        Today, support is the people who build it. That has an obvious limit and one real
        advantage, which is that the person answering can fix the thing. Reach us at{" "}
        <a className="textlink" href={`mailto:${CONTACT_EMAIL}`}>
          {CONTACT_EMAIL}
        </a>
        ; agencies under contract get a direct route and an out-of-hours number.
      </p>
      <p>These are the response targets we hold ourselves to. They are targets, not warranties.</p>
      <div className="scroller">
        <table>
          <thead>
            <tr>
              <th scope="col">Severity</th>
              <th scope="col">What it means</th>
              <th scope="col">First response</th>
            </tr>
          </thead>
          <tbody>
            {SEVERITIES.map((row) => (
              <tr key={row.level}>
                <th scope="row">{row.level}</th>
                <td>{row.meaning}</td>
                <td>{row.response}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Business hours are 9am to 6pm Eastern, Monday to Friday, excluding US federal holidays.
        Urgent is deliberately not restricted to those hours, because care is not.
      </p>

      <h2>Maintenance</h2>
      <p>
        Planned maintenance that could interrupt clock-in is announced at least five business days
        ahead and scheduled between 1am and 5am Eastern on a weekend, which is the quietest window
        for home care rather than the quietest window generally. Changes that carry no
        interruption ship whenever they are ready and are not announced individually.
      </p>
      <p>
        Emergency maintenance — a security fix that cannot wait — happens when it has to, and we
        tell you during rather than afterwards.
      </p>

      <h2>Incidents</h2>
      <p>
        For anything that interrupted your agency, you get a written account: what happened, what
        it affected, what we did, and what changes so it does not recur. It goes out within five
        business days of resolution whether or not you asked, and it does not omit the part where
        the cause was ours.
      </p>
      <p>
        Where an incident involved protected health information, the notification commitments on
        the{" "}
        <Link className="textlink" href="/legal/hipaa/">
          HIPAA page
        </Link>{" "}
        apply and are faster.
      </p>

      <h2>Your data, if we stop</h2>
      <p>
        Export is a feature of the product rather than a favour we do on the way out. An agency can
        export everything it holds, at any time, without asking us. That is deliberate: the point
        at which you most need your records is the point at which a vendor is least able or least
        willing to help.
      </p>
    </LegalPage>
  );
}
