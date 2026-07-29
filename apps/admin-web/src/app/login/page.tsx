import { redirect } from "next/navigation";
import { ErrorNote } from "@/components/ui";
import { getSession } from "@/lib/session";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  if (await getSession()) redirect("/dashboard");
  const { error } = await searchParams;

  return (
    <main className="login">
      <div className="login__panel">
        <div className="login__brand">
          <span className="brand__mark" aria-hidden="true">
            C
          </span>
          <div>
            <h1 className="login__title">CareOS</h1>
            <p className="login__subtitle">Agency administration</p>
          </div>
        </div>

        {error && <ErrorNote title={error} />}

        {/*
          A plain form post to a server route handler. No client-side JavaScript touches the
          credentials or the resulting token, and the form works before hydration.
        */}
        <form method="post" action="/api/auth/login">
          <div className="field">
            <label className="field__label" htmlFor="email">
              Email
            </label>
            <input
              className="field__input"
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              required
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="password">
              Password
            </label>
            <input
              className="field__input"
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </div>

          <button className="button" type="submit" style={{ width: "100%" }}>
            Sign in
          </button>
        </form>

        <p className="small muted" style={{ marginTop: "var(--space-5)" }}>
          Multi-factor authentication is required for owner, clinical supervisor and billing
          roles before production use.
        </p>
      </div>
    </main>
  );
}
