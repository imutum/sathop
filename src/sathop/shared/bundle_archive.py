from __future__ import annotations

from collections.abc import Iterable


def detect_wrapper_dir(rel_paths: Iterable[str]) -> str | None:
    """Return the single top-level directory name that wraps every file AND
    contains manifest.yaml; None when the archive is flat, has multiple roots,
    or its sole top-level dir lacks manifest.yaml.

    Accepts both zip namelist entries (directory entries may end with '/') and
    on-disk relative paths. Always uses '/' as separator.
    """
    files = [p for p in rel_paths if p and not p.endswith("/")]
    if not files:
        return None
    if any("/" not in p for p in files):
        return None
    first_segs = {p.split("/", 1)[0] for p in files}
    if len(first_segs) != 1:
        return None
    wrapper = first_segs.pop()
    if f"{wrapper}/manifest.yaml" not in files:
        return None
    return wrapper
