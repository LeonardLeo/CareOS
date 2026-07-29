/**
 * Chart components.
 *
 * Each one starts from the data's job, not from a chart type:
 *
 * - **Coverage** is a single ratio against a limit → a **meter**, not a pie of two slices.
 * - **Recruiting funnel** is an ordered scale → the validated **ordinal ramp**, one hue,
 *   light→dark. Nominal categories would get one color; these stages have a real order.
 * - **Match score** is magnitude → a **bar**, so a scheduler compares candidates by length
 *   rather than by reading numbers. Its factor breakdown is a **stacked bar** whose segments
 *   sum to the score.
 * - **Schedule** is occupancy over time → a **timeline**, which is the actual shape of a
 *   scheduler's problem. A table of start times is not.
 *
 * Every mark follows the fixed specs: bars ≤24px with a 4px rounded data-end squared at the
 * baseline, a 2px surface gap between touching fills, hairline solid gridlines, and no
 * number on every point. Values are always reachable without hover — direct labels or the
 * adjacent table — so a tooltip never gates a value.
 */

import type { ReactNode } from "react";

import { TimelineMark } from "@/components/timeline-mark";

/* --- Meter: one ratio against a limit ------------------------------------------------ */

export function Meter({
  label,
  value,
  total,
  severity = "accent",
  caption,
}: {
  label: string;
  value: number;
  total: number;
  severity?: "accent" | "good" | "warning" | "critical";
  caption?: string;
}) {
  const pct = total === 0 ? 0 : Math.round((value / total) * 100);
  return (
    <div className="meter">
      <div className="meter__head">
        <span className="meter__label">{label}</span>
        <span className="meter__value">
          {value}
          <span className="meter__total">/{total}</span>
        </span>
      </div>
      <div
        className="meter__track"
        role="meter"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={`${label}: ${value} of ${total}`}
      >
        {/* The unfilled track is a lighter step of the fill's own ramp, so state reads
            across the whole bar rather than only where it happens to stop. */}
        <div className={`meter__fill meter__fill--${severity}`} style={{ width: `${pct}%` }} />
      </div>
      {caption && <p className="meter__caption">{caption}</p>}
    </div>
  );
}

/* --- Sparkline: trend context on a stat tile ----------------------------------------- */

export function Sparkline({
  points,
  label,
}: {
  points: number[];
  label: string;
}) {
  if (points.length < 2) return null;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const range = max - min || 1;
  const w = 96;
  const h = 24;
  const step = w / (points.length - 1);

  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - ((p - min) / range) * h).toFixed(1)}`)
    .join(" ");
  const lastX = w;
  const lastY = h - (((points[points.length - 1] ?? 0) - min) / range) * h;

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${w} ${h}`}
      width={w}
      height={h}
      role="img"
      aria-label={label}
      preserveAspectRatio="none"
    >
      {/* 2px line, round join/cap. The end-dot carries a surface ring so it stays legible
          where it meets the card edge. */}
      <path d={d} className="sparkline__line" fill="none" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX - 2} cy={lastY} r="3" className="sparkline__end" />
    </svg>
  );
}

/* --- Stat tile ----------------------------------------------------------------------- */

export function StatTile({
  label,
  value,
  hint,
  severity = "neutral",
  trend,
  href,
}: {
  label: string;
  value: string | number;
  hint?: string;
  severity?: "neutral" | "good" | "warning" | "critical";
  trend?: number[];
  href?: string;
}) {
  const body = (
    <>
      <div className="stat__label">{label}</div>
      <div className="stat__row">
        {/* Proportional figures, not tabular: equal-width digits make a large standalone
            number look loose. tabular-nums is reserved for columns that align. */}
        <div className={`stat__value stat__value--${severity}`}>{value}</div>
        {trend && <Sparkline points={trend} label={`${label} trend`} />}
      </div>
      {hint && <div className="stat__hint">{hint}</div>}
    </>
  );
  return href ? (
    <a className="stat stat--link" href={href}>
      {body}
    </a>
  ) : (
    <div className="stat">{body}</div>
  );
}

/* --- Hero figure: exactly one per view ----------------------------------------------- */

export function HeroFigure({
  value,
  label,
  detail,
  severity = "neutral",
}: {
  value: string | number;
  label: string;
  detail?: ReactNode;
  severity?: "neutral" | "good" | "warning" | "critical";
}) {
  return (
    <div className="hero">
      <div className={`hero__value hero__value--${severity}`}>{value}</div>
      <div className="hero__label">{label}</div>
      {detail && <div className="hero__detail">{detail}</div>}
    </div>
  );
}

/* --- Funnel: ordered stages on the validated ordinal ramp ----------------------------- */

