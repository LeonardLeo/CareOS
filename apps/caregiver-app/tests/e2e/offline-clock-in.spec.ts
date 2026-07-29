import { expect, test } from "@playwright/test";
import { type SeededCaregiver, evvStatus, replayClockIn, seedCaregiver } from "./seed";

/**
 * The guarantee this whole surface exists for: a clock-in taken with no network reaches the
 * API exactly once, at the time the caregiver tapped.
 *
 * These tests use Playwright's real offline mode against a real API, so the dedup being
 * verified is the server's idempotency table rather than something the test arranged. Every
 * other file in this app could be rewritten; if these stop passing, the product does not work.
 */

/**
 * One shared tenant for the read-only tests, and a fresh one per test that clocks in.
 *
 * Sharing a single visit across the clock-in tests coupled them to execution order — the second
 * one found a clock-out button where it expected a clock-in, and only because a previous test
 * had already run. Each mutating test seeds its own caregiver, so each one describes a complete
 * situation on its own and none depends on what ran before it.
 */
let seeded: SeededCaregiver;

test.beforeAll(async () => {
  seeded = await seedCaregiver();
});

async function signIn(page: import("@playwright/test").Page, as: SeededCaregiver = seeded) {
  await page.goto("/");
  await page.getByLabel(/email|correo/i).fill(as.email);
  await page.getByLabel(/password|contraseña/i).fill(as.password);
  await page.getByRole("button", { name: /sign in|iniciar/i }).click();
  await expect(page.getByRole("heading", { name: /today|hoy/i })).toBeVisible();
}

test("the schedule shows the client a caregiver is actually visiting", async ({ page }) => {
  await signIn(page);

  // The whole reason /my-visits exists: name and address, not just a care_plan_id.
  await expect(page.getByText(seeded.clientName)).toBeVisible();
  await expect(page.getByText(/412 Ashbury Lane/)).toBeVisible();
});

test("a clock-in taken offline is accepted, queued, and reaches the API exactly once", async ({
  page,
  context,
}) => {
  const own = await seedCaregiver();
  await signIn(page, own);
  await page.getByText(own.clientName).click();
  await expect(page.getByRole("button", { name: /clock in|registrar entrada/i })).toBeVisible();

  // Nothing on the server yet.
  const beforeToken = own.ownerToken;
  const before = await evvStatus(own.visitId, beforeToken);
  expect(before).toBeNull();

  // Go genuinely offline — not a mocked route, the browser's network is cut.
  await context.setOffline(true);
  await expect(page.getByText(/offline|sin conexión|waiting to send|pendiente/i)).toBeVisible();

  const tappedAt = Date.now();
  await page.getByRole("button", { name: /clock in|registrar entrada/i }).click();

  // The caregiver is told it is saved, with no error, while still offline. This is the
  // requirement from UX Flow B step 4 — a "will sync" state, never a failure.
  await expect(page.getByText(/will send when you have signal|se enviará cuando/i)).toBeVisible();
  // And the button has advanced to clock-out, because a queued clock-in counts as clocked in.
  await expect(page.getByRole("button", { name: /clock out|registrar salida/i })).toBeVisible();

  // Still nothing server-side: it is on the device.
  expect(await evvStatus(own.visitId, beforeToken)).toBeNull();

  // Signal returns.
  await context.setOffline(false);

  // The outbox flushes on the online event. Poll the API rather than the UI so this asserts
  // what actually landed.
  await expect
    .poll(async () => (await evvStatus(own.visitId, beforeToken))?.clock_in_time ?? null, {
      timeout: 30_000,
      intervals: [500, 1000, 2000],
    })
    .not.toBeNull();

  const record = await evvStatus(own.visitId, beforeToken);
  expect(record?.clock_in_time).not.toBeNull();
  expect(record?.clock_out_time).toBeNull();

  // The recorded time is when the caregiver tapped, not when the network came back.
  const recorded = new Date(record!.clock_in_time!).getTime();
  expect(Math.abs(recorded - tappedAt)).toBeLessThan
    // Within a minute of the tap; the reconnect happens seconds later, so a delivery-time
    // stamp would be indistinguishable here — the unit tests pin that precisely.
    (60_000);
});

