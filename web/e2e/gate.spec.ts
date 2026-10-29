import { writeFileSync } from "node:fs";

import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { ADMIN, ADMIN_TOTP_FILE, api, expectAccessible, login, scriptedEpub, totp } from "./helpers";

// Phase 3's gate (docs/plan.sv.md): a user logs in, scans, reviews, reads
// every format, and sees the position follow to a second browser; then
// adds a passkey and two-step login, and logs in with each. The stack
// starts empty, with only the metadata sources that need no keys: whatever
// they answer for the invented titles, series and books they don't match
// with confidence wait in the review queue.

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext();
  page = await context.newPage();
});

test.afterAll(async () => {
  await context.close();
});

interface Book {
  id: number;
  file_format: string;
  series_id: number | null;
  page_count: number | null;
}

async function books(format: string): Promise<Book[]> {
  const all = (await api(context, page.request, "GET", "/api/books?limit=500")) as Book[];
  return all.filter((book) => book.file_format === format);
}

test("the first visit creates the admin", async () => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Välkommen till Kodex" })).toBeVisible();
  await expectAccessible(page, "the first visit");
  await page.getByLabel("Användarnamn").fill(ADMIN.username);
  await page.getByLabel("Lösenord", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Skapa administratör" }).click();
  await expect(page.getByText("Inga bibliotek ännu")).toBeVisible();
});

test("a wrong password is refused, the right one logs in", async ({ browser }) => {
  const other = await browser.newContext();
  const second = await other.newPage();
  await second.goto("/login");
  await second.getByLabel("Användarnamn").fill(ADMIN.username);
  await second.getByLabel("Lösenord", { exact: true }).fill("not the password");
  await second.getByRole("button", { name: "Logga in", exact: true }).click();
  await expect(second.getByText("Fel användarnamn eller lösenord.")).toBeVisible();
  await login(second);
  await expect(second.getByRole("navigation", { name: "Huvudmeny" }).first()).toBeVisible();
  await other.close();
});

