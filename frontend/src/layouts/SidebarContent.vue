<script setup lang="ts">
import { Icon, type IconName } from "@/components/Icon";
import VersionStatus from "@/components/VersionStatus.vue";
import BrandMark from "@/components/BrandMark.vue";
import { logout } from "@/composables/useAuthGate";

type NavItem = { to: string; label: string; icon: IconName; end?: boolean };
defineProps<{
  nav: { label?: string; items: NavItem[] }[];
  collapsed?: boolean;
}>();
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="flex h-[72px] shrink-0 items-center gap-3 px-4">
      <BrandMark />
      <div v-if="!collapsed" class="min-w-0">
        <div class="text-lg font-semibold leading-none tracking-tight">SatHop</div>
        <div class="mt-1.5 text-mini text-muted-foreground">数据服务控制台</div>
      </div>
    </div>

    <nav class="flex-1 overflow-y-auto px-3 pb-4 pt-2">
      <div v-for="(group, gi) in nav" :key="gi" :class="gi > 0 ? 'mt-4' : ''">
        <div
          v-if="group.label && !collapsed"
          class="px-3 pb-2 text-mini font-medium tracking-label text-muted-foreground"
        >
          {{ group.label }}
        </div>
        <div v-else-if="group.label && collapsed" class="mx-auto mb-2 h-px w-6 bg-border" aria-hidden />
        <ul class="space-y-1">
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
                :aria-current="(n.end ? isExactActive : isActive) ? 'page' : undefined"
                :class="[
                  'group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors outline-none',
                  (n.end ? isExactActive : isActive)
                    ? 'bg-accent font-medium text-accent-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  collapsed ? 'justify-center' : '',
                ]"
              >
                <Icon
                  :name="n.icon"
                  :class="[
                    'shrink-0 transition-colors',
                    (n.end ? isExactActive : isActive) ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground',
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
