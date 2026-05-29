<script setup lang="ts">
import { Icon, type IconName } from "@/components/Icon";
import VersionStatus from "@/components/VersionStatus.vue";
import { logout } from "@/composables/useAuthGate";

type NavItem = { to: string; label: string; icon: IconName; end?: boolean };
defineProps<{
  nav: { label?: string; items: NavItem[] }[];
  collapsed?: boolean;
}>();
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="flex h-16 items-center gap-3 border-b border-border px-4">
      <div class="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border bg-background text-foreground shadow-soft">
        <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3" />
          <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
        </svg>
      </div>
      <div v-if="!collapsed" class="min-w-0">
        <div class="text-[15px] font-semibold leading-none">SatHop</div>
        <div class="mt-1 text-mini uppercase tracking-brand text-muted-foreground">控制面板</div>
      </div>
    </div>

    <nav class="flex-1 overflow-y-auto px-3 py-3">
      <div v-for="(group, gi) in nav" :key="gi" :class="gi > 0 ? 'mt-4' : ''">
        <div
          v-if="group.label && !collapsed"
          class="px-2.5 pb-1 text-mini font-medium uppercase tracking-brand text-muted-foreground/70"
        >
          {{ group.label }}
        </div>
        <div v-else-if="group.label && collapsed" class="mx-auto mb-2 h-px w-6 bg-border" aria-hidden />
        <ul class="space-y-0.5">
          <li v-for="n in group.items" :key="n.to">
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
                  'group relative flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors outline-none',
                  (n.end ? isExactActive : isActive)
                    ? 'bg-muted text-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  collapsed ? 'justify-center' : '',
                ]"
              >
                <span
                  :class="[
                    'absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full transition-colors',
                    (n.end ? isExactActive : isActive) ? 'bg-foreground' : 'bg-transparent',
                  ]"
                  aria-hidden
                />
                <Icon
                  :name="n.icon"
                  :class="[
                    'shrink-0 transition-colors',
                    (n.end ? isExactActive : isActive) ? 'text-foreground' : 'text-muted-foreground group-hover:text-foreground',
                  ]"
                />
                <span v-if="!collapsed" class="truncate">{{ n.label }}</span>
              </a>
            </RouterLink>
          </li>
        </ul>
      </div>
    </nav>

    <div class="space-y-1 border-t border-border p-3">
      <VersionStatus :collapsed="collapsed" />
      <button
        type="button"
        @click="logout"
        :title="collapsed ? '退出登录' : undefined"
        :class="[
          'flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
          collapsed ? 'justify-center' : '',
        ]"
      >
        <Icon name="logout" class="shrink-0" />
        <span v-if="!collapsed">退出登录</span>
      </button>
    </div>
  </div>
</template>