test("the admin adds the libraries and scans them", async () => {
  for (const [name, path, type] of [["Serier", "serier", "Serier"], ["Manga", "manga", "Manga"], ["Böcker", "bocker", "E-böcker"]] as const) {
    await page.goto("/admin/libraries");
    await page.getByRole("button", { name: "Nytt bibliotek" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Namn").fill(name);
    await dialog.getByLabel("Sökväg").fill(path);
    await dialog.getByRole("combobox").click();
    await page.getByRole("option", { name: type, exact: true }).click();
    await dialog.getByRole("button", { name: "Skapa" }).click();
    await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  }
  for (const row of await page.getByRole("button", { name: "Skanna" }).all()) await row.click();
  // The scans run one after another: wait for every library, not just for some books.
  type Library = { id: number; name: string; last_scanned_at: string | null };
  await expect.poll(async () => {
    const libraries = (await api(context, page.request, "GET", "/api/libraries")) as Library[];
    return libraries.filter((library) => library.last_scanned_at).length;
  }, { timeout: 120_000 }).toBe(3);
  const comics = ((await api(context, page.request, "GET", "/api/libraries")) as Library[]).find((library) => library.name === "Serier")!;
  await expect.poll(async () => ((await api(context, page.request, "GET", `/api/series?library_id=${comics.id}`)) as unknown[]).length, { timeout: 60_000 }).toBeGreaterThan(0);
  expect((await books("cbz")).length).toBeGreaterThan(5);
  expect((await books("epub")).length).toBeGreaterThan(0);
  expect((await books("pdf")).length).toBeGreaterThan(0);

  await page.goto("/libraries");
  await page.getByRole("link", { name: /^Serier/ }).first().click();
  await expect(page.locator('a[href^="/series/"]').first()).toBeVisible();
});

test("the review queue decides and undoes", async () => {
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Granskningskö" })).toBeVisible();
  // Matching runs after the scans, as a job: wait until it's done.
  const queue = page.getByRole("list", { name: "Granskningskö" });
  type Job = { kind: string; status: string };
  await expect.poll(async () => {
    const jobs = (await api(context, page.request, "GET", "/api/jobs")) as Job[];
    const matching = jobs.filter((job) => job.kind === "match_library_task");
    return matching.length > 0 && matching.every((job) => job.status === "finished" || job.status === "failed");
  }, { timeout: 180_000, intervals: [5_000] }).toBe(true);
  await page.reload();
  await expect(queue.getByRole("listitem").first()).toBeVisible();
  const before = await queue.getByRole("listitem").count();
  await page.getByRole("button", { name: "Hoppa över (d)" }).click();
  await expect(queue.getByRole("listitem")).toHaveCount(before - 1);
  await page.getByRole("tab", { name: /Överhoppade/ }).click();
  await expect(page.getByRole("list", { name: "Granskningskö" }).getByRole("listitem")).toHaveCount(1);
  await page.getByRole("tab", { name: /Att granska/ }).click();
  await expect(page.getByRole("list", { name: "Granskningskö" }).getByRole("listitem")).toHaveCount(before - 1);
  await page.keyboard.press("u");
  await expect(page.getByRole("list", { name: "Granskningskö" }).getByRole("listitem")).toHaveCount(before);
});

test("the main pages pass an accessibility check", async () => {
  const comics = ((await api(context, page.request, "GET", "/api/libraries")) as { id: number; name: string }[]).find((l) => l.name === "Serier")!;
  const series = (await api(context, page.request, "GET", `/api/series?library_id=${comics.id}`)) as { id: number }[];
  const pages: [string, string][] = [
    ["/", "Hem"],
    ["/libraries", "Bibliotek"],
    [`/libraries/${comics.id}`, "a library"],
    [`/series/${series[0]!.id}`, "a series"],
    ["/search?q=a", "search"],
    ["/settings", "Inställningar"],
    ["/admin/libraries", "the admin's libraries"],
  ];
  for (const [path, what] of pages) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expectAccessible(page, what);
  }
});

test("a comic is read and its position follows to a second browser", async ({ browser }) => {
  const comic = (await books("cbz")).find((book) => (book.page_count ?? 0) >= 6)!;
  await page.goto(`/books/${comic.id}/read`);
  const label = page.locator("p[aria-live=polite]").first();
  await expect(label).toHaveText(`Sida 1 av ${comic.page_count}`);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(label).toHaveText(`Sida 3 av ${comic.page_count}`);
  await expect.poll(async () => (await api(context, page.request, "GET", `/api/books/${comic.id}/progress`))?.position, { timeout: 10_000 }).toBe("2");

  // A second browser: its own login, its own device.
  const otherContext = await browser.newContext({ locale: "sv-SE" });
  const other = await otherContext.newPage();
  await login(other);
  await other.goto(`/books/${comic.id}/read`);
  const otherLabel = other.locator("p[aria-live=polite]").first();
  await expect(otherLabel).toHaveText(`Sida 3 av ${comic.page_count}`);
  await other.keyboard.press("ArrowRight");
  await other.keyboard.press("ArrowRight");
  await expect(otherLabel).toHaveText(`Sida 5 av ${comic.page_count}`);
  await expect.poll(async () => (await api(otherContext, other.request, "GET", `/api/books/${comic.id}/progress`))?.position, { timeout: 10_000 }).toBe("4");

  // The first browser comes back to the tab and is offered the newer position.
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const notice = page.getByRole("status").filter({ hasText: "Du har läst vidare" });
  await expect(notice).toBeVisible();
  await notice.getByRole("button", { name: "Gå dit" }).click();
  await expect(label).toHaveText(`Sida 5 av ${comic.page_count}`);

  const journal = (await api(context, page.request, "GET", `/api/books/${comic.id}/journal`)) as { position: string; device_id: string }[];
  expect(new Set(journal.map((entry) => entry.device_id)).size).toBeGreaterThanOrEqual(2);
  await otherContext.close();
});

test("a PDF is read", async () => {
  const pdf = (await books("pdf"))[0]!;
  await page.goto(`/books/${pdf.id}/read`);
  const label = page.locator("p[aria-live=polite]").first();
  await expect(label).toHaveText(/^Sida 1 av \d+$/);
  await expect.poll(async () => page.locator("canvas").first().evaluate((canvas: HTMLCanvasElement) => canvas.width)).toBeGreaterThan(0);
  await page.keyboard.press("ArrowRight");
  await expect(label).toHaveText(/^Sida 2 av \d+$/);
});

test("an EPUB is read", async () => {
  const epub = (await books("epub"))[0]!;
  await page.goto(`/books/${epub.id}/read`);
  await expect(page.locator("foliate-view")).toBeAttached();
  await expect(page.locator("p[aria-live=polite]").first()).toHaveText(/%/, { timeout: 30_000 });
  await page.getByRole("button", { name: "Innehåll" }).click();
  await expect(page.getByRole("dialog").getByRole("button").first()).toBeVisible();
});

test("a script in a book doesn't run", async () => {
  const libraries = (await api(context, page.request, "GET", "/api/libraries")) as { id: number; name: string }[];
  const shelf = libraries.find((library) => library.name === "Böcker")!;
  const upload = await page.request.post(`/api/libraries/${shelf.id}/upload`, {
    headers: { "X-CSRF-Token": (await context.cookies()).find((c) => c.name === "kodex_csrf")!.value },
    multipart: { file: { name: "Script Test.epub", mimeType: "application/epub+zip", buffer: scriptedEpub("Script Test") }, subfolder: "E2E", rescan: "true" },
  });
  expect(upload.ok()).toBe(true);
  let book: Book | undefined;
  await expect.poll(async () => {
    const all = (await api(context, page.request, "GET", "/api/books?limit=500")) as (Book & { file_path: string })[];
    book = all.find((b) => b.file_path.endsWith("Script Test.epub"));
    return book?.id;
  }, { timeout: 60_000 }).toBeTruthy();

  const violations: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text())) violations.push(message.text());
  });
  await page.goto(`/books/${book!.id}/read`);
  await expect(page.locator("p[aria-live=polite]").first()).toHaveText(/%/, { timeout: 30_000 });
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => (window as unknown as { __kodexPwned?: boolean }).__kodexPwned)).toBeUndefined();
  expect(await page.title()).not.toBe("pwned");
});

