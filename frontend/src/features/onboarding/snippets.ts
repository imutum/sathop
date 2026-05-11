// Code-snippet generators for the onboarding wizards (receiver + worker).
// Pure functions: take form config, produce a copy-pasteable command string.
// No DOM, no I/O — testable in isolation.
//
// All emitted commands assume a bash-like shell (Linux/macOS/WSL/Git Bash).
// Native Windows PowerShell users must paste into WSL or Git Bash — '\' line
// continuation, `$(id -u)`, and `$(pwd)` are all bash-isms that PowerShell
// would reject. The docs/UI tell users this; we do not try to emit
// PowerShell-compatible alternatives.

// ─── Common helpers ────────────────────────────────────────────────────

export const RECEIVER_IMAGE = "ghcr.io/imutum/sathop/receiver:latest";
export const WORKER_IMAGE = "ghcr.io/imutum/sathop/worker:latest";
// Caddy is still used for caddy mode (public domain + ACME). selfsigned mode
// no longer needs caddy — worker handles internal TLS itself via cryptography.
export const CADDY_IMAGE = "caddy:2-alpine";
export const DEFAULT_GIT_REPO = "https://github.com/imutum/sathop.git";

// Default host paths emitted as placeholders. Absolute so that copy-pasting
// into a different PWD does not silently change the mount target — which
// would lose the worker's persisted self-signed cert across restarts.
export const DEFAULT_RECEIVER_DIR = "/var/lib/sathop/receiver";
export const DEFAULT_WORKER_DIR = "/var/lib/sathop/worker";

// http(s)://host:port  →  sathop(s)://TOKEN@host:port
// Token is %-encoded so a literal '@' or ':' in it can't fracture the URL.
export function buildSathopUrl(orchUrl: string, token: string): string {
  let u: URL;
  try {
    u = new URL(orchUrl);
  } catch {
    return "sathop://INVALID@host:port";
  }
  const scheme = u.protocol === "https:" ? "sathops" : "sathop";
  const host = u.host;
  const path = u.pathname.replace(/\/+$/, "");
  return `${scheme}://${encodeURIComponent(token)}@${host}${path}`;
}

function joinDockerArgs(lines: string[]): string {
  return lines.join(" \\\n  ");
}

// True when `hostDir` is an absolute filesystem path (POSIX `/x` or Windows
// `C:\x`). Anything else — `./x`, `x`, `~/x`, empty — is treated as relative
// for the purpose of warning the operator.
export function isAbsolutePath(hostDir: string): boolean {
  const t = hostDir.trim();
  if (!t) return false;
  return t.startsWith("/") || /^[A-Za-z]:[\\/]/.test(t);
}

