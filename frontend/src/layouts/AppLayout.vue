<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Icon, type IconName } from "@/components/Icon";
import { useTheme } from "@/composables/useTheme";
import { useLiveStream } from "@/composables/useLiveStream";
import { logout } from "@/composables/useAuthGate";
import LiveTick from "@/components/chrome/LiveTick.vue";

// Orbital Ops chrome — sidebar with section numbering, top bar with UTC
// mission clock + uplink LED. Sidebar carries the brand mark; the top bar
// stays narrow to maximize vertical real estate for the main panels.

const { connected } = useLiveStream();
const route = useRoute();

type NavItem = { to: string; label: string; icon: IconName; end?: boolean; group?: "ops" | "fleet" | "system" };
const NAV: NavItem[] = [
  { to: "/",          label: "总览",       icon: "dashboard", end: true, group: "ops" },
  { to: "/batches",   label: "批次",       icon: "batches",   group: "ops" },
  { to: "/bundles",   label: "任务包",     icon: "bundles",   group: "ops" },
  { to: "/shared",    label: "共享文件",   icon: "shared",    group: "ops" },
  { to: "/workers",   label: "工作节点",   icon: "workers",   group: "fleet" },
  { to: "/receivers", label: "接收端",     icon: "receivers", group: "fleet" },
  { to: "/events",    label: "事件日志",   icon: "events",    group: "system" },
  { to: "/settings",  label: "设置",       icon: "settings",  group: "system" },
];

// Section number is its 1-based position within the nav list, two-digit padded.
function ord(idx: number): string {
  return String(idx + 1).padStart(2, "0");
}

// Group dividers — render a section heading before the first item in a new
// group while iterating, so the markup stays a single map.
const GROUP_LABEL: Record<NonNullable<NavItem["group"]>, string> = {
  ops: "OPERATIONS",
  fleet: "FLEET",
  system: "SYSTEM",
};

function isFirstInGroup(idx: number): boolean {
  if (idx === 0) return true;
  return NAV[idx].group !== NAV[idx - 1].group;
}

const COLLAPSE_KEY = "sathop.sidebar.collapsed";
const collapsed = ref(localStorage.getItem(COLLAPSE_KEY) === "1");
watch(collapsed, (v) => localStorage.setItem(COLLAPSE_KEY, v ? "1" : "0"));

const mobileOpen = ref(false);
watch(() => route.fullPath, () => {
  mobileOpen.value = false;
});

const { effective, toggle: toggleTheme } = useTheme();
const isDark = computed(() => effective.value === "dark");
</script>

