<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Icon, type IconName } from "@/components/Icon";
import { useTheme } from "@/composables/useTheme";
import { useLiveStream } from "@/composables/useLiveStream";
import { logout } from "@/composables/useAuthGate";

// Sidebar + topbar + <router-view>. Breadcrumbs and auth-open warning land
// here once those composables / pages migrate.

const { connected } = useLiveStream();
const route = useRoute();

type NavItem = { to: string; label: string; icon: IconName; end?: boolean };
const NAV: NavItem[] = [
  { to: "/", label: "总览", icon: "dashboard", end: true },
  { to: "/batches", label: "批次", icon: "batches" },
  { to: "/bundles", label: "任务包", icon: "bundles" },
  { to: "/shared", label: "共享文件", icon: "shared" },
  { to: "/workers", label: "工作节点", icon: "workers" },
  { to: "/receivers", label: "接收端", icon: "receivers" },
  { to: "/events", label: "事件日志", icon: "events" },
  { to: "/settings", label: "设置", icon: "settings" },
];

const COLLAPSE_KEY = "sathop.sidebar.collapsed";
const collapsed = ref(localStorage.getItem(COLLAPSE_KEY) === "1");
watch(collapsed, (v) => localStorage.setItem(COLLAPSE_KEY, v ? "1" : "0"));

const mobileOpen = ref(false);
// Close the mobile drawer whenever the route changes (link clicks, browser
// back/forward, programmatic navigations all share this signal).
watch(() => route.fullPath, () => {
  mobileOpen.value = false;
});

const { effective, toggle: toggleTheme } = useTheme();
const isDark = computed(() => effective.value === "dark");
</script>

