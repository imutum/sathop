"""Per-granule validation against an `InputsSchema`.

This module used to also house the schema parser; that has moved to
`sathop.shared.bundle_manifest` (single canonical type, used by Worker too).
What remains is the orchestrator-only operation of validating a single granule
at batch-create time."""

from __future__ import annotations

from dataclasses import dataclass

from sathop.shared.bundle_manifest import InputsSchema


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
