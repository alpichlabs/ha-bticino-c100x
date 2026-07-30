"""mTLS certificate provisioning."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .api import LegrandApi
from .const import CERTIFICATE_ORGANIZATIONAL_UNIT, CERTIFICATE_TEMPLATE
from .models import CertificateBundle


async def provision_certificate(
    api: LegrandApi,
    *,
    plant: dict,
    gateway_id: str,
    client_id: str,
    user_oid: str,
) -> CertificateBundle:
    """Generate a local private key and submit only its CSR to Legrand."""
    owner_email = str(plant.get("ownerEmail", ""))
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, client_id),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, CERTIFICATE_ORGANIZATIONAL_UNIT),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LEGRAND"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Paris"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "France"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
            *([x509.NameAttribute(NameOID.EMAIL_ADDRESS, owner_email)] if owner_email else []),
        ]
    )
    sip_uri = f"sip:{user_oid}_{client_id}@{gateway_id}.bs.iotleg.com"
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(sip_uri)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    response = await api.provision_certificate(
        {
            "csr": base64.b64encode(csr.public_bytes(serialization.Encoding.DER)).decode(),
            "sender": {
                "addressType": "addressLocation",
                "plant": {
                    "_gatewayDbIdx": -1,
                    "country": plant.get("country", "fr"),
                    "dbIdx": -1,
                    "id": plant["id"],
                    "name": plant.get("name", "Home"),
                    "ownerEmail": owner_email,
                    "ownerId": plant.get("ownerId", user_oid),
                    "type": plant.get("type"),
                },
                "system": "information",
            },
            "template": CERTIFICATE_TEMPLATE,
        }
    )
    ca_response = await api.certificate_authority()
    encoded_certificate = str(response["cert"])
    certificate_pem = (
        "-----BEGIN CERTIFICATE-----\n"
        + "\n".join(encoded_certificate[index : index + 64] for index in range(0, len(encoded_certificate), 64))
        + "\n-----END CERTIFICATE-----\n"
    )
    private_key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    certificate = x509.load_pem_x509_certificate(certificate_pem.encode())
    encoded_ca = str(ca_response["chain"])
    ca_pem = (
        "-----BEGIN CERTIFICATE-----\n"
        + "\n".join(
            encoded_ca[index : index + 64]
            for index in range(0, len(encoded_ca), 64)
        )
        + "\n-----END CERTIFICATE-----\n"
    )
    expires_at = certificate.not_valid_after_utc.astimezone(UTC)
    return CertificateBundle(certificate_pem, private_key_pem, ca_pem, expires_at)


def certificate_expiry(certificate_pem: str) -> datetime:
    """Return the timezone-aware certificate expiry."""
    return x509.load_pem_x509_certificate(certificate_pem.encode()).not_valid_after_utc
