/**
 * Passkeys (WebAuthn) through @simplewebauthn/browser: the backend hands
 * out the options with a ticket (kodex/core/auth/passkeys.py), the browser
 * asks the phone, computer or security key, and the answer goes back with
 * the ticket.
 */
import {
  browserSupportsWebAuthn,
  browserSupportsWebAuthnAutofill,
  startAuthentication,
  startRegistration,
  WebAuthnAbortService,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";

import { fetchClient, type Schemas } from "@/api/client";
import type { Account } from "@/lib/account";

export function passkeysSupported(): boolean {
  return browserSupportsWebAuthn();
}

export { browserSupportsWebAuthnAutofill };

/** Whether the person closed the browser's dialog (or it was replaced by another). */
export function wasCancelled(error: unknown): boolean {
  return error instanceof Error && (error.name === "NotAllowedError" || error.name === "AbortError");
}

export class PasskeyFailed extends Error {}

function detail(error: unknown): string | undefined {
  return error && typeof error === "object" && "detail" in error && typeof error.detail === "string" ? error.detail : undefined;
}

/** Adds a passkey to the logged-in account. */
export async function addPasskey(name: string): Promise<Schemas["PasskeyOut"]> {
  const ceremony = await fetchClient.POST("/api/auth/passkeys/options");
  if (!ceremony.data) throw new PasskeyFailed(detail(ceremony.error));
  const credential = await startRegistration({ optionsJSON: ceremony.data.options as unknown as PublicKeyCredentialCreationOptionsJSON });
  const added = await fetchClient.POST("/api/auth/passkeys", {
    body: { ticket: ceremony.data.ticket, credential: credential as unknown as Record<string, unknown>, name },
  });
  if (!added.data) throw new PasskeyFailed(detail(added.error));
  return added.data;
}

/**
 * Logs in with a passkey: any of this site's, or with a password login's
 * second-step ticket, one of that account's. `autofill` waits for the
 * person to pick one in the username field's suggestions instead of
 * opening a dialog.
 */
export async function loginWithPasskey({ ticket, autofill = false, remember = true }: { ticket?: string; autofill?: boolean; remember?: boolean } = {}): Promise<Account> {
  const ceremony = await fetchClient.POST("/api/auth/passkeys/login/options", { body: { ticket: ticket ?? null } });
  if (!ceremony.data) throw new PasskeyFailed(detail(ceremony.error));
  const credential = await startAuthentication({
    optionsJSON: ceremony.data.options as unknown as PublicKeyCredentialRequestOptionsJSON,
    useBrowserAutofill: autofill,
  });
  const done = await fetchClient.POST("/api/auth/passkeys/login", {
    body: { ticket: ceremony.data.ticket, credential: credential as unknown as Record<string, unknown>, remember },
  });
  if (!done.data) throw new PasskeyFailed(detail(done.error));
  return done.data;
}

export function cancelPasskeyPrompt() {
  WebAuthnAbortService.cancelCeremony();
}
