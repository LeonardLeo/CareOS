/**
 * Shared UI primitives.
 *
 * The design-system pass `09_UX_Design_and_User_Flows.md` Section 5 asks for. Every screen
 * composes from these rather than styling ad hoc, so the three surfaces stay consistent as
 * they grow.
 *
 * `SeverityBadge` always pairs colour with a text label, because design principle 6 makes
 * accessibility a baseline: colour alone is not a signal. Charts and figures live in
 * `charts.tsx`.
 */

import type { ReactNode } from "react";

export type Severity = "critical" | "warning" | "serious" | "info" | "good" | "neutral";

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  warning: "Warning",
  serious: "Serious",
  info: "Info",
  good: "OK",
  neutral: "—",
};

export function SeverityBadge({
  severity,
  children,
}: {
  severity: Severity;
  children?: ReactNode;
}) {
  return (
    <span className={`badge badge--${severity}`}>{children ?? SEVERITY_LABEL[severity]}</span>
  );
}

export function Card({
  title,
  subtitle,
  action,
  children,
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {(title || action) && (
        <header className="card__header">
          <div>
            {title && <h2 className="card__title">{title}</h2>}
            {subtitle && <p className="card__subtitle">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="card__body">{children}</div>
    </section>
  );
}

/**
 * Shown when a list is empty.
 *
 * An empty exception queue is good news, not a broken page — `09_UX...` principle 3 makes
 * these queues the default view, so they are empty most of the time and the message should
 * read as reassurance rather than absence.
 */
export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {detail && <p className="empty__detail">{detail}</p>}
    </div>
  );
}

export function ErrorNote({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="error-note" role="alert">
      <span className="error-note__icon" aria-hidden="true">
        !
      </span>
      <div>
        <p className="error-note__title">{title}</p>
        {detail && <p className="error-note__detail">{detail}</p>}
      </div>
    </div>
  );
}

/**
 * A standing condition the reader needs to know about, which is neither an error nor a
 * success. Styled apart from `ErrorNote` on purpose: a shadow period is the system working
 * as designed, and dressing it in the colour of a failure would train people to dismiss it.
 */
export function InfoNote({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="info-note" role="note">
      <span className="info-note__icon" aria-hidden="true">
        i
      </span>
      <div>
        <p className="info-note__title">{title}</p>
        {detail && <p className="info-note__detail">{detail}</p>}
      </div>
    </div>
  );
}

/**
 * Inline reasoning for an AI suggestion.
 *
 * `09_UX...` principle 4: an AI-generated score is never shown as an unexplained number.
 *
 * The magnitude of each factor is carried by the stacked `ScoreBar` above this list, whose
 * segments sum to the score. Repeating that magnitude as a per-row bar here would
 * double-encode it and add ink that is not data — so each row gets a small colored key
 * matching its segment, and the text does the rest. The text never wears the data color:
 * the lighter ramp steps are illegible as type, so identity comes from the swatch beside
 * the words.
 */
export function FactorList({
  factors,
}: {
  factors: { factor: string; weight: number; rationale: string }[];
}) {
  if (factors.length === 0) return null;
  return (
    <ul className="factors">
      {factors.map((f, index) => (
        <li key={f.factor} className="factor">
          <span
            className="factor__dot"
            style={{ background: `var(--ordinal-${Math.min(index + 2, 4)})` }}
            aria-hidden="true"
          />
          <span>{f.rationale}</span>
        </li>
      ))}
    </ul>
  );
}

export function Table({
  headers,
  children,
  caption,
}: {
  headers: string[];
  children: ReactNode;
  caption?: string;
}) {
  return (
    <div className="table-wrap">
      <table className="table">
        {caption && <caption className="visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** "in 3 days" / "5 days ago" — easier to act on than a bare date in a renewal queue. */
export function relativeDays(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${Math.abs(days)} days ago`;
}