<template>
  <div class="flex h-full bg-background text-foreground">
    <!-- ─── Sidebar (desktop) ─────────────────────────────────────────────── -->
    <aside
      :class="[
        collapsed ? 'w-[68px]' : 'w-[244px]',
        'relative hidden shrink-0 flex-col border-r border-border bg-card transition-[width] duration-200 ease-out md:flex',
      ]"
      aria-label="主导航"
    >
      <!-- Brand block -->
      <div class="relative h-[68px] border-b border-border px-4">
        <div class="flex h-full items-center gap-3">
          <div
            class="relative grid h-9 w-9 shrink-0 place-items-center rounded-md border border-border bg-background text-primary shadow-soft"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
              <circle cx="12" cy="12" r="6.5" />
              <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
            </svg>
            <span class="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_6px_hsl(var(--primary))]" />
          </div>
          <div v-if="!collapsed" class="min-w-0">
            <div class="font-display text-[17px] font-medium leading-none tracking-tight text-foreground">
              SatHop
            </div>
            <div class="readout mt-1.5 text-3xs uppercase tracking-brand text-muted-foreground">
              Mission · Console
            </div>
          </div>
        </div>
      </div>

      <!-- Nav list with group section labels and ordinal codes -->
      <nav class="flex-1 overflow-y-auto px-2 py-4">
        <ul class="space-y-0.5">
          <template v-for="(n, idx) in NAV" :key="n.to">
            <li v-if="!collapsed && n.group && isFirstInGroup(idx)" class="mt-3 first:mt-0">
              <div class="flex items-center gap-2 px-2 pb-1.5 text-3xs font-semibold uppercase tracking-section text-muted-foreground/70">
                <span class="readout text-primary/70">§</span>
                <span>{{ GROUP_LABEL[n.group] }}</span>
                <span class="ml-auto h-px flex-1 bg-border/70" aria-hidden />
              </div>
            </li>
            <li>
              <RouterLink
                v-slot="{ isActive, isExactActive, navigate, href }"
                :to="n.to"
                custom
              >
                <a
                  :href="href"
                  @click="navigate"
                  :title="collapsed ? n.label : undefined"
                  :class="[
                    'group/nav relative flex items-center gap-3 rounded-md px-2 py-2 text-[13px] transition outline-none',
                    (n.end ? isExactActive : isActive)
                      ? 'bg-primary/10 text-foreground'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                    collapsed ? 'justify-center' : '',
                  ]"
                >
                  <span
                    :class="[
                      'absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r-sm transition',
                      (n.end ? isExactActive : isActive) ? 'bg-primary' : 'bg-transparent',
                    ]"
                    aria-hidden
                  />
                  <Icon
                    :name="n.icon"
                    :size="16"
                    :stroke-width="1.6"
                    :class="[
                      'shrink-0 transition',
                      (n.end ? isExactActive : isActive) ? 'text-primary' : 'text-muted-foreground group-hover/nav:text-foreground',
                    ]"
                  />
                  <span v-if="!collapsed" class="truncate">{{ n.label }}</span>
                  <span
                    v-if="!collapsed"
                    class="readout ml-auto text-3xs text-muted-foreground/60"
                    aria-hidden
                  >
                    {{ ord(idx) }}
                  </span>
                </a>
              </RouterLink>
            </li>
          </template>
        </ul>
      </nav>

      <!-- Footer: build credit + sign out -->
      <div class="border-t border-border p-2.5">
        <button
          type="button"
          @click="logout"
          :title="collapsed ? '退出登录' : undefined"
          :class="[
            'flex w-full items-center gap-3 rounded-md px-2 py-2 text-[13px] text-muted-foreground transition hover:bg-muted hover:text-foreground',
            collapsed ? 'justify-center' : '',
          ]"
        >
          <Icon name="logout" :size="15" :stroke-width="1.6" class="shrink-0" />
          <span v-if="!collapsed">退出登录</span>
        </button>
        <div v-if="!collapsed" class="mt-2 flex items-center justify-between border-t border-border/60 px-2 pt-2">
          <span class="readout text-3xs uppercase tracking-section text-muted-foreground/70">
            v0.2.3
          </span>
          <span class="readout text-3xs text-muted-foreground/60">build · stable</span>
        </div>
      </div>

      <!-- Collapse toggle anchored to the right edge of the sidebar. -->
      <button
        type="button"
        @click="collapsed = !collapsed"
        :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
        class="absolute -right-3 top-[60px] z-10 grid h-6 w-6 place-items-center rounded-full border border-border bg-card text-muted-foreground shadow-soft transition hover:border-primary/50 hover:text-primary"
      >
        <Icon :name="collapsed ? 'chevronRight' : 'chevronLeft'" :size="11" :stroke-width="2" />
      </button>
    </aside>

    <!-- ─── Mobile drawer ────────────────────────────────────────────────── -->
    <Sheet v-model:open="mobileOpen">
      <SheetContent side="left" class="w-72 max-w-[80vw] gap-0 p-0">
        <div class="h-[68px] border-b border-border px-4">
          <div class="flex h-full items-center gap-3">
            <div class="relative grid h-9 w-9 shrink-0 place-items-center rounded-md border border-border bg-background text-primary shadow-soft">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
                <circle cx="12" cy="12" r="6.5" />
                <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
                <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
              </svg>
              <span class="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-primary" />
            </div>
            <div class="min-w-0">
              <div class="font-display text-[17px] font-medium leading-none tracking-tight">SatHop</div>
              <div class="readout mt-1.5 text-3xs uppercase tracking-brand text-muted-foreground">
                Mission · Console
              </div>
            </div>
          </div>
        </div>
        <nav class="flex-1 overflow-y-auto px-2 py-4">
          <ul class="space-y-0.5">
            <template v-for="(n, idx) in NAV" :key="n.to">
              <li v-if="n.group && isFirstInGroup(idx)" class="mt-3 first:mt-0">
                <div class="flex items-center gap-2 px-2 pb-1.5 text-3xs font-semibold uppercase tracking-section text-muted-foreground/70">
                  <span class="readout text-primary/70">§</span>
                  <span>{{ GROUP_LABEL[n.group] }}</span>
                  <span class="ml-auto h-px flex-1 bg-border/70" />
                </div>
              </li>
              <li>
                <RouterLink
                  v-slot="{ isActive, isExactActive, navigate, href }"
                  :to="n.to"
                  custom
                >
                  <a
                    :href="href"
                    @click="navigate"
                    :class="[
                      'group/nav relative flex items-center gap-3 rounded-md px-2 py-2 text-[13px] transition outline-none',
                      (n.end ? isExactActive : isActive)
                        ? 'bg-primary/10 text-foreground'
                        : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                    ]"
                  >
                    <Icon :name="n.icon" :size="16" class="shrink-0" />
                    <span class="truncate">{{ n.label }}</span>
                    <span class="readout ml-auto text-3xs text-muted-foreground/60">{{ ord(idx) }}</span>
                  </a>
                </RouterLink>
              </li>
            </template>
          </ul>
        </nav>
        <div class="border-t border-border p-2.5">
          <button
            type="button"
            @click="logout"
            class="flex w-full items-center gap-3 rounded-md px-2 py-2 text-[13px] text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <Icon name="logout" :size="15" class="shrink-0" />
            <span>退出登录</span>
          </button>
        </div>
      </SheetContent>
    </Sheet>

    <!-- ─── Main column ──────────────────────────────────────────────────── -->
    <div class="flex min-w-0 flex-1 flex-col">
      <!-- Top bar: live mission clock, uplink status, theme toggle. The
           horizontal hairline rule beneath echoes the "instrument panel" feel. -->
      <header class="sticky top-0 z-20 flex h-[60px] items-center justify-between gap-4 border-b border-border bg-background/85 px-4 backdrop-blur-md md:px-6 lg:px-8">
        <div class="flex items-center gap-4">
          <button
            type="button"
            @click="mobileOpen = true"
            aria-label="打开导航"
            class="grid h-8 w-8 place-items-center rounded-md border border-border bg-background text-muted-foreground transition hover:text-foreground md:hidden"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <!-- Mission tag — small editorial label that hints "this is an
               instrument" without consuming UI bandwidth. -->
          <span class="hidden items-center gap-3 md:inline-flex">
            <span class="readout text-3xs uppercase tracking-section text-muted-foreground/70">
              MISSION
            </span>
            <span aria-hidden class="h-3 w-px bg-border" />
            <span class="font-display text-[14px] italic text-foreground/80">
              Distributed Pipeline Operations
            </span>
          </span>
        </div>

        <div class="flex items-center gap-3">
          <!-- Uplink status — replaces the old "实时" pill. -->
          <span
            :class="[
              'hidden items-center gap-2 rounded-full border px-3 py-1 text-3xs font-medium uppercase tracking-section md:inline-flex',
              connected
                ? 'border-primary/30 bg-primary/10 text-primary'
                : 'border-border bg-muted text-muted-foreground',
            ]"
            :title="connected ? 'SSE 已连接' : 'SSE 未连接'"
          >
            <span :class="['signal-led', !connected && 'signal-led--idle']" aria-hidden />
            <span class="readout">{{ connected ? "UPLINK · LIVE" : "UPLINK · DARK" }}</span>
          </span>

          <span aria-hidden class="hidden h-4 w-px bg-border md:inline-block" />

          <LiveTick :live="connected" class="hidden md:inline-flex" />

          <span aria-hidden class="hidden h-4 w-px bg-border md:inline-block" />

          <button
            type="button"
            @click="toggleTheme"
            :aria-label="isDark ? '切换到亮色模式' : '切换到暗色模式'"
            :title="isDark ? '切换到亮色模式' : '切换到暗色模式'"
            class="grid h-8 w-8 place-items-center rounded-md border border-border bg-background text-muted-foreground transition hover:border-primary/50 hover:text-primary"
          >
            <Icon :name="isDark ? 'sun' : 'moon'" :size="14" :stroke-width="1.8" />
          </button>
        </div>
      </header>

      <main class="flex-1 overflow-auto">
        <div class="mx-auto w-full max-w-[1480px] px-4 py-6 md:px-8 md:py-8 lg:px-10">
          <div class="animate-fade-in">
            <RouterView />
          </div>
        </div>
      </main>
    </div>
  </div>
</template>
