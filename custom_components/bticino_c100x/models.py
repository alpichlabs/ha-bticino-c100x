"""Data models for BTicino C100X."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class SipAccount:
    """Credentials for a Legrand SIP client."""

    client_id: str
    sip_uri: str
    sip_password: str
    user_oid: str

    @property
    def username(self) -> str:
        return self.sip_uri.split("@", maxsplit=1)[0]

    @property
    def domain(self) -> str:
        return self.sip_uri.split("@", maxsplit=1)[1]

    @classmethod
    def from_api(cls, value: dict) -> SipAccount:
        return cls(
            client_id=str(value["clientId"]),
            sip_uri=str(value["sipUri"]).removeprefix("sip:"),
            sip_password=str(value["sipPassword"]),
            user_oid=str(value.get("userOid", "")),
        )


@dataclass(slots=True)
class CertificateBundle:
    """Persisted mTLS material."""

    certificate_pem: str
    private_key_pem: str
    expires_at: datetime