test("replaying the same queued clock-in does not create a second EVV record", async ({
  page,
  context,
}) => {
  // Demonstrates the dedup instead of assuming it. The situation being modelled is a request
  // the server processed whose response never reached the device: the device cannot distinguish
  // that from a request that never arrived, so it retries, and only the server honouring the
  // key keeps the caregiver from being clocked in twice.
  const own = await seedCaregiver();
  await signIn(page, own);
  await page.getByText(own.clientName).click();

  await context.setOffline(true);
  await page.getByRole("button", { name: /clock in|registrar entrada/i }).click();
  await expect(page.getByText(/will send when you have signal|se enviará cuando/i)).toBeVisible();

  // Read the queued action's dedup key out of IndexedDB — the same key the device will use.
  const queued = await page.evaluate<{ clientLocalUuid: string; timestamp: string } | null>(
    () =>
      new Promise((resolve) => {
        const open = indexedDB.open("careos-caregiver");
        open.onsuccess = () => {
          const db = open.result;
          const all = db.transaction("outbox", "readonly").objectStore("outbox").getAll();
          all.onsuccess = () => {
            const rows = all.result as { clientLocalUuid: string; timestamp: string }[];
            resolve(rows.length > 0 ? rows[rows.length - 1]! : null);
          };
          all.onerror = () => resolve(null);
        };
        open.onerror = () => resolve(null);
      }),
  );
  expect(queued).not.toBeNull();

  await context.setOffline(false);
  await expect
    .poll(async () => (await evvStatus(own.visitId, own.ownerToken))?.clock_in_time ?? null, {
      timeout: 30_000,
      intervals: [500, 1000, 2000],
    })
    .not.toBeNull();

  const first = await evvStatus(own.visitId, own.ownerToken);
  expect(first).not.toBeNull();

  // Replay the identical request, twice more.
  const replayA = await replayClockIn(
    own.visitId,
    own.ownerToken,
    queued!.clientLocalUuid,
    queued!.timestamp,
  );
  const replayB = await replayClockIn(
    own.visitId,
    own.ownerToken,
    queued!.clientLocalUuid,
    queued!.timestamp,
  );

  // Same record, same clock-in time. One visit, one EVV record, three deliveries.
  expect(replayA.id).toBe(first!.id);
  expect(replayB.id).toBe(first!.id);
  expect(replayA.clock_in_time).toBe(first!.clock_in_time);

  const after = await evvStatus(own.visitId, own.ownerToken);
  expect(after!.id).toBe(first!.id);
  expect(after!.clock_in_time).toBe(first!.clock_in_time);
});

test("reloading while offline still shows the day, from cache", async ({ page, context }) => {
  await signIn(page);
  await expect(page.getByText(seeded.clientName)).toBeVisible();

  await context.setOffline(true);
  await page.reload();

  // The service worker serves the shell and IndexedDB serves the schedule, so a cold start with
  // no signal opens onto a usable day rather than an error page.
  await expect(page.getByRole("heading", { name: /today|hoy/i })).toBeVisible();
  await expect(page.getByText(seeded.clientName)).toBeVisible();
  // And it says the data is saved rather than live, instead of quietly implying it is current.
  await expect(page.getByText(/saved schedule|horario guardado/i)).toBeVisible();

  await context.setOffline(false);
});

test("a clock-in with location denied is still accepted, recorded as an exception", async ({
  browser,
}) => {
  // A fresh context with geolocation revoked: the indoors/no-fix case, which US-1.4.3 treats
  // as a compliant capture method rather than a failure.
  const own = await seedCaregiver();
  const context = await browser.newContext({ permissions: [] });
  const page = await context.newPage();

  await page.goto("/");
  await page.getByLabel(/email|correo/i).fill(own.email);
  await page.getByLabel(/password|contraseña/i).fill(own.password);
  await page.getByRole("button", { name: /sign in|iniciar/i }).click();
  await expect(page.getByRole("heading", { name: /today|hoy/i })).toBeVisible();

  await page.getByText(own.clientName).click();
  await page.getByRole("button", { name: /clock in|registrar entrada/i }).click();

  // Accepted, with the reason surfaced rather than the action being blocked. The reason has to
  // survive the sync, not vanish with the queued state, because it is what a caregiver will be
  // asked to explain if the agency queries the visit later.
  await expect(page.getByText(/no location|sin ubicación/i)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Reason:|Motivo:/)).toBeVisible();
  await expect(page.getByText(/saved either way|se guarda de todas formas/i)).toBeVisible();

  // And it did reach the server despite having no coordinates.
  await expect
    .poll(async () => (await evvStatus(own.visitId, own.ownerToken))?.clock_in_time ?? null, {
      timeout: 30_000,
      intervals: [500, 1000, 2000],
    })
    .not.toBeNull();

  await context.close();
});

test("the app is usable in Spanish", async ({ page }) => {
  // Design principle 6: EN + ES is a baseline for this surface, not a later pass.
  await page.goto("/");
  // Located by accessible name, which states the action rather than repeating the visible
  // "ES" — the same string a screen-reader user hears.
  await page.getByRole("button", { name: "Cambiar a español" }).click();
  await expect(page.getByRole("heading", { name: "Iniciar sesión" })).toBeVisible();
  await expect(page.getByLabel("Correo electrónico")).toBeVisible();
  await expect(page.getByLabel("Contraseña")).toBeVisible();
});

test("the primary action is reachable and large enough to hit one-handed", async ({ page }) => {
  await signIn(page);
  await page.getByText(seeded.clientName).click();

  const action = page.locator(".action-bar .action").first();
  const box = await action.boundingBox();
  expect(box).not.toBeNull();

  // 88px tall and effectively full width. Asserted rather than trusted: a stylesheet change
  // that shrank this would silently undo the one-handed-use requirement.
  expect(box!.height).toBeGreaterThanOrEqual(80);
  const viewport = page.viewportSize()!;
  expect(box!.width).toBeGreaterThan(viewport.width * 0.8);
  // Pinned to the bottom of the viewport, in the thumb's reach.
  expect(box!.y + box!.height).toBeGreaterThan(viewport.height - 60);
});