export function Funnel({
  stages,
}: {
  stages: { stage: string; count: number; conversion: number | null }[];
}) {
  const top = Math.max(...stages.map((s) => s.count), 1);

  return (
    <div className="funnel">
      {stages.map((stage, index) => {
        const pct = (stage.count / top) * 100;
        return (
          <div key={stage.stage} className="funnel__row">
            <div className="funnel__label">{stage.stage}</div>
            <div className="funnel__track">
              <div
                className="funnel__bar"
                style={{
                  // A zero-count stage renders no bar at all. A minimum-width stub would
                  // give length to a value that has none, which misstates it — the count
                  // label beside the track already says the stage exists.
                  width: stage.count === 0 ? 0 : `${Math.max(pct, 1.5)}%`,
                  // Ordinal ramp step, positioned by stage order rather than by value —
                  // the stages have a real sequence, so hue carries that sequence.
                  background: `var(--ordinal-${Math.min(index + 1, 4)})`,
                }}
              />
              {/* Direct label outside the bar end, never clipped inside it. */}
              <span className="funnel__count">{stage.count}</span>
            </div>
            <div className="funnel__conversion">
              {stage.conversion === null ? (
                <span className="muted">—</span>
              ) : (
                `${Math.round(stage.conversion * 100)}%`
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* --- Score bar: magnitude, compared by length ---------------------------------------- */

export function ScoreBar({ score, segments }: { score: number; segments?: number[] }) {
  const pct = Math.round(score * 100);
  return (
    <div className="scorebar" title={`Match score ${pct} of 100`}>
      <div className="scorebar__track">
        {segments && segments.length > 0 ? (
          // Stacked: each factor's contribution, summing to the score. A 2px surface gap
          // separates segments — never a border drawn around them.
          segments.map((seg, i) => (
            <div
              key={i}
              className="scorebar__segment"
              style={{ width: `${seg * 100}%`, background: `var(--ordinal-${Math.min(i + 2, 4)})` }}
            />
          ))
        ) : (
          <div className="scorebar__fill" style={{ width: `${pct}%` }} />
        )}
      </div>
      <span className="scorebar__value">
        {pct}
        <span className="visually-hidden"> out of 100 match score</span>
      </span>
    </div>
  );
}

/* --- Schedule timeline --------------------------------------------------------------- */

export interface TimelineVisit {
  id: string;
  start: string;
  end: string;
  assigned: boolean;
  label: string;
  detail: string;
}

/**
 * Visits laid out across days, positioned by time of day.
 *
 * This is the form a scheduler's problem actually has: where are the holes, and when. A
 * table sorted by start time answers "what is next" but hides clustering — three unfilled
 * visits at the same hour on Thursday is a different problem from three spread across the
 * week, and only the spatial layout shows that at a glance.
 */
export function ScheduleTimeline({
  visits,
  days = 7,
  selectedId,
}: {
  visits: TimelineVisit[];
  days?: number;
  selectedId?: string;
}) {
  const start = new Date();
  start.setHours(0, 0, 0, 0);

  const dayBuckets = Array.from({ length: days }, (_, i) => {
    const day = new Date(start);
    day.setDate(day.getDate() + i);
    return {
      date: day,
      visits: visits.filter((v) => {
        const vd = new Date(v.start);
        return vd.toDateString() === day.toDateString();
      }),
    };
  });

  // 6am–10pm covers the realistic span of home-care visits; anything outside is clamped
  // to the edge rather than dropped, so an unusual overnight visit still appears.
  const dayStartHour = 6;
  const dayEndHour = 22;
  const span = dayEndHour - dayStartHour;

  return (
    <div className="timeline">
      <div className="timeline__hours" aria-hidden="true">
        {[6, 10, 14, 18, 22].map((h) => (
          <span
            key={h}
            className="timeline__hour"
            style={{ left: `${((h - dayStartHour) / span) * 100}%` }}
          >
            {h === 12 ? "12p" : h < 12 ? `${h}a` : `${h - 12}p`}
          </span>
        ))}
      </div>

      {dayBuckets.map((bucket) => (
        <div key={bucket.date.toISOString()} className="timeline__row">
          <div className="timeline__day">
            <span className="timeline__dow">
              {bucket.date.toLocaleDateString(undefined, { weekday: "short" })}
            </span>
            <span className="timeline__date">
              {bucket.date.toLocaleDateString(undefined, { day: "numeric", month: "short" })}
            </span>
          </div>

          <div className="timeline__lane">
            {/* Hairline gridlines, solid — dashing reads as "threshold" when it is just a grid. */}
            {[10, 14, 18].map((h) => (
              <div
                key={h}
                className="timeline__gridline"
                style={{ left: `${((h - dayStartHour) / span) * 100}%` }}
                aria-hidden="true"
              />
            ))}

            {bucket.visits.length === 0 && <span className="timeline__quiet">No visits</span>}

            {bucket.visits.map((visit) => {
              const s = new Date(visit.start);
              const e = new Date(visit.end);
              const startPct =
                ((s.getHours() + s.getMinutes() / 60 - dayStartHour) / span) * 100;
              const widthPct = ((e.getTime() - s.getTime()) / 3600000 / span) * 100;
              return (
                <TimelineMark
                  key={visit.id}
                  className={[
                    "timeline__visit",
                    visit.assigned ? "timeline__visit--assigned" : "timeline__visit--open",
                    selectedId === visit.id ? "timeline__visit--selected" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  style={{
                    left: `${Math.max(0, Math.min(startPct, 98))}%`,
                    width: `${Math.max(widthPct, 2)}%`,
                  }}
                  label={visit.label}
                  detail={visit.detail}
                />
              );
            })}
          </div>
        </div>
      ))}

      {/* Two states, so a legend is required — identity is never color-alone. */}
      <div className="timeline__legend">
        <span className="legend__item">
          <span className="legend__swatch legend__swatch--open" aria-hidden="true" />
          Unfilled
        </span>
        <span className="legend__item">
          <span className="legend__swatch legend__swatch--assigned" aria-hidden="true" />
          Assigned
        </span>
      </div>
    </div>
  );
}
