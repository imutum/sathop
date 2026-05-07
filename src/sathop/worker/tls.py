"""Self-signed TLS for worker storage server.

For internal-network deployments without a domain, worker generates its own
IP/hostname SAN certificate on first boot, persists it under `data/tls/`, and
uses it both as uvicorn's serving cert *and* as the `ca_pem` uploaded at
register time. Receivers fetch the CA bundle via
`/api/receivers/ca-bundle` and pin trust against it.

Self-signed cert IS its own root — no separate CA hierarchy needed. The
upside: zero runtime dependencies (no caddy, no Caddyfile, no ACME). The
downside: rotation = new cert; receivers must refresh their trust bundle.
That tradeoff fits internal SatHop deployments fine."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# 10 years — the cert is locked to a private IP/hostname that doesn't change,
# and renewal would force every receiver to refetch the CA bundle. Cheaper to
# rotate by reissuing the worker.
_CERT_VALIDITY = timedelta(days=3650)


def _host_from_public_url(public_url: str) -> str:
    parsed = urlparse(public_url)
    if not parsed.hostname:
        raise ValueError(f"SATHOP_PUBLIC_URL has no hostname: {public_url!r}")
    return parsed.hostname


def _san_for(host: str) -> x509.GeneralName:
    """IP literal → IPAddress SAN; otherwise → DNSName SAN. Browsers and
    httpx both check the matching field, so picking the wrong one yields a
    confusing 'hostname doesn't match' error at first connection."""
    try:
        return x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        return x509.DNSName(host)


def _write_secret(path: Path, data: bytes) -> None:
    """0600-ish: write then chmod. On Windows chmod is a no-op but the file
    still lives in the worker container's data dir which the operator owns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def generate_self_signed(host: str, cert_path: Path, key_path: Path) -> None:
    """Generate a 10-year RSA-2048 self-signed cert covering `host` (as IP
    SAN if it parses as an IP, else DNS SAN). Writes PEM cert + key to the
    given paths, replacing any existing files. Caller is responsible for
    deciding when to (re)generate; this function is unconditional."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + _CERT_VALIDITY)
        .add_extension(x509.SubjectAlternativeName([_san_for(host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    _write_secret(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    _write_secret(
        key_path,
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )


def _cert_matches_host(cert_path: Path, host: str) -> bool:
    """Refuse to reuse a cached cert whose SAN doesn't cover the current
    `host` — operator changed SATHOP_PUBLIC_URL, or persisted data dir
    was copied across hosts. Forces regeneration in those cases."""
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except Exception:
        return False
    expected = _san_for(host)
    if isinstance(expected, x509.IPAddress):
        return any(isinstance(g, x509.IPAddress) and g.value == expected.value for g in san)
    return any(isinstance(g, x509.DNSName) and g.value == expected.value for g in san)


def ensure_self_signed(public_url: str, cert_path: Path, key_path: Path) -> str:
    """Idempotent: load existing cert if it covers `public_url`'s host, else
    regenerate. Returns the cert PEM as a string (also serves as ca_pem since
    the cert is its own root)."""
    host = _host_from_public_url(public_url)
    if not (cert_path.is_file() and key_path.is_file() and _cert_matches_host(cert_path, host)):
        generate_self_signed(host, cert_path, key_path)
    return cert_path.read_text(encoding="utf-8")
