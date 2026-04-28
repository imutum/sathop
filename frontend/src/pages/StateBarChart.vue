<script setup lang="ts">
import { computed } from "vue";
import { use } from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import VChart from "vue-echarts";
import { STATE_ORDER, type GranuleState } from "../api";
import { stateLabel } from "../i18n";
import { useTheme } from "../composables/useTheme";

use([BarChart, GridComponent, TooltipComponent, SVGRenderer]);

const props = defineProps<{ counts: Partial<Record<GranuleState, number>> }>();

const { effective } = useTheme();
const isDark = computed(() => effective.value === "dark");

const COLORS_DARK: Record<GranuleState, string> = {
  pending: "#64748b",
  queued: "#fbbf24",
  downloading: "#38bdf8",
  downloaded: "#0ea5e9",
  processing: "#818cf8",
  processed: "#6366f1",
  uploaded: "#a78bfa",
  acked: "#34d399",
  deleted: "#10b981",
  failed: "#fb7185",
  blacklisted: "#9f1239",
};

const COLORS_LIGHT: Record<GranuleState, string> = {
  pending: "#94a3b8",
  queued: "#d97706",
  downloading: "#0284c7",
  downloaded: "#0369a1",
  processing: "#4f46e5",
  processed: "#4338ca",
  uploaded: "#7c3aed",
  acked: "#059669",
  deleted: "#047857",
  failed: "#e11d48",
  blacklisted: "#9f1239",
};

const option = computed(() => {
  const COLORS = isDark.value ? COLORS_DARK : COLORS_LIGHT;
  const axisColor = isDark.value ? "#94a3b8" : "#64748b";
  const axisLine = isDark.value ? "#334155" : "#cbd5e1";
  const splitLine = isDark.value ? "#1e293b" : "#e2e8f0";
  const labelColor = isDark.value ? "#e2e8f0" : "#0f172a";

  const visible = STATE_ORDER.filter((s) => (props.counts[s] ?? 0) > 0);
  const cats = [...visible].reverse().map((s) => stateLabel(s));
  const vals = [...visible].reverse().map((s) => ({
    value: props.counts[s]!,
    itemStyle: { color: COLORS[s], borderRadius: [0, 4, 4, 0] },
  }));

  return {
    grid: { left: 80, right: 56, top: 12, bottom: 32, containLabel: false },
    tooltip: {
      trigger: "axis" as const,
      axisPointer: { type: "shadow" as const },
      backgroundColor: isDark.value ? "rgba(15,23,42,0.95)" : "rgba(255,255,255,0.97)",
      borderColor: axisLine,
      textStyle: { color: labelColor, fontSize: 12 },
      formatter: (params: { name: string; value: number }[]) =>
        params.map((p) => `${p.name}: <b>${p.value.toLocaleString()}</b>`).join("<br/>"),
    },
    xAxis: {
      type: "value" as const,
      name: "数据粒数",
      nameLocation: "middle" as const,
      nameGap: 22,
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLine: { lineStyle: { color: axisLine } },
      axisLabel: { color: axisColor },
      splitLine: { lineStyle: { color: splitLine } },
      minInterval: 1,
    },
    yAxis: {
      type: "category" as const,
      data: cats,
      axisLine: { lineStyle: { color: axisLine } },
      axisLabel: { color: labelColor, fontSize: 12 },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar" as const,
        data: vals,
        label: {
          show: true,
          position: "right" as const,
          color: labelColor,
          formatter: "{c}",
          fontSize: 11,
        },
        barMaxWidth: 18,
      },
    ],
  };
});
</script>

<template>
  <VChart :option="option" :style="{ height: '280px' }" autoresize />
</template>
