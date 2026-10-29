import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

import { devices, expect, test, type BrowserContext, type BrowserContextOptions, type Page } from "@playwright/test";

import { ADMIN, ADMIN_TOTP_FILE, api, expectAccessible, totp } from "./helpers";

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

/**
 * The whole page, taller than the screen: the viewport grows to the page's height for the shot.
 * (Playwright's fullPage drops Chromium's touch emulation while it captures, so a touch screen's
 * page would be photographed with a mouse's sizes.)
 */
async function photograph(page: Page, path: string) {
  const viewport = page.viewportSize()!;
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  if (height > viewport.height) {
    await page.setViewportSize({ width: viewport.width, height: Math.min(height, 8000) });
    await page.waitForTimeout(200);
  }
  await page.screenshot({ path });
  if (height > viewport.height) await page.setViewportSize(viewport);
}

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
      await photograph(page, `screenshots/login-${scheme}-${device}.png`);

      await page.getByRole("button", { name: "Glömt lösenord?" }).click();
      await page.locator("#forgot").waitFor();
      await photograph(page, `screenshots/login-forgot-${scheme}-${device}.png`);

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
      await photograph(page, `screenshots/setup-${scheme}-${device}.png`);
      await context.close();
    });
  }
}

// The app's pages after login, as the admin (gate.spec.ts turned two-step
// login on and left the secret), on the same devices. Each page is
// photographed and must fit: no sideways scrolling, no text under 12
// pixels and, on the touch screens, nothing to tap smaller than 24 pixels
// (WCAG 2.5.8; a link inside running text excepted). The measurements go
// to screenshots/app/fit-<device>-<scheme>.json as well.
interface Fit {
  width: number;
  viewport: number;
  smallest: number;
  smallText: string[];
  smallTargets: string[];
  overflowing: string[];
}

async function measure(page: Page): Promise<Fit> {
  return page.evaluate(() => {
    // Visually hidden (sr-only, a native input under a styled control) or not laid out.
    const hidden = (element: Element) => {
      for (let node: Element | null = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.clipPath === "inset(50%)" || style.clip.startsWith("rect(0") || style.opacity === "0" || style.visibility === "hidden") return true;
      }
      return false;
    };
    const shown = (element: Element) => {
      const box = element.getBoundingClientRect();
      return box.width > 1 && box.height > 1 && !hidden(element);
    };
    const name = (element: Element) => {
      const text = (element.getAttribute("aria-label") ?? element.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 40);
      return `${element.tagName.toLowerCase()}${text ? ` "${text}"` : ""}`;
    };
    // The box a finger can hit: the element's, widened by an absolutely placed ::after (the
    // checkbox's, the switch's and the slider thumb's larger hit areas).
    const hitBox = (element: Element) => {
      const box = element.getBoundingClientRect();
      const after = getComputedStyle(element, "::after");
      if (after.content === "none" || after.position !== "absolute") return { width: box.width, height: box.height };
      const out = (value: string) => Math.max(0, -parseFloat(value) || 0);
      return { width: box.width + out(after.left) + out(after.right), height: box.height + out(after.top) + out(after.bottom) };
    };
    const all = Array.from(document.querySelectorAll("body *")).filter(shown);
    const texts = all.filter((element) => Array.from(element.childNodes).some((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim()));
    const size = (element: Element) => parseFloat(getComputedStyle(element).fontSize);
    const targets = all.filter((element) =>
      element.matches("a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=tab], [role=checkbox], [role=switch], [role=slider], [role=combobox], [role=menuitem], [role=menuitemradio], [role=option]")
      && !(element.matches("a") && element.closest("p")),
    );
    // Sticking out past the right edge, unless a scrolling or clipping box around it holds it.
    const held = (element: Element) => {
      for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
        if (getComputedStyle(parent).overflowX !== "visible" && parent.getBoundingClientRect().right <= window.innerWidth + 1) return true;
      }
      return false;
    };
    return {
      width: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
      smallest: Math.min(...texts.map(size)),
      smallText: [...new Set(texts.filter((element) => size(element) < 12).map((element) => `${size(element)}px ${name(element)}`))].slice(0, 15),
      smallTargets: [...new Set(targets.filter((element) => {
        const box = hitBox(element);
        return box.width < 24 || box.height < 24;
      }).map((element) => {
        const box = hitBox(element);
        return `${Math.round(box.width)}×${Math.round(box.height)} ${name(element)}`;
      }))].slice(0, 15),
      overflowing: all.filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1 && !held(element)).map(name).slice(0, 10),
    };
  });
}

function expectFits(fit: Fit, what: string, viewport: number, touch: boolean) {
  expect.soft(fit.width, `${what}: no sideways scrolling (${fit.overflowing.join(", ")})`).toBeLessThanOrEqual(viewport + 1);
  expect.soft(fit.viewport, `${what}: not zoomed out`).toBe(viewport);
  expect.soft(fit.smallText, `${what}: no text under 12 px`).toEqual([]);
  if (touch) expect.soft(fit.smallTargets, `${what}: nothing to tap under 24 px`).toEqual([]);
}

interface Targets {
  comics: number;
  series: number;
  comic: number;
  epub: number;
  pdf: number;
}

