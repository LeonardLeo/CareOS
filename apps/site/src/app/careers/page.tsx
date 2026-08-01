import type { Metadata } from "next";

import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";
import { CONTACT_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Careers",
  description:
    "How we work, what we are hiring for, and what a first week looks like. Small team, real constraints, no growth-stage theatre.",
};

/**
 * Careers.
 *
 * Every role says what is hard about it. A job page that only lists what is exciting selects
 * for people who leave in four months, and in a team this size that is the most expensive
 * mistake available.
 */

const ROLES = [
  {
    title: "Senior backend engineer",
    where: "Remote (US timezones)",
    body: "Own the compliance surface: EVV adapters, exclusion screening, the reconciliation control. Python, FastAPI, Postgres — with Row-Level Security doing real work rather than decorating a diagram.",
    hard: "Much of this is regulation translated into code. You will read a state's EVV specification and a CMS rule before you write anything, and the interesting part is not the framework.",
  },
  {
    title: "Product engineer, caregiver app",
    where: "Remote (US timezones)",
    body: "The highest-stakes surface in the product and the least forgiving. Offline-first sync, an outbox that must never double-send, and a UI used one-handed in a doorway.",
    hard: "The success criterion is not a design review. It is a caregiver with one bar of signal on a five-year-old Android who clocks in and never thinks about it again.",
  },
  {
    title: "Founding designer",
    where: "Remote (US timezones)",
    body: "Two audiences with opposite needs — a coordinator with forty tabs open and a caregiver in someone's home — and one system that has to serve both without feeling like two products.",
    hard: "Low-literacy and low-bandwidth are hard constraints, not accessibility checkboxes to satisfy at the end. Several of your best ideas will not survive them.",
  },
  {
    title: "Clinical operations lead",
    where: "Remote (US timezones)",
    body: "A home care background is required: you have run scheduling or compliance at an agency. You know what a state auditor asks for and what a coordinator actually does at 6am when someone calls out.",
    hard: "You would be the only person here who has done the job the software is for, which means being listened to and also being the one who has to say no.",
  },
];

const HOW = [
  {
    title: "Small on purpose, for now",
    body: "Hiring ahead of a first customer is how a company ends up building the wrong thing efficiently. The team grows when a real agency tells us what is missing.",
  },
  {
    title: "Written before spoken",
    body: "Decisions live in the repository next to the code they constrain, with the reasoning attached. If you cannot write down why, it is not a decision yet.",
  },
  {
    title: "Run it before you claim it",
    body: "Every significant feature here was verified by using it, not by reading it. That discipline has caught defects a green test suite missed in five consecutive increments, and it is not negotiable.",
  },
  {
    title: "Say what is broken",
    body: "The build status in this repository lists open defects and unfinished work by name. Nobody is punished for adding to it and the fastest way to lose trust is to quietly leave something off.",
  },
];

export default function CareersPage() {
  return (
    <>
      <PageHero
        eyebrow="Careers"
        title="Four roles, and what is hard about each."
        lede="We are pre-revenue and pre-launch. If that is disqualifying, it should be — and better now than in month three."
      />

      <section className="section section--tight">
        <div className="shell">
          <div className="cards">
            {ROLES.map((role, index) => (
              <Reveal key={role.title} className="card" delay={index * 70}>
                <span className="tag">{role.where}</span>
                <h2 className="display d3">{role.title}</h2>
                <p style={{ color: "var(--ink-2)", fontSize: "0.97rem" }}>{role.body}</p>
                <p
                  style={{
                    fontSize: "0.94rem",
                    color: "var(--ink-2)",
                    borderLeft: "2px solid var(--signal)",
                    paddingLeft: "var(--s3)",
                  }}
                >
                  <strong style={{ color: "var(--ink)" }}>The hard part. </strong>
                  {role.hard}
                </p>
                <p style={{ marginTop: "auto", paddingTop: "var(--s2)" }}>
                  <a
                    className="textlink"
                    href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(role.title)}`}
                  >
                    Apply <span className="arrow">→</span>
                  </a>
                </p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section section--sunken">
        <div className="shell">
          <div className="split">
            <Reveal className="split__aside">
              <p className="eyebrow">How we work</p>
              <h2 className="display d2" style={{ marginTop: "var(--s4)" }}>
                Four habits, held to.
              </h2>
            </Reveal>
            <div className="steps">
              {HOW.map((item, index) => (
                <Reveal key={item.title} className="step" delay={index * 60}>
                  <div>
                    <h3 className="display" style={{ fontSize: "1.2rem" }}>
                      {item.title}
                    </h3>
                    <p style={{ marginTop: "var(--s2)", color: "var(--ink-2)" }}>{item.body}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="shell shell--narrow" style={{ textAlign: "center" }}>
          <Reveal>
            <h2 className="display d2" style={{ marginInline: "auto", maxWidth: "22ch" }}>
              Nothing above fits, and you still want in?
            </h2>
            <p className="lede" style={{ marginInline: "auto", marginTop: "var(--s4)" }}>
              Write to us with what you would want to own. We would rather hear from the right
              person about the wrong role than the other way round.
            </p>
            <div style={{ marginTop: "var(--s6)" }}>
              <a
                className="btn btn--accent"
                href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Working at CareOS")}`}
              >
                Write to us <span className="arrow">→</span>
              </a>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
