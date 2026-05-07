// Code-snippet generators for the onboarding wizards (receiver + worker).
// Pure functions: take form config, produce a copy-pasteable command string.
// No DOM, no I/O — testable in isolation.

export type Platform = "linux" | "windows";

// ─── Common helpers ────────────────────────────────────────────────────

export const RECEIVER_IMAGE = "ghcr.io/imutum/sathop/receiver:latest";
export const WORKER_IMAGE = "ghcr.io/imutum/sathop/worker:latest";
export const CADDY_IMAGE = "caddy:2-alpine";
export const DEFAULT_GIT_REPO = "https://github.com/imutum/sathop.git";

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

// Linux/macOS uses '\' for line continuation; PowerShell uses backtick '`'.
function linecont(p: Platform): string {
  return p === "linux" ? "\\" : "`";
}

function joinDockerArgs(lines: string[], p: Platform): string {
  return lines.join(` ${linecont(p)}\n  `);
}

function userFlag(p: Platform): string[] {
  return p === "linux" ? ["--user $(id -u):$(id -g)"] : [];
}

function mountSrc(p: Platform, hostDir: string): string {
  const d = hostDir.replace(/^\.\//, "").replace(/^\.\\/, "");
  return p === "linux" ? `"$(pwd)/${d}"` : `"\${PWD}/${d}"`;
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
  platform: Platform;
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
  if (cfg.tlsMode === "insecure") out.push(["SATHOP_TLS_VERIFY", "false"]);
  if (cfg.tlsMode === "trust-orch") out.push(["SATHOP_TLS_TRUST_ORCH", "true"]);
  return out;
}

export function receiverDockerRun(cfg: ReceiverConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const lines: string[] = [
    "docker run -d",
    "--name sathop-receiver",
    "--restart unless-stopped",
    ...userFlag(cfg.platform),
    ...receiverEnv(cfg, sathopUrl).map(([k, v]) => `-e ${k}="${v}"`),
    `-v ${mountSrc(cfg.platform, cfg.outputDir)}:/data/archive`,
    RECEIVER_IMAGE,
  ];
  return joinDockerArgs(lines, cfg.platform);
}

export function receiverDockerCompose(cfg: ReceiverConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const userLine = cfg.platform === "linux" ? '    user: "${UID:-1000}:${GID:-1000}"\n' : "";
  const envLines = receiverEnv(cfg, sathopUrl)
    .map(([k, v]) => `      ${k}: "${v}"`)
    .join("\n");
  return `services:
  receiver:
    image: ${RECEIVER_IMAGE}
    restart: unless-stopped
${userLine}    environment:
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
  return joinDockerArgs(lines, cfg.platform);
}

// Linux preflight hint: ensure host dir exists and is owned by current user
// before docker run mounts it (otherwise --user can't mkdir into root-owned mount).
export function linuxPrestep(outputDir: string): string {
  return `mkdir -p ${outputDir} && sudo chown -R "$(id -u):$(id -g)" ${outputDir}`;
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
  platform: Platform;
  capacity: number;
  heartbeat: number;
  downloadConcurrency: number;
};

export function workerPublicUrl(cfg: WorkerConfig): string {
  if (cfg.exposeMode === "caddy") {
    const d = cfg.domain.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
    return d ? `https://${d}` : "https://<your-domain>";
  }
  if (cfg.exposeMode === "selfsigned") {
    const ip = cfg.ipAddress.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
    return ip ? `https://${ip}` : "https://<worker-ip>";
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

export function workerDockerRun(cfg: WorkerConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  // selfsigned mode: worker reads Caddy's root CA from a shared volume and
  // uploads at register time, so receivers can pin trust via /api/receivers/ca-bundle.
  // Caddy's pki/ dir is 700 (protects CA private key) — worker must be root to
  // descend into it. Other modes can stay as the host user since worker /app/data
  // is internal cache, not user-facing output.
  const caddyDataMount =
    cfg.exposeMode === "selfsigned" ? ["-v caddy_data:/caddy-data:ro"] : [];
  const userLines = cfg.exposeMode === "selfsigned" ? [] : userFlag(cfg.platform);
  const workerLines: string[] = [
    "docker run -d",
    "--name sathop-worker",
    "--restart unless-stopped",
    ...userLines,
    ...workerEnv(cfg, sathopUrl).map(([k, v]) => `-e ${k}="${v}"`),
    `-p ${cfg.storagePort}:${cfg.storagePort}`,
    `-v ${mountSrc(cfg.platform, cfg.dataDir)}:/app/data`,
    ...caddyDataMount,
    WORKER_IMAGE,
  ];
  const worker = "# --- Worker ---\n" + joinDockerArgs(workerLines, cfg.platform);

  if (cfg.exposeMode === "direct") return worker;

  if (cfg.exposeMode === "caddy") {
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
      "# --- Caddy 反向代理 (HTTPS 自动签发 + 续签) ---\n" + joinDockerArgs(caddyLines, cfg.platform);
    return `${worker}\n\n${caddy}`;
  }

  // selfsigned: Caddy CLI does not support `tls internal`; need a Caddyfile.
  const ip = cfg.ipAddress.trim() || "192.168.1.50";
  const caddyfileBody = `{
    auto_https disable_redirects
}

https://${ip} {
    tls internal
    reverse_proxy host.docker.internal:${cfg.storagePort}
}`;
  const heredoc =
    cfg.platform === "linux"
      ? `cat > Caddyfile <<'EOF'\n${caddyfileBody}\nEOF`
      : `@'\n${caddyfileBody}\n'@ | Set-Content -Encoding utf8 Caddyfile`;
  const caddyVolume =
    cfg.platform === "linux"
      ? `-v "$(pwd)/Caddyfile:/etc/caddy/Caddyfile:ro"`
      : `-v "\${PWD}/Caddyfile:/etc/caddy/Caddyfile:ro"`;
  const caddyLines: string[] = [
    "docker run -d",
    "--name sathop-caddy",
    "--restart unless-stopped",
    "--add-host=host.docker.internal:host-gateway",
    "-p 443:443",
    caddyVolume,
    "-v caddy_data:/data",
    "-v caddy_config:/config",
    CADDY_IMAGE,
  ];
  const caddyfileSection = "# --- Caddyfile (写入当前目录) ---\n" + heredoc;
  const caddyContainer =
    "# --- Caddy 反向代理 (HTTPS 自签 IP 证书) ---\n" + joinDockerArgs(caddyLines, cfg.platform);
  return `${worker}\n\n${caddyfileSection}\n\n${caddyContainer}`;
}

export function workerDockerCompose(cfg: WorkerConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  // selfsigned mode: worker stays root to read Caddy's 700-mode pki dir; other
  // modes keep host UID for friendlier file ownership on bind-mounted ./data.
  const userLine =
    cfg.platform === "linux" && cfg.exposeMode !== "selfsigned"
      ? '    user: "${UID:-1000}:${GID:-1000}"\n'
      : "";
  const envLines = workerEnv(cfg, sathopUrl)
    .map(([k, v]) => `      ${k}: "${v}"`)
    .join("\n");
  const portLine = `    ports:\n      - "${cfg.storagePort}:${cfg.storagePort}"\n`;

  // selfsigned mode: worker mounts caddy_data:ro to read Caddy's root CA and
  // upload it on register, so receivers can pin trust via the orchestrator.
  const caddyDataVol =
    cfg.exposeMode === "selfsigned" ? "      - caddy_data:/caddy-data:ro\n" : "";
  let body = `services:
  worker:
    image: ${WORKER_IMAGE}
    restart: unless-stopped
${userLine}    environment:
${envLines}
${cfg.exposeMode === "direct" ? portLine : ""}    volumes:
      - ${cfg.dataDir}:/app/data
${caddyDataVol}`;

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
  } else if (cfg.exposeMode === "selfsigned") {
    const ip = cfg.ipAddress.trim() || "192.168.1.50";
    body += `
  caddy:
    image: ${CADDY_IMAGE}
    restart: unless-stopped
    ports:
      - "443:443"
    configs:
      - source: caddyfile
        target: /etc/caddy/Caddyfile
    volumes:
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - worker

# 内联 Caddyfile 需要 docker compose v2.23+；旧版改为 bind-mount 同目录 ./Caddyfile
configs:
  caddyfile:
    content: |
      {
          auto_https disable_redirects
      }

      https://${ip} {
          tls internal
          reverse_proxy worker:${cfg.storagePort}
      }

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
