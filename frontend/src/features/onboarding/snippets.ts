// Code-snippet generators for the receiver onboarding wizard. Pure functions:
// take form config, produce a copy-pasteable command string. No DOM, no I/O.

export type Platform = "linux" | "windows";

export type OnboardConfig = {
  receiverId: string;
  token: string;
  orchUrl: string;
  outputDir: string;
  platform: Platform;
  concurrent: number;
  poll: number;
};

export const DEFAULT_IMAGE = "ghcr.io/imutum/sathop/receiver:latest";
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

function envFlags(cfg: OnboardConfig, sathopUrl: string): Array<[string, string]> {
  const out: Array<[string, string]> = [
    ["SATHOP_RECEIVER_ID", cfg.receiverId],
    ["SATHOP_URL", sathopUrl],
  ];
  if (cfg.concurrent !== 4) out.push(["SATHOP_CONCURRENT_PULLS", String(cfg.concurrent)]);
  if (cfg.poll !== 10) out.push(["SATHOP_POLL_INTERVAL", String(cfg.poll)]);
  return out;
}

// Linux/macOS uses '\' for line continuation; PowerShell uses backtick '`'.
function linecont(p: Platform): string {
  return p === "linux" ? "\\" : "`";
}

export function dockerRun(cfg: OnboardConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const cont = linecont(cfg.platform);
  const lines: string[] = ["docker run --rm -it"];
  if (cfg.platform === "linux") lines.push("--user $(id -u):$(id -g)");
  for (const [k, v] of envFlags(cfg, sathopUrl)) lines.push(`-e ${k}="${v}"`);
  // Mount the host output dir to the image's fixed /data/archive (set by Dockerfile).
  const hostDir = cfg.outputDir;
  const mountSrc = cfg.platform === "linux" ? `"$(pwd)/${stripDot(hostDir)}"` : `"\${PWD}/${stripDot(hostDir)}"`;
  lines.push(`-v ${mountSrc}:/data/archive`);
  lines.push(DEFAULT_IMAGE);
  return lines.join(` ${cont}\n  `);
}

export function dockerCompose(cfg: OnboardConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const userLine = cfg.platform === "linux" ? '    user: "${UID:-1000}:${GID:-1000}"\n' : "";
  const envLines = envFlags(cfg, sathopUrl)
    .map(([k, v]) => `      ${k}: "${v}"`)
    .join("\n");
  return `services:
  receiver:
    image: ${DEFAULT_IMAGE}
    restart: unless-stopped
${userLine}    environment:
${envLines}
    volumes:
      - ${cfg.outputDir}:/data/archive
`;
}

export function uvxCommand(cfg: OnboardConfig): string {
  const sathopUrl = buildSathopUrl(cfg.orchUrl, cfg.token);
  const cont = linecont(cfg.platform);
  const lines: string[] = [
    `uvx --from 'sathop[receiver] @ git+${DEFAULT_GIT_REPO}'`,
    `sathop-pull`,
    `--url '${sathopUrl}'`,
    `--id '${cfg.receiverId}'`,
    `--dir '${cfg.outputDir}'`,
  ];
  if (cfg.concurrent !== 4) lines.push(`--concurrent ${cfg.concurrent}`);
  if (cfg.poll !== 10) lines.push(`--poll ${cfg.poll}`);
  return lines.join(` ${cont}\n  `);
}

// Linux preflight hint: ensure host dir exists and is owned by current user
// before docker run mounts it (otherwise --user can't mkdir into root-owned mount).
export function linuxPrestep(outputDir: string): string {
  const d = outputDir;
  return `mkdir -p ${d} && sudo chown -R "$(id -u):$(id -g)" ${d}`;
}

function stripDot(p: string): string {
  return p.replace(/^\.\//, "").replace(/^\.\\/, "");
}
