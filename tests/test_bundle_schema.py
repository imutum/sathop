"""Unit tests for the inputs-schema parser + granule validator."""

from __future__ import annotations

import pytest

from sathop.orchestrator.bundle_schema import InputsSchema, validate_granule


def _manifest(slots: list[dict], meta: list[dict] | None = None) -> dict:
    out = {
        "name": "b",
        "version": "0.1",
        "execution": {"entrypoint": "true"},
        "outputs": {"watch_dir": "output"},
        "inputs": {"slots": slots},
    }
    if meta is not None:
        out["inputs"]["meta"] = meta
    return out


# ─── parser ─────────────────────────────────────────────────────────────────


def test_parse_minimal_schema():
    s = InputsSchema.parse(_manifest([{"name": "p", "product": "X"}]))
    assert len(s.slots) == 1
    assert s.slots[0].name == "p"
    assert s.slots[0].product == "X"
    assert s.slots[0].filename_pattern is None
    assert s.slots[0].credential is None
    assert s.meta == []


def test_parse_full_schema():
    s = InputsSchema.parse(
        _manifest(
            [{"name": "p", "product": "X", "filename_pattern": r"\.hdf$", "credential": "c1"}],
            [{"name": "year", "pattern": r"^\d{4}$"}],
        )
    )
    assert s.slots[0].filename_pattern is not None
    assert s.slots[0].credential == "c1"
    assert len(s.meta) == 1 and s.meta[0].name == "year"


def test_parse_rejects_missing_slots():
    with pytest.raises(ValueError, match="slots"):
        InputsSchema.parse({"inputs": {}})


def test_parse_rejects_empty_slots():
    with pytest.raises(ValueError):
        InputsSchema.parse({"inputs": {"slots": []}})


def test_parse_rejects_duplicate_slot_names():
    with pytest.raises(ValueError, match="duplicate"):
        InputsSchema.parse(
            _manifest(
                [
                    {"name": "p", "product": "X"},
                    {"name": "p", "product": "Y"},
                ]
            )
        )


def test_parse_rejects_bad_regex():
    with pytest.raises(ValueError, match="regex"):
        InputsSchema.parse(
            _manifest(
                [
                    {"name": "p", "product": "X", "filename_pattern": "["},
                ]
            )
        )


def test_parse_rejects_missing_slot_fields():
    with pytest.raises(ValueError):
        InputsSchema.parse(_manifest([{"product": "X"}]))  # no name
    with pytest.raises(ValueError):
        InputsSchema.parse(_manifest([{"name": "p"}]))  # no product


# ─── granule validation ─────────────────────────────────────────────────────


def _schema(slots, meta=None):
    return InputsSchema.parse(_manifest(slots, meta))


def test_validate_happy_path():
    schema = _schema([{"name": "p", "product": "MOD09A1"}])
    r = validate_granule(
        schema,
        "g1",
        [{"url": "http://x", "filename": "f.hdf", "product": "MOD09A1"}],
        {},
    )
    assert r.ok
    assert r.errors == []
    assert r.warnings == []


def test_validate_missing_slot_is_error():
    schema = _schema([{"name": "p", "product": "MOD09A1"}])
    r = validate_granule(schema, "g1", [], {})
    assert not r.ok
    assert any("slot 'p'" in e and "MOD09A1" in e for e in r.errors)


def test_validate_duplicate_inputs_for_slot_is_error():
    schema = _schema([{"name": "p", "product": "MOD09A1"}])
    r = validate_granule(
        schema,
        "g1",
        [
            {"filename": "a.hdf", "product": "MOD09A1"},
            {"filename": "b.hdf", "product": "MOD09A1"},
        ],
        {},
    )
    assert not r.ok
    assert any("2 inputs" in e for e in r.errors)


def test_validate_filename_pattern_mismatch_is_error():
    schema = _schema(
        [
            {"name": "p", "product": "X", "filename_pattern": r"\.hdf$"},
        ]
    )
    r = validate_granule(
        schema,
        "g1",
        [{"filename": "foo.txt", "product": "X"}],
        {},
    )
    assert not r.ok
    assert any("pattern" in e for e in r.errors)


def test_validate_extra_product_is_warning_not_error():
    """Uploads with a product not in any slot should warn but still pass —
    the user may have uploaded a superset of what the bundle uses."""
    schema = _schema([{"name": "p", "product": "X"}])
    r = validate_granule(
        schema,
        "g1",
        [
            {"filename": "a", "product": "X"},
            {"filename": "b", "product": "Y"},  # extra
        ],
        {},
    )
    assert r.ok
    assert any("extra input" in w and "Y" in w for w in r.warnings)


def test_validate_meta_required():
    schema = _schema(
        [{"name": "p", "product": "X"}],
        [{"name": "year", "pattern": r"^\d{4}$"}],
    )
    r = validate_granule(
        schema,
        "g1",
        [{"filename": "a", "product": "X"}],
        {},
    )
    assert not r.ok
    assert any("meta" in e and "year" in e for e in r.errors)


def test_validate_meta_pattern_mismatch():
    schema = _schema(
        [{"name": "p", "product": "X"}],
        [{"name": "year", "pattern": r"^\d{4}$"}],
    )
    r = validate_granule(
        schema,
        "g1",
        [{"filename": "a", "product": "X"}],
        {"year": "24"},  # 2 digits, not 4
    )
    assert not r.ok
    assert any("year" in e and "pattern" in e for e in r.errors)


def test_validate_extra_meta_key_warns_not_errors():
    schema = _schema([{"name": "p", "product": "X"}])
    r = validate_granule(
        schema,
        "g1",
        [{"filename": "a", "product": "X"}],
        {"note": "some extra"},
    )
    assert r.ok
    assert any("note" in w for w in r.warnings)
