<script setup lang="ts">
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
</script>

<template>
  <section class="space-y-10 py-2">
    <header class="space-y-1">
      <h1 class="font-display text-2xl font-semibold">UI Kit</h1>
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
          <Button size="icon" aria-label="icon">★</Button>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Badge</CardTitle>
      </CardHeader>
      <CardContent class="flex flex-wrap items-center gap-3">
        <Badge>Default</Badge>
        <Badge variant="secondary">Secondary</Badge>
        <Badge variant="destructive">Destructive</Badge>
        <Badge variant="outline">Outline</Badge>
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
  </section>
</template>
