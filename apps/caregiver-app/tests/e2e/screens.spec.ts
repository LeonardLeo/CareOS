import { expect, test } from "@playwright/test";
import { type SeededCaregiver, seedCaregiver } from "./seed";

/**
 * Renders each screen in both colour schemes and saves a screenshot.
 *
 * Not an assertion suite — it exists so the app can be looked at. Every visual bug found in
 * this project so far (white-on-light button text, a zero-count bar drawn with width, an
 * unstyled offline shell) was found by rendering it and looking, not by reading the code.
 */

let seeded: SeededCaregiver;
let queuedShot: SeededCaregiver;

test.beforeAll(async () => {
  seeded = await seedCaregiver();
  queuedShot = await seedCaregiver();
});

for (const scheme of ["light", "dark"] as const) {
  test(`screens render in ${scheme}`, async ({ browser }) => {
    const context = await browser.newContext({
      colorScheme: scheme,
      permissions: ["geolocation"],
      geolocation: { latitude: 43.1566, longitude: -77.6088 },
      viewport: { width: 412, height: 915 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();

    await page.goto("/");
    await page.screenshot({ path: `screenshots/${scheme}-1-login.png` });

    await page.getByLabel(/email/i).fill(seeded.email);
    await page.getByLabel(/password/i).fill(seeded.password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByRole("heading", { name: /today/i })).toBeVisible();
    await page.screenshot({ path: `screenshots/${scheme}-2-today.png` });

    await page.getByText(seeded.clientName).click();
    await expect(page.getByRole("button", { name: /clock in/i })).toBeVisible();
    await page.screenshot({ path: `screenshots/${scheme}-3-visit.png` });

    await context.close();
  });
}

test("the queued-offline state renders", async ({ browser }) => {
  const context = await browser.newContext({
    colorScheme: "light",
    permissions: [],
    viewport: { width: 412, height: 915 },
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();

  await page.goto("/");
  await page.getByLabel(/email/i).fill(queuedShot.email);
  await page.getByLabel(/password/i).fill(queuedShot.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: /today/i })).toBeVisible();

  await page.getByText(queuedShot.clientName).click();
  await context.setOffline(true);
  await page.getByRole("button", { name: /clock in/i }).click();
  await expect(page.getByText(/will send when you have signal/i)).toBeVisible();
  await page.screenshot({ path: "screenshots/light-4-visit-queued.png" });

  await page.getByRole("button", { name: /back/i }).click();
  await expect(page.getByRole("heading", { name: /today/i })).toBeVisible();
  await page.screenshot({ path: "screenshots/light-5-today-queued.png" });

  await context.setOffline(false);
  await context.close();
});
