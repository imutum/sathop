import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const credential = { scheme: "basic" as const, username: "operator", secret: "test-only-value" };

beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
  vi.stubGlobal("crypto", webcrypto);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("optional credential cache", () => {
  it("loads on an HTTP origin without initializing crypto or storing plaintext", async () => {
    vi.stubGlobal("crypto", {});
    const cache = await import("@/credCache");
    expect(cache.canRememberCredentials()).toBe(false);
    expect(await cache.loadCred("source")).toBeNull();
    expect(await cache.saveCred("source", credential)).toBe(false);
    expect(localStorage.length).toBe(0);
  });

  it("round trips encrypted credentials and supports clearing them", async () => {
    const cache = await import("@/credCache");
    expect(await cache.saveCred("source", credential)).toBe(true);
    expect(localStorage.getItem("sathop.cred.source")).not.toContain(credential.secret);
    expect(await cache.loadCred("source")).toEqual(credential);
    expect(cache.hasCred("source")).toBe(true);
    expect(cache.clearCred("source")).toBe(true);
    expect(await cache.loadCred("source")).toBeNull();
  });

  it("can read legacy records and replaces them with encrypted data on save", async () => {
    localStorage.setItem("sathop.cred.source", JSON.stringify(credential));
    const cache = await import("@/credCache");
    expect(await cache.loadCred("source")).toEqual(credential);
    expect(await cache.saveCred("source", credential)).toBe(true);
    expect(localStorage.getItem("sathop.cred.source")).not.toContain(credential.secret);
  });

  it("ignores damaged cache records", async () => {
    localStorage.setItem("sathop.cred.source", "invalid ciphertext");
    const cache = await import("@/credCache");
    expect(await cache.loadCred("source")).toBeNull();
  });

  it("keeps blocked storage and quota failures separate from batch creation", async () => {
    for (const method of ["getItem", "setItem", "removeItem"] as const) {
      vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new Error("Storage blocked"); });
    }
    const cache = await import("@/credCache");
    expect(await cache.loadCred("source")).toBeNull();
    expect(await cache.saveCred("source", credential)).toBe(false);
    expect(cache.hasCred("source")).toBe(false);
    expect(cache.clearCred("source")).toBe(false);
  });

  it("handles a crypto failure without an unhandled rejection or plaintext fallback", async () => {
    const digest = vi.fn().mockRejectedValue(new Error("Crypto unavailable"));
    vi.stubGlobal("crypto", { subtle: { digest } });
    const cache = await import("@/credCache");
    expect(digest).not.toHaveBeenCalled();
    expect(await cache.saveCred("source", credential)).toBe(false);
    expect(localStorage.length).toBe(0);
  });
});
