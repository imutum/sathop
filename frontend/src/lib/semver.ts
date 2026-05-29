// Lenient semver parse + compare, shared by the orchestrator version banner
// and every per-node version check. Tolerates a leading `v` and ignores any
// pre-release/build suffix — only major.minor.patch participate in ordering.

export function parseSemver(v: string): [number, number, number] {
  const m = v.trim().match(/v?(\d+)\.(\d+)\.(\d+)/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [0, 0, 0];
}

// <0 if a older than b, 0 if equal, >0 if a newer.
export function compareSemver(a: string, b: string): number {
  const pa = parseSemver(a);
  const pb = parseSemver(b);
  for (let i = 0; i < 3; i++) {
    if (pa[i] !== pb[i]) return pa[i] - pb[i];
  }
  return 0;
}
