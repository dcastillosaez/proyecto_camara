"""Auto-generate a self-signed TLS certificate for local HTTPS."""
import datetime
import ipaddress
import logging
import os
import platform
import socket
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_self_signed_cert(certfile: str, keyfile: str) -> None:
    """Create cert+key PEM files if they don't already exist."""
    cert_path = Path(certfile)
    key_path = Path(keyfile)
    if cert_path.exists() and key_path.exists():
        return

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tapo Dashboard")])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName(_build_san_entries()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    _restrict_key_permissions(key_path)
    logger.info("Self-signed cert generated → %s / %s", certfile, keyfile)


def _build_san_entries() -> list:
    from cryptography import x509

    entries: list = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    lan_ip = _detect_lan_ip()
    if lan_ip and lan_ip != "127.0.0.1":
        try:
            entries.append(x509.IPAddress(ipaddress.IPv4Address(lan_ip)))
            logger.debug("SAN incluye IP LAN: %s", lan_ip)
        except ValueError:
            pass
    return entries


def _detect_lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _restrict_key_permissions(key_path: Path) -> None:
    if platform.system() == "Windows":
        try:
            username = os.environ.get("USERNAME", "")
            if username:
                subprocess.run(
                    ["icacls", str(key_path), "/inheritance:r", "/grant:r", f"{username}:R"],
                    check=False,
                    capture_output=True,
                )
        except Exception:
            pass
    else:
        try:
            os.chmod(key_path, 0o600)
        except Exception:
            pass
