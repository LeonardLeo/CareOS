/**
 * Shared UI primitives.
 *
 * The design-system pass `09_UX_Design_and_User_Flows.md` Section 5 asks for. Every screen
 * composes from these rather than styling ad hoc, so the three surfaces stay consistent as
 * they grow.
 *
 * `SeverityBadge` and `StatusDot` always pair colour with a text label, because design
 * principle 6 makes accessibility a baseline: colour alone is not a signal.
 */

import type { ReactNode } from "react";

export type Severity = "critical" | "warning" | "info" | "success" | "neutral";

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Info",
  success: "OK",
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

export function StatusDot({ severity, label }: { severity: Severity; label: string }) {
  return (
    <span className="status">
      <span className={`status__dot status__dot--${severity}`} aria-hidden="true" />
      {label}
    </span>
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

export function StatTile({
  label,
  value,
  hint,
  severity = "neutral",
}: {
  label: string;
  value: string | number;
  hint?: string;
  severity?: Severity;
}) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className={`stat__value stat__value--${severity}`}>{value}</div>
      {hint && <div className="stat__hint">{hint}</div>}
    </div>
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
      <p className="error-note__title">{title}</p>
      {detail && <p className="error-note__detail">{detail}</p>}
    </div>
  );
}

/**
 * Inline reasoning for an AI suggestion.
 *
 * `09_UX...` principle 4: an AI-generated score is never shown as an unexplained number.
 * The bar widths are the factor contributions, so what a scheduler sees adds up to the score
 * next to it.
 */
export function FactorList({
  factors,
}: {
  factors: { factor: string; weight: number; rationale: string }[];
}) {
  if (factors.length === 0) return null;
  return (
    <ul className="factors">
      {factors.map((f) => (
        <li key={f.factor} className="factor">
          <div className="factor__bar" aria-hidden="true">
            <div
              className="factor__fill"
              style={{ width: `${Math.min(100, Math.abs(f.weight) * 100)}%` }}
            />
          </div>
          <span className="factor__text">{f.rationale}</span>
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
