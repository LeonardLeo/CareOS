/**
 * The page people are sent to before they have an account.
 *
 * Every number on it comes from `docs/01_Product_Vision_and_Executive_Summary.md` Section 2
 * and carries its source in the markup. That is not decoration: this is a page aimed at
 * agency owners, and an agency owner can tell the difference between a statistic with a
 * citation and one without. It also means the page cannot drift from the document — if a
 * figure is re-verified there, it gets changed here, and the source line makes the omission
 * obvious if it is not.
 *
 * What the page deliberately does not claim: nothing about customers, results, or scale.
 * There are none yet. A landing page for a pre-launch product that invents social proof is
 * the first thing a design partner will catch, and the credibility it costs is not
 * recoverable.
 */

const SIGN_IN_URL = "https://app.careos.example/login";
const CONTACT_EMAIL = "hello@careos.example";

/** Each row is a day; each bar is a visit positioned by time of day. `gap` means unfilled. */
const COVERAGE: { day: string; bars: { start: number; width: number; gap?: boolean }[] }[] = [
  { day: "Mon", bars: [{ start: 8, width: 18 }, { start: 30, width: 14 }, { start: 62, width: 20 }] },
  { day: "Tue", bars: [{ start: 6, width: 22 }, { start: 34, width: 16, gap: true }, { start: 64, width: 18 }] },
  { day: "Wed", bars: [{ start: 10, width: 16 }, { start: 30, width: 20 }, { start: 58, width: 24 }] },
  { day: "Thu", bars: [{ start: 8, width: 20 }, { start: 32, width: 14 }, { start: 54, width: 18, gap: true }] },
  { day: "Fri", bars: [{ start: 6, width: 24 }, { start: 36, width: 18 }, { start: 60, width: 22 }] },
  { day: "Sat", bars: [{ start: 12, width: 20, gap: true }, { start: 44, width: 16 }] },
];

const FIGURES = [
  {
    value: "63.3%",
    critical: true,
    label: "of agencies turned down cases in 2023 because they could not staff them",
    source: "Activated Insights Benchmarking Report",
  },
  {
    value: "79.2%",
    critical: true,
    label: "caregiver turnover in 2023, easing to roughly 75% in 2024",
    source: "Activated Insights Benchmarking Report",
  },
  {
    value: "$2,600",
    label: "to replace one caregiver — about $171,600 a year for an average agency",
    source: "Activated Insights Benchmarking Report",
  },
  {
    value: "12.8%",
    label: "of applicants were hired in 2023. The pipeline is not the problem; the process is",
    source: "Activated Insights Benchmarking Report",
  },
];

const PHASES = [
  {
    tag: "Phase 1 — building now",
    now: true,
    title: "AI Workforce Engine",
    body: "Solve the staffing crisis first, because every other problem an agency has is downstream of an unfilled shift.",
    items: [
      "Applicant sourcing, screening, and explainable ranking",
      "Sub-72-hour onboarding with parallel credential verification",
      "EVV-compliant, drive-time-aware scheduling",
      "Real-time gap detection and AI-assisted gap filling",
      "Offline-first caregiver app with EVV clock-in and clock-out",
    ],
  },
  {
    tag: "Phase 2",
    title: "Ambient documentation",
    body: "Eliminate after-hours charting, and catch a documentation gap before it becomes a denial.",
    items: [
      "Voice and ambient point-of-care notes, reviewed and signed",
      "Structured extraction into care-plan and billing fields",
      "Compliance copilot for survey readiness and PPS-rule risk",
      "Family and client portal",
    ],
  },
  {
    tag: "Phase 3",
    title: "Revenue engine",
    body: "Become the system of record for cash, not only for care.",
    items: [
      "EVV-verified visits into claims across Medicaid, MA, and private pay",
      "Eligibility checks, claim scrubbing, denial prevention",
      "Remittance, AR aging, payer-mix analytics",
      "Payroll integration and multi-location rollups",
    ],
  },
];

