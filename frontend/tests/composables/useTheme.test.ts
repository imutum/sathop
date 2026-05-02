import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// useTheme is a module-level singleton: state is captured at import time
// from localStorage + matchMedia. We use vi.resetModules() + dynamic import
// to re-init the module with the surrounding stubs in scope per test.

type MqStub = {
  matches: boolean;
  listeners: Array<(e: { matches: boolean }) => void>;
};

function installMatchMedia(prefersDark: boolean): MqStub {
  const stub: MqStub = { matches: prefersDark, listeners: [] };
  // useTheme's listener closes over the MediaQueryList and reads `mq.matches`
  // each time the change fires, so the stub needs a live getter — a static
  // value snapshot at factory-call time would never reflect later flips.
  const factory = vi.fn(() => ({
    get matches() {
      return stub.matches;
    },
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: (_evt: string, cb: (e: { matches: boolean }) => void) => {
      stub.listeners.push(cb);
    },
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  vi.stubGlobal("matchMedia", factory);
  return stub;
}

async function loadFresh(seed: { stored?: string | null; prefersDark?: boolean } = {}) {
  vi.resetModules();
  if (seed.stored === undefined || seed.stored === null) {
    localStorage.removeItem("sathop.theme");
  } else {
    localStorage.setItem("sathop.theme", seed.stored);
  }
  document.documentElement.classList.remove("dark");
  const mq = installMatchMedia(seed.prefersDark ?? false);
  const mod = await import("@/composables/useTheme");
  return { mod, mq };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("composables/useTheme — initial mode", () => {
  it("defaults to dark when nothing is persisted", async () => {
    const { mod } = await loadFresh();
    expect(mod.useTheme().mode.value).toBe("dark");
  });

  it("reads a persisted 'light' value", async () => {
    const { mod } = await loadFresh({ stored: "light" });
    expect(mod.useTheme().mode.value).toBe("light");
  });

  it("reads a persisted 'system' value", async () => {
    const { mod } = await loadFresh({ stored: "system" });
    expect(mod.useTheme().mode.value).toBe("system");
  });

  it("falls back to dark on a corrupt persisted value", async () => {
    const { mod } = await loadFresh({ stored: "neon" });
    expect(mod.useTheme().mode.value).toBe("dark");
  });
});

describe("composables/useTheme — effective + DOM reflection", () => {
  it("'effective' follows mode for explicit light/dark", async () => {
    const { mod } = await loadFresh({ stored: "light" });
    expect(mod.useTheme().effective.value).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("'effective' follows the OS preference when mode = 'system'", async () => {
    const { mod } = await loadFresh({ stored: "system", prefersDark: true });
    expect(mod.useTheme().effective.value).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("re-evaluates 'effective' when the OS preference changes (mode=system)", async () => {
    const { mod, mq } = await loadFresh({ stored: "system", prefersDark: false });
    const t = mod.useTheme();
    expect(t.effective.value).toBe("light");
    // Simulate the OS flipping to dark mode: matchMedia listeners fire.
    mq.matches = true;
    mq.listeners.forEach((cb) => cb({ matches: true }));
    await new Promise((r) => setTimeout(r, 0));
    expect(t.effective.value).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

describe("composables/useTheme — set + toggle", () => {
  it("set(m) updates mode, reflects on <html>, and persists", async () => {
    const { mod } = await loadFresh({ stored: "dark" });
    const t = mod.useTheme();
    t.set("light");
    await new Promise((r) => setTimeout(r, 0));
    expect(t.mode.value).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("sathop.theme")).toBe("light");
  });

  it("toggle() flips dark → light", async () => {
    const { mod } = await loadFresh({ stored: "dark" });
    const t = mod.useTheme();
    t.toggle();
    expect(t.mode.value).toBe("light");
  });

  it("toggle() flips light → dark", async () => {
    const { mod } = await loadFresh({ stored: "light" });
    const t = mod.useTheme();
    t.toggle();
    expect(t.mode.value).toBe("dark");
  });

  it("toggle() from 'system' resolves the current effective and flips it", async () => {
    const { mod } = await loadFresh({ stored: "system", prefersDark: true });
    const t = mod.useTheme();
    expect(t.effective.value).toBe("dark");
    t.toggle();
    expect(t.mode.value).toBe("light");
  });
});
