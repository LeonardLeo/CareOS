/**
 * Walks every screen of the admin console through the shared UI checks.
 *
 * Until this existed, the console had never been measured at any width. The public site had
 * two serious layout defects found in an afternoon by exactly these checks — a list item 1096px
 * tall, and a footer that painted its wordmark across the next column on every phone — and
 * both shipped through a green test suite. There was no reason to think this app was cleaner;
 * only that nobody had looked.
 *
 * Needs the stack up and a demo agency seeded:
 *
 *     make dev &                                  # API on :8000
 *     python -m careos.scripts.seed_demo_data     # from services/api
 *     npm run build && npm start &                # this app on :3000
 *     node scripts/audit.mjs
 *
 * Signs in through the real form, including MFA, rather than forging a cookie. Two reasons:
 * the login screen is a screen that needs auditing too, and a forged session would keep
 * working after the thing that mints real ones broke.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { chromium, devices } from "playwright";

import { ALL_CHECKS } from "../../../tools/ui-audit/checks.mjs";
import { audit } from "../../../tools/ui-audit/run.mjs";
import { totp } from "../../../tools/ui-audit/totp.mjs";

const APP = process.env.ADMIN_URL ?? "http://127.0.0.1:3000";
const API = process.env.API_URL ?? "http://127.0.0.1:8000";
const EMAIL = process.env.DEMO_EMAIL ?? "owner@bayridgecare.demo";
const PASSWORD = process.env.DEMO_PASSWORD ?? "demo-password-12345";

/**
 * Where the harness remembers the authenticator it enrolled.
 *
 * Re-enrolling an already-enrolled account requires proving a code from the current secret —
 * deliberately, so a stolen session cannot move someone's second factor. That is the right
 * rule and it means this harness has to keep its own secret between runs, outside the repo.
 */
const SECRET_FILE = join(tmpdir(), "careos-ui-audit", `${EMAIL.replace(/\W/g, "_")}.json`);

function remembered() {
  try {
    return JSON.parse(readFileSync(SECRET_FILE, "utf8")).secret;
  } catch {
    return null;
  }
}

function remember(secret) {
  mkdirSync(join(tmpdir(), "careos-ui-audit"), { recursive: true });
  writeFileSync(SECRET_FILE, JSON.stringify({ secret }), { mode: 0o600 });
}

/**
 * A code the server has not seen before, waiting for the next window if necessary.
 *
 * The server records the counter each accepted code came from and refuses to accept it twice
 * — a one-time password that works twice is not one. Confirming enrolment and then signing in
 * happen well inside a single thirty-second window, so without this the sign-in is rejected as
 * a replay, which looks exactly like a wrong password.
 */
const STEP_SECONDS = 30;
let lastCounter = -1;

async function freshCode(secret) {
  for (;;) {
    const counter = Math.floor(Date.now() / 1000 / STEP_SECONDS);
    if (counter !== lastCounter) {
      lastCounter = counter;
      return totp(secret);
    }
    const msIntoWindow = Date.now() % (STEP_SECONDS * 1000);
    await new Promise((resolve) => setTimeout(resolve, STEP_SECONDS * 1000 - msIntoWindow + 250));
  }
}