<template>
  <div class="flex h-full bg-background text-foreground">
    <aside
      :class="[
        collapsed ? 'w-[72px]' : 'w-60',
        'relative hidden shrink-0 flex-col border-r border-border bg-background transition-[width] duration-200 ease-out md:flex',
      ]"
      aria-label="主导航"
    >
      <div class="flex h-16 items-center gap-3 border-b border-border px-4">
        <div class="relative grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border bg-background text-foreground shadow-soft">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3" />
            <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
          </svg>
        </div>
        <div v-if="!collapsed" class="min-w-0">
          <div class="font-display text-[15px] font-semibold leading-none">SatHop</div>
          <div class="mt-1 text-mini uppercase tracking-[0.18em] text-muted-foreground">Mission Console</div>
        </div>
      </div>

      <nav class="flex-1 overflow-y-auto px-3 py-3">
        <div v-if="!collapsed" class="mb-2 px-2 text-3xs font-semibold uppercase tracking-[0.12em] text-muted-foreground/80">
          控制台
        </div>
        <ul class="space-y-0.5">
          <li v-for="n in NAV" :key="n.to">
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
                  'group relative flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition outline-none',
                  (n.end ? isExactActive : isActive)
                    ? 'bg-muted text-foreground shadow-soft'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  collapsed ? 'justify-center' : '',
                ]"
              >
                <span
                  :class="[
                    'absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full transition',
                    (n.end ? isExactActive : isActive) ? 'bg-foreground' : 'bg-transparent',
                  ]"
                  aria-hidden
                />
                <Icon
                  :name="n.icon"
                  :class="[
                    'shrink-0 transition',
                    (n.end ? isExactActive : isActive) ? 'text-foreground' : 'text-muted-foreground group-hover:text-foreground',
                  ]"
                />
                <span v-if="!collapsed" class="truncate">{{ n.label }}</span>
              </a>
            </RouterLink>
          </li>
        </ul>
      </nav>

      <div class="border-t border-border p-3">
        <button
          type="button"
          @click="logout"
          :title="collapsed ? '退出登录' : undefined"
          :class="[
            'flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground',
            collapsed ? 'justify-center' : '',
          ]"
        >
          <Icon name="logout" class="shrink-0" />
          <span v-if="!collapsed">退出登录</span>
        </button>
      </div>

      <button
        type="button"
        @click="collapsed = !collapsed"
        :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
        class="absolute -right-3 top-20 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-background text-muted-foreground shadow-soft transition hover:text-foreground"
      >
        <Icon :name="collapsed ? 'chevronRight' : 'chevronLeft'" :size="12" :stroke-width="2.2" />
      </button>
    </aside>

    <Sheet v-model:open="mobileOpen">
      <SheetContent side="left" class="w-72 max-w-[80vw] gap-0 p-0">
        <div class="flex h-16 items-center gap-3 border-b border-border px-4">
          <div class="relative grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border bg-background text-foreground shadow-soft">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3" />
              <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
            </svg>
          </div>
          <div class="min-w-0">
            <div class="font-display text-[15px] font-semibold leading-none">SatHop</div>
            <div class="mt-1 text-mini uppercase tracking-[0.18em] text-muted-foreground">Mission Console</div>
          </div>
        </div>
        <nav class="flex-1 overflow-y-auto px-3 py-3">
          <div class="mb-2 px-2 text-3xs font-semibold uppercase tracking-[0.12em] text-muted-foreground/80">
            控制台
          </div>
          <ul class="space-y-0.5">
            <li v-for="n in NAV" :key="n.to">
              <RouterLink
                v-slot="{ isActive, isExactActive, navigate, href }"
                :to="n.to"
                custom
              >
                <a
                  :href="href"
                  @click="navigate"
                  :class="[
                    'group relative flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition outline-none',
                    (n.end ? isExactActive : isActive)
                      ? 'bg-muted text-foreground shadow-soft'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  ]"
                >
                  <Icon :name="n.icon" class="shrink-0" />
                  <span class="truncate">{{ n.label }}</span>
                </a>
              </RouterLink>
            </li>
          </ul>
        </nav>
        <div class="border-t border-border p-3">
          <button
            type="button"
            @click="logout"
            class="flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <Icon name="logout" class="shrink-0" />
            <span>退出登录</span>
          </button>
        </div>
      </SheetContent>
    </Sheet>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-border bg-background/85 px-4 backdrop-blur-md md:px-6 lg:px-8">
        <div class="flex items-center gap-3">
          <button
            type="button"
            @click="mobileOpen = true"
            aria-label="打开导航"
            class="grid h-9 w-9 place-items-center rounded-md border border-border bg-background text-muted-foreground transition hover:text-foreground md:hidden"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <div class="text-[12.5px] text-muted-foreground">
            <!-- breadcrumbs land here once route metadata + nested-route migration is in -->
          </div>
        </div>
        <div class="flex items-center gap-2">
          <span
            :class="[
              'hidden items-center gap-2 rounded-full border px-2.5 py-1 text-2xs font-medium md:inline-flex',
              connected
                ? 'border-success/30 bg-success/10 text-success'
                : 'border-border bg-muted text-muted-foreground',
            ]"
            :title="connected ? 'SSE 已连接' : 'SSE 未连接'"
          >
            <span class="relative grid h-1.5 w-1.5 place-items-center">
              <span
                :class="[
                  'absolute inset-0 rounded-full',
                  connected ? 'bg-success animate-pulse-soft' : 'bg-muted-foreground',
                ]"
              />
            </span>
            {{ connected ? "实时" : "离线" }}
          </span>
          <button
            type="button"
            @click="toggleTheme"
            :aria-label="isDark ? '切换到亮色模式' : '切换到暗色模式'"
            :title="isDark ? '切换到亮色模式' : '切换到暗色模式'"
            class="grid h-9 w-9 place-items-center rounded-md border border-border bg-background text-muted-foreground transition hover:text-foreground hover:shadow-soft"
          >
            <Icon :name="isDark ? 'sun' : 'moon'" :stroke-width="2" />
          </button>
        </div>
      </header>

      <main class="flex-1 overflow-auto">
        <div class="mx-auto w-full max-w-[1480px] px-4 py-5 md:px-6 md:py-6 lg:px-8 lg:py-8">
          <div class="animate-fade-in">
            <RouterView />
          </div>
        </div>
      </main>
    </div>
  </div>
</template>
