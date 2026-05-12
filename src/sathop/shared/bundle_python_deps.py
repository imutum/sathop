"""Python dependency source for a Bundle: requirements.txt (if present)
beats `manifest.requirements.pip`.

Lives in `shared/` so the canonical mapping `RequirementsConfig + bundle_dir`
→ pip install args is the same fact for the Worker (which builds the venv),
the CLI (which previews + optionally pip-installs), and any future caller.
Earlier this dataclass sat in `worker/bundle.py`, which forced the CLI to
import a worker module — an inverted layering left over from the bundle
manifest consolidation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sathop.shared.bundle_manifest import RequirementsConfig


@dataclass(frozen=True)
class PythonDepsSource:
    kind: Literal["requirements.txt", "manifest.pip"]
    values: tuple[str, ...]
    requirements_file: Path | None = None

    def pip_install_args(self) -> list[str]:
        if self.requirements_file is not None:
            return ["-r", str(self.requirements_file)]
        return list(self.values)


def python_deps_source(requirements: RequirementsConfig, bundle_dir: Path) -> PythonDepsSource | None:
    """Resolve the Bundle's Python dependency source.

    Precedence: a `requirements.txt` at the bundle root wins over
    `manifest.requirements.pip` (matches what the Worker actually installs).
    Comment-only / option-only `requirements.txt` is treated as no deps."""
    req_file = bundle_dir / "requirements.txt"
    if req_file.exists():
        lines = req_file.read_text(encoding="utf-8").splitlines()
        values = tuple(line.strip() for line in lines if _meaningful_requirement(line))
        return PythonDepsSource("requirements.txt", values, req_file) if values else None
    return PythonDepsSource("manifest.pip", requirements.pip) if requirements.pip else None


_PIP_OPTION_PREFIXES = (
    "--extra-index-url",
    "--find-links",
    "--index-url",
    "--no-index",
    "--require-hashes",
    "--trusted-host",
    "-f",
    "-i",
)


def _meaningful_requirement(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and not stripped.startswith("#") and not stripped.startswith(_PIP_OPTION_PREFIXES))