test.describe("the app's pages", () => {
  let storageState: Awaited<ReturnType<BrowserContext["storageState"]>>;
  let targets: Targets;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({ locale: "sv-SE" });
    const page = await context.newPage();
    await page.goto("/login");
    await page.getByLabel("Användarnamn").fill(ADMIN.username);
    await page.getByLabel("Lösenord", { exact: true }).fill(ADMIN.password);
    await page.getByRole("button", { name: "Logga in", exact: true }).click();
    await page.getByLabel("Kod från appen").fill(totp(readFileSync(ADMIN_TOTP_FILE, "utf8").trim()));
    await page.getByRole("button", { name: "Fortsätt" }).click();
    await page.getByRole("navigation", { name: "Huvudmeny" }).first().waitFor();

    const libraries = (await api(context, page.request, "GET", "/api/libraries")) as { id: number; name: string }[];
    const comics = libraries.find((library) => library.name === "Serier")!.id;
    const series = (await api(context, page.request, "GET", `/api/series?library_id=${comics}`)) as { id: number }[];
    type Book = { id: number; file_format: string; file_path: string; page_count: number | null };
    const books = (await api(context, page.request, "GET", "/api/books?limit=500")) as Book[];
    const first = (format: string) => books.find((book) => book.file_format === format && !book.file_path.endsWith("Script Test.epub"))!.id;
    targets = {
      comics,
      series: series[0]!.id,
      comic: books.find((book) => book.file_format === "cbz" && (book.page_count ?? 0) >= 6)!.id,
      epub: first("epub"),
      pdf: first("pdf"),
    };
    storageState = await context.storageState();
    await context.close();
  });

  const pages = (t: Targets): [string, string][] => [
    ["home", "/"],
    ["libraries", "/libraries"],
    ["library", `/libraries/${t.comics}`],
    ["series", `/series/${t.series}`],
    ["book", `/books/${t.comic}`],
    ["search", "/search?q=a"],
    ["collections", "/collections"],
    ["following", "/following"],
    ["discover", "/discover"],
    ["releases", "/releases"],
    ["requests", "/requests"],
    ["stats", "/stats"],
    ["settings", "/settings"],
    ["admin-review", "/admin"],
    ["admin-libraries", "/admin/libraries"],
    ["admin-users", "/admin/users"],
    ["admin-jobs", "/admin/jobs"],
    ["admin-stats", "/admin/stats"],
    ["admin-missing", "/admin/missing"],
    ["admin-duplicates", "/admin/duplicates"],
    ["admin-page-flags", "/admin/page-flags"],
    ["admin-integrations", "/admin/integrations"],
    ["admin-import", "/admin/import"],
  ];

  const runs: [string, "dark" | "light"][] = [
    ["phone", "dark"],
    ["phone", "light"],
    ["tablet-portrait", "dark"],
    ["tablet-landscape", "dark"],
    ["desktop", "dark"],
  ];
  for (const [device, scheme] of runs) {
    test(`photographed, ${scheme}, ${device}`, async ({ browser }) => {
      test.setTimeout(10 * 60_000);
      const options = DEVICES[device]!;
      const viewport = options.viewport!.width;
      const touch = options.hasTouch === true;
      const context = await browser.newContext({ ...options, colorScheme: scheme, locale: "sv-SE", storageState });
      const page = await context.newPage();
      await page.goto("/");
      // The touch sizes hang on this media query; the emulated touch screens must match it.
      expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches), "pointer: coarse").toBe(touch);
      const dir = `screenshots/app/${device}-${scheme}`;
      mkdirSync(dir, { recursive: true });
      const report: Record<string, Fit> = {};
      for (const [name, path] of pages(targets)) {
        await page.goto(path);
        await page.locator("main").waitFor();
        await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => undefined);
        await settle(page);
        report[name] = await measure(page);
        expectFits(report[name], `${name}, ${device}`, viewport, touch);
        await photograph(page, `${dir}/${name}.png`);
        if (name === "home") {
          await page.getByRole("button", { name: "Konto" }).click();
          await page.getByRole("menu").waitFor();
          await settle(page);
          report["account-menu"] = await measure(page);
          expectFits(report["account-menu"], `the account menu, ${device}`, viewport, touch);
          await page.screenshot({ path: `${dir}/account-menu.png` });
          await page.keyboard.press("Escape");
          if (device === "phone") {
            await page.getByRole("navigation", { name: "Huvudmeny" }).getByRole("button", { name: "Mer" }).click();
            await page.getByRole("dialog").waitFor();
            await settle(page);
            report["more"] = await measure(page);
            expectFits(report["more"], `Mer, ${device}`, viewport, touch);
            await page.screenshot({ path: `${dir}/more.png` });
            await page.keyboard.press("Escape");
          }
        }
      }
      for (const [name, id] of [["read-comic", targets.comic], ["read-epub", targets.epub], ["read-pdf", targets.pdf]] as const) {
        await page.goto(`/books/${id}/read`);
        await expect(page.locator("p[aria-live=polite]").first()).toHaveText(/\S/, { timeout: 30_000 }).catch(() => undefined);
        await page.waitForTimeout(1_500);
        report[name] = await measure(page);
        expectFits(report[name], `${name}, ${device}`, viewport, touch);
        await page.screenshot({ path: `${dir}/${name}.png` });
      }
      writeFileSync(`screenshots/app/fit-${device}-${scheme}.json`, JSON.stringify(report, null, 2));
      await context.close();
    });
  }
});
