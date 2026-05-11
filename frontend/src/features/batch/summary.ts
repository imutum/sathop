import { IN_FLIGHT_STATES, type BatchSummary, type GranuleState } from "@/api";

const TERMINAL: GranuleState[] = ["acked", "deleted"];
const ERRORED: GranuleState[] = ["failed", "blacklisted"];

type StateCounts = Partial<Record<GranuleState, number>>;

export function totalCount(counts: StateCounts): number {
  return Object.values(counts).reduce((sum, n) => sum + (n ?? 0), 0);
}

function countStates(counts: StateCounts, states: GranuleState[]): number {
  return states.reduce((sum, state) => sum + (counts[state] ?? 0), 0);
}

export function completedTotal(batch: Pick<BatchSummary, "counts">): number {
  return countStates(batch.counts, TERMINAL);
}

export function errorTotal(batch: Pick<BatchSummary, "counts">): number {
  return countStates(batch.counts, ERRORED);
}

export function inFlightTotal(batch: Pick<BatchSummary, "counts">): number {
  return countStates(batch.counts, IN_FLIGHT_STATES);
}

export function isBatchClosed(batch: Pick<BatchSummary, "counts">): boolean {
  const total = totalCount(batch.counts);
  return total > 0 && completedTotal(batch) === total && errorTotal(batch) === 0;
}