// Host paths are wrapped to survive spaces. Relative paths are pinned to the
// invocation PWD via $(pwd); absolute paths are passed through. The modal
// surfaces a warning when the operator enters a relative path because the
// resulting mount silently shifts with PWD.
function mountSrc(hostDir: string): string {
  const trimmed = hostDir.trim();
  if (isAbsolutePath(trimmed)) return `"${trimmed}"`;
  const d = trimmed.replace(/^\.\//, "").replace(/^\.\\/, "");
  return `"$(pwd)/${d}"`;
}

// ─── Receiver ──────────────────────────────────────────────────────────

// strict      = system CAs (publicly-trusted certs only)
// trust-orch  = fetch orchestrator-aggregated worker CA bundle, verify against it
// insecure    = skip TLS verification entirely (escape hatch)
export type TlsMode = "strict" | "trust-orch" | "insecure";

export type ReceiverConfig = {
  receiverId: string;
  token: string;
  orchUrl: string;
  outputDir: string;
  concurrent: number;
  poll: number;
  tlsMode: TlsMode;
};

function receiverEnv(cfg: ReceiverConfig, sathopUrl: string): Array<[string, string]> {
  const out: Array<[string, string]> = [
    ["SATHOP_RECEIVER_ID", cfg.receiverId],
    ["SATHOP_URL", sathopUrl],
  ];
  if (cfg.concurrent !== 4) out.push(["SATHOP_CONCURRENT_PULLS", String(cfg.concurrent)]);
  if (cfg.poll !== 10) out.push(["SATHOP_POLL_INTERVAL", String(cfg.poll)]);
  // Receiver defaults to SATHOP_TLS_TRUST_ORCH=true (see receiver/config.py).
  // "strict" must explicitly opt out, otherwise the UI label "只信任系统 CA"
  // would not match runtime behaviour (receiver would still fetch + trust
  // the orch-aggregated worker CA bundle).
  if (cfg.tlsMode === "strict") out.push(["SATHOP_TLS_TRUST_ORCH", "false"]);
  if (cfg.tlsMode === "insecure") out.push(["SATHOP_TLS_VERIFY", "false"]);
  return out;
}

export function receiverDockerRun(cfg: ReceiverConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const lines: string[] = [
    "docker run -d",
    "--name sathop-receiver",
    "--restart unless-stopped",
    "--user $(id -u):$(id -g)",
    ...receiverEnv(cfg, sathopUrl).map(([k, v]) => `-e ${k}="${v}"`),
    `-v ${mountSrc(cfg.outputDir)}:/data/archive`,
    RECEIVER_IMAGE,
  ];
  return joinDockerArgs(lines);
}

export function receiverDockerCompose(cfg: ReceiverConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const envLines = receiverEnv(cfg, sathopUrl)
    .map(([k, v]) => `      ${k}: "${v}"`)
    .join("\n");
  return `services:
  receiver:
    image: ${RECEIVER_IMAGE}
    restart: unless-stopped
    user: "\${UID:-1000}:\${GID:-1000}"
    environment:
${envLines}
    volumes:
      - ${cfg.outputDir}:/data/archive
`;
}

export function receiverUvx(cfg: ReceiverConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const lines: string[] = [
    `uvx --from 'sathop[receiver] @ git+${DEFAULT_GIT_REPO}'`,
    `sathop-pull`,
    `--url '${sathopUrl}'`,
    `--id '${cfg.receiverId}'`,
    `--dir '${cfg.outputDir}'`,
  ];
  if (cfg.concurrent !== 4) lines.push(`--concurrent ${cfg.concurrent}`);
  if (cfg.poll !== 10) lines.push(`--poll ${cfg.poll}`);
  if (cfg.tlsMode === "trust-orch") lines.push("--trust-orch-ca");
  if (cfg.tlsMode === "insecure") lines.push("--insecure-tls");
  return joinDockerArgs(lines);
}

// Preflight hint: ensure host dir exists and is owned by current user before
// `docker run --user $(id -u):$(id -g)` mounts it. sudo is unconditional —
// the default placeholder is an absolute path under /var/lib that the
// operator's account does not own. Relative paths still work; sudo there is
// harmless (just a no-op chown on already-owned dirs).
export function hostDirPrestep(outputDir: string): string {
  return `sudo mkdir -p ${outputDir} && sudo chown -R "$(id -u):$(id -g)" ${outputDir}`;
}

export function receiverOpsHint(): string {
  return `# 查看日志：docker logs -f sathop-receiver
# 停止：    docker stop sathop-receiver && docker rm sathop-receiver`;
}

// ─── Worker ────────────────────────────────────────────────────────────

export type ExposeMode = "caddy" | "selfsigned" | "direct";

export type WorkerConfig = {
  workerId: string;
  token: string;
  orchUrl: string;
  exposeMode: ExposeMode;
  domain: string; // for caddy mode
  ipAddress: string; // for selfsigned mode
  hostPort: string; // "ip:port" for direct mode
  storagePort: number;
  dataDir: string;
  capacity: number;
  heartbeat: number;
  downloadConcurrency: number;
};

// Parse "ip" or "ip:port" or "[::1]:port" into the URL's host portion (the
// part after the scheme, before the first /). IPv6 literals must already be
// bracket-wrapped — same expectation as `URL`.
function parseHostPort(raw: string): { host: string; port: number | null } {
  const cleaned = raw.trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
  if (!cleaned) return { host: "", port: null };
  try {
    // `URL` rejects bare host:port without a scheme; prepending one is the
    // canonical workaround and lets us reuse the spec-correct parser for
    // IPv6 brackets, IDN hostnames, etc.
    const u = new URL(`https://${cleaned}`);
    return { host: u.host.replace(/:\d+$/, "").replace(/^\[|\]$/g, ""), port: u.port ? Number(u.port) : null };
  } catch {
    return { host: cleaned, port: null };
  }
}

// True when the host part of `raw` (with optional ":port") is a private /
// internal address: RFC 1918, loopback, link-local, RFC 6598 CGNAT, IPv6 ULA
// / loopback / link-local. Bare hostnames pass — assume the operator knows
// their DNS. Empty input returns false (treated as invalid).
//
// Used by the worker onboarding modal to gate `direct` (plaintext HTTP) mode:
// receivers pulling over HTTP across the public internet would expose every
// byte, so direct mode is restricted to internal addressing.
export function isPrivateHost(raw: string): boolean {
  const { host } = parseHostPort(raw);
  if (!host) return false;
  const ipv4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (ipv4) {
    const a = +ipv4[1]!;
    const b = +ipv4[2]!;
    const c = +ipv4[3]!;
    const d = +ipv4[4]!;
    if (a > 255 || b > 255 || c > 255 || d > 255) return false;
    if (a === 10) return true;
    if (a === 127) return true;
    if (a === 169 && b === 254) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
    if (a === 192 && b === 168) return true;
    if (a === 100 && b >= 64 && b <= 127) return true;
    return false;
  }
  if (host.includes(":")) {
    const lower = host.toLowerCase();
    if (lower === "::1") return true;
    if (/^f[cd][0-9a-f]/.test(lower)) return true; // fc00::/7
    if (/^fe[89ab][0-9a-f]/.test(lower)) return true; // fe80::/10
    return false;
  }
  return true; // hostname — operator's call
}

export function workerPublicUrl(cfg: WorkerConfig): string {
  if (cfg.exposeMode === "caddy") {
    const d = cfg.domain.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
    return d ? `https://${d}` : "https://<your-domain>";
  }
  if (cfg.exposeMode === "selfsigned") {
    const { host, port } = parseHostPort(cfg.ipAddress);
    if (!host) return "https://<worker-ip>";
    // 443 is implicit in https://; emit explicitly only for non-default
    // ports so the URL stays clean when operators stick with the default.
    return port && port !== 443 ? `https://${host}:${port}` : `https://${host}`;
  }
  const hp = cfg.hostPort.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
  return hp ? `http://${hp}` : `http://<host>:${cfg.storagePort}`;
}

function workerEnv(cfg: WorkerConfig, sathopUrl: string): Array<[string, string]> {
  const out: Array<[string, string]> = [
    ["SATHOP_WORKER_ID", cfg.workerId],
    ["SATHOP_PUBLIC_URL", workerPublicUrl(cfg)],
    ["SATHOP_URL", sathopUrl],
  ];
  if (cfg.capacity !== 20) out.push(["SATHOP_CAPACITY", String(cfg.capacity)]);
  if (cfg.heartbeat !== 15) out.push(["SATHOP_HEARTBEAT", String(cfg.heartbeat)]);
  if (cfg.downloadConcurrency !== 1)
    out.push(["SATHOP_DOWNLOAD_CONCURRENCY", String(cfg.downloadConcurrency)]);
  if (cfg.storagePort !== 9000) out.push(["SATHOP_STORAGE_PORT", String(cfg.storagePort)]);
  return out;
}

// Host-side port to publish in the docker -p mapping. selfsigned mode reads
// it from the IP field (operator may write `192.168.1.50:8443` to use a
// non-443 port); falls back to 443 when only an IP is given. Other modes
// keep the conventional storagePort (container-internal, 9000 by default).
function hostPortFor(cfg: WorkerConfig): number {
  if (cfg.exposeMode !== "selfsigned") return cfg.storagePort;
  const { port } = parseHostPort(cfg.ipAddress);
  return port ?? 443;
}

export function workerDockerRun(cfg: WorkerConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const workerLines: string[] = [
    "docker run -d",
    "--name sathop-worker",
    "--restart unless-stopped",
    "--user $(id -u):$(id -g)",
    ...workerEnv(cfg, sathopUrl).map(([k, v]) => `-e ${k}="${v}"`),
    `-p ${hostPortFor(cfg)}:${cfg.storagePort}`,
    `-v ${mountSrc(cfg.dataDir)}:/app/data`,
    WORKER_IMAGE,
  ];
  const worker = "# --- Worker ---\n" + joinDockerArgs(workerLines);

  if (cfg.exposeMode !== "caddy") return worker;

  // caddy mode: public domain + ACME. selfsigned and direct modes don't
  // need an extra container — selfsigned is handled by worker's built-in
  // Python self-signed cert; direct is plain HTTP.
  const domain = cfg.domain.trim() || "your-domain.example.com";
  const caddyLines: string[] = [
    "docker run -d",
    "--name sathop-caddy",
    "--restart unless-stopped",
    "--add-host=host.docker.internal:host-gateway",
    "-p 80:80 -p 443:443",
    "-v caddy_data:/data",
    "-v caddy_config:/config",
    CADDY_IMAGE,
    "caddy reverse-proxy",
    `--from ${domain}`,
    `--to host.docker.internal:${cfg.storagePort}`,
  ];
  const caddy =
    "# --- Caddy 反向代理 (HTTPS 自动签发 + 续签) ---\n" + joinDockerArgs(caddyLines);
  return `${worker}\n\n${caddy}`;
}

export function workerDockerCompose(cfg: WorkerConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const envLines = workerEnv(cfg, sathopUrl)
    .map(([k, v]) => `      ${k}: "${v}"`)
    .join("\n");
  const portLine = `    ports:\n      - "${hostPortFor(cfg)}:${cfg.storagePort}"\n`;

  let body = `services:
  worker:
    image: ${WORKER_IMAGE}
    restart: unless-stopped
    user: "\${UID:-1000}:\${GID:-1000}"
    environment:
${envLines}
${cfg.exposeMode !== "caddy" ? portLine : ""}    volumes:
      - ${cfg.dataDir}:/app/data
`;

  if (cfg.exposeMode === "caddy") {
    const domain = cfg.domain.trim() || "your-domain.example.com";
    body += `
  caddy:
    image: ${CADDY_IMAGE}
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    command: caddy reverse-proxy --from ${domain} --to worker:${cfg.storagePort}
    volumes:
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - worker

volumes:
  caddy_data:
  caddy_config:
`;
  }

  return body;
}

export function workerOpsHint(): string {
  return `# 查看日志：docker logs -f sathop-worker
# 停止：    docker stop sathop-worker && docker rm sathop-worker`;
}
