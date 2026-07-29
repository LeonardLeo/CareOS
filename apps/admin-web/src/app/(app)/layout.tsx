import Link from "next/link";
import { redirect } from "next/navigation";
import { canSee, getSession } from "@/lib/session";

const NAV = [
  { href: "/dashboard", label: "Dashboard", area: "dashboard" },
  { href: "/scheduling", label: "Scheduling", area: "scheduling" },
  { href: "/recruiting", label: "Recruiting", area: "recruiting" },
  { href: "/credentialing", label: "Credentialing", area: "credentialing" },
  { href: "/compliance", label: "Compliance", area: "compliance" },
] as const;

const ROLE_LABEL: Record<string, string> = {
  owner_admin: "Owner / Admin",
  scheduler: "Scheduler",
  clinical_supervisor: "Clinical Supervisor",
  caregiver: "Caregiver",
  billing_rcm: "Billing / RCM",
  auditor: "Auditor",
};

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");

  // Hiding a link the role cannot use is a usability courtesy only. The real boundary is the
  // API's RBAC plus row-level security — this layout is not a security control.
  const links = NAV.filter((item) => canSee(item.area, session.role));

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            C
          </span>
          <span className="brand__text">
            CareOS
            <span className="brand__sub">Agency admin</span>
          </span>
        </div>

        <nav className="nav" aria-label="Main">
          {links.map((item) => (
            <Link key={item.href} className="nav__link" href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="sidebar__role">{ROLE_LABEL[session.role] ?? session.role}</div>
          <form method="post" action="/api/auth/logout">
            <button className="button button--ghost button--small" type="submit">
              Sign out
            </button>
          </form>
        </div>
      </aside>

      <main className="main">{children}</main>
    </div>
  );
}
