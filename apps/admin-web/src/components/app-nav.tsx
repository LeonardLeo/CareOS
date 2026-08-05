"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export type AppNavItem = {
  href: string;
  label: string;
  /** Shown only when > 0 — an unattended queue should be visible without opening it. */
  count?: number;
};

export type AppNavGroup = {
  /** Omit for a flat list (operator console has four links and no sections). */
  label?: string;
  items: AppNavItem[];
};

/**
 * Sidebar navigation with current-route highlighting.
 *
 * Active state lives here because the App Router only exposes the pathname to client
 * components. The CSS has always styled `[data-active="true"]` / the original
 * `[aria-current="page"]`; neither attribute was ever set on the links, so the rail
 * looked like a plain list with no location signal.
 */
export function AppNav({ groups, ariaLabel }: { groups: AppNavGroup[]; ariaLabel: string }) {
  const pathname = usePathname();

  return (
    <nav className="nav" aria-label={ariaLabel}>
      {groups.map((group) => (
        <div
          key={group.label ?? group.items.map((i) => i.href).join("|")}
          className="nav__group"
        >
          {group.label ? <div className="nav__group-label">{group.label}</div> : null}
          {group.items.map((item) => {
            const active = linkIsActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                className="nav__link"
                href={item.href}
                aria-current={active ? "page" : undefined}
                data-active={active ? "true" : undefined}
              >
                <span>{item.label}</span>
                {item.count != null && item.count > 0 ? (
                  <span className="nav__count">{item.count}</span>
                ) : null}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

function linkIsActive(pathname: string, href: string): boolean {
  // Console roots must be exact: `/platform` must not light up for `/platform/operators`,
  // and `/dashboard` must not match every agency route.
  if (href === "/platform" || href === "/dashboard") {
    return pathname === href;
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}