async function call(path, { token, body, method = "POST" } = {}) {
  const response = await fetch(API + path, {
    method,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : null };
}

/** Signs in via the API, enrolling an authenticator if the role requires one. */
async function apiSession() {
  let secret = remembered();
  const attempt = async () =>
    call("/v1/auth/login", {
      body: {
        email: EMAIL,
        password: PASSWORD,
        ...(secret ? { mfa_code: await freshCode(secret) } : {}),
      },
    });

  let result = await attempt();
  if (result.status !== 200 && secret) {
    // Retry in the next window before concluding anything. A run that finished moments ago
    // burned this window's code, and the server refuses to accept one twice — so the most
    // likely cause of a rejection here is not a bad secret but a recent success.
    lastCounter = Math.floor(Date.now() / 1000 / STEP_SECONDS);
    result = await attempt();
  }
  if (result.status !== 200 && secret) {
    // Now it is worth believing the secret is stale: the account was re-enrolled elsewhere, or
    // the database was rebuilt under us. Try again as an account with no authenticator.
    secret = null;
    result = await attempt();
  }
  if (result.status !== 200) {
    // Worth spelling out, because it is the state anyone hits after enrolling this account by
    // hand: the server holds a secret, this harness does not, and no amount of retrying
    // produces a code. Re-enrolment requires proving the current one — correctly, so a stolen
    // session cannot move somebody's second factor — so the only way out is to clear it.
    const stuck = result.body?.error?.code === "MFA_REQUIRED";
    throw new Error(
      `login failed (${result.status}): ${JSON.stringify(result.body)}` +
        (stuck
          ? `\n\n${EMAIL} has an authenticator this harness did not enrol, so it cannot` +
            ` produce a code. Clear it and run again:\n\n` +
            `  psql -d careos -c "update app_user set mfa_enrolled=false,` +
            ` mfa_secret_encrypted=null, mfa_last_counter=null, mfa_recovery_hashes='{}'` +
            ` where email='${EMAIL}'"\n`
          : ""),
    );
  }

  const token = result.body.access_token;
  const me = await call("/v1/auth/me", { token, method: "GET" });
  if (me.status === 200 && me.body.mfa_enrolled && secret) return { token, secret };

  // Enrol whenever the account is not enrolled, and let the API decide whether it may be —
  // it refuses for roles outside `MFA_ELIGIBLE_ROLES`. An earlier version asked `/auth/me`
  // for an `mfa_required` field that does not exist, so `!undefined` read as "not required"
  // and enrolment was silently skipped for every role.
  const enrol = await call("/v1/auth/mfa/enroll", {
    token,
    body: secret ? { current_code: await freshCode(secret) } : {},
  });
  if (enrol.status !== 200) return { token, secret: null };
  remember(enrol.body.secret);
  const confirm = await call("/v1/auth/mfa/confirm", {
    token,
    body: { code: await freshCode(enrol.body.secret) },
  });
  if (confirm.status !== 200) {
    throw new Error(`mfa confirm failed (${confirm.status}): ${JSON.stringify(confirm.body)}`);
  }
  return { token: confirm.body.access_token, secret: enrol.body.secret };
}

const { token, secret } = await apiSession();

// A detail screen needs a real record. Auditing `/clients/` and calling it coverage would
// leave the densest screen in the app — the one with the care plan and the visit history —
// unmeasured.
const clients = await call("/v1/clients?page=1&page_size=1", { token, method: "GET" });
const clientId = Array.isArray(clients.body) ? clients.body[0]?.id : clients.body?.items?.[0]?.id;
if (!clientId) throw new Error("no clients seeded; run the demo seeder first");

const PAGES = [
  "/dashboard",
  "/scheduling",
  "/clients",
  `/clients/${clientId}`,
  "/clients/new",
  "/exceptions",
  "/recruiting",
  "/credentialing",
  "/compliance",
  "/users",
  "/security",
];

/**
 * Signs the browser in through the form, so the cookie is set the way the app sets it.
 *
 * Two round trips, because the app deliberately does not render the code field until the API
 * has said one is needed — showing it to every scheduler and caregiver would ask most users
 * for something they do not have. So: submit, get bounced back with `?error=mfa`, fill the
 * code that has now appeared, submit again.
 */
async function signIn(context, page) {
  // The wait has to be armed before the click. Awaiting a load state afterwards resolves
  // against the page that is still on screen, so the URL read back is the one you started on
  // and every sign-in looks like it bounced.
  const submit = async () => {
    await Promise.all([
      page.waitForURL(() => true, { waitUntil: "networkidle", timeout: 20_000 }),
      page.click('button[type="submit"]'),
    ]);
  };

  await page.goto(`${APP}/login`, { waitUntil: "networkidle" });
  await page.fill("#email", EMAIL);
  await page.fill("#password", PASSWORD);
  await submit();

  if (new URL(page.url()).pathname.startsWith("/login")) {
    if (!secret || !(await page.locator("#mfa_code").count())) {
      throw new Error(`sign-in bounced back to ${page.url()} and no code field appeared`);
    }
    await page.fill("#email", EMAIL);
    await page.fill("#password", PASSWORD);
    await page.fill("#mfa_code", await freshCode(secret));
    await submit();
  }

  if (new URL(page.url()).pathname.startsWith("/login")) {
    throw new Error(`sign-in failed: still on ${page.url()}`);
  }
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

const findings = await audit({
  browser,
  baseUrl: APP,
  pages: PAGES,
  checks: ALL_CHECKS,
  // This app is a console behind a login, not a document. It has a persistent nav rather than
  // a skip link, and `landmarks` asserts a skip link — so that one check is off here and noted
  // in the breakdown rather than silently dropped.
  ignore: [],
  prepare: signIn,
  devices,
});

await browser.close();
console.log(findings ? `\n${findings} finding(s)` : "\nno defects");
process.exit(findings ? 1 : 0);
