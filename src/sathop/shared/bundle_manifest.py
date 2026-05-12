"""Canonical bundle manifest: single source of truth for the user↔Orchestrator↔Worker contract.

`manifest.yaml` shape:

    name: <str>                    required
    version: <str>                 required
    description: <str>             optional
    execution:                     required
      entrypoint: <str>            required
      timeout_sec: <int>           default 900
      env: <dict[str,str]>         default {}
    outputs:                       required
      watch_dir: <str>             default "output"
      extensions: <list[str]>      default []  (dot-prefixed)
      object_key_template: <str>   default "{stem}{ext}"
    requirements:                  optional
      python: <str | None>         optional, PEP 440 specifier (informational)
      pip: <list[str]>             default []
      apt: <list[str]>             default []
      credentials: <list[str]>     default []
    inputs:                        required
      slots: <list[InputSlot]>     required, non-empty
      meta: <list[MetaField]>      optional
    shared_files: <list[str]>      optional

The dataclasses below are immutable; `BundleManifest.from_yaml` + `BundleManifest.parse`
are the only legitimate entry points. Both raise `ValueError` on shape problems with a
caller-suitable message — invalid manifests should fail loudly, not degrade to defaults.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sathop.shared.safe_path import is_safe_name

RE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
RE_VERSION = re.compile(r"^[A-Za-z0-9._+-]+$")


def parse_meta(data: dict) -> tuple[str, str, str | None]:
    """Strict parse of top-level `name` / `version` / `description`.

    Authoritative regex constraints live here so every entry point
    (HTTP upload, CLI validate, batch create) agrees on what a legal
    Bundle identifier looks like. Returns the tuple; raises ValueError
    on the first shape problem."""
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("manifest.name must be a non-empty string")
    if not RE_NAME.fullmatch(name):
        raise ValueError(f"manifest.name must match {RE_NAME.pattern}, got {name!r}")
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("manifest.version must be a non-empty string")
    if not RE_VERSION.fullmatch(version):
        raise ValueError(f"manifest.version must match {RE_VERSION.pattern}, got {version!r}")
    description = data.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError("manifest.description must be a string if present")
    return name, version, description


@dataclass(frozen=True)
class ExecutionConfig:
    entrypoint: str
    timeout_sec: int = 900
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: object) -> ExecutionConfig:
        if not isinstance(raw, dict):
            raise ValueError("manifest.execution must be a mapping")
        entrypoint = raw.get("entrypoint")
        if not isinstance(entrypoint, str) or not entrypoint:
            raise ValueError("manifest.execution.entrypoint must be a non-empty string")
        timeout = raw.get("timeout_sec", 900)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError(f"manifest.execution.timeout_sec must be a positive int, got {timeout!r}")
        env_raw = raw.get("env", {})
        if not isinstance(env_raw, dict):
            raise ValueError("manifest.execution.env must be a mapping")
        env: dict[str, str] = {}
        for k, v in env_raw.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(f"manifest.execution.env entries must be string→string, got {k!r}={v!r}")
            env[k] = v
        return cls(entrypoint=entrypoint, timeout_sec=timeout, env=env)


@dataclass(frozen=True)
class OutputsConfig:
    watch_dir: str = "output"
    extensions: tuple[str, ...] = ()
    object_key_template: str = "{stem}{ext}"

    @classmethod
    def parse(cls, raw: object) -> OutputsConfig:
        if not isinstance(raw, dict):
            raise ValueError("manifest.outputs must be a mapping")
        watch_dir = raw.get("watch_dir", "output")
        if not isinstance(watch_dir, str) or not watch_dir:
            raise ValueError("manifest.outputs.watch_dir must be a non-empty string")
        exts_raw = raw.get("extensions", [])
        if not isinstance(exts_raw, list):
            raise ValueError("manifest.outputs.extensions must be a list if present")
        for e in exts_raw:
            if not isinstance(e, str) or not e.startswith("."):
                raise ValueError(
                    f"manifest.outputs.extensions entries must be dot-prefixed strings, got {e!r}"
                )
        template = raw.get("object_key_template", "{stem}{ext}")
        if not isinstance(template, str) or not template:
            raise ValueError("manifest.outputs.object_key_template must be a non-empty string")
        return cls(watch_dir=watch_dir, extensions=tuple(exts_raw), object_key_template=template)


@dataclass(frozen=True)
class RequirementsConfig:
    python: str | None = None
    pip: tuple[str, ...] = ()
    apt: tuple[str, ...] = ()
    credentials: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw: object) -> RequirementsConfig:
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ValueError("manifest.requirements must be a mapping if present")
        py = raw.get("python")
        if py is not None and not isinstance(py, str):
            raise ValueError("manifest.requirements.python must be a string (PEP 440 specifier)")
        parsed: dict[str, tuple[str, ...]] = {}
        for key in ("pip", "apt", "credentials"):
            v = raw.get(key)
            if v is None:
                parsed[key] = ()
                continue
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValueError(f"manifest.requirements.{key} must be a list of strings")
            parsed[key] = tuple(v)
        return cls(python=py, **parsed)


@dataclass(frozen=True)
class InputSlot:
    name: str
    product: str
    filename_pattern: re.Pattern[str] | None
    credential: str | None


@dataclass(frozen=True)
class MetaField:
    name: str
    pattern: re.Pattern[str] | None


@dataclass(frozen=True)
class InputsSchema:
    slots: list[InputSlot]
    meta: list[MetaField]

    @classmethod
    def parse(cls, manifest: dict) -> InputsSchema:
        """Strict parse. Raises ValueError with a caller-suitable message.

        Accepts the full manifest dict (not just the `inputs` sub-dict) for back-compat
        with the previous `bundle_schema.InputsSchema.parse(manifest)` signature."""
        inputs = manifest.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError("manifest.inputs must be a mapping")
        slots_raw = inputs.get("slots")
        if not isinstance(slots_raw, list) or not slots_raw:
            raise ValueError("manifest.inputs.slots must be a non-empty list")

        slots: list[InputSlot] = []
        seen: set[str] = set()
        for idx, s in enumerate(slots_raw):
            if not isinstance(s, dict):
                raise ValueError(f"inputs.slots[{idx}] must be a mapping")
            name = s.get("name")
            product = s.get("product")
            if not isinstance(name, str) or not name:
                raise ValueError(f"inputs.slots[{idx}].name is required")
            if not isinstance(product, str) or not product:
                raise ValueError(f"inputs.slots[{idx}].product is required")
            if name in seen:
                raise ValueError(f"duplicate slot name {name!r}")
            seen.add(name)
            fp = s.get("filename_pattern")
            fp_compiled: re.Pattern[str] | None = None
            if fp is not None:
                if not isinstance(fp, str):
                    raise ValueError(f"inputs.slots[{idx}].filename_pattern must be a string")
                try:
                    fp_compiled = re.compile(fp)
                except re.error as e:
                    raise ValueError(f"inputs.slots[{idx}].filename_pattern invalid regex: {e}")
            credential = s.get("credential")
            if credential is not None and not isinstance(credential, str):
                raise ValueError(f"inputs.slots[{idx}].credential must be a string")
            slots.append(
                InputSlot(name=name, product=product, filename_pattern=fp_compiled, credential=credential)
            )

        meta_raw = inputs.get("meta") or []
        if not isinstance(meta_raw, list):
            raise ValueError("inputs.meta must be a list if present")
        meta: list[MetaField] = []
        for idx, m in enumerate(meta_raw):
            if not isinstance(m, dict):
                raise ValueError(f"inputs.meta[{idx}] must be a mapping")
            name = m.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError(f"inputs.meta[{idx}].name is required")
            pat = m.get("pattern")
            pat_compiled: re.Pattern[str] | None = None
            if pat is not None:
                if not isinstance(pat, str):
                    raise ValueError(f"inputs.meta[{idx}].pattern must be a string")
                try:
                    pat_compiled = re.compile(pat)
                except re.error as e:
                    raise ValueError(f"inputs.meta[{idx}].pattern invalid regex: {e}")
            meta.append(MetaField(name=name, pattern=pat_compiled))

        return cls(slots=slots, meta=meta)


def parse_shared_files(manifest: dict) -> tuple[str, ...]:
    """Strict parse of `manifest.shared_files`. Returns () if key absent.
    Raises ValueError on shape problems. Each name must be a non-empty string;
    existence in the orchestrator registry is validated separately by the
    caller (bundle upload + batch creation both need that check)."""
    raw = manifest.get("shared_files")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("manifest.shared_files must be a list if present")
    names: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, str) or not item:
            raise ValueError(f"shared_files[{idx}] must be a non-empty string")
        if not is_safe_name(item):
            raise ValueError(
                f"shared_files[{idx}]={item!r} must be a single safe segment (no '/', '\\', '..')"
            )
        if item in seen:
            raise ValueError(f"shared_files has duplicate entry {item!r}")
        seen.add(item)
        names.append(item)
    return tuple(names)


@dataclass(frozen=True)
class BundleManifest:
    name: str
    version: str
    description: str | None
    execution: ExecutionConfig
    outputs: OutputsConfig
    requirements: RequirementsConfig
    inputs: InputsSchema
    shared_files: tuple[str, ...]

    @classmethod
    def parse(cls, data: object) -> BundleManifest:
        """Strict parse from a dict. Raises ValueError on the first shape problem.

        For the CLI's "show all errors at once" UX, call individual section parsers
        (`parse_meta`, `ExecutionConfig.parse`, `OutputsConfig.parse`, etc.) directly
        — each one raises only on its own section."""
        if not isinstance(data, dict):
            raise ValueError("manifest top level must be a mapping")
        name, version, description = parse_meta(data)
        return cls(
            name=name,
            version=version,
            description=description,
            execution=ExecutionConfig.parse(data.get("execution")),
            outputs=OutputsConfig.parse(data.get("outputs", {})),
            requirements=RequirementsConfig.parse(data.get("requirements")),
            inputs=InputsSchema.parse(data),
            shared_files=parse_shared_files(data),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> BundleManifest:
        return cls.parse(yaml.safe_load(path.read_text(encoding="utf-8")))
