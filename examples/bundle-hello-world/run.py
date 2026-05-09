"""hello-world entrypoint.

For each granule the worker invokes this once with these env vars set:

    SATHOP_INPUT_DIR    where input files were staged
    SATHOP_OUTPUT_DIR   where to write outputs (the worker collects matching files
                        from here after we exit 0)
    SATHOP_GRANULE_ID   composite "<batch_id>:<user_gid>"
    SATHOP_BATCH_ID     batch this granule belongs to
    SATHOP_META_JSON    JSON-encoded per-granule meta dict
    SATHOP_PROGRESS_URL optional checkpoint endpoint

We copy every input through, prepending a one-line header. stdlib only —
worker secrets aren't inherited, but the bundle's venv would still have any
declared `pip` deps if we needed them.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.request


def progress(step: str, pct: float | None = None) -> None:
    """Best-effort checkpoint. No-op when run standalone (env var absent) or
    when the orchestrator/worker is briefly unreachable — checkpoints aren't
    load-bearing, so a swallow-all is the right policy."""
    url = os.environ.get("SATHOP_PROGRESS_URL")
    if not url:
        return
    body = json.dumps({"step": step, "pct": pct}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).close()
    except Exception:
        pass


def main() -> int:
    input_dir = pathlib.Path(os.environ["SATHOP_INPUT_DIR"])
    output_dir = pathlib.Path(os.environ["SATHOP_OUTPUT_DIR"])
    granule_id = os.environ["SATHOP_GRANULE_ID"]
    batch_id = os.environ["SATHOP_BATCH_ID"]
    meta = json.loads(os.environ.get("SATHOP_META_JSON", "{}"))
    tag = str(meta.get("tag", "untagged"))

    progress("starting", 0.0)
    inputs = sorted(p for p in input_dir.iterdir() if p.is_file())
    if not inputs:
        print(f"no inputs in {input_dir}", file=sys.stderr)
        return 1

    for i, src in enumerate(inputs):
        dst = output_dir / f"{src.stem}-tagged.txt"
        body = src.read_text(encoding="utf-8")
        dst.write_text(
            f"# granule={granule_id} batch={batch_id} tag={tag}\n{body}",
            encoding="utf-8",
        )
        progress(f"wrote {dst.name}", (i + 1) * 100.0 / len(inputs))

    progress("done", 100.0)
    print(f"hello-world processed {len(inputs)} input(s) for granule {granule_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
