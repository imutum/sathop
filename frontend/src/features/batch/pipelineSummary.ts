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
