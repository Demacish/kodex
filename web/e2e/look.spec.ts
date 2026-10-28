import { devices, expect, test, type BrowserContextOptions, type Page } from "@playwright/test";

import { expectAccessible } from "./helpers";

// The pages before login (AuthLayout), dark and light, on a desktop, a phone
// and the tablet Kodex is mostly read on (a Galaxy Tab S10+, 12.4 inches:
// about 1318 × 824 CSS pixels), both ways round. Phones and tablets are
// emulated as mobile browsers, so the viewport meta tag and the device's
// scale apply. Each is checked with axe, for fitting the screen (no
// sideways scrolling, no zooming out, no text under 12 pixels), and
// photographed for looking at by eye (CI keeps web/screenshots). Runs after
// gate.spec.ts made the admin, so /login is the login itself.
const tablet = { deviceScaleFactor: 2.125, isMobile: true, hasTouch: true, userAgent: devices["Galaxy Tab S4"].userAgent };
const DEVICES: Record<string, BrowserContextOptions> = {
  desktop: { viewport: { width: 1440, height: 900 } },
  phone: devices["Pixel 7"],
  "tablet-portrait": { ...tablet, viewport: { width: 824, height: 1318 } },
  "tablet-landscape": { ...tablet, viewport: { width: 1318, height: 824 } },
};

async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
}

async function expectToFit(page: Page, what: string) {
  const fit = await page.evaluate(() => {
    const texts = Array.from(document.querySelectorAll("main *")).filter((element) =>
      Array.from(element.childNodes).some((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim()),
    );
    return {
      width: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
      scale: window.visualViewport?.scale ?? 1,
      smallest: Math.min(...texts.map((element) => parseFloat(getComputedStyle(element).fontSize))),
    };
  });
  expect(fit.width, `${what}: no sideways scrolling`).toBeLessThanOrEqual(fit.viewport + 1);
  expect(fit.scale, `${what}: not zoomed out`).toBe(1);
  expect(fit.smallest, `${what}: no text under 12 px`).toBeGreaterThanOrEqual(12);
}

for (const scheme of ["dark", "light"] as const) {
  for (const [device, options] of Object.entries(DEVICES)) {
    test(`the login, ${scheme}, ${device}`, async ({ browser }) => {
      const context = await browser.newContext({ ...options, colorScheme: scheme, locale: "sv-SE" });
      const page = await context.newPage();
      await page.goto("/login");
      await page.getByRole("button", { name: "Logga in", exact: true }).waitFor();
      await page.getByRole("button", { name: "Visa lösenord" }).waitFor();
      await settle(page);
      await expectAccessible(page, `the login, ${scheme}, ${device}`);
      await expectToFit(page, `the login, ${scheme}, ${device}`);
      await page.screenshot({ path: `screenshots/login-${scheme}-${device}.png`, fullPage: true });

      await page.getByRole("button", { name: "Glömt lösenord?" }).click();
      await page.locator("#forgot").waitFor();
      await page.screenshot({ path: `screenshots/login-forgot-${scheme}-${device}.png`, fullPage: true });

      // A server adopted from v1, whose admins can't log in: the same page with the setup code.
      await page.route("**/api/auth/config", async (route) => {
        const response = await route.fetch();
        await route.fulfill({ response, json: { ...(await response.json()), setup_required: true, setup_code_required: true } });
      });
      await page.reload();
      await page.getByLabel("Uppsättningskod").waitFor();
      await settle(page);
      await expectAccessible(page, `setting up an admin, ${scheme}, ${device}`);
      await expectToFit(page, `setting up an admin, ${scheme}, ${device}`);
      await page.screenshot({ path: `screenshots/setup-${scheme}-${device}.png`, fullPage: true });
      await context.close();
    });
  }
}
