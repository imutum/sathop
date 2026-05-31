import { STATE_ORDER, type GranuleState } from "@/api";

export type PipelineStateCounts = Partial<Record<GranuleState, number>>;

type PipelineTotals = {
  total: number;
  pending: number;
  active: number;
  done: number;
  failed: number;
};

const PENDING: GranuleState[] = ["pending"];
// In-flight = leased through delivery. `uploaded` (待分发) is worker-done but
// NOT yet delivered, so it stays here, not in DONE. `uploading` was previously
// dropped from every bucket — fixed.
const ACTIVE: GranuleState[] = [
  "queued",
  "downloading",
  "downloaded",
  "processing",
  "processed",
  "uploading",
  "uploaded",
];
// Done = delivered. Matches summary.ts (acked+deleted); "完成"=接收端确认.
const DONE: GranuleState[] = ["acked", "deleted"];
const FAILED: GranuleState[] = ["failed", "blacklisted"];

function countStates(counts: PipelineStateCounts, states: GranuleState[]): number {
  return states.reduce((sum, state) => sum + (counts[state] ?? 0), 0);
}

export function pipelineTotals(counts: PipelineStateCounts): PipelineTotals {
  return {
    total: countStates(counts, STATE_ORDER),
    pending: countStates(counts, PENDING),
    active: countStates(counts, ACTIVE),
    done: countStates(counts, DONE),
    failed: countStates(counts, FAILED),
  };
}

export function pipelineSegments(counts: PipelineStateCounts) {
  const total = countStates(counts, STATE_ORDER);
  return STATE_ORDER.filter((state) => (counts[state] ?? 0) > 0).map((state) => ({
    state,
    value: counts[state] ?? 0,
    pct: total > 0 ? ((counts[state] ?? 0) / total) * 100 : 0,
  }));
}

// The canonical pipeline hierarchy — the single 口径 shared by the overview
// (aggregate) and a batch's progress (single batch). Three ordered big stages
// (待分配 → 进行中 → 已交付) partition the delivery pipeline; 异常 is an
// out-of-band fourth. Each big stage carries its small stages (the states that
// roll up into it) in processing order — ALWAYS, even at count 0, so positions
// are stable. `待分配` is a leaf (it IS its one state), so it has no sub-rows.
export type PipelineGroupKey = "pending" | "active" | "done" | "failed";

export type PipelineGroup = {
  key: PipelineGroupKey;
  label: string;
  total: number;
  pct: number; // share of the pipeline grand total (待分配+进行中+已交付)
  subs: { state: GranuleState; value: number }[];
};

const GROUP_DEFS: { key: PipelineGroupKey; label: string; states: GranuleState[]; leaf?: boolean }[] = [
  { key: "pending", label: "待分配", states: PENDING, leaf: true },
  { key: "active", label: "进行中", states: ACTIVE },
  { key: "done", label: "已交付", states: DONE },
  { key: "failed", label: "异常", states: FAILED },
];

export function pipelineGroups(counts: PipelineStateCounts): PipelineGroup[] {
  const grand = countStates(counts, STATE_ORDER); // excludes 异常, so the 3 stages sum to 100%
  return GROUP_DEFS.map((g) => {
    const total = countStates(counts, g.states);
    return {
      key: g.key,
      label: g.label,
      total,
      pct: grand > 0 ? (total / grand) * 100 : 0,
      subs: g.leaf ? [] : g.states.map((state) => ({ state, value: counts[state] ?? 0 })),
    };
  });
}
