import { describe, expect, it } from "vitest";
import {
  isAbsolutePath,
  isPrivateHost,
  receiverDockerRun,
  workerDockerRun,
  workerPublicUrl,
  type ReceiverConfig,
  type WorkerConfig,
} from "@/features/onboarding/snippets";

function selfsigned(ipAddress: string): WorkerConfig {
  return {
    workerId: "w1",
    token: "t",
    orchUrl: "http://orch:8765",
    exposeMode: "selfsigned",
    domain: "",
    ipAddress,
    hostPort: "",
    storagePort: 9000,
    dataDir: "/var/lib/sathop/worker",
    capacity: 20,
    heartbeat: 15,
    downloadConcurrency: 1,
  };
}

describe("workerPublicUrl — selfsigned", () => {
  it("bare IP defaults to https://ip (no :443)", () => {
    expect(workerPublicUrl(selfsigned("192.168.1.50"))).toBe("https://192.168.1.50");
  });

  it("IP with explicit :443 still strips it (default port)", () => {
    expect(workerPublicUrl(selfsigned("192.168.1.50:443"))).toBe("https://192.168.1.50");
  });

  it("IP with non-default port preserves it", () => {
    expect(workerPublicUrl(selfsigned("192.168.1.50:8443"))).toBe("https://192.168.1.50:8443");
  });

  it("IP with high port preserves it", () => {
    expect(workerPublicUrl(selfsigned("10.0.0.5:19000"))).toBe("https://10.0.0.5:19000");
  });

  it("hostname with port works the same", () => {
    expect(workerPublicUrl(selfsigned("worker.lan:8443"))).toBe("https://worker.lan:8443");
  });

  it("strips https:// prefix and trailing slash if pasted in", () => {
    expect(workerPublicUrl(selfsigned("https://192.168.1.50:8443/"))).toBe(
      "https://192.168.1.50:8443",
    );
  });

  it("empty falls back to placeholder", () => {
    expect(workerPublicUrl(selfsigned(""))).toBe("https://<worker-ip>");
  });
});

describe("workerDockerRun — selfsigned port mapping", () => {
  it("bare IP maps host 443 → container 9000", () => {
    const out = workerDockerRun(selfsigned("192.168.1.50"));
    expect(out).toContain("-p 443:9000");
  });

  it("IP:port maps host port → container 9000", () => {
    const out = workerDockerRun(selfsigned("192.168.1.50:8443"));
    expect(out).toContain("-p 8443:9000");
  });

  it("high-port IP maps correctly", () => {
    const out = workerDockerRun(selfsigned("10.0.0.5:19000"));
    expect(out).toContain("-p 19000:9000");
  });

  it("SATHOP_PUBLIC_URL env reflects the same port", () => {
    const out = workerDockerRun(selfsigned("192.168.1.50:8443"));
    expect(out).toContain('SATHOP_PUBLIC_URL="https://192.168.1.50:8443"');
  });

  it("no caddy container appended in selfsigned mode", () => {
    const out = workerDockerRun(selfsigned("192.168.1.50:8443"));
    expect(out).not.toContain("sathop-caddy");
    expect(out).not.toContain("Caddyfile");
  });
});

describe("isAbsolutePath", () => {
  it.each([
    ["/var/lib/sathop/worker", true],
    ["/srv/data", true],
    ["/", true],
    ["C:\\sathop", true],
    ["D:/data", true],
    ["./data", false],
    [".\\data", false],
    ["data", false],
    ["~/sathop", false], // tilde not expanded by docker
    ["", false],
    ["   ", false], // whitespace
  ])("isAbsolutePath(%j) === %s", (input, expected) => {
    expect(isAbsolutePath(input)).toBe(expected);
  });
});

describe("docker run mount path — absolute pass-through, relative pinned to PWD", () => {
  it("absolute dataDir is emitted verbatim (no $(pwd) prefix)", () => {
    const cfg = selfsigned("192.168.1.50");
    cfg.dataDir = "/var/lib/sathop/worker";
    const out = workerDockerRun(cfg);
    expect(out).toContain('-v "/var/lib/sathop/worker":/app/data');
    expect(out).not.toContain("$(pwd)");
  });

  it("relative dataDir is pinned to docker run PWD via $(pwd)", () => {
    const cfg = selfsigned("192.168.1.50");
    cfg.dataDir = "./data";
    const out = workerDockerRun(cfg);
    expect(out).toContain('-v "$(pwd)/data":/app/data');
  });
});

