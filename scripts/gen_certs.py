"""Generate a self-signed TLS certificate and key for local/dev use.

    python scripts/gen_certs.py

Writes certs/server.crt and certs/server.key. The certificate is valid for
localhost and 127.0.0.1, so client and test TLS verification succeeds.
Pure Python (the `cryptography` package), so it works the same on Windows,
macOS and Linux without bash or openssl. Skips if the files already exist.
"""

from __future__ import annotations

import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_DIR = Path(__file__).resolve().parents[1] / "certs"


def main() -> None:
    cert_path, key_path = CERT_DIR / "server.crt", CERT_DIR / "server.key"
    if cert_path.is_file() and key_path.is_file():
        print(f"Certs already exist in {CERT_DIR}, skipping. Delete them to regenerate.")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)                      # self-signed: issuer == subject
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"Wrote {cert_path} and {key_path}")


if __name__ == "__main__":
    main()
