"""Certificate provisioning tests."""

import base64
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from custom_components.bticino_c100x.certificate import provision_certificate


class FakeCertificateApi:
    request: dict

    async def provision_certificate(self, request: dict) -> dict:
        self.request = request
        csr = x509.load_der_x509_csr(base64.b64decode(request["csr"]))
        issuer_key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")]))
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value, False)
            .sign(issuer_key, hashes.SHA256())
        )
        return {"cert": base64.b64encode(certificate.public_bytes(serialization.Encoding.DER)).decode()}


async def test_provisioning_keeps_private_key_local() -> None:
    api = FakeCertificateApi()
    bundle = await provision_certificate(
        api,  # type: ignore[arg-type]
        plant={
            "id": "plant",
            "name": "Home",
            "ownerId": "owner",
            "ownerEmail": "owner@example.com",
            "country": "fr",
            "type": "doorEntry",
        },
        gateway_id="gateway",
        client_id="1234567890123456789012",
        user_oid="owner",
    )
    certificate = x509.load_pem_x509_certificate(bundle.certificate_pem.encode())
    private_key = serialization.load_pem_private_key(bundle.private_key_pem.encode(), password=None)
    assert certificate.public_key().public_numbers() == private_key.public_key().public_numbers()
    assert "PRIVATE KEY" not in str(api.request)
    assert api.request["template"] == "sipuser-DIY"
    san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.UniformResourceIdentifier) == [
        "sip:owner_1234567890123456789012@gateway.bs.iotleg.com"
    ]