const FOUNDATIONS = [
  {
    term: "Tenant isolation in the database, not the application",
    detail: (
      <>
        Every table carries <code>FORCE ROW LEVEL SECURITY</code> and the application connects
        as a role with no <code>BYPASSRLS</code>. One agency cannot read another&rsquo;s data
        even if a query forgets to filter, because the database refuses rather than the code
        remembering.
      </>
    ),
  },
  {
    term: "EVV built in, not bolted on",
    detail: (
      <>
        The six federally required data elements are modelled as required fields, so an
        incomplete visit fails here rather than as a state rejection weeks later. State
        aggregators sit behind an adapter, and no adapter transmits production data until it
        has been validated against that vendor&rsquo;s sandbox.
      </>
    ),
  },
  {
    term: "Hiring AI you can audit",
    detail: (
      <>
        Ranking runs on a closed allowlist of operational signals. Protected attributes and
        their known proxies &mdash; ZIP code, graduation year, school, salary history &mdash;
        are refused by the scorer itself, and every score ships with the reasoning behind it.
        Scores stay hidden from decision-makers until a bias audit has run on real outcomes.
      </>
    ),
  },
  {
    term: "Offline is the normal case",
    detail: (
      <>
        Caregivers work in homes with no signal. Clock-in and clock-out queue on the device
        and sync when the phone finds a network, so a visit is never lost and never
        transmitted twice.
      </>
    ),
  },
  {
    term: "Every disclosure is recorded",
    detail: (
      <>
        Reading a client record, opening a schedule, exporting an agency&rsquo;s data, cutting
        off a user&rsquo;s access &mdash; each writes an audit row in the same transaction as
        the thing it describes. An audit trail that can be rolled back separately is not one.
      </>
    ),
  },
];

const AUDIENCE = [
  {
    role: "Owners and administrators",
    line: "Independent and regional agencies, roughly $2M–$50M in revenue, currently on a legacy EHR-style platform or on spreadsheets.",
  },
  {
    role: "Scheduling coordinators",
    line: "The people who find out at 6am that nobody is going to Mrs. Whitfield today, and have ninety minutes to fix it.",
  },
  {
    role: "Caregivers",
    line: "One screen, today's visits, a clock-in that works with no signal, and pay and hours they can see without calling the office.",
  },
  {
    role: "Clinical supervisors and billing",
    line: "Compliance exceptions surfaced before a payer finds them, and visit data that reaches a claim without re-keying.",
  },
];

