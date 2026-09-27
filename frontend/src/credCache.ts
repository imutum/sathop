/* Per-credential localStorage cache, AES-GCM-encrypted with a fixed key
 * derived from the literal "sathop". This is *obfuscation*, not real secrecy:
 * the key lives in the shipped JS bundle, so anyone running JS on this origin
 * can decrypt. The threat model is "casual peek at DevTools / localStorage" —
 * not a hostile script (which already wins on this origin).
 *
 * Format: base64( IV[12] || AES-GCM(JSON({scheme,username,secret})) ). */

export type StoredCred = {
  scheme: "basic" | "bearer";
  username: string;
  secret: string;
};

const PREFIX = "sathop.cred.";

export function canRememberCredentials(): boolean {
  return !!globalThis.crypto?.subtle;
}

let keyPromise: Promise<CryptoKey> | undefined;

function cacheKey(): Promise<CryptoKey> {
  // HTTP origins may not expose Web Crypto. Initialize only inside a cache
  // operation so importing the batch page cannot create an unhandled rejection.
  return keyPromise ??= (async () => {
    const raw = new TextEncoder().encode("sathop");
    const hash = await crypto.subtle.digest("SHA-256", raw);
    return crypto.subtle.importKey("raw", hash, "AES-GCM", false, ["encrypt", "decrypt"]);
  })();
}

async function encrypt(plain: string): Promise<string> {
  const key = await cacheKey();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(plain)),
  );
  const blob = new Uint8Array(iv.length + ct.length);
  blob.set(iv);
  blob.set(ct, iv.length);
  let s = "";
  for (const b of blob) s += String.fromCharCode(b);
  return btoa(s);
}

async function decrypt(b64: string): Promise<string> {
  const key = await cacheKey();
  const blob = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  if (blob.length <= 12) throw new Error("ciphertext too short");
  const iv = blob.subarray(0, 12);
  const ct = blob.subarray(12);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ct);
  return new TextDecoder().decode(plain);
}

function parseCred(json: string): StoredCred | null {
  try {
    const v = JSON.parse(json);
    if (typeof v !== "object" || v === null) return null;
    return {
      scheme: v.scheme === "bearer" ? "bearer" : "basic",
      username: typeof v.username === "string" ? v.username : "",
      secret: typeof v.secret === "string" ? v.secret : "",
    };
  } catch {
    return null;
  }
}

export async function loadCred(name: string): Promise<StoredCred | null> {
  if (!canRememberCredentials()) return null;
  let raw: string | null = null;
  // New-format records are AES-GCM ciphertext; legacy records (from the
  // earlier plaintext-JSON revision) are valid JSON. Try decrypt first; on
  // failure fall through to plaintext, the next save will re-encrypt.
  try {
    raw = localStorage.getItem(PREFIX + name);
    if (!raw) return null;
    return parseCred(await decrypt(raw));
  } catch {
    return raw ? parseCred(raw) : null;
  }
}

export async function saveCred(name: string, c: StoredCred): Promise<boolean> {
  if (!canRememberCredentials()) return false;
  try {
    localStorage.setItem(PREFIX + name, await encrypt(JSON.stringify(c)));
    return true;
  } catch {
    return false;
  }
}

export function clearCred(name: string): boolean {
  try {
    localStorage.removeItem(PREFIX + name);
    return true;
  } catch {
    return false;
  }
}

export function hasCred(name: string): boolean {
  try {
    return localStorage.getItem(PREFIX + name) !== null;
  } catch {
    return false;
  }
}
