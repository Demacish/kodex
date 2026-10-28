import { createHmac } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { expect } from "@playwright/test";

import { zlib } from "./zlib";

import type { APIRequestContext, BrowserContext, Page } from "@playwright/test";

/** WCAG 2.1 A and AA (axe): no serious or critical violations on the page as it is now. */
export async function expectAccessible(page: Page, what: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help} (${v.nodes.length}×, e.g. ${v.nodes[0]?.target.join(" ")})`);
  expect(serious, `accessibility of ${what}`).toEqual([]);
}

export const ADMIN = { username: "admin", password: "e2e admin password" };

export async function csrf(context: BrowserContext): Promise<string> {
  const cookie = (await context.cookies()).find((c) => c.name === "kodex_csrf");
  if (!cookie) throw new Error("not logged in");
  return cookie.value;
}

export async function login(page: Page, user = ADMIN) {
  await page.goto("/login");
  await page.getByLabel("Användarnamn").fill(user.username);
  await page.getByLabel("Lösenord", { exact: true }).fill(user.password);
  await page.getByRole("button", { name: "Logga in", exact: true }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

/** The code an authenticator app shows for a base32 secret (RFC 6238). */
export function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((byte) => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1]! & 0x0f;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

/** The API as the logged-in user of ``context``. */
export async function api(context: BrowserContext, request: APIRequestContext, method: "GET" | "POST", path: string, data?: unknown) {
  const response = await request.fetch(path, {
    method,
    data,
    headers: method === "POST" ? { "X-CSRF-Token": await csrf(context) } : {},
  });
  if (!response.ok()) throw new Error(`${method} ${path}: ${response.status()} ${await response.text()}`);
  return response.status() === 204 ? null : response.json();
}

/** A minimal zip (stored, not compressed), enough for an EPUB. */
export function zip(files: [string, string][]): Buffer {
  const local: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const [name, text] of files) {
    const data = Buffer.from(text, "utf8");
    const nameBytes = Buffer.from(name, "utf8");
    const crc = zlib.crc32(data);
    const header = Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50, 0);
    header.writeUInt16LE(20, 4);
    header.writeUInt32LE(crc, 14);
    header.writeUInt32LE(data.length, 18);
    header.writeUInt32LE(data.length, 22);
    header.writeUInt16LE(nameBytes.length, 26);
    local.push(header, nameBytes, data);
    const entry = Buffer.alloc(46);
    entry.writeUInt32LE(0x02014b50, 0);
    entry.writeUInt16LE(20, 4);
    entry.writeUInt16LE(20, 6);
    entry.writeUInt32LE(crc, 16);
    entry.writeUInt32LE(data.length, 20);
    entry.writeUInt32LE(data.length, 24);
    entry.writeUInt16LE(nameBytes.length, 28);
    entry.writeUInt32LE(offset, 42);
    central.push(entry, nameBytes);
    offset += header.length + nameBytes.length + data.length;
  }
  const centralSize = central.reduce((n, b) => n + b.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, ...central, end]);
}

/** An EPUB whose chapter tries to run a script, to prove it can't. */
export function scriptedEpub(title: string): Buffer {
  const chapter = `<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>${title}</title></head><body>
<h1>Script test</h1><p>If this book could run scripts, the page title would change.</p>
<script>try { top.document.title = "pwned"; top.__kodexPwned = true; } catch (e) {} document.body.setAttribute("data-ran", "yes");</script>
<img src="x" onerror="top.__kodexPwned = true" alt="" />
</body></html>`;
  return zip([
    ["mimetype", "application/epub+zip"],
    ["META-INF/container.xml", `<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>`],
    ["content.opf", `<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">kodex-e2e-script</dc:identifier><dc:title>${title}</dc:title><dc:language>en</dc:language></metadata><manifest><item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml" properties="scripted"/></manifest><spine><itemref idref="c1"/></spine></package>`],
    ["chapter1.xhtml", chapter],
  ]);
}
