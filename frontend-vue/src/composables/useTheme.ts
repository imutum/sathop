import { computed, ref, watch } from "vue";

// Singleton-style composable: module-level reactive state shared across every
// caller, no provider needed. (React version was a Context; Vue makes that
// boilerplate disappear.)

export type ThemeMode = "light" | "dark" | "system";
type Effective = "light" | "dark";

const KEY = "sathop.theme";

function readPersisted(): ThemeMode {
  const v = localStorage.getItem(KEY);
  return v === "light" || v === "dark" || v === "system" ? v : "dark";
}

function resolveSystem(): Effective {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const mode = ref<ThemeMode>(readPersisted());
const systemEffective = ref<Effective>(resolveSystem());

// Track OS theme exactly once, lazily on first useTheme() call.
let mqHooked = false;
function hookSystem() {
  if (mqHooked) return;
  mqHooked = true;
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", () => {
    systemEffective.value = mq.matches ? "dark" : "light";
  });
}

const effective = computed<Effective>(() =>
  mode.value === "system" ? systemEffective.value : mode.value,
);

// Reflect on <html> + persist preference.
watch(
  [mode, effective],
  ([m, eff]) => {
    document.documentElement.classList.toggle("dark", eff === "dark");
    localStorage.setItem(KEY, m);
  },
  { immediate: true },
);

export function useTheme() {
  hookSystem();
  return {
    mode,
    effective,
    set(m: ThemeMode) {
      mode.value = m;
    },
    toggle() {
      const eff = effective.value;
      mode.value = eff === "dark" ? "light" : "dark";
    },
  };
}
