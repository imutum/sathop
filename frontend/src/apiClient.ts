export function getToken(): string {
  return localStorage.getItem("sathop.token") ?? "";
}

export function setToken(t: string): void {
  localStorage.setItem("sathop.token", t);
}

let recoverOn401 = true;

export function suspendAuthRecovery<T>(fn: () => Promise<T>): Promise<T> {
  recoverOn401 = false;
  return fn().finally(() => {
    recoverOn401 = true;
  });
}

function handleAuthFailure(): void {
  if (!recoverOn401) return;
  if (!localStorage.getItem("sathop.token")) return;
  recoverOn401 = false;
  localStorage.removeItem("sathop.token");
  window.location.reload();
}

export function authHeaders(init?: HeadersInit, jsonBody = false): Headers {
  const headers = new Headers(init);
  headers.set("Authorization", `Bearer ${getToken()}`);
  if (jsonBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

function errorMessage(body: string): string {
  const fallback = body.trim();
  try {
    const j = JSON.parse(body);
    const d = j?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length) return d.map((x) => x?.msg ?? JSON.stringify(x)).join("; ");
  } catch {
    return fallback;
  }
  return fallback;
}

export async function httpError(r: Response, bodyLimit = 400): Promise<Error> {
  const msg = errorMessage(await r.text());
  if (!msg) return new Error(`${r.status} ${r.statusText}`);
  return new Error(msg.length > bodyLimit ? msg.slice(0, bodyLimit) + "…" : msg);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: authHeaders(init.headers, init.body !== undefined),
  });
  if (!r.ok) {
    if (r.status === 401) handleAuthFailure();
    throw await httpError(r);
  }
  return (await r.json()) as T;
}

export function jsonInit(method: string, body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, body: JSON.stringify(body) };
}

export const getJson = <T>(path: string) => api<T>(path);
export const postJson = <T>(path: string, body?: unknown) => api<T>(path, jsonInit("POST", body));
export const putJson = <T>(path: string, body?: unknown) => api<T>(path, jsonInit("PUT", body));
export const deleteJson = <T>(path: string) => api<T>(path, { method: "DELETE" });
