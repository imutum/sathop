import { defineComponent, h, type PropType } from "vue";

// Single source of truth for inline SVG icons. Use:
//   <Icon name="search" :size="13" />
//   <Icon name="trash" />            <!-- defaults to 16 -->
// Stroke defaults to 1.8 with currentColor; pass `:stroke-width="2.4"` to
// override. Color is inherited from surrounding text-* utility.

const PATHS = {
  // ─── Sidebar ───
  dashboard: () => [
    h("rect", { x: 3, y: 3, width: 7, height: 9, rx: 1.5 }),
    h("rect", { x: 14, y: 3, width: 7, height: 5, rx: 1.5 }),
    h("rect", { x: 14, y: 12, width: 7, height: 9, rx: 1.5 }),
    h("rect", { x: 3, y: 16, width: 7, height: 5, rx: 1.5 }),
  ],
  batches: () => [
    h("rect", { x: 3, y: 4, width: 18, height: 4, rx: 1 }),
    h("rect", { x: 3, y: 10, width: 18, height: 4, rx: 1 }),
    h("rect", { x: 3, y: 16, width: 18, height: 4, rx: 1 }),
  ],
  bundles: () => [
    h("path", {
      d: "M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z",
    }),
    h("path", { d: "M3.27 6.96L12 12.01l8.73-5.05" }),
    h("path", { d: "M12 22.08V12" }),
  ],
  shared: () => [
    h("path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }),
    h("path", { d: "M14 2v6h6" }),
    h("path", { d: "M9 13h6" }),
    h("path", { d: "M9 17h6" }),
  ],
  workers: () => [
    h("rect", { x: 3, y: 3, width: 7, height: 7, rx: 1.5 }),
    h("rect", { x: 14, y: 3, width: 7, height: 7, rx: 1.5 }),
    h("rect", { x: 3, y: 14, width: 7, height: 7, rx: 1.5 }),
    h("rect", { x: 14, y: 14, width: 7, height: 7, rx: 1.5 }),
  ],
  receivers: () => [
    h("path", { d: "M5 12h14" }),
    h("polyline", { points: "12 5 19 12 12 19" }),
    h("circle", { cx: 5, cy: 12, r: 1.5, fill: "currentColor", stroke: "none" }),
  ],
  events: () => [h("polyline", { points: "22 12 18 12 15 21 9 3 6 12 2 12" })],
  pulse: () => [h("path", { d: "M22 12h-4l-3 9L9 3l-3 9H2" })],
  settings: () => [
    h("circle", { cx: 12, cy: 12, r: 3 }),
    h("path", {
      d: "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
    }),
  ],

  // ─── Action / form ───
  search: () => [
    h("circle", { cx: 11, cy: 11, r: 7 }),
    h("line", { x1: 21, y1: 21, x2: 16.65, y2: 16.65 }),
  ],
  plus: () => [
    h("line", { x1: 12, y1: 5, x2: 12, y2: 19 }),
    h("line", { x1: 5, y1: 12, x2: 19, y2: 12 }),
  ],
  upload: () => [
    h("path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }),
    h("polyline", { points: "17 8 12 3 7 8" }),
    h("line", { x1: 12, y1: 3, x2: 12, y2: 15 }),
  ],
  download: () => [
    h("path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }),
    h("polyline", { points: "7 10 12 15 17 10" }),
    h("line", { x1: 12, y1: 15, x2: 12, y2: 3 }),
  ],
  trash: () => [
    h("polyline", { points: "3 6 5 6 21 6" }),
    h("path", { d: "M19 6l-1.5 14a2 2 0 0 1-2 1.85H8.5a2 2 0 0 1-2-1.85L5 6" }),
    h("path", { d: "M10 11v6M14 11v6" }),
    h("path", { d: "M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" }),
  ],
  arrowRight: () => [
    h("line", { x1: 5, y1: 12, x2: 19, y2: 12 }),
    h("polyline", { points: "12 5 19 12 12 19" }),
  ],
  arrowLeft: () => [
    h("line", { x1: 19, y1: 12, x2: 5, y2: 12 }),
    h("polyline", { points: "12 19 5 12 12 5" }),
  ],
  alert: () => [
    h("path", {
      d: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z",
    }),
    h("line", { x1: 12, y1: 9, x2: 12, y2: 13 }),
    h("line", { x1: 12, y1: 17, x2: 12.01, y2: 17 }),
  ],
  check: () => [h("polyline", { points: "20 6 9 17 4 12" })],
  clipboard: () => [
    h("rect", { x: 9, y: 9, width: 13, height: 13, rx: 2 }),
    h("path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" }),
  ],
  info: () => [
    h("circle", { cx: 12, cy: 12, r: 10 }),
    h("line", { x1: 12, y1: 16, x2: 12, y2: 12 }),
    h("line", { x1: 12, y1: 8, x2: 12.01, y2: 8 }),
  ],
  x: () => [
    h("line", { x1: 18, y1: 6, x2: 6, y2: 18 }),
    h("line", { x1: 6, y1: 6, x2: 18, y2: 18 }),
  ],
  chevronRight: () => [h("polyline", { points: "9 6 15 12 9 18" })],
  chevronLeft: () => [h("polyline", { points: "15 6 9 12 15 18" })],
  sun: () => [
    h("circle", { cx: 12, cy: 12, r: 4 }),
    h("path", {
      d: "M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41",
    }),
  ],
  moon: () => [h("path", { d: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" })],
  logout: () => [
    h("path", { d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" }),
    h("polyline", { points: "16 17 21 12 16 7" }),
    h("line", { x1: 21, y1: 12, x2: 9, y2: 12 }),
  ],
} satisfies Record<string, () => ReturnType<typeof h>[]>;

export type IconName = keyof typeof PATHS;

export const Icon = defineComponent({
  name: "Icon",
  props: {
    name: { type: String as PropType<IconName>, required: true },
    size: { type: [Number, String], default: 16 },
  },
  setup(props, { attrs }) {
    return () =>
      h(
        "svg",
        {
          viewBox: "0 0 24 24",
          fill: "none",
          stroke: "currentColor",
          "stroke-width": 1.8,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          ...attrs,
          width: props.size,
          height: props.size,
        },
        PATHS[props.name]?.() ?? [],
      );
  },
});
