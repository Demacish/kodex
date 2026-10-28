import { test, type Page } from "@playwright/test";

import { expectAccessible } from "./helpers";

// The pages before login (AuthLayout), dark and light, on a desktop and a
// phone: checked with axe, and photographed for looking at by eye (CI keeps
// web/screenshots as an artifact). Runs after gate.spec.ts made the admin,
// so /login is the login itself.
const SIZES = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } };

async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
}

for (const scheme of ["dark", "light"] as const) {
  for (const [size, viewport] of Object.entries(SIZES)) {
    test(`the login, ${scheme}, ${size}`, async ({ browser }) => {
      const context = await browser.newContext({ viewport, colorScheme: scheme, locale: "sv-SE" });
      const page = await context.newPage();
      await page.goto("/login");
      await page.getByRole("button", { name: "Logga in", exact: true }).waitFor();
      await page.getByRole("button", { name: "Visa lösenord" }).waitFor();
      await settle(page);
      await expectAccessible(page, `the login, ${scheme}, ${size}`);
      await page.screenshot({ path: `screenshots/login-${scheme}-${size}.png`, fullPage: true });

      await page.getByRole("button", { name: "Glömt lösenord?" }).click();
      await page.locator("#forgot").waitFor();
      await page.screenshot({ path: `screenshots/login-forgot-${scheme}-${size}.png`, fullPage: true });

      // A server adopted from v1, whose admins can't log in: the same page with the setup code.
      await page.route("**/api/auth/config", async (route) => {
        const response = await route.fetch();
        await route.fulfill({ response, json: { ...(await response.json()), setup_required: true, setup_code_required: true } });
      });
      await page.reload();
      await page.getByLabel("Uppsättningskod").waitFor();
      await settle(page);
      await expectAccessible(page, `setting up an admin, ${scheme}, ${size}`);
      await page.screenshot({ path: `screenshots/setup-${scheme}-${size}.png`, fullPage: true });
      await context.close();
    });
  }
}
