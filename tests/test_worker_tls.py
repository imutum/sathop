"""Self-signed TLS cert generation for worker storage server.

Covers the IP-vs-hostname SAN branch, idempotent regeneration when host
changes, and the cert-as-CA assumption that lets worker upload the cert
itself as `ca_pem`."""

from __future__ import annotations

import ssl
from pathlib import Path

import pytest
from cryptography import x509

from sathop.worker.tls import _host_from_public_url, ensure_self_signed


def _read_san(cert_path: Path) -> list:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return list(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)


def test_host_from_public_url_extracts_host():
    assert _host_from_public_url("https://192.168.1.50") == "192.168.1.50"
    assert _host_from_public_url("https://worker.lan:443") == "worker.lan"


def test_host_from_public_url_rejects_no_host():
    with pytest.raises(ValueError):
        _host_from_public_url("not-a-url")


def test_ip_address_gets_ip_san(tmp_path: Path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    pem = ensure_self_signed("https://192.168.1.50", cert_path, key_path)
    assert "BEGIN CERTIFICATE" in pem
    san = _read_san(cert_path)
    assert any(isinstance(g, x509.IPAddress) for g in san)
    assert not any(isinstance(g, x509.DNSName) for g in san)


def test_hostname_gets_dns_san(tmp_path: Path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    ensure_self_signed("https://worker.lan", cert_path, key_path)
    san = _read_san(cert_path)
    assert any(isinstance(g, x509.DNSName) and g.value == "worker.lan" for g in san)


def test_idempotent_when_host_unchanged(tmp_path: Path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    ensure_self_signed("https://192.168.1.50", cert_path, key_path)
    serial1 = x509.load_pem_x509_certificate(cert_path.read_bytes()).serial_number

    # Same host, same paths: should reuse, not regenerate.
    ensure_self_signed("https://192.168.1.50", cert_path, key_path)
    serial2 = x509.load_pem_x509_certificate(cert_path.read_bytes()).serial_number
    assert serial1 == serial2


def test_regenerates_when_host_changes(tmp_path: Path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    ensure_self_signed("https://192.168.1.50", cert_path, key_path)
    serial1 = x509.load_pem_x509_certificate(cert_path.read_bytes()).serial_number

    # Operator changed SATHOP_PUBLIC_URL — old cert no longer covers new host.
    ensure_self_signed("https://10.0.0.5", cert_path, key_path)
    serial2 = x509.load_pem_x509_certificate(cert_path.read_bytes()).serial_number
    assert serial1 != serial2


def test_cert_loadable_as_tls_ca(tmp_path: Path):
    """The cert must work as both serving cert AND its own trust root —
    that's the whole point of using the self-signed cert as ca_pem."""
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    ensure_self_signed("https://192.168.1.50", cert_path, key_path)

    # Server side: cert + key load into an SSLContext.
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

    # Client side: the same cert loads as a trust anchor.
    client_ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    client_ctx.load_verify_locations(cafile=str(cert_path))


def test_cert_is_ca_constrained(tmp_path: Path):
    """Self-signed cert needs CA:TRUE so it can be its own issuer in the
    receiver's trust bundle."""
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    ensure_self_signed("https://192.168.1.50", cert_path, key_path)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
