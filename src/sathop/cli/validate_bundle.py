"""Pre-flight bundle validator CLI.

Thin adapter over `sathop.shared.bundle_validate.validate` — the validation
logic is library code in `shared/` so the Worker and Orchestrator can reuse it.

Usage:
    sathop-validate-bundle <bundle-dir> [--build-venv] [--quiet]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sathop.shared.bundle_validate import Report, validate


def _print(r: Report, quiet: bool) -> None:
    for line in r.passed:
        if not quiet:
            print(f"  ✓ {line}")
    for w in r.warnings:
        print(f"  ⚠ {w}", file=sys.stderr)
    for e in r.errors:
        print(f"  ✗ {e}", file=sys.stderr)
    if r.ok:
        print(f"\nOK ({len(r.passed)} checks passed, {len(r.warnings)} warning(s))")
    else:
        print(f"\nFAILED ({len(r.errors)} error(s), {len(r.warnings)} warning(s))", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a bundle directory before upload")
    ap.add_argument("bundle_dir", type=Path)
    ap.add_argument("--build-venv", action="store_true", help="actually pip-install requirements (slow)")
    ap.add_argument("--quiet", action="store_true", help="only print warnings + errors")
    args = ap.parse_args()
    r = validate(args.bundle_dir.resolve(), build_venv=args.build_venv)
    _print(r, args.quiet)
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
