import type { CSSProperties } from "react";

/**
 * A week of scheduled visits, with the unfilled ones in red.
 *
 * The site's central image, and it is the product's own scheduling board rather than a stock
 * illustration. Built from elements and custom properties: no image request, no layout shift,
 * legible at any width, and correct in dark mode without a second asset.
 *
 * Hidden from assistive technology with a written equivalent beside it. An animated grid of
 * coloured rectangles carries nothing to a screen reader, and a forty-word alt attribute
 * describing bar positions would be worse than the one sentence that says what it means.
 */

export interface Bar {
  /** Percentage across the day, 0–100. */
  start: number;
  width: number;
  gap?: boolean;
}

export interface Day {
  day: string;
  bars: Bar[];
}

export const DEFAULT_WEEK: Day[] = [
  { day: "Mon", bars: [{ start: 8, width: 18 }, { start: 32, width: 15 }, { start: 62, width: 20 }] },
  { day: "Tue", bars: [{ start: 6, width: 22 }, { start: 34, width: 16, gap: true }, { start: 64, width: 18 }] },
  { day: "Wed", bars: [{ start: 10, width: 16 }, { start: 30, width: 21 }, { start: 58, width: 24 }] },
  { day: "Thu", bars: [{ start: 8, width: 20 }, { start: 33, width: 14 }, { start: 55, width: 18, gap: true }] },
  { day: "Fri", bars: [{ start: 6, width: 24 }, { start: 36, width: 18 }, { start: 60, width: 22 }] },
  { day: "Sat", bars: [{ start: 12, width: 20, gap: true }, { start: 46, width: 16 }] },
  { day: "Sun", bars: [{ start: 14, width: 18 }, { start: 48, width: 19 }] },
];

export function CoverageBoard({
  week = DEFAULT_WEEK,
  title = "Coverage, next seven days",
  caption = "A week of scheduled visits in which three shifts are unfilled.",
}: {
  week?: Day[];
  title?: string;
  caption?: string;
}) {
  let index = 0;

  return (
    <figure className="board">
      <div className="board__head">
        <span className="board__title">{title}</span>
        <span className="board__legend">
          <span>
            <i className="swatch swatch--filled" aria-hidden="true" />
            Assigned
          </span>
          <span>
            <i className="swatch swatch--gap" aria-hidden="true" />
            Unfilled
          </span>
        </span>
      </div>

      <div className="board__grid" aria-hidden="true">
        {week.map((row) => (
          <div className="board__row" key={row.day}>
            <span className="board__day">{row.day}</span>
            <span className="board__track">
              {row.bars.map((bar, barIndex) => {
                // A single running counter across the whole board, so the bars draw in
                // reading order rather than all seven rows starting at once.
                const delay = index++ * 55;
                return (
                  <span
                    key={barIndex}
                    className={`board__bar${bar.gap ? " board__bar--gap" : ""}`}
                    style={
                      {
                        "--start": `${bar.start}%`,
                        "--width": `${bar.width}%`,
                        "--delay": `${delay}ms`,
                      } as CSSProperties
                    }
                  />
                );
              })}
            </span>
          </div>
        ))}
      </div>

      <figcaption className="vh">{caption}</figcaption>
    </figure>
  );
}