describe("isPrivateHost — direct HTTP IP gating", () => {
  it.each([
    ["10.0.0.1", true],
    ["10.255.255.254", true],
    ["172.16.0.1", true],
    ["172.20.5.10", true],
    ["172.31.255.254", true],
    ["172.32.0.1", false], // outside 172.16/12
    ["172.15.0.1", false],
    ["192.168.0.1", true],
    ["192.168.255.254", true],
    ["127.0.0.1", true],
    ["169.254.1.1", true], // link-local
    ["100.64.0.1", true], // CGNAT
    ["100.127.255.254", true],
    ["100.63.0.1", false], // just below CGNAT
    ["100.128.0.1", false], // just above CGNAT
    ["8.8.8.8", false], // public DNS
    ["1.1.1.1", false],
    ["203.0.113.5", false], // TEST-NET-3
    ["192.168.1.50:9000", true], // with port
    ["http://192.168.1.50:9000", true], // tolerant of scheme prefix
    ["10.0.0.1:8080", true],
    ["8.8.8.8:80", false],
    ["::1", true],
    ["fd12:3456::1", true], // ULA
    ["fc00::1", true],
    ["fe80::1", true], // link-local
    ["[fd12::1]:8443", true],
    ["2001:db8::1", false], // documentation prefix, treat as public
    ["[2001:db8::1]:8080", false],
    ["worker.local", true], // hostname
    ["sathopworker.example.com", true], // hostname — operator's call
    ["", false],
  ])("isPrivateHost(%j) === %s", (input, expected) => {
    expect(isPrivateHost(input)).toBe(expected);
  });
});

describe("receiver TLS modes — UI label ↔ runtime env wiring", () => {
  // receiver/config.py defaults SATHOP_TLS_TRUST_ORCH to true. Without an
  // explicit override, "strict" (label: 只信任系统 CA) silently behaves like
  // "trust-orch". Lock the wiring: strict ⇒ TLS_TRUST_ORCH=false; trust-orch
  // relies on defaults; insecure ⇒ TLS_VERIFY=false.
  const base: ReceiverConfig = {
    receiverId: "r1",
    token: "t",
    orchUrl: "http://orch:8765",
    outputDir: "/var/lib/sathop/receiver",
    concurrent: 4,
    poll: 10,
    tlsMode: "strict",
  };

  it("strict explicitly disables trust-orch", () => {
    const out = receiverDockerRun({ ...base, tlsMode: "strict" });
    expect(out).toContain('SATHOP_TLS_TRUST_ORCH="false"');
    expect(out).not.toContain("SATHOP_TLS_VERIFY");
  });

  it("trust-orch leaves both flags at receiver defaults", () => {
    const out = receiverDockerRun({ ...base, tlsMode: "trust-orch" });
    expect(out).not.toContain("SATHOP_TLS_TRUST_ORCH");
    expect(out).not.toContain("SATHOP_TLS_VERIFY");
  });

  it("insecure disables TLS_VERIFY", () => {
    const out = receiverDockerRun({ ...base, tlsMode: "insecure" });
    expect(out).toContain('SATHOP_TLS_VERIFY="false"');
  });
});

describe("docker run line continuation — always '\\' (never backtick)", () => {
  // Snippets target bash-compatible shells (Linux / macOS / WSL / Git Bash).
  // Lock '\' as the continuation char — PowerShell's backtick would silently
  // sneak back if anyone reintroduces a platform fork.
  it("worker docker run uses '\\'", () => {
    const out = workerDockerRun(selfsigned("192.168.1.50"));
    expect(out).toContain(" \\\n");
    expect(out).not.toMatch(/ `\n/);
  });

  it("receiver docker run uses '\\'", () => {
    const cfg: ReceiverConfig = {
      receiverId: "r1",
      token: "t",
      orchUrl: "http://orch:8765",
      outputDir: "/var/lib/sathop/receiver",
      concurrent: 4,
      poll: 10,
      tlsMode: "strict",
    };
    const out = receiverDockerRun(cfg);
    expect(out).toContain(" \\\n");
    expect(out).not.toMatch(/ `\n/);
  });
});