test("a passkey and two-step login", async ({ browser }) => {
  // Chrome's virtual authenticator answers in place of a phone or a key.
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true },
  });
  await page.goto("/settings");
  const security = page.getByRole("region", { name: "Inloggning och säkerhet" });
  await security.getByRole("button", { name: "Lägg till passkey" }).click();
  await expect(security.getByRole("list", { name: "Passkeys" }).getByRole("listitem")).toHaveCount(1);

  await security.getByRole("button", { name: "Slå på" }).click();
  const dialog = page.getByRole("dialog");
  const secret = (await dialog.locator("code").textContent())!.trim();
  writeFileSync(ADMIN_TOTP_FILE, secret);
  await dialog.getByLabel("Kod från appen").fill(totp(secret));
  await dialog.getByRole("button", { name: "Slå på" }).click();
  const codes = dialog.getByRole("list", { name: "Reservkoder" }).getByRole("listitem");
  await expect(codes).toHaveCount(10);
  const recovery = (await codes.first().textContent())!;
  await dialog.getByRole("button", { name: "Jag har sparat dem" }).click();
  await expect(security.getByText("10 reservkoder kvar.")).toBeVisible();

  // Another browser: the password, then the second step.
  const other = await browser.newContext();
  const second = await other.newPage();
  await second.goto("/login");
  await second.getByLabel("Användarnamn").fill(ADMIN.username);
  await second.getByLabel("Lösenord", { exact: true }).fill(ADMIN.password);
  await second.getByRole("button", { name: "Logga in", exact: true }).click();
  await expect(second.getByRole("heading", { name: "Tvåstegsverifiering" })).toBeVisible();
  await second.getByLabel("Kod från appen").fill("000000");
  await second.getByRole("button", { name: "Fortsätt" }).click();
  await expect(second.getByText("Fel kod.")).toBeVisible();
  await second.getByRole("button", { name: "Använd en reservkod i stället" }).click();
  await second.getByLabel("Reservkod").fill(recovery);
  await second.getByRole("button", { name: "Fortsätt" }).click();
  await expect(second.getByRole("navigation", { name: "Huvudmeny" }).first()).toBeVisible();
  await other.close();

  // This browser: out, and in again with the passkey alone.
  await page.getByRole("button", { name: "Konto" }).click();
  await page.getByRole("menuitem", { name: "Logga ut" }).click();
  await expect(page).toHaveURL(/\/login/);
  // The virtual authenticator answers the login page's passkey suggestions
  // on its own, which a person would pick from; if it hasn't, the button.
  const elsewhere = (url: URL) => !url.pathname.startsWith("/login");
  const waiting = await page.waitForURL(elsewhere, { timeout: 3_000 }).then(() => false, () => true);
  if (waiting) await page.getByRole("button", { name: "Logga in med passkey" }).click({ timeout: 5_000 }).catch(() => undefined);
  await expect(page.getByRole("navigation", { name: "Huvudmeny" }).first()).toBeVisible();
  await expect(page).not.toHaveURL(/\/login/);
  // Gone before the next test logs out, or it would log straight back in.
  await cdp.send("WebAuthn.removeVirtualAuthenticator", { authenticatorId });
});

test("the admin logs out", async () => {
  await page.goto("/");
  await page.getByRole("button", { name: "Konto" }).click();
  await page.getByRole("menuitem", { name: "Logga ut" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login/);
});
