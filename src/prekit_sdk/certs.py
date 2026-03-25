"""CA certificate download and caching.

The SDK bundles the Alpamayo Root CA certificate URL and can download it
on demand. Fingerprint verification is intentionally NOT done here — it
should be an explicit, visible step in the user's notebook or script.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

CA_URL = "https://raw.githubusercontent.com/alpamayo-solutions/prekit-sdk/main/certs/alpamayo-root-ca.crt"
CA_FINGERPRINT = "62:96:51:A7:63:CC:14:B3:74:2A:BB:4B:A3:7A:17:20:5E:6D:58:9F:46:E9:CC:D8:E6:38:94:FE:3B:3C:7C:5C"

_DEFAULT_PATH = Path.home() / ".prekit" / "alpamayo-root-ca.crt"


def ensure_ca_cert(path: Path | str | None = None) -> str:
    """Download the Alpamayo Root CA certificate if not already cached.

    Args:
        path: Where to store the cert. Defaults to ~/.prekit/alpamayo-root-ca.crt.

    Returns:
        Absolute path to the certificate file.
    """
    cert_path = Path(path) if path else _DEFAULT_PATH
    if cert_path.exists():
        return str(cert_path)

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["curl", "-sSfL", "-o", str(cert_path), CA_URL],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to download CA certificate: {result.stderr.strip()}")

    return str(cert_path)


def get_fingerprint(path: Path | str | None = None) -> str:
    """Compute the SHA-256 fingerprint of a CA certificate.

    Args:
        path: Path to the certificate file. Defaults to the cached location.

    Returns:
        Colon-separated SHA-256 fingerprint string.
    """
    cert_path = Path(path) if path else _DEFAULT_PATH
    if not cert_path.exists():
        raise FileNotFoundError(f"Certificate not found at {cert_path}")

    der = subprocess.run(
        ["openssl", "x509", "-in", str(cert_path), "-outform", "DER"],
        capture_output=True,
    ).stdout
    return ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())


def verify_ca_cert(path: Path | str | None = None) -> None:
    """Print the certificate fingerprint for manual verification.

    This is meant to be called explicitly in notebooks so the user
    can see and confirm the fingerprint. Raises on mismatch.
    """
    cert_path = Path(path) if path else _DEFAULT_PATH
    fp = get_fingerprint(cert_path)
    expected = CA_FINGERPRINT

    print(f"  Certificate:  {cert_path}")
    print(f"  Fingerprint:  {fp}")
    print(f"  Expected:     {expected}")

    if fp == expected:
        print("  Status:       OK")
    else:
        raise RuntimeError(
            f"Fingerprint mismatch! Certificate at {cert_path} may be tampered with.\n"
            f"Delete it and re-download, or verify manually with:\n"
            f"  openssl x509 -in {cert_path} -noout -sha256 -fingerprint"
        )
