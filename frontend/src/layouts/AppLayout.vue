<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Icon, type IconName } from "@/components/Icon";
import HintTip from "@/components/HintTip.vue";
import SidebarContent from "@/layouts/SidebarContent.vue";
import { useTheme } from "@/composables/useTheme";
import { useLiveStream } from "@/composables/useLiveStream";

const { connected } = useLiveStream();
const route = useRoute();

type NavItem = { to: string; label: string; icon: IconName; end?: boolean };
type NavGroup = { label?: string; items: NavItem[] };
// Grouped by task domain so new operators orient by intent, not a flat list:
// 总览 → 工作流（跑任务）→ 基础设施（节点）→ 运维（审计/配置）.
const NAV: NavGroup[] = [
  { items: [{ to: "/", label: "总览", icon: "dashboard", end: true }] },
  {
    label: "工作流",
    items: [
      { to: "/batches", label: "批次", icon: "batches" },
      { to: "/bundles", label: "任务包", icon: "bundles" },
      { to: "/shared", label: "共享文件", icon: "shared" },
    ],
  },
  {
    label: "基础设施",
    items: [
      { to: "/workers", label: "工作节点", icon: "workers" },
      { to: "/receivers", label: "接收端", icon: "receivers" },
    ],
  },
  {
    label: "运维",
    items: [
      { to: "/events", label: "事件日志", icon: "events" },
      { to: "/settings", label: "设置", icon: "settings" },
    ],
  },
];

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
    <a
      href="#main-content"
      class="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:border focus:border-border focus:bg-background focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-foreground focus:shadow-pop"
    >
      跳到主内容
    </a>
    <aside
      :class="[
        collapsed ? 'w-[72px]' : 'w-60',
        'relative hidden shrink-0 flex-col border-r border-border bg-background transition-[width] duration-200 ease-out md:flex',
      ]"
      aria-label="主导航"
    >
      <SidebarContent :nav="NAV" :collapsed="collapsed" />

      <button
        type="button"
        @click="collapsed = !collapsed"
        :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
        :title="collapsed ? '展开侧边栏' : '收起侧边栏'"
        class="absolute -right-3 top-20 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-background text-muted-foreground shadow-soft transition-colors hover:text-foreground"
      >
        <Icon :name="collapsed ? 'chevronRight' : 'chevronLeft'" :size="12" :stroke-width="2.2" />
      </button>
    </aside>

    <Sheet v-model:open="mobileOpen">
      <SheetContent side="left" class="w-72 max-w-[80vw] gap-0 p-0">
        <SidebarContent :nav="NAV" />
      </SheetContent>
    </Sheet>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-border bg-background/85 px-4 backdrop-blur-md md:px-6 lg:px-8">
        <div class="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="icon"
            class="text-muted-foreground md:hidden"
            aria-label="打开导航"
            @click="mobileOpen = true"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </Button>
        </div>
        <div class="flex items-center gap-2">
          <HintTip :text="connected ? '后台事件流已连接，页面会自动刷新' : 'SSE 未连接，数据可能延迟，会在 60s 安全网内重试'">
            <Badge
              :variant="connected ? 'success' : 'outline'"
              role="status"
              aria-live="polite"
              :class="[
                'hidden h-7 rounded-full md:inline-flex',
                connected ? '' : 'text-muted-foreground',
              ]"
            >
              <span
                :class="[
                  'h-1.5 w-1.5 rounded-full',
                  connected ? 'bg-success animate-pulse-soft' : 'bg-muted-foreground',
                ]"
                aria-hidden
              />
              {{ connected ? "实时" : "离线" }}
            </Badge>
          </HintTip>
          <HintTip :text="isDark ? '切换到亮色模式' : '切换到暗色模式'">
            <Button
              type="button"
              variant="outline"
              size="icon"
              class="text-muted-foreground hover:text-foreground"
              :aria-label="isDark ? '切换到亮色模式' : '切换到暗色模式'"
              @click="toggleTheme"
            >
              <Icon :name="isDark ? 'sun' : 'moon'" :stroke-width="2" />
            </Button>
          </HintTip>
        </div>
      </header>

      <main id="main-content" class="flex-1 overflow-auto">
        <div class="mx-auto w-full max-w-[1480px] px-4 py-5 md:px-6 md:py-6 lg:px-8 lg:py-8">
          <RouterView v-slot="{ Component }">
            <Transition
              mode="out-in"
              enter-active-class="transition-opacity duration-150"
              leave-active-class="transition-opacity duration-100"
              enter-from-class="opacity-0"
              leave-to-class="opacity-0"
            >
              <component :is="Component" :key="$route.path" />
            </Transition>
          </RouterView>
        </div>
      </main>
    </div>
  </div>
</template>
