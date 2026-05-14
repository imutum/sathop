<script setup lang="ts">
import { ref } from "vue";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import CardSection from "@/components/CardSection.vue";
import RowActions from "@/components/RowActions.vue";
import { Icon } from "@/components/Icon";

const tab = ref("overview");
const collapsibleOpen = ref(false);
</script>

<template>
  <section class="space-y-10 py-2">
    <header class="space-y-1">
      <h1 class="text-2xl font-semibold tracking-tight">UI Kit</h1>
      <p class="text-sm text-muted-foreground">
        shadcn-vue 组件视觉冒烟入口。配合 light/dark 切换走查 token 是否对齐。
      </p>
    </header>

    <Card>
      <CardHeader>
        <CardTitle>Button</CardTitle>
        <CardDescription>variant × size 全集。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="flex flex-wrap items-center gap-3">
          <Button>Default</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="link">Link</Button>
        </div>
        <Separator />
        <div class="flex flex-wrap items-center gap-3">
          <Button size="xs">XS</Button>
          <Button size="sm">SM</Button>
          <Button>Default</Button>
          <Button size="lg">LG</Button>
          <Button size="icon" aria-label="icon"><Icon name="search" :size="14" /></Button>
          <Button size="icon-sm" variant="outline" aria-label="more"><Icon name="more" :size="14" /></Button>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Badge</CardTitle>
        <CardDescription>variant + tone（管线状态色覆盖）。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <div class="flex flex-wrap items-center gap-3">
          <Badge>Default</Badge>
          <Badge variant="secondary">Secondary</Badge>
          <Badge variant="destructive">Destructive</Badge>
          <Badge variant="outline">Outline</Badge>
          <Badge variant="info">Info</Badge>
          <Badge variant="success">Success</Badge>
          <Badge variant="warning">Warning</Badge>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <Badge tone="pending" dot>待分配</Badge>
          <Badge tone="queued" dot>已分配</Badge>
          <Badge tone="downloading" dot>下载中</Badge>
          <Badge tone="processing" dot>处理中</Badge>
          <Badge tone="uploaded" dot>待分发</Badge>
          <Badge tone="acked" dot>已确认</Badge>
          <Badge tone="failed" dot>待重试</Badge>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Alert</CardTitle>
      </CardHeader>
      <CardContent class="space-y-3">
        <Alert>
          <AlertTitle>提示</AlertTitle>
          <AlertDescription>这是一条默认风格的提示消息。</AlertDescription>
        </Alert>
        <Alert variant="destructive">
          <AlertTitle>警告</AlertTitle>
          <AlertDescription>这是一条破坏性操作前的警示。</AlertDescription>
        </Alert>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Form primitives</CardTitle>
      </CardHeader>
      <CardContent class="grid max-w-md gap-4">
        <div class="grid gap-1.5">
          <Label for="kit-input">用户名</Label>
          <Input id="kit-input" placeholder="example" />
        </div>
        <div class="flex items-center gap-2">
          <Checkbox id="kit-check" />
          <Label for="kit-check">记住我</Label>
        </div>
      </CardContent>
      <CardFooter class="gap-2">
        <Button>提交</Button>
        <Button variant="ghost">取消</Button>
      </CardFooter>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Skeleton</CardTitle>
        <CardDescription>加载占位条。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <Skeleton class="h-5 w-2/3" />
        <Skeleton class="h-5 w-1/2" />
        <Skeleton class="h-24 w-full" />
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Popover · Collapsible · Tabs</CardTitle>
        <CardDescription>本次新增的 shadcn-vue wrapper。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-6">
        <div class="flex flex-wrap items-center gap-3">
          <Popover>
            <PopoverTrigger as-child>
              <Button variant="outline" size="sm">
                <Icon name="help" :size="14" />
                Popover
              </Button>
            </PopoverTrigger>
            <PopoverContent>
              <div class="text-mini font-medium tracking-label text-muted-foreground">说明</div>
              <p class="mt-2 text-cell text-muted-foreground">
                用于挂载图例、解释、上下文操作 — 比放在页面里更克制。
              </p>
            </PopoverContent>
          </Popover>

          <Tabs v-model="tab">
            <TabsList>
              <TabsTrigger value="overview">概览</TabsTrigger>
              <TabsTrigger value="activity">活动</TabsTrigger>
              <TabsTrigger value="settings">设置</TabsTrigger>
            </TabsList>
            <TabsContent value="overview" class="text-cell text-muted-foreground">
              当前选中：概览。Tabs 适合互斥的、平铺的多视图。
            </TabsContent>
            <TabsContent value="activity" class="text-cell text-muted-foreground">
              当前选中：活动。
            </TabsContent>
            <TabsContent value="settings" class="text-cell text-muted-foreground">
              当前选中：设置。
            </TabsContent>
          </Tabs>
        </div>

        <Collapsible v-model:open="collapsibleOpen" class="rounded-lg border border-border">
          <CollapsibleTrigger as-child>
            <button
              type="button"
              class="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm transition-colors hover:bg-muted/60"
            >
              <span class="font-medium">高级选项</span>
              <Icon name="chevronDown" :size="14" :class="['transition-transform', collapsibleOpen ? 'rotate-180' : '']" />
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent class="border-t border-border px-4 py-3 text-cell text-muted-foreground">
            渐进披露——把次要 / 高级控件放进 Collapsible 里，
            让默认视图保持清爽，需要时再展开。
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>

    <CardSection
      title="CardSection · RowActions"
      description="项目级 helper —— 统一卡片节奏 + 行级『主操作 + 更多菜单』模式。"
    >
      <template #meta>
        <Badge variant="info" class="tabular-nums">12 项</Badge>
      </template>

      <ul class="divide-y divide-border/60">
        <li
          v-for="i in 3"
          :key="i"
          class="flex items-center justify-between gap-3 py-3"
        >
          <div>
            <div class="text-sm font-medium">示例条目 #{{ i }}</div>
            <div class="text-cell text-muted-foreground">主操作 + ⋯ 菜单 收起破坏性动作</div>
          </div>
          <RowActions align="end">
            <template #primary>
              <Button size="sm">查看</Button>
            </template>
            <DropdownMenuItem>复制链接</DropdownMenuItem>
            <DropdownMenuItem>导出 JSON</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem class="text-danger focus:bg-danger/10 focus:text-danger">
              删除…
            </DropdownMenuItem>
          </RowActions>
        </li>
      </ul>
    </CardSection>
  </section>
</template>