export default function Home() {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>

      <header className="masthead">
        <div className="shell masthead__inner">
          <a className="brand" href="/">
            <span className="brand__mark" aria-hidden="true">
              C
            </span>
            CareOS
          </a>
          <nav className="masthead__nav" aria-label="Primary">
            <a className="masthead__link" href="#problem">
              The problem
            </a>
            <a className="masthead__link" href="#product">
              What we build
            </a>
            <a className="masthead__link" href="#foundations">
              How it is built
            </a>
            <a className="button button--small" href={SIGN_IN_URL}>
              Sign in
            </a>
          </nav>
        </div>
      </header>

      <main id="main">
        <section className="hero">
          <div className="shell">
            <p className="hero__eyebrow">
              <span className="hero__dot" aria-hidden="true" />
              Home care · Home health · Hospice
            </p>
            <h1>
              The shift you cannot fill is the revenue you <em>already lost</em>.
            </h1>
            <p className="hero__lede">
              Home-based care agencies turn down work every week for want of a caregiver, while
              the software they run on was built to document care after the fact. CareOS is the
              layer that fills the shift: recruiting, credentialing, and EVV-compliant
              scheduling in one system.
            </p>
            <div className="hero__actions">
              <a className="button" href={`mailto:${CONTACT_EMAIL}?subject=CareOS%20design%20partner`}>
                Become a design partner
              </a>
              <a className="button button--quiet" href="#product">
                See what we build
              </a>
            </div>
            <p className="hero__note">
              In active development. We are looking for a small number of agencies to build
              with, not to sell to.
            </p>

            <figure className="board">
              <div className="board__head">
                <span className="board__title">Coverage, next seven days</span>
                <span className="board__legend">
                  <span>
                    <i className="board__swatch board__swatch--filled" aria-hidden="true" />
                    Assigned
                  </span>
                  <span>
                    <i className="board__swatch board__swatch--gap" aria-hidden="true" />
                    Unfilled
                  </span>
                </span>
              </div>
              <div className="board__grid" aria-hidden="true">
                {COVERAGE.map((row) => (
                  <div className="board__row" key={row.day}>
                    <span className="board__day">{row.day}</span>
                    <span className="board__track">
                      {row.bars.map((bar, index) => (
                        <span
                          key={index}
                          className={`board__bar${bar.gap ? " board__bar--gap" : ""}`}
                          style={
                            {
                              "--start": `${bar.start}%`,
                              "--width": `${bar.width}%`,
                            } as React.CSSProperties
                          }
                        />
                      ))}
                    </span>
                  </div>
                ))}
              </div>
              {/* The written equivalent. A grid of coloured rectangles carries no meaning to a
                  screen reader, and describing it in an alt attribute of forty words would be
                  worse than saying the one thing it is for. */}
              <figcaption className="visually-hidden">
                An illustration of a week of scheduled visits, in which three shifts are
                unfilled.
              </figcaption>
            </figure>
          </div>
        </section>

        <section className="section section--sunken" id="problem">
          <div className="shell">
            <p className="section__eyebrow">The problem, in numbers</p>
            <h2 className="section__title">
              Agencies are not short of demand. They are short of people.
            </h2>
            <p className="section__lede">
              Ten thousand Americans turn 65 every day, and three quarters of adults over 50 want
              to age at home. The constraint is not the market. It is that the average agency
              cannot hire and onboard fast enough to say yes.
            </p>

            <div className="figures">
              {FIGURES.map((figure) => (
                <div className="figure" key={figure.value}>
                  <div
                    className={`figure__value${figure.critical ? " figure__value--critical" : ""}`}
                  >
                    {figure.value}
                  </div>
                  <p className="figure__label">{figure.label}</p>
                  <p className="figure__source">{figure.source}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="section" id="product">
          <div className="shell">
            <p className="section__eyebrow">What we build</p>
            <h2 className="section__title">Three layers on one data model.</h2>
            <p className="section__lede">
              Each phase is useful on its own, and each one is designed so the next extends the
              system rather than replacing it. The billing tables exist today, unused, so that a
              visit recorded this year can be traced onto a claim next year without a migration.
            </p>

            <div className="phases">
              {PHASES.map((phase) => (
                <article className={`phase${phase.now ? " phase--now" : ""}`} key={phase.title}>
                  <span className="phase__tag">{phase.tag}</span>
                  <h3 className="phase__title">{phase.title}</h3>
                  <p className="phase__body">{phase.body}</p>
                  <ul className="phase__list">
                    {phase.items.map((item) => (
                      <li key={item}>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="section section--sunken" id="foundations">
          <div className="shell">
            <p className="section__eyebrow">How it is built</p>
            <h2 className="section__title">
              The parts that are hard to retrofit, done first.
            </h2>
            <p className="section__lede">
              Multi-tenancy, EVV, and auditability are not features to add once there are
              customers. Each one is a decision that reaches every table in the schema, and each
              one is cheaper now than it will ever be again.
            </p>

            <dl className="rows">
              {FOUNDATIONS.map((item) => (
                <div className="row" key={item.term}>
                  <dt className="row__term">{item.term}</dt>
                  <dd className="row__detail">{item.detail}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section className="section">
          <div className="shell">
            <p className="section__eyebrow">Who it is for</p>
            <h2 className="section__title">Four people, one system.</h2>

            <div className="audience">
              {AUDIENCE.map((who) => (
                <div className="who" key={who.role}>
                  <p className="who__role">{who.role}</p>
                  <p className="who__line">{who.line}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="closing">
          <div className="shell">
            <h2 className="closing__title">We are looking for a few agencies to build with.</h2>
            <p className="closing__lede">
              Not a pilot programme and not a waiting list. A small number of operators willing
              to tell us what is actually broken, in exchange for shaping what gets built.
            </p>
            <div className="closing__actions">
              <a
                className="button"
                href={`mailto:${CONTACT_EMAIL}?subject=CareOS%20design%20partner`}
              >
                Talk to us
              </a>
              <a className="button button--quiet" href={SIGN_IN_URL}>
                Sign in
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="footer">
        <div className="shell footer__inner">
          <span>© {new Date().getFullYear()} CareOS</span>
          <nav className="footer__links" aria-label="Footer">
            <a href={`mailto:${CONTACT_EMAIL}`}>Contact</a>
            <a href={SIGN_IN_URL}>Sign in</a>
          </nav>
        </div>
      </footer>
    </>
  );
}
