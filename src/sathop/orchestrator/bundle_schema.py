"""Bundle inputs schema parsing + per-granule validation.

The shape lives in `manifest.yaml`:

    inputs:
      slots:                         # required, ≥1
        - name: primary              # slot label, unique within slots
          product: MOD09A1           # matches InputSpec.product
          filename_pattern: "..."    # optional regex
          credential: nasa-earthdata # optional default credential for downloads
      meta:                          # optional
        - name: year
          pattern: "^\\d{4}$"        # optional regex

Validation policy:
  - Slots: every declared slot must be filled exactly once per granule. A
    granule with no matching input for a slot, or multiple, is rejected.
  - Meta: every declared meta field must be present and match its pattern.
  - Extras: inputs whose product isn't in any slot, or meta keys not declared
    in the schema, produce a warning (emitted to the event log) but are not
    blocked.

Bundles may also declare `shared_files: [name, ...]` at the manifest root.
Names must match the orchestrator's shared-file registry at both bundle-upload
and batch-create time; the worker lazily syncs them into $SATHOP_SHARED_DIR
before running the entrypoint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


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
        """Strict parse. Raises ValueError with a caller-suitable message."""
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


def parse_shared_files(manifest: dict) -> list[str]:
    """Strict parse of `manifest.shared_files`. Returns [] if key absent.
    Raises ValueError on shape problems. Each name must be a non-empty string;
    existence in the orchestrator registry is validated separately by the
    caller (bundle upload + batch creation both need that check)."""
    raw = manifest.get("shared_files")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("manifest.shared_files must be a list if present")
    names: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, str) or not item:
            raise ValueError(f"shared_files[{idx}] must be a non-empty string")
        if item in seen:
            raise ValueError(f"shared_files has duplicate entry {item!r}")
        seen.add(item)
        names.append(item)
    return names


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_granule(
    schema: InputsSchema,
    granule_id: str,
    inputs: list[dict],
    meta: dict,
) -> ValidationResult:
    """Validate a single granule against the schema.

    `inputs` are InputSpec-shaped dicts (at least `product` + `filename`).
    Returns a ValidationResult with explicit errors (blocking) and warnings
    (non-blocking, caller logs them)."""
    errors: list[str] = []
    warnings: list[str] = []

    by_product: dict[str, list[dict]] = {}
    for i in inputs:
        by_product.setdefault(str(i.get("product", "")), []).append(i)

    declared_products = {s.product for s in schema.slots}
    for slot in schema.slots:
        matches = by_product.get(slot.product, [])
        if len(matches) == 0:
            errors.append(
                f"granule {granule_id!r}: slot {slot.name!r} needs an input with product={slot.product!r}"
            )
            continue
        if len(matches) > 1:
            errors.append(
                f"granule {granule_id!r}: slot {slot.name!r} (product={slot.product!r}) got {len(matches)} inputs, expected 1"
            )
            continue
        got = matches[0]
        if slot.filename_pattern is not None:
            fname = str(got.get("filename", ""))
            if not slot.filename_pattern.search(fname):
                errors.append(
                    f"granule {granule_id!r}: slot {slot.name!r} filename {fname!r} does not match pattern {slot.filename_pattern.pattern!r}"
                )

    for product, matches in by_product.items():
        if product not in declared_products:
            warnings.append(
                f"granule {granule_id!r}: extra input(s) with product={product!r} not declared in bundle schema ({len(matches)} file(s))"
            )

    declared_meta_names = {m.name for m in schema.meta}
    for field in schema.meta:
        if field.name not in meta:
            errors.append(f"granule {granule_id!r}: missing required meta key {field.name!r}")
            continue
        value = str(meta[field.name])
        if field.pattern is not None and not field.pattern.search(value):
            errors.append(
                f"granule {granule_id!r}: meta.{field.name}={value!r} does not match pattern {field.pattern.pattern!r}"
            )

    for k in meta.keys():
        if k not in declared_meta_names:
            warnings.append(f"granule {granule_id!r}: extra meta key {k!r} not declared in bundle schema")

    return ValidationResult(errors=errors, warnings=warnings)
