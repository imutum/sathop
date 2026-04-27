"""Tests for sathop.cli.validate_bundle — covers happy path + every shape error
the orchestrator would also reject at upload time."""

from __future__ import annotations

from pathlib import Path

from sathop.cli import validate_bundle as validator


def _write(bundle: Path, manifest: str, extra_files: dict[str, str] | None = None) -> Path:
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "manifest.yaml").write_text(manifest, encoding="utf-8")
    for rel, body in (extra_files or {}).items():
        p = bundle / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return bundle


GOOD_MANIFEST = """\
name: demo
version: "0.1"
execution:
  entrypoint: bash run.sh
  timeout_sec: 600
outputs:
  watch_dir: output
  extensions: [".nc"]
inputs:
  slots:
    - name: primary
      product: MOD09A1
"""


def test_happy_path(tmp_path: Path):
    bundle = _write(tmp_path / "b", GOOD_MANIFEST, {"run.sh": "#!/bin/bash\n"})
    r = validator.validate(bundle)
    assert r.ok, r.errors
    assert any("entrypoint script 'run.sh'" in p for p in r.passed)


def test_missing_directory(tmp_path: Path):
    r = validator.validate(tmp_path / "nope")
    assert not r.ok
    assert "is not a directory" in r.errors[0]


def test_missing_manifest(tmp_path: Path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    r = validator.validate(bundle)
    assert not r.ok
    assert "manifest.yaml" in r.errors[0]


def test_bad_yaml(tmp_path: Path):
    bundle = _write(tmp_path / "b", "name: demo\n  bad indent: x")
    r = validator.validate(bundle)
    assert not r.ok
    assert "not valid YAML" in r.errors[0]


def test_top_level_not_mapping(tmp_path: Path):
    bundle = _write(tmp_path / "b", "- a\n- b\n")
    r = validator.validate(bundle)
    assert not r.ok
    assert "must be a mapping" in r.errors[0]


def test_missing_required_keys(tmp_path: Path):
    bundle = _write(tmp_path / "b", "name: demo\nversion: '0.1'\n")
    r = validator.validate(bundle)
    assert not r.ok
    assert any("missing required keys" in e for e in r.errors)


def test_bad_name_pattern(tmp_path: Path):
    bad = GOOD_MANIFEST.replace("name: demo", "name: 'demo!'")
    bundle = _write(tmp_path / "b", bad, {"run.sh": ""})
    r = validator.validate(bundle)
    assert not r.ok
    assert any("manifest.name" in e for e in r.errors)


def test_entrypoint_script_missing(tmp_path: Path):
    # No run.sh on disk
    bundle = _write(tmp_path / "b", GOOD_MANIFEST)
    r = validator.validate(bundle)
    assert not r.ok
    assert any("does not exist in bundle" in e for e in r.errors)


def test_entrypoint_python_resolves(tmp_path: Path):
    m = GOOD_MANIFEST.replace("bash run.sh", "python proc.py")
    bundle = _write(tmp_path / "b", m, {"proc.py": "print('ok')\n"})
    r = validator.validate(bundle)
    assert r.ok, r.errors


def test_entrypoint_direct_script(tmp_path: Path):
    m = GOOD_MANIFEST.replace("bash run.sh", "./run.sh --foo")
    bundle = _write(tmp_path / "b", m, {"run.sh": ""})
    r = validator.validate(bundle)
    assert r.ok, r.errors


def test_outputs_extensions_must_be_dotted(tmp_path: Path):
    m = GOOD_MANIFEST.replace('extensions: [".nc"]', 'extensions: ["nc"]')
    bundle = _write(tmp_path / "b", m, {"run.sh": ""})
    r = validator.validate(bundle)
    assert not r.ok
    assert any("dot-prefixed" in e for e in r.errors)


def test_timeout_must_be_positive_int(tmp_path: Path):
    m = GOOD_MANIFEST.replace("timeout_sec: 600", "timeout_sec: -5")
    bundle = _write(tmp_path / "b", m, {"run.sh": ""})
    r = validator.validate(bundle)
    assert not r.ok
    assert any("timeout_sec" in e for e in r.errors)


def test_requirements_pip_must_be_list_of_str(tmp_path: Path):
    m = GOOD_MANIFEST + "requirements:\n  pip: 'numpy'\n"
    bundle = _write(tmp_path / "b", m, {"run.sh": ""})
    r = validator.validate(bundle)
    assert not r.ok
    assert any("requirements.pip" in e for e in r.errors)


def test_inputs_slots_required(tmp_path: Path):
    m = GOOD_MANIFEST.replace(
        "inputs:\n  slots:\n    - name: primary\n      product: MOD09A1\n",
        "inputs: {}\n",
    )
    bundle = _write(tmp_path / "b", m, {"run.sh": ""})
    r = validator.validate(bundle)
    assert not r.ok
    assert any("inputs" in e for e in r.errors)


def test_requirements_txt_alone(tmp_path: Path):
    """requirements.txt with no manifest.requirements: validator must announce
    the file (not say 'no requirements declared') — matches worker/bundle.py
    install-time precedence."""
    bundle = _write(tmp_path / "b", GOOD_MANIFEST, {"run.sh": "", "requirements.txt": "numpy\n"})
    r = validator.validate(bundle)
    assert r.ok, r.errors
    assert any("requirements.txt found" in p for p in r.passed)
    assert not any("no requirements declared" in p for p in r.passed)


def test_requirements_txt_and_manifest_pip_conflict_warns(tmp_path: Path):
    """Both declared: worker prefers requirements.txt and ignores manifest.pip.
    Validator must warn so the user knows manifest.pip is dead weight."""
    m = GOOD_MANIFEST + "requirements:\n  pip: [scipy]\n"
    bundle = _write(tmp_path / "b", m, {"run.sh": "", "requirements.txt": "numpy\n"})
    r = validator.validate(bundle)
    assert r.ok, r.errors
    assert any("both requirements.txt and manifest.requirements.pip" in w for w in r.warnings)


def test_full_featured_manifest(tmp_path: Path):
    """Synthetic manifest exercising every optional field at once: timeout,
    extensions, multi-slot inputs + meta, full requirements (python/pip/apt/
    credentials), shared_files. Guards against the validator silently dropping
    a field check."""
    manifest = """\
name: full.demo_bundle-1
version: "2.0.0+build.7"
execution:
  entrypoint: python proc.py --flag
  timeout_sec: 1800
outputs:
  watch_dir: out
  extensions: [".nc", ".tif"]
inputs:
  slots:
    - name: a
      product: PROD_A
      filename_pattern: "^A.*\\\\.h5$"
    - name: b
      product: PROD_B
      credential: cred-x
  meta:
    - name: year
      pattern: "^\\\\d{4}$"
    - name: tile
requirements:
  python: ">=3.11"
  pip: [numpy, "xarray>=2024.1"]
  apt: [libhdf5-dev]
  credentials: [cred-x, cred-y]
shared_files: [coast_mask.tif]
"""
    bundle = _write(tmp_path / "b", manifest, {"proc.py": "print('ok')\n"})
    r = validator.validate(bundle)
    assert r.ok, r.errors
    assert any("inputs.slots: ['a', 'b']" in p for p in r.passed)
    assert any("inputs.meta: ['year', 'tile']" in p for p in r.passed)
    assert any("shared_files: ['coast_mask.tif']" in p for p in r.passed)
    assert any("pip=2, apt=1, credentials=2" in p for p in r.passed)
