import { describe, expect, it } from "vitest";
import { workerDockerRun, workerPublicUrl, type WorkerConfig } from "@/features/onboarding/snippets";

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
    dataDir: "./data",
    platform: "linux",
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
